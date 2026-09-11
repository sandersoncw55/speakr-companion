import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import Settings
from core.recorder import AudioRecorder
from core.monitor import ProcessMonitor

class TestCooldown(unittest.TestCase):

    def setUp(self):
        self.settings = Settings()
        self.settings.auto_record_enabled = True
        self.settings.cooldown_seconds = 60
        
        self.mock_recorder = MagicMock(spec=AudioRecorder)
        self.mock_recorder.is_recording = False
        self.mock_recorder.output_file_path = "test_cooldown.wav"

        self.cooldown_callback = MagicMock()
        self.upload_callback = MagicMock()

        self.monitor = ProcessMonitor(
            settings=self.settings,
            recorder=self.mock_recorder,
            upload_callback=self.upload_callback,
            cooldown_callback=self.cooldown_callback
        )

    def test_trigger_cooldown(self):
        self.monitor.trigger_cooldown(60.0)
        self.assertGreater(self.monitor.cooldown_until, time.time() + 50)
        self.cooldown_callback.assert_called_once_with(60.0)

    def test_cancel_cooldown(self):
        self.monitor.trigger_cooldown(60.0)
        self.assertGreater(self.monitor.cooldown_until, time.time())
        self.monitor.cancel_cooldown()
        self.assertEqual(self.monitor.cooldown_until, 0.0)

if __name__ == "__main__":
    unittest.main()
