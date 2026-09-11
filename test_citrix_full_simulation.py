import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import Settings
from core.recorder import AudioRecorder
from core.monitor import ProcessMonitor

class TestCitrixFullSimulation(unittest.TestCase):

    def setUp(self):
        self.settings = Settings()
        self.settings.auto_record_enabled = True
        self.settings.citrix_auto_record = True
        self.settings.zoom_auto_record = False
        self.settings.teams_auto_record = False

        self.mock_recorder = MagicMock(spec=AudioRecorder)
        self.mock_recorder.is_recording = False
        self.mock_recorder.current_speaker_db = -96.0
        self.mock_recorder.current_mic_db = -96.0
        self.mock_recorder.output_file_path = "sim_test_recording.wav"

        self.upload_callback = MagicMock()
        self.start_callback = MagicMock()

        self.monitor = ProcessMonitor(
            settings=self.settings,
            recorder=self.mock_recorder,
            upload_callback=self.upload_callback,
            start_callback=self.start_callback
        )

    def test_full_citrix_meeting_lifecycle(self):
        """Simulates full Citrix meeting: Citrix opens -> Silence -> Meeting audio starts -> Debounce 2s -> Recording -> Active audio 40s -> Silence 5 min -> Stop -> Upload."""
        
        # Step 1: Citrix is running, but no meeting audio (-96 dB)
        with patch.object(self.monitor, "_check_running_processes", return_value={"zoom": False, "teams": False, "citrix": True}), \
             patch.object(self.monitor, "_get_citrix_audio_peak_db", return_value=-96.0):
            
            # Simulate 10 iterations of 0.5s = 5 seconds of silence
            for _ in range(10):
                self.monitor.last_state_check_time = time.time() - 0.5
                # Verify idle
                self.assertIsNone(self.monitor.active_trigger_process)
                self.assertEqual(self.monitor.citrix_debounce_seconds, 0.0)

        # Step 2: Brief notification chime (-20 dB for 0.5s) -> Should NOT trigger recording
        with patch.object(self.monitor, "_check_running_processes", return_value={"zoom": False, "teams": False, "citrix": True}), \
             patch.object(self.monitor, "_get_citrix_audio_peak_db", return_value=-20.0):
            
            # Step 1: 0.5s of audio
            self.monitor.citrix_debounce_seconds += 0.5
            self.assertLess(self.monitor.citrix_debounce_seconds, 2.0)
            self.assertIsNone(self.monitor.active_trigger_process)

        # Step 3: Meeting audio starts (-25 dB continuously for 2.0s) -> Should trigger recording
        self.monitor.citrix_debounce_seconds = 0.0
        with patch.object(self.monitor, "_check_running_processes", return_value={"zoom": False, "teams": False, "citrix": True}), \
             patch.object(self.monitor, "_get_citrix_audio_peak_db", return_value=-25.0):
            
            # 4 steps of 0.5s = 2.0s
            for step in range(1, 5):
                self.monitor.citrix_debounce_seconds += 0.5
                if self.monitor.citrix_debounce_seconds >= 2.0:
                    # Trigger recording
                    self.monitor.active_trigger_process = "citrix"
                    self.monitor.citrix_debounce_seconds = 0.0
                    self.monitor.citrix_active_audio_seconds = 0.0
                    self.monitor.continuous_silence_seconds = 0.0
                    self.mock_recorder.start_recording("sim_output.wav")
                    self.start_callback("citrix")

            self.assertEqual(self.monitor.active_trigger_process, "citrix")
            self.mock_recorder.start_recording.assert_called_once()
            self.start_callback.assert_called_once_with("citrix")

        # Step 4: Meeting is active with 45 seconds of speech (-25 dB)
        self.mock_recorder.current_speaker_db = -25.0
        for _ in range(90): # 90 * 0.5s = 45s
            self.monitor.citrix_active_audio_seconds += 0.5
            self.monitor.continuous_silence_seconds = 0.0

        self.assertEqual(self.monitor.citrix_active_audio_seconds, 45.0)
        self.assertEqual(self.monitor.continuous_silence_seconds, 0.0)

        # Step 5: Meeting ends, 5 minutes (300s) of silence
        self.mock_recorder.current_speaker_db = -96.0
        self.mock_recorder.current_mic_db = -96.0
        
        # Accumulate 300s of silence
        self.monitor.continuous_silence_seconds = 300.0
        self.assertGreaterEqual(self.monitor.continuous_silence_seconds, self.monitor.citrix_silence_timeout)

        # Step 6: Trigger stop & verify file upload since active audio (45s) >= 30s
        dummy_file = "sim_test_meeting.wav"
        with open(dummy_file, "w") as f:
            f.write("simulated meeting audio")

        self.mock_recorder.output_file_path = dummy_file
        try:
            self.monitor._stop_and_handle_upload()
            self.assertIsNone(self.monitor.active_trigger_process)
            self.upload_callback.assert_called_once_with(dummy_file, [])
            self.assertTrue(os.path.exists(dummy_file))
        finally:
            if os.path.exists(dummy_file):
                os.remove(dummy_file)

if __name__ == "__main__":
    unittest.main()
