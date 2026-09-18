import time
import threading
import array
from collections import deque
from dataclasses import dataclass
from typing import Optional, Callable, Dict, List
import numpy as np

@dataclass
class AudioSegment:
    """Represents a discrete segmented speech turn ready for ASR."""
    channel: str           # "you", "participants", "room"
    pcm_bytes: bytes       # 16kHz 16-bit mono PCM
    timestamp: float       # Wall-clock start time
    duration: float        # Duration in seconds
    turn_id: int           # Sequential turn counter

class ChannelVADTracker:
    """Tracks voice activity and boundaries for a single audio stream."""

    def __init__(
        self,
        channel: str,
        vad_model,
        on_segment_callback: Callable[[AudioSegment], None],
        sample_rate: int = 16000,
        frame_size: int = 512,  # 32ms at 16kHz
        speech_threshold: float = 0.5,
        silence_duration_sec: float = 0.8,
        min_speech_sec: float = 0.6,
        max_speech_sec: float = 12.0
    ):
        self.channel = channel
        self.vad_model = vad_model
        self.on_segment_callback = on_segment_callback
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.speech_threshold = speech_threshold
        
        self.silence_frames_threshold = int(silence_duration_sec * sample_rate / frame_size)
        self.min_speech_frames = int(min_speech_sec * sample_rate / frame_size)
        self.max_speech_frames = int(max_speech_sec * sample_rate / frame_size)
        
        # Ring buffer for pre-speech context (~300ms)
        self.pre_speech_buffer = deque(maxlen=int(0.3 * sample_rate / frame_size))
        
        # State
        self.is_speaking = False
        self.current_speech_frames: List[bytes] = []
        self.silence_counter = 0
        self.speech_start_time = 0.0
        self.leftover_pcm = bytearray()
        self.turn_counter = 0
        self.lock = threading.Lock()

    def process_pcm(self, pcm_data: bytes, current_time: float, turn_counter_func: Callable[[], int]):
        """Processes incoming 16kHz int16 PCM bytes through VAD."""
        with self.lock:
            self.leftover_pcm.extend(pcm_data)
            bytes_per_frame = self.frame_size * 2  # 16-bit = 2 bytes/sample

            while len(self.leftover_pcm) >= bytes_per_frame:
                frame_bytes = bytes(self.leftover_pcm[:bytes_per_frame])
                del self.leftover_pcm[:bytes_per_frame]

                # Convert to float32 normalized [-1.0, 1.0] for VAD
                samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                
                # Check speech probability
                try:
                    if self.vad_model is not None:
                        prob = float(self.vad_model(samples)[0])
                    else:
                        # Energy-based fallback: RMS
                        rms = np.sqrt(np.mean(samples ** 2))
                        prob = 1.0 if rms > 0.02 else 0.0
                except Exception:
                    rms = np.sqrt(np.mean(samples ** 2))
                    prob = 1.0 if rms > 0.02 else 0.0

                is_voice = prob >= self.speech_threshold

                if is_voice:
                    if not self.is_speaking:
                        # Speech onset
                        self.is_speaking = True
                        self.speech_start_time = current_time - (len(self.pre_speech_buffer) * (self.frame_size / self.sample_rate))
                        self.current_speech_frames = list(self.pre_speech_buffer)
                    
                    self.current_speech_frames.append(frame_bytes)
                    self.silence_counter = 0
                    
                    # Cut segment if it reached maximum duration to avoid huge audio chunks
                    if len(self.current_speech_frames) >= self.max_speech_frames:
                        self._flush_segment(turn_counter_func)
                else:
                    if self.is_speaking:
                        self.current_speech_frames.append(frame_bytes)
                        self.silence_counter += 1
                        
                        if self.silence_counter >= self.silence_frames_threshold:
                            # Speech ended naturally
                            self._flush_segment(turn_counter_func)
                    else:
                        self.pre_speech_buffer.append(frame_bytes)

    def _flush_segment(self, turn_counter_func: Callable[[], int]):
        """Emits completed speech segment if it meets minimum duration."""
        if len(self.current_speech_frames) >= self.min_speech_frames:
            combined_pcm = b"".join(self.current_speech_frames)
            duration = len(combined_pcm) / (self.sample_rate * 2)
            turn_id = turn_counter_func()
            
            segment = AudioSegment(
                channel=self.channel,
                pcm_bytes=combined_pcm,
                timestamp=self.speech_start_time,
                duration=duration,
                turn_id=turn_id
            )
            try:
                self.on_segment_callback(segment)
            except Exception as e:
                print(f"[VADSegmenter] Error in segment callback: {e}")

        # Reset state
        self.is_speaking = False
        self.current_speech_frames = []
        self.silence_counter = 0
        self.pre_speech_buffer.clear()

    def reset(self):
        """Resets tracker state."""
        with self.lock:
            self.is_speaking = False
            self.current_speech_frames.clear()
            self.pre_speech_buffer.clear()
            self.silence_counter = 0
            self.leftover_pcm.clear()

