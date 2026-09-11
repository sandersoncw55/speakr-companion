import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller bundle."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        # Root directory of the application
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

def get_app_icon() -> QIcon:
    """Returns the application QIcon with multi-format fallback handling."""
    for name in ["app_icon.ico", "app_icon.png"]:
        path = get_resource_path(name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    # Fallback to standard volume icon if files missing
    if QApplication.instance():
        return QApplication.style().standardIcon(QStyle.SP_MediaVolume)
    return QIcon()


class Settings:
    """Manages application settings stored in a local JSON file."""

    DEFAULT_SETTINGS = {
        "servers": [
            {
                "name": "Default Speakr",
                "url": "http://192.168.0.88:8899",
                "api_key": ""
            }
        ],
        "active_server_idx": 0,
        "upload_mode": "api",  # 'api' or 'folder'
        "nas_folder_path": "Z:\\AudioRecordings\\Inbox",
        "auto_record_enabled": True,
        "auto_upload_enabled": True,
        "selected_mic": "Default",
        "selected_speaker": "Default",
        "recording_format": "mp4",  # 'mp4' (AAC) or 'wav' (PCM)
        "zoom_auto_record": True,
        "teams_auto_record": True,
        "citrix_auto_record": True,
        "local_recordings_dir": "",  # Empty string defaults to AppData/SpeakrCompanion/recordings
        "retention_days": 30,        # 30 days retention policy (0 = keep forever)
        "cooldown_seconds": 60       # 60s cooldown delay after recording stops
    }

    def __init__(self):
        # Determine settings file path
        appdata_dir = os.getenv("LOCALAPPDATA")
        if appdata_dir:
            self.settings_dir = Path(appdata_dir) / "SpeakrCompanion"
        else:
            self.settings_dir = Path.home() / ".speakr_companion"

        self.settings_file = self.settings_dir / "settings.json"
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load settings from the JSON file, or initialize with defaults if not present."""
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            if self.settings_file.exists():
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    # Merge loaded data with defaults to handle new settings fields
                    self.data = {**self.DEFAULT_SETTINGS, **file_data}
            else:
                self.data = self.DEFAULT_SETTINGS.copy()
                self.save()
        except Exception as e:
            print(f"[Config] Error loading settings: {e}")
            self.data = self.DEFAULT_SETTINGS.copy()

    def save(self) -> None:
        """Save settings to the JSON file."""
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error saving settings: {e}")

    # Properties for easy access
    @property
    def servers(self) -> List[Dict[str, str]]:
        return self.data.get("servers", self.DEFAULT_SETTINGS["servers"])

    @servers.setter
    def servers(self, val: List[Dict[str, str]]) -> None:
        self.data["servers"] = val
        self.save()

    @property
    def active_server_idx(self) -> int:
        return self.data.get("active_server_idx", 0)

    @active_server_idx.setter
    def active_server_idx(self, val: int) -> None:
        self.data["active_server_idx"] = val
        self.save()

    @property
    def active_server(self) -> Dict[str, str]:
        idx = self.active_server_idx
        servers = self.servers
        if 0 <= idx < len(servers):
            return servers[idx]
        if servers:
            return servers[0]
        return {"name": "Default Speakr", "url": "http://192.168.0.88:8899", "api_key": ""}

    @property
    def upload_mode(self) -> str:
        return self.data.get("upload_mode", "api")

    @upload_mode.setter
    def upload_mode(self, val: str) -> None:
        self.data["upload_mode"] = val
        self.save()

    @property
    def nas_folder_path(self) -> str:
        return self.data.get("nas_folder_path", "Z:\\AudioRecordings\\Inbox")

    @nas_folder_path.setter
    def nas_folder_path(self, val: str) -> None:
        self.data["nas_folder_path"] = val
        self.save()

    @property
    def auto_record_enabled(self) -> bool:
        return self.data.get("auto_record_enabled", True)

    @auto_record_enabled.setter
    def auto_record_enabled(self, val: bool) -> None:
        self.data["auto_record_enabled"] = val
        self.save()

    @property
    def auto_upload_enabled(self) -> bool:
        return self.data.get("auto_upload_enabled", True)

    @auto_upload_enabled.setter
    def auto_upload_enabled(self, val: bool) -> None:
        self.data["auto_upload_enabled"] = val
        self.save()

    @property
    def selected_mic(self) -> str:
        return self.data.get("selected_mic", "Default")

    @selected_mic.setter
    def selected_mic(self, val: str) -> None:
        self.data["selected_mic"] = val
        self.save()

    @property
    def selected_speaker(self) -> str:
        return self.data.get("selected_speaker", "Default")

    @selected_speaker.setter
    def selected_speaker(self, val: str) -> None:
        self.data["selected_speaker"] = val
        self.save()

    @property
    def recording_format(self) -> str:
        return self.data.get("recording_format", "mp4")

    @recording_format.setter
    def recording_format(self, val: str) -> None:
        self.data["recording_format"] = val
        self.save()

    @property
    def zoom_auto_record(self) -> bool:
        return self.data.get("zoom_auto_record", True)

    @zoom_auto_record.setter
    def zoom_auto_record(self, val: bool) -> None:
        self.data["zoom_auto_record"] = val
        self.save()

    @property
    def teams_auto_record(self) -> bool:
        return self.data.get("teams_auto_record", True)

    @teams_auto_record.setter
    def teams_auto_record(self, val: bool) -> None:
        self.data["teams_auto_record"] = val
        self.save()

    @property
    def citrix_auto_record(self) -> bool:
        return self.data.get("citrix_auto_record", True)

    @citrix_auto_record.setter
    def citrix_auto_record(self, val: bool) -> None:
        self.data["citrix_auto_record"] = val
        self.save()

    @property
    def local_recordings_dir(self) -> str:
        return self.data.get("local_recordings_dir", "")

    @local_recordings_dir.setter
    def local_recordings_dir(self, val: str) -> None:
        self.data["local_recordings_dir"] = val
        self.save()

    @property
    def resolved_recordings_dir(self) -> Path:
        """Returns the configured Path or defaults to settings_dir/recordings."""
        custom = self.local_recordings_dir.strip()
        if custom:
            p = Path(custom)
            if not p.is_absolute():
                p = (self.settings_dir / p).resolve()
        else:
            p = (self.settings_dir / "recordings").resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return p

    @property
    def retention_days(self) -> int:
        return int(self.data.get("retention_days", 30))

    @retention_days.setter
    def retention_days(self, val: int) -> None:
        self.data["retention_days"] = val
        self.save()

    @property
    def cooldown_seconds(self) -> int:
        return int(self.data.get("cooldown_seconds", 60))

    @cooldown_seconds.setter
    def cooldown_seconds(self, val: int) -> None:
        self.data["cooldown_seconds"] = val
        self.save()

