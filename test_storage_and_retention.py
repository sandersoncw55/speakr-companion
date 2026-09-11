import os
import sys
import time
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import Settings
from core.storage import RecordingsManager

class TestStorageAndRetention(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("test_temp_storage_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        self.settings = Settings()
        self.settings.settings_dir = self.test_dir
        self.settings.data = self.settings.data.copy()
        self.settings.data["local_recordings_dir"] = str(self.test_dir / "recordings")
        self.settings.data["retention_days"] = 30
        
        self.storage = RecordingsManager(self.settings)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_duration_formatting(self):
        self.assertEqual(RecordingsManager.format_duration(0), "00:00")
        self.assertEqual(RecordingsManager.format_duration(45), "00:45")
        self.assertEqual(RecordingsManager.format_duration(125), "02:05")
        self.assertEqual(RecordingsManager.format_duration(3665), "01:01:05")

    def test_size_formatting(self):
        self.assertEqual(RecordingsManager.format_size(500), "500 B")
        self.assertEqual(RecordingsManager.format_size(2048), "2.0 KB")
        self.assertEqual(RecordingsManager.format_size(5 * 1024 * 1024), "5.0 MB")

    def test_add_and_update_recording(self):
        dummy_file = str(self.test_dir / "test_rec.mp4")
        with open(dummy_file, "w") as f:
            f.write("audio data")

        # Add
        rec = self.storage.add_recording(
            file_path=dummy_file,
            trigger="manual",
            duration_seconds=120.5,
            tag_ids=[1, 2],
            status="Local Only"
        )
        self.assertEqual(rec["filename"], "test_rec.mp4")
        self.assertEqual(rec["trigger"], "manual")
        self.assertEqual(rec["status"], "Local Only")

        # Update
        self.storage.update_status(dummy_file, "Uploaded", server_id="rec_123")
        recordings = self.storage.get_recordings()
        self.assertEqual(len(recordings), 1)
        self.assertEqual(recordings[0]["status"], "Uploaded")
        self.assertEqual(recordings[0]["server_id"], "rec_123")

    def test_retention_pruning(self):
        rec_dir = self.settings.resolved_recordings_dir
        
        # 1. Fresh file (1 day old)
        fresh_file = str(rec_dir / "fresh.mp4")
        with open(fresh_file, "w") as f:
            f.write("fresh data")
        self.storage.add_recording(fresh_file, "manual", 60.0)
        
        # 2. Old file (35 days old)
        old_file = str(rec_dir / "old.mp4")
        with open(old_file, "w") as f:
            f.write("old data")
        old_time = time.time() - (35 * 86400)
        os.utime(old_file, (old_time, old_time))
        
        old_rec = self.storage.add_recording(old_file, "citrix", 300.0)
        old_rec["created_at"] = old_time
        self.storage.save()

        # Prune with 30-day retention
        pruned = self.storage.prune_expired_recordings(retention_days=30)
        self.assertGreaterEqual(pruned, 1)
        
        # Fresh file must still exist
        self.assertTrue(os.path.exists(fresh_file))
        # Old file must be deleted
        self.assertFalse(os.path.exists(old_file))

if __name__ == "__main__":
    unittest.main()