class VADSegmenter:
    """Multi-channel VAD and turn segmentation controller."""

    def __init__(
        self,
        on_segment_callback: Callable[[AudioSegment], None],
        meeting_mode: str = "virtual"
    ):
        self.on_segment_callback = on_segment_callback
        self.meeting_mode = meeting_mode
        self.global_turn_id = 0
        self.turn_lock = threading.Lock()
        
        # Initialize Silero VAD
        self.vad_model = None
        try:
            from faster_whisper.vad import get_vad_model
            self.vad_model = get_vad_model()
            print("[VADSegmenter] Silero VAD loaded successfully.")
        except Exception as e:
            print(f"[VADSegmenter] Notice: Using energy VAD fallback ({e})")

        # Trackers map
        self.trackers: Dict[str, ChannelVADTracker] = {}
        self._init_trackers()

    def _next_turn_id(self) -> int:
        with self.turn_lock:
            self.global_turn_id += 1
            return self.global_turn_id

    def _init_trackers(self):
        self.trackers.clear()
        if self.meeting_mode == "in_person":
            self.trackers["room"] = ChannelVADTracker("room", self.vad_model, self.on_segment_callback)
        elif self.meeting_mode == "hybrid":
            self.trackers["room"] = ChannelVADTracker("room", self.vad_model, self.on_segment_callback)
            self.trackers["participants"] = ChannelVADTracker("participants", self.vad_model, self.on_segment_callback)
        else:  # virtual (default)
            self.trackers["you"] = ChannelVADTracker("you", self.vad_model, self.on_segment_callback)
            self.trackers["participants"] = ChannelVADTracker("participants", self.vad_model, self.on_segment_callback)

    def set_meeting_mode(self, mode: str):
        """Updates meeting mode and re-initializes channel trackers."""
        if mode in ("virtual", "in_person", "hybrid"):
            self.meeting_mode = mode
            self._init_trackers()
            print(f"[VADSegmenter] Meeting mode switched to: {mode}")

    def push_audio(self, channel: str, pcm_bytes: bytes):
        """Ingests raw 16kHz PCM data from audio recorder tap."""
        # Map channel name according to current mode
        target_channel = channel
        if self.meeting_mode == "in_person":
            target_channel = "room"
        elif self.meeting_mode == "virtual":
            if channel == "mic":
                target_channel = "you"
            elif channel == "loopback":
                target_channel = "participants"
        elif self.meeting_mode == "hybrid":
            if channel == "mic":
                target_channel = "room"
            elif channel == "loopback":
                target_channel = "participants"

        tracker = self.trackers.get(target_channel)
        if tracker:
            tracker.process_pcm(pcm_bytes, time.time(), self._next_turn_id)

    def reset(self):
        """Resets all trackers."""
        with self.turn_lock:
            self.global_turn_id = 0
        for tracker in self.trackers.values():
            tracker.reset()
