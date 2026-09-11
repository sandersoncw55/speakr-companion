import os
import time
import math
import threading
from typing import Dict, Any, List, Optional, Callable
import psutil
from core.config import Settings
from core.recorder import AudioRecorder

try:
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False

class ProcessMonitor:
    """Monitors running processes and manages audio-gated auto-recording triggers."""

    def __init__(
        self, 
        settings: Settings, 
        recorder: AudioRecorder, 
        upload_callback: Callable[[str, List[int]], None],
        start_callback: Optional[Callable[[str], None]] = None,
        cooldown_callback: Optional[Callable[[float], None]] = None
    ):
        self.settings = settings
        self.recorder = recorder
        self.upload_callback = upload_callback
        self.start_callback = start_callback
        self.cooldown_callback = cooldown_callback
        
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Monitor configuration
        self.check_interval = 0.5  # Responsive polling for debounce and silence tracking
        
        # State tracking
        self.active_trigger_process: Optional[str] = None
        self.recording_start_time = 0.0
        self.cooldown_until = 0.0
        
        # Citrix audio-gating rules
        self.citrix_active_audio_seconds = 0.0
        self.continuous_silence_seconds = 0.0
        self.citrix_debounce_seconds = 0.0
        self.last_state_check_time = 0.0
        
        # Thresholds
        self.audio_active_threshold_db = -48.0  # Decibels threshold for meeting audio
        self.citrix_debounce_threshold = 2.0     # 2 seconds debounce before starting recording
        self.citrix_silence_timeout = 300.0      # 5 minutes (300s) silence tolerance before stopping
        self.citrix_min_active_audio = 30.0      # Discard recording if < 30s accumulated active audio
        
        # Selected tags for the current recording
        self.current_tags: List[int] = []

    def start(self) -> None:
        """Starts the process monitoring thread."""
        if self.is_running:
            return
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("[Monitor] Process and audio activity monitoring started.")

    def stop(self) -> None:
        """Stops the process monitoring thread."""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        print("[Monitor] Process activity monitoring stopped.")

    def _check_running_processes(self) -> Dict[str, bool]:
        """Checks for target process presence in running list."""
        results = {
            "zoom": False,
            "teams": False,
            "citrix": False
        }
        
        citrix_keywords = ["wfica", "cdviewer", "citrix", "wfcrun", "receiver", "msteamsvdi", "concentr"]
        
        try:
            for proc in psutil.process_iter(attrs=["name"]):
                try:
                    name = proc.info["name"]
                    if not name:
                        continue
                    name_lower = name.lower()
                    
                    if "cpthost.exe" in name_lower:
                        results["zoom"] = True
                    # Check Citrix: matches wfica32.exe, cdviewer.exe, Citrix.DesktopViewer, receiver, msteamsvdi, etc.
                    elif any(k in name_lower for k in citrix_keywords):
                        results["citrix"] = True
                    # Check Teams: matches teams.exe or ms-teams.exe or msteams.exe
                    elif ("teams.exe" in name_lower or "ms-teams" in name_lower or "msteams" in name_lower) and "vdi" not in name_lower:
                        results["teams"] = True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            print(f"[Monitor] Process checking error: {e}")
            
        return results

    def _get_citrix_audio_peak_db(self) -> float:
        """Meters the instantaneous audio peak level in decibels for all Citrix audio sessions."""
        if not HAS_PYCAW:
            return -96.0
        
        citrix_keywords = ["wfica", "cdviewer", "citrix", "wfcrun", "receiver", "msteamsvdi", "concentr"]
        max_peak = 0.0
        
        try:
            comtypes.CoInitialize()
            try:
                sessions = AudioUtilities.GetAllSessions()
                for session in sessions:
                    proc = session.Process
                    if not proc:
                        continue
                    try:
                        pname = proc.name().lower()
                    except Exception:
                        continue
                    if any(k in pname for k in citrix_keywords):
                        try:
                            meter = session._ctl.QueryInterface(IAudioMeterInformation)
                            peak = meter.GetPeakValue()
                            if peak > max_peak:
                                max_peak = peak
                        except Exception:
                            pass
            finally:
                comtypes.CoUninitialize()
        except Exception as e:
            pass
        
        if max_peak <= 0.0:
            return -96.0
        db = 20 * math.log10(max_peak)
        return max(-96.0, min(0.0, db))

    def trigger_cooldown(self, seconds: Optional[float] = None) -> None:
        """Arms the cooldown timer to prevent immediate auto/manual re-triggers."""
        if seconds is None:
            seconds = float(self.settings.cooldown_seconds)
        self.cooldown_until = time.time() + seconds
        print(f"[Monitor] Cooldown activated for {seconds:.0f} seconds.")
        if self.cooldown_callback:
            try:
                self.cooldown_callback(seconds)
            except Exception as e:
                print(f"[Monitor] cooldown_callback error: {e}")

    def cancel_cooldown(self) -> None:
        """Cancels any active cooldown."""
        self.cooldown_until = 0.0
        print("[Monitor] Cooldown cancelled.")

    def _monitor_loop(self) -> None:
        """Main monitoring loop with audio-gated meeting detection."""
        self.last_state_check_time = time.time()
        
        while self.is_running:
            # Check settings
            if not self.settings.auto_record_enabled:
                # If auto-record was disabled while we were auto-recording, stop the recording
                if self.active_trigger_process is not None:
                    self._stop_and_handle_upload()
                self.citrix_debounce_seconds = 0.0
                time.sleep(self.check_interval)
                continue

            current_time = time.time()
            dt = current_time - self.last_state_check_time
            self.last_state_check_time = current_time

            # Check if currently in post-recording cooldown
            if current_time < self.cooldown_until:
                self.citrix_debounce_seconds = 0.0
                time.sleep(self.check_interval)
                continue

            # Poll processes
            process_states = self._check_running_processes()

            # State machine: Idle vs Recording
            if self.active_trigger_process is None:
                # If user is currently manual recording, do NOT hijack
                if self.recorder.is_recording:
                    self.citrix_debounce_seconds = 0.0
                    time.sleep(self.check_interval)
                    continue

                active_trigger = None

                # 1. Direct process triggers (Zoom / Teams)
                if process_states["zoom"] and self.settings.zoom_auto_record:
                    active_trigger = "zoom"
                elif process_states["teams"] and self.settings.teams_auto_record:
                    active_trigger = "teams"
                
                # 2. Audio-gated Citrix trigger (Citrix running + 2s debounce above -48 dB)
                elif process_states["citrix"] and self.settings.citrix_auto_record:
                    citrix_db = self._get_citrix_audio_peak_db()
                    if citrix_db > self.audio_active_threshold_db:
                        self.citrix_debounce_seconds += dt
                        if self.citrix_debounce_seconds >= self.citrix_debounce_threshold:
                            print(f"[Monitor] Citrix audio ({citrix_db:.1f} dB) debounced for {self.citrix_debounce_seconds:.1f}s. Triggering recording!")
                            active_trigger = "citrix"
                    else:
                        self.citrix_debounce_seconds = 0.0
                else:
                    self.citrix_debounce_seconds = 0.0

                # Idle state -> Start recording if trigger fired
                if active_trigger is not None:
                    self.active_trigger_process = active_trigger
                    self.recording_start_time = current_time
                    self.citrix_active_audio_seconds = 0.0
                    self.continuous_silence_seconds = 0.0
                    self.citrix_debounce_seconds = 0.0
                    
                    # Generate recording filename in configured recordings directory
                    rec_dir = self.settings.resolved_recordings_dir
                    rec_dir.mkdir(parents=True, exist_ok=True)
                    ext = self.settings.recording_format.lower().lstrip(".")
                    timestamp_str = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(current_time))
                    file_name = f"Meeting_{timestamp_str}_Auto{active_trigger.capitalize()}.{ext}"
                    output_path = str(rec_dir / file_name)
                    
                    self.recorder.start_recording(
                        output_path=output_path,
                        mic_name=self.settings.selected_mic,
                        speaker_name=self.settings.selected_speaker
                    )
                    if self.start_callback:
                        try:
                            self.start_callback(active_trigger)
                        except Exception as ex:
                            print(f"[Monitor] start_callback error: {ex}")
            else:
                # Recording state
                proc = self.active_trigger_process
                if proc == "zoom":
                    if not process_states["zoom"]:
                        self._stop_and_handle_upload()
                elif proc == "teams":
                    if not process_states["teams"]:
                        self._stop_and_handle_upload()
                elif proc == "citrix":
                    if not process_states["citrix"]:
                        # Citrix application was closed
                        print("[Monitor] Citrix process closed. Stopping recording...")
                        self._stop_and_handle_upload()
                    else:
                        # Check audio activity during Citrix recording
                        spk_db = self.recorder.current_speaker_db
                        mic_db = self.recorder.current_mic_db
                        citrix_db = self._get_citrix_audio_peak_db()
                        effective_db = max(spk_db, mic_db, citrix_db)
                        
                        # Active audio accumulation
                        if effective_db > self.audio_active_threshold_db:
                            self.citrix_active_audio_seconds += dt
                            self.continuous_silence_seconds = 0.0
                        else:
                            self.continuous_silence_seconds += dt
                        
                        # Silence tolerance: stop recording if silence exceeds 5 minutes (300 seconds)
                        if self.continuous_silence_seconds >= self.citrix_silence_timeout:
                            print(f"[Monitor] Citrix silence exceeded {self.citrix_silence_timeout:.0f}s (5 minutes). Stopping recording...")
                            self._stop_and_handle_upload()

            time.sleep(self.check_interval)

    def _stop_and_handle_upload(self) -> None:
        """Stops the recorder and dispatches the file to uploader or discards it."""
        if self.active_trigger_process is None:
            return

        proc = self.active_trigger_process
        self.active_trigger_process = None
        
        file_path = self.recorder.output_file_path
        self.recorder.stop_recording()

        # Arm cooldown timer
        self.trigger_cooldown()

        if not file_path or not os.path.exists(file_path):
            return

        # Citrix rule: discard if total active audio < 30 seconds
        if proc == "citrix" and self.citrix_active_audio_seconds < self.citrix_min_active_audio:
            print(f"[Monitor] Citrix active audio ({self.citrix_active_audio_seconds:.1f}s) was < {self.citrix_min_active_audio:.0f}s threshold. Discarding recording.")
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"[Monitor] Error deleting discarded Citrix recording: {e}")
            return

        # Trigger upload callback
        self.upload_callback(file_path, self.current_tags.copy())
        # Clear tags for next run
        self.current_tags.clear()
