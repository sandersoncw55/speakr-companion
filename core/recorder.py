import os
import time
import wave
import math
import struct
import array
import threading
from queue import Queue
from collections import deque
from typing import Tuple, List, Optional, Callable
import pyaudiowpatch as pyaudio

class AudioRecorder:
    """Manages recording from microphone and system loopback simultaneously."""

    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.is_recording = False
        self.is_paused = False
        
        # Audio configuration
        self.target_rate = 16000
        self.chunk_size = 1024
        
        # Threads
        self.mic_thread: Optional[threading.Thread] = None
        self.loopback_thread: Optional[threading.Thread] = None
        self.mix_thread: Optional[threading.Thread] = None
        
        # Buffers
        self.mic_samples = deque(maxlen=320000)  # ~10 seconds of buffer space
        self.loopback_samples = deque(maxlen=320000)
        self.lock = threading.Lock()
        
        # Callbacks for live level meters: callback(mic_db, speaker_db)
        self.level_callback: Optional[Callable[[float, float], None]] = None
        
        # Real-time audio tap callback for live Copilot: callback(channel, pcm_bytes)
        self.audio_tap_callback: Optional[Callable[[str, bytes], None]] = None
        self.meeting_mode: str = "virtual"  # "virtual", "in_person", "hybrid"
        
        self.current_mic_db = -96.0
        self.current_speaker_db = -96.0
        
        # Output file paths
        self.output_file_path: Optional[str] = None
        self.temp_wav_path: Optional[str] = None
        self.wav_file: Optional[wave.Wave_write] = None
        
        # Timing tracking
        self.recording_start_time = 0.0
        self.pause_start_time = 0.0
        self.total_paused_duration = 0.0

    @property
    def elapsed_seconds(self) -> float:
        """Returns the actual elapsed active recording duration in seconds."""
        if not self.is_recording or self.recording_start_time <= 0:
            return 0.0
        import time as _t
        current = _t.time()
        current_paused = 0.0
        if self.is_paused and self.pause_start_time > 0:
            current_paused = current - self.pause_start_time
        return max(0.0, current - self.recording_start_time - self.total_paused_duration - current_paused)

    @staticmethod
    def get_devices() -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
        """Lists available MME microphones (inputs) and WASAPI loopback speakers."""
        p = pyaudio.PyAudio()
        mics = []
        speakers = []

        try:
            # Find MME Host API Index for mics
            mme_idx = None
            for i in range(p.get_host_api_count()):
                info = p.get_host_api_info_by_index(i)
                if info.get("type") == pyaudio.paMME:
                    mme_idx = info.get("index")
                    break

            # Find WASAPI Host API Index for loopback
            wasapi_idx = None
            for i in range(p.get_host_api_count()):
                info = p.get_host_api_info_by_index(i)
                if info.get("type") == pyaudio.paWASAPI:
                    wasapi_idx = info.get("index")
                    break

            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                
                # Check for loopbacks on WASAPI
                if wasapi_idx is not None and info.get("hostApi") == wasapi_idx:
                    if info.get("isLoopbackDevice"):
                        speakers.append((i, info.get("name")))
                
                # Check for standard inputs on MME (resampling is handled automatically by Windows MME Mapper)
                if mme_idx is not None and info.get("hostApi") == mme_idx:
                    if info.get("maxInputChannels") > 0 and "mapper" not in info.get("name", "").lower():
                        mics.append((i, info.get("name")))
        except Exception as e:
            print(f"[Recorder] Error listing devices: {e}")
        finally:
            p.terminate()

        return mics, speakers

    def _calculate_db(self, audio_data: array.array) -> float:
        """Calculate decibel level from RMS of audio samples."""
        if not audio_data:
            return -96.0
        sum_squares = sum(float(sample) ** 2 for sample in audio_data)
        rms = math.sqrt(sum_squares / len(audio_data))
        if rms <= 0:
            return -96.0
        # Reference level for 16-bit signed integer is 32767
        db = 20 * math.log10(rms / 32767.0)
        return max(-96.0, min(0.0, db))

    def _find_device_index(self, name_pattern: str, loopback: bool = False) -> int:
        """Finds PyAudio device index matching the name pattern."""
        p = self.p
        try:
            # Find WASAPI Host API Index for loopback
            wasapi_idx = None
            for i in range(p.get_host_api_count()):
                info = p.get_host_api_info_by_index(i)
                if info.get("type") == pyaudio.paWASAPI:
                    wasapi_idx = info.get("index")
                    break

            # Find MME Host API Index for mic
            mme_idx = None
            for i in range(p.get_host_api_count()):
                info = p.get_host_api_info_by_index(i)
                if info.get("type") == pyaudio.paMME:
                    mme_idx = info.get("index")
                    break

            if name_pattern == "Default":
                if loopback:
                    # Resolve default loopback device using MME speaker name prefix match
                    default_speakers = p.get_default_output_device_info()
                    clean_name = default_speakers["name"]
                    # Take first 20 chars to safely match truncated MME names in WASAPI lists
                    if len(clean_name) > 20:
                        clean_name = clean_name[:20]
                        
                    for info in p.get_loopback_device_info_generator():
                        if clean_name.lower() in info["name"].lower():
                            return info["index"]
                    # Fallback to first loopback
                    for info in p.get_loopback_device_info_generator():
                        return info["index"]
                else:
                    return p.get_default_input_device_info()["index"]

            # Match by name pattern
            target_api_idx = wasapi_idx if loopback else mme_idx
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if target_api_idx is not None and info.get("hostApi") != target_api_idx:
                    continue
                if name_pattern.lower() in info.get("name", "").lower():
                    if loopback == bool(info.get("isLoopbackDevice")):
                        return info["index"]
        except Exception as e:
            print(f"[Recorder] Error resolving device index: {e}")
        
        # Final fallback
        if loopback:
            # Try to return first loopback device found
            for info in p.get_loopback_device_info_generator():
                return info["index"]
            raise RuntimeError("No WASAPI loopback device found on this system.")
        else:
            return p.get_default_input_device_info()["index"]

    def start_recording(self, output_path: str, mic_name: str = "Default", speaker_name: str = "Default", meeting_mode: str = "virtual") -> None:
        """Starts recording threads."""
        if self.is_recording:
            return

        self.meeting_mode = meeting_mode
        self.output_file_path = output_path
        self.recording_start_time = time.time()
        self.pause_start_time = 0.0
        self.total_paused_duration = 0.0
        
        # Clear buffers
        self.mic_samples.clear()
        self.loopback_samples.clear()

        # Initialize PyAudio if closed
        if not hasattr(self, 'p') or self.p is None:
            self.p = pyaudio.PyAudio()

        try:
            # Determine intermediate capture path (record raw PCM to temp WAV for MP4)
            if output_path.lower().endswith(".mp4"):
                self.temp_wav_path = output_path + ".tmp.wav"
                write_path = self.temp_wav_path
            else:
                self.temp_wav_path = None
                write_path = output_path

            # Open WAV file for PCM capture
            self.wav_file = wave.open(write_path, "wb")
            self.wav_file.setnchannels(1)
            self.wav_file.setsampwidth(2)  # 16-bit
            self.wav_file.setframerate(self.target_rate)

            # Resolve indices
            mic_idx = self._find_device_index(mic_name, loopback=False)
            loopback_idx = self._find_device_index(speaker_name, loopback=True) if self.meeting_mode != "in_person" else None

            self.is_recording = True
            self.is_paused = False

            # Spawn threads
            self.mic_thread = threading.Thread(target=self._record_mic, args=(mic_idx,), daemon=True)
            self.mic_thread.start()

            if self.meeting_mode != "in_person" and loopback_idx is not None:
                self.loopback_thread = threading.Thread(target=self._record_loopback, args=(loopback_idx,), daemon=True)
                self.loopback_thread.start()
            else:
                self.loopback_thread = None
                self.current_speaker_db = -96.0

            self.mix_thread = threading.Thread(target=self._mix_and_write, daemon=True)
            self.mix_thread.start()
            print(f"[Recorder] Recording started (Mode: {self.meeting_mode}). Output: {output_path}")
        except Exception:
            self.is_recording = False
            self.is_paused = False
            if self.wav_file:
                try:
                    self.wav_file.close()
                except Exception:
                    pass
                self.wav_file = None
            raise

    def stop_recording(self) -> None:
        """Stops recording and closes files."""
        if not self.is_recording:
            return

        self.is_recording = False
        
        # Wait for threads to complete
        if self.mic_thread:
            self.mic_thread.join(timeout=2.0)
        if self.loopback_thread:
            self.loopback_thread.join(timeout=2.0)
        if self.mix_thread:
            self.mix_thread.join(timeout=2.0)

        # Close intermediate WAV file
        if self.wav_file:
            try:
                self.wav_file.close()
            except Exception as e:
                print(f"[Recorder] Error closing WAV: {e}")
            self.wav_file = None

        # If target was MP4, encode intermediate WAV to MP4 AAC and remove temp WAV
        if self.temp_wav_path and os.path.exists(self.temp_wav_path) and self.output_file_path:
            try:
                self._encode_wav_to_mp4(self.temp_wav_path, self.output_file_path)
            finally:
                if os.path.exists(self.temp_wav_path):
                    try:
                        os.remove(self.temp_wav_path)
                    except Exception as e:
                        print(f"[Recorder] Error removing temp WAV: {e}")
                self.temp_wav_path = None

        # Reset DB values
        self.current_mic_db = -96.0
        self.current_speaker_db = -96.0
        if self.level_callback:
            self.level_callback(-96.0, -96.0)

        print("[Recorder] Recording stopped and saved.")

    def _encode_wav_to_mp4(self, wav_path: str, mp4_path: str) -> bool:
        """Encodes intermediate WAV PCM into AAC MP4 container using PyAV via streaming."""
        try:
            import av
            with wave.open(wav_path, 'rb') as wf:
                n_channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()

                container = av.open(mp4_path, mode='w', format='mp4')
                stream = container.add_stream('aac', rate=sample_rate, layout='mono' if n_channels == 1 else 'stereo')
                stream.bit_rate = 64000

                frame_size = 1024
                pts = 0

                if n_frames == 0:
                    # Write 1 frame of silence for valid container
                    silence = bytes(frame_size * 2 * n_channels)
                    frame = av.AudioFrame(format='s16', layout='mono' if n_channels == 1 else 'stereo', samples=frame_size)
                    frame.planes[0].update(silence)
                    frame.sample_rate = sample_rate
                    frame.pts = pts
                    for packet in stream.encode(frame):
                        container.mux(packet)
                else:
                    while True:
                        raw_chunk = wf.readframes(frame_size)
                        if not raw_chunk:
                            break
                        num_samples = len(raw_chunk) // (2 * n_channels)
                        if num_samples == 0:
                            break
                        frame = av.AudioFrame(format='s16', layout='mono' if n_channels == 1 else 'stereo', samples=num_samples)
                        frame.planes[0].update(raw_chunk)
                        frame.sample_rate = sample_rate
                        frame.pts = pts
                        pts += num_samples
                        for packet in stream.encode(frame):
                            container.mux(packet)

                for packet in stream.encode():
                    container.mux(packet)

                container.close()
                print(f"[Recorder] Successfully encoded MP4: {mp4_path}")
                return True
        except Exception as e:
            print(f"[Recorder] Error encoding MP4 via PyAV: {e}")
            return False

    def pause_recording(self) -> None:
        if not self.is_paused:
            self.pause_start_time = time.time()
            self.is_paused = True
            print("[Recorder] Recording paused.")

    def resume_recording(self) -> None:
        if self.is_paused:
            if self.pause_start_time > 0:
                self.total_paused_duration += time.time() - self.pause_start_time
                self.pause_start_time = 0.0
            self.is_paused = False
            print("[Recorder] Recording resumed.")

    def _record_mic(self, device_idx: int) -> None:
        """Thread to capture microphone audio."""
        try:
            stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.target_rate,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=self.chunk_size
            )
        except Exception as e:
            print(f"[Recorder] Failed to open microphone stream: {e}")
            return

        while self.is_recording:
            if self.is_paused:
                # Clear incoming data to avoid buildup and calculate silent DB
                try:
                    stream.read(self.chunk_size, exception_on_overflow=False)
                except:
                    pass
                self.current_mic_db = -96.0
                continue

            try:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                samples = array.array("h", data)
                self.current_mic_db = self._calculate_db(samples)
                
                with self.lock:
                    self.mic_samples.extend(samples)

                if self.audio_tap_callback:
                    ch = "room" if self.meeting_mode == "in_person" else "mic"
                    try:
                        self.audio_tap_callback(ch, data)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Recorder] Mic read error: {e}")
                break

        stream.stop_stream()
        stream.close()

    def _record_loopback(self, device_idx: int) -> None:
        """Thread to capture system output loopback."""
        try:
            device_info = self.p.get_device_info_by_index(device_idx)
            native_rate = int(device_info["defaultSampleRate"])
            native_channels = int(device_info.get("maxInputChannels", 2))
            if native_channels == 0:
                native_channels = 2
            
            stream = self.p.open(
                format=pyaudio.paInt16,
                channels=native_channels,
                rate=native_rate,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=self.chunk_size
            )
        except Exception as e:
            print(f"[Recorder] Failed to open loopback stream: {e}")
            return

        # Precompute resampling ratio
        resample_ratio = native_rate / self.target_rate

        while self.is_recording:
            if self.is_paused:
                try:
                    stream.read(self.chunk_size, exception_on_overflow=False)
                except:
                    pass
                self.current_speaker_db = -96.0
                continue

            try:
                # Loopback buffer size can overflow easily, read larger chunk if needed
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                raw_samples = array.array("h", data)
                
                # Convert Stereo/Multi-channel to Mono
                mono_samples = []
                if native_channels >= 2:
                    for i in range(0, len(raw_samples), native_channels):
                        # Average Left and Right channels
                        mono_sample = (raw_samples[i] + raw_samples[i+1]) // 2
                        mono_samples.append(mono_sample)
                else:
                    mono_samples = list(raw_samples)
                
                # Resample from native_rate to target_rate (nearest-neighbor)
                target_len = int(len(mono_samples) / resample_ratio)
                resampled_samples = array.array("h", [0] * target_len)
                for j in range(target_len):
                    src_idx = int(j * resample_ratio)
                    if src_idx < len(mono_samples):
                        resampled_samples[j] = mono_samples[src_idx]

                # Update live meter DB levels
                self.current_speaker_db = self._calculate_db(resampled_samples)
                
                with self.lock:
                    self.loopback_samples.extend(resampled_samples)

                if self.audio_tap_callback:
                    try:
                        self.audio_tap_callback("loopback", resampled_samples.tobytes())
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Recorder] Loopback read error: {e}")
                break

        stream.stop_stream()
        stream.close()

    def _mix_and_write(self) -> None:
        """Mixes mic and speaker audio samples and writes to WAV file."""
        while self.is_recording or len(self.mic_samples) > 0 or len(self.loopback_samples) > 0:
            # Emit volume levels to GUI callback
            if self.level_callback:
                # If paused, force meters to minimum
                if self.is_paused:
                    self.level_callback(-96.0, -96.0)
                else:
                    self.level_callback(self.current_mic_db, self.current_speaker_db)

            # Check samples in buffers
            mic_len = len(self.mic_samples)
            spk_len = len(self.loopback_samples)
            
            if self.meeting_mode == "in_person":
                if mic_len > 0:
                    drain_len = min(mic_len, self.chunk_size)
                    chunk = []
                    with self.lock:
                        for _ in range(drain_len):
                            chunk.append(self.mic_samples.popleft())
                    mixed = array.array("h", chunk)
                    frame_bytes = mixed.tobytes()
                    if self.wav_file:
                        try:
                            self.wav_file.writeframes(frame_bytes)
                        except Exception as e:
                            print(f"[Recorder] WAV write error: {e}")
                else:
                    threading.Event().wait(0.01)

            elif mic_len > 0 and spk_len > 0:
                mix_len = min(mic_len, spk_len)
                mic_chunk = []
                spk_chunk = []
                
                with self.lock:
                    for _ in range(mix_len):
                        mic_chunk.append(self.mic_samples.popleft())
                        spk_chunk.append(self.loopback_samples.popleft())
                
                # Mix (sum) the samples and clip to 16-bit range [-32768, 32767]
                mixed = array.array("h", [0] * mix_len)
                for i in range(mix_len):
                    val = mic_chunk[i] + spk_chunk[i]
                    if val > 32767:
                        val = 32767
                    elif val < -32768:
                        val = -32768
                    mixed[i] = val
                
                # Write mixed frame to WAV file
                frame_bytes = mixed.tobytes()
                if self.wav_file:
                    try:
                        self.wav_file.writeframes(frame_bytes)
                    except Exception as e:
                        print(f"[Recorder] WAV write error: {e}")

            elif mic_len > 0 and (not self.loopback_thread or not self.loopback_thread.is_alive() or mic_len >= self.chunk_size * 4):
                # Drain microphone samples if loopback is absent or lagging behind
                drain_len = min(mic_len, self.chunk_size)
                chunk = []
                with self.lock:
                    for _ in range(drain_len):
                        chunk.append(self.mic_samples.popleft())
                out_samples = array.array("h", chunk)
                frame_bytes = out_samples.tobytes()
                if self.wav_file:
                    try:
                        self.wav_file.writeframes(frame_bytes)
                    except Exception as e:
                        print(f"[Recorder] WAV write error: {e}")

            elif spk_len > 0 and (not self.mic_thread or not self.mic_thread.is_alive() or spk_len >= self.chunk_size * 4):
                # Drain loopback samples if mic is absent or lagging behind
                drain_len = min(spk_len, self.chunk_size)
                chunk = []
                with self.lock:
                    for _ in range(drain_len):
                        chunk.append(self.loopback_samples.popleft())
                out_samples = array.array("h", chunk)
                frame_bytes = out_samples.tobytes()
                if self.wav_file:
                    try:
                        self.wav_file.writeframes(frame_bytes)
                    except Exception as e:
                        print(f"[Recorder] WAV write error: {e}")

            else:
                # Sleep a tiny bit to wait for incoming samples
                threading.Event().wait(0.01)

        # Clear remaining samples if any stream died early
        with self.lock:
            self.mic_samples.clear()
            self.loopback_samples.clear()

    def terminate(self) -> None:
        """Free resources on application shutdown."""
        self.stop_recording()
        if hasattr(self, 'p') and self.p is not None:
            self.p.terminate()
            self.p = None
