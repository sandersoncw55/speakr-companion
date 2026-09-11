import os
import sys
import unittest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.widgets import VolumeMeter
from gui.tray_icon import create_badged_icon
from core.config import Settings, get_app_icon

# Create QApplication for GUI test if not present
app = QApplication.instance() or QApplication(sys.argv)

class TestWidgetsAndTray(unittest.TestCase):

    def test_volume_meter_labels(self):
        mic_meter = VolumeMeter("Microphone")
        spk_meter = VolumeMeter("Speakers (Loopback)")

        # When below min_db (-60.0 dB) -> should show context-aware idle labels, NOT "Mute"
        mic_meter.set_level(-96.0)
        spk_meter.set_level(-96.0)
        self.assertEqual(mic_meter.db_level, -60.0)
        self.assertEqual(spk_meter.db_level, -60.0)

    def test_tray_badged_icon_creation(self):
        icon_ready = create_badged_icon("ready")
        self.assertFalse(icon_ready.isNull())

        icon_rec = create_badged_icon("recording")
        self.assertFalse(icon_rec.isNull())

        icon_paused = create_badged_icon("paused")
        self.assertFalse(icon_paused.isNull())

        icon_cd = create_badged_icon("cooldown")
        self.assertFalse(icon_cd.isNull())

    def test_app_icon_resolution(self):
        icon = get_app_icon()
        self.assertFalse(icon.isNull(), "App icon should load properly from app_icon.ico/png")

    def test_tray_preferences_settings(self):
        settings = Settings()
        # Default should be True
        self.assertTrue(isinstance(settings.minimize_to_tray, bool))
        self.assertTrue(isinstance(settings.close_to_tray, bool))
        
        # Test setter
        original_min = settings.minimize_to_tray
        settings.minimize_to_tray = not original_min
        self.assertEqual(settings.minimize_to_tray, not original_min)
        settings.minimize_to_tray = original_min

if __name__ == "__main__":
    unittest.main()
