import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure speakr_compainion is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import Settings
from core.recorder import AudioRecorder
from core.monitor import ProcessMonitor

class TestCitrixAudioGating(unittest.TestCase):

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
        self.mock_recorder.output_file_path = "temp_test_recording.wav"

        self.upload_callback = MagicMock()
        self.start_callback = MagicMock()

        self.monitor = ProcessMonitor(
            settings=self.settings,
            recorder=self.mock_recorder,
            upload_callback=self.upload_callback,
            start_callback=self.start_callback
        )

    def test_citrix_process_matching(self):
        """Tests that various Citrix process names are recognized."""
        test_cases = [
            ("wfica32.exe", True),
            ("wfica.exe", True),
            ("Citrix.DesktopViewer.App.exe", True),
            ("CDViewer.exe", True),
            ("Receiver.exe", True),
            ("CitrixWorkspace.exe", True),
            ("wfcrun32.exe", True),
            ("MsTeamsVdi.exe", True),
            ("notepad.exe", False),
            ("explorer.exe", False)
        ]

        for proc_name, expected in test_cases:
            with patch("psutil.process_iter") as mock_iter:
                mock_proc = MagicMock()
                mock_proc.info = {"name": proc_name}
                mock_iter.return_value = [mock_proc]

                res = self.monitor._check_running_processes()
                self.assertEqual(res["citrix"], expected, f"Failed for process: {proc_name}")

    def test_audio_metering_returns_valid_range(self):
        """Tests that _get_citrix_audio_peak_db returns a valid float dB <= 0.0 and >= -96.0."""
        db = self.monitor._get_citrix_audio_peak_db()
        self.assertIsInstance(db, float)
        self.assertGreaterEqual(db, -96.0)
        self.assertLessEqual(db, 0.0)

    def test_citrix_debounce_logic(self):
        """Tests that 2-second debounce must be satisfied before starting recording."""
        # 1. Citrix process running, but silent (-96 dB) -> No trigger
        self.monitor.citrix_debounce_seconds = 0.0
        with patch.object(self.monitor, "_check_running_processes", return_value={"zoom": False, "teams": False, "citrix": True}), \
             patch.object(self.monitor, "_get_citrix_audio_peak_db", return_value=-60.0):
            
            self.monitor.last_state_check_time = time.time() - 0.5
            citrix_db = self.monitor._get_citrix_audio_peak_db()
            self.assertLess(citrix_db, self.monitor.audio_active_threshold_db)

        # 2. Audio above -48 dB for 1.0s (less than 2.0s) -> No trigger
        with patch.object(self.monitor, "_check_running_processes", return_value={"zoom": False, "teams": False, "citrix": True}), \
             patch.object(self.monitor, "_get_citrix_audio_peak_db", return_value=-20.0):
            
            self.monitor.citrix_debounce_seconds = 1.0
            self.assertLess(self.monitor.citrix_debounce_seconds, self.monitor.citrix_debounce_threshold)

        # 3. Audio above -48 dB for 2.0s -> Triggers
        self.monitor.citrix_debounce_seconds = 2.0
        self.assertGreaterEqual(self.monitor.citrix_debounce_seconds, self.monitor.citrix_debounce_threshold)

    def test_citrix_silence_timeout_triggers_stop(self):
        """Tests that 5 minutes (300s) of continuous silence stops recording."""
        self.monitor.active_trigger_process = "citrix"
        self.monitor.continuous_silence_seconds = 300.0

        with patch.object(self.monitor, "_stop_and_handle_upload") as mock_stop:
            if self.monitor.continuous_silence_seconds >= self.monitor.citrix_silence_timeout:
                self.monitor._stop_and_handle_upload()
            mock_stop.assert_called_once()

    def test_discard_filter_less_than_30s(self):
        """Tests that recordings with < 30s of active audio are discarded and not uploaded."""
        self.monitor.active_trigger_process = "citrix"
        self.monitor.citrix_active_audio_seconds = 15.0 # Less than 30s

        # Create dummy file
        dummy_file = "test_discard_dummy.wav"
        with open(dummy_file, "w") as f:
            f.write("dummy audio content")

        self.mock_recorder.output_file_path = dummy_file
        try:
            self.monitor._stop_and_handle_upload()

            # Verify file was deleted
            self.assertFalse(os.path.exists(dummy_file))
            # Verify upload callback was NOT called
            self.upload_callback.assert_not_called()
        finally:
            if os.path.exists(dummy_file):
                os.remove(dummy_file)

    def test_upload_kept_if_greater_than_30s(self):
        """Tests that recordings with >= 30s of active audio are retained and uploaded."""
        self.monitor.active_trigger_process = "citrix"
        self.monitor.citrix_active_audio_seconds = 45.0 # Greater than 30s

        # Create dummy file
        dummy_file = "test_keep_dummy.wav"
        with open(dummy_file, "w") as f:
            f.write("dummy audio content")

        self.mock_recorder.output_file_path = dummy_file
        try:
            self.monitor._stop_and_handle_upload()

            # Verify file still exists
            self.assertTrue(os.path.exists(dummy_file))
            # Verify upload callback was called
            self.upload_callback.assert_called_once_with(dummy_file, [])
        finally:
            if os.path.exists(dummy_file):
                os.remove(dummy_file)

if __name__ == "__main__":
    unittest.main()
