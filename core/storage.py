import os
import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from core.config import Settings

class RecordingsManager:
    """Manages local recordings library, metadata history, and retention pruning with thread safety."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.history_file = self.settings.settings_dir / "recordings_history.json"
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        """Loads recording history metadata from JSON file."""
        with self._lock:
            try:
                if self.history_file.exists():
                    with open(self.history_file, "r", encoding="utf-8") as f:
                        self._history = json.load(f)
                else:
                    self._history = []
            except Exception as e:
                print(f"[Storage] Error loading history: {e}")
                self._history = []

    def save(self) -> None:
        """Atomically saves recording history metadata to JSON file."""
        with self._lock:
            try:
                self.settings.settings_dir.mkdir(parents=True, exist_ok=True)
                temp_file = self.history_file.with_suffix(".tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self._history, f, indent=2, ensure_ascii=False)
                # Atomic file replace
                temp_file.replace(self.history_file)
            except Exception as e:
                print(f"[Storage] Error saving history: {e}")

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Formats seconds into HH:MM:SS or MM:SS."""
        if seconds < 0:
            seconds = 0
        secs = int(seconds)
        mins, s = divmod(secs, 60)
        hrs, m = divmod(mins, 60)
        if hrs > 0:
            return f"{hrs:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """Formats bytes into human-readable size."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def add_recording(
        self,
        file_path: str,
        trigger: str = "manual",
        duration_seconds: float = 0.0,
        tag_ids: Optional[List[int]] = None,
        status: str = "Local Only",
        server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Adds a new recording record to the history."""
        abs_path = str(Path(file_path).resolve())
        size_bytes = 0
        if os.path.exists(abs_path):
            try:
                size_bytes = os.path.getsize(abs_path)
            except Exception:
                pass

        now = time.time()
        record = {
            "file_path": abs_path,
            "filename": os.path.basename(abs_path),
            "created_at": now,
            "created_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "trigger": trigger.lower(),
            "duration_seconds": round(duration_seconds, 1),
            "size_bytes": size_bytes,
            "tag_ids": tag_ids or [],
            "status": status,
            "server_id": server_id
        }

        with self._lock:
            # Check if record already exists for this path or filename, update it if so
            updated = False
            for i, item in enumerate(self._history):
                if item.get("file_path") == abs_path or item.get("filename") == record["filename"]:
                    self._history[i] = record
                    updated = True
                    break

            if not updated:
                self._history.insert(0, record)  # Newest first

            self.save()
        return record

    def update_status(self, file_path: str, status: str, server_id: Optional[str] = None) -> None:
        """Updates upload status and server ID for a recording."""
        target_name = os.path.basename(file_path)
        with self._lock:
            for item in self._history:
                if item.get("file_path") == file_path or item.get("filename") == target_name:
                    item["status"] = status
                    if server_id:
                        item["server_id"] = server_id
                    break
            self.save()

    def get_recordings(self) -> List[Dict[str, Any]]:
        """Returns all history items, verifying file existence status."""
        with self._lock:
            self.load()
            for item in self._history:
                path = item.get("file_path", "")
                item["exists_locally"] = bool(path and os.path.exists(path))
                if item["exists_locally"]:
                    try:
                        item["size_bytes"] = os.path.getsize(path)
                    except Exception:
                        pass
            return list(self._history)

    def delete_recording(self, file_path: str) -> bool:
        """Deletes recording file from disk and removes from history."""
        target_name = os.path.basename(file_path)
        with self._lock:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"[Storage] Error removing file {file_path}: {e}")

            self._history = [
                item for item in self._history 
                if item.get("file_path") != file_path and item.get("filename") != target_name
            ]
            self.save()
        return True

    def prune_expired_recordings(self, retention_days: Optional[int] = None) -> int:
        """Prunes recording files older than retention_days. 0 = keep forever."""
        if retention_days is None:
            retention_days = self.settings.retention_days

        if retention_days <= 0:
            return 0  # Retention disabled / keep forever

        cutoff_time = time.time() - (retention_days * 86400.0)
        pruned_count = 0

        with self._lock:
            # 1. Prune tracked files in history
            remaining = []
            for item in self._history:
                created = item.get("created_at", 0.0)
                file_path = item.get("file_path", "")
                if created > 0 and created < cutoff_time:
                    try:
                        if file_path and os.path.exists(file_path):
                            os.remove(file_path)
                            print(f"[Storage] Pruned expired recording ({retention_days}d retention): {file_path}")
                            pruned_count += 1
                    except Exception as e:
                        print(f"[Storage] Error pruning expired file {file_path}: {e}")
                else:
                    remaining.append(item)

            self._history = remaining
            self.save()

            # 2. Also scan recordings folder for any untracked audio files older than cutoff
            try:
                rec_dir = self.settings.resolved_recordings_dir
                if rec_dir.exists():
                    for entry in rec_dir.iterdir():
                        if entry.is_file() and entry.suffix.lower() in [".mp4", ".wav", ".aac"]:
                            try:
                                mtime = entry.stat().st_mtime
                                if mtime < cutoff_time:
                                    entry.unlink()
                                    print(f"[Storage] Pruned untracked expired file: {entry}")
                                    pruned_count += 1
                            except Exception as ex:
                                print(f"[Storage] Error inspecting {entry}: {ex}")
            except Exception as e:
                print(f"[Storage] Error scanning directory for pruning: {e}")

        return pruned_count
