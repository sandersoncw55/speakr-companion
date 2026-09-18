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
        "cooldown_seconds": 60,      # 60s cooldown delay after recording stops
        "minimize_to_tray": True,    # Hide window to tray on minimize
        "close_to_tray": True,       # Hide window to tray on close button
        
        # Copilot & Live Meeting Intelligence
        "copilot_enabled": True,
        "meeting_mode": "virtual",   # 'virtual', 'in_person', 'hybrid'
        "asr_provider": "local",     # 'local', 'mac_lan', 'groq', 'openai'
        "asr_model_size": "base.en",
        "asr_cpu_threads": 4,
        "mac_mlx_url": "http://192.168.0.88:9000",
        "groq_api_key": "",
        "openai_api_key": "",
        "gemini_api_key": "",
        "openrouter_api_key": "",
        "llm_provider": "openrouter", # 'openrouter', 'gemini', 'ollama'
        "llm_model": "openai/gpt-4o-mini",
        "privacy_mode": False,       # Locks ASR to Local CPU and LLM to Ollama/offline
        "copilot_cadence_seconds": 35,
        "hud_opacity": 0.92,
        "custom_quick_prompts": []
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

    @property
    def minimize_to_tray(self) -> bool:
        return bool(self.data.get("minimize_to_tray", True))

    @minimize_to_tray.setter
    def minimize_to_tray(self, val: bool) -> None:
        self.data["minimize_to_tray"] = val
        self.save()

    @property
    def close_to_tray(self) -> bool:
        return bool(self.data.get("close_to_tray", True))

    @close_to_tray.setter
    def close_to_tray(self, val: bool) -> None:
        self.data["close_to_tray"] = val
        self.save()

    # --- Copilot Settings Properties ---
    @property
    def copilot_enabled(self) -> bool:
        return bool(self.data.get("copilot_enabled", True))

    @copilot_enabled.setter
    def copilot_enabled(self, val: bool) -> None:
        self.data["copilot_enabled"] = val
        self.save()

    @property
    def meeting_mode(self) -> str:
        return self.data.get("meeting_mode", "virtual")

    @meeting_mode.setter
    def meeting_mode(self, val: str) -> None:
        self.data["meeting_mode"] = val
        self.save()

    @property
    def asr_provider(self) -> str:
        return self.data.get("asr_provider", "local")

    @asr_provider.setter
    def asr_provider(self, val: str) -> None:
        self.data["asr_provider"] = val
        self.save()

    @property
    def asr_model_size(self) -> str:
        return self.data.get("asr_model_size", "base.en")

    @asr_model_size.setter
    def asr_model_size(self, val: str) -> None:
        self.data["asr_model_size"] = val
        self.save()

    @property
    def asr_cpu_threads(self) -> int:
        return int(self.data.get("asr_cpu_threads", 4))

    @asr_cpu_threads.setter
    def asr_cpu_threads(self, val: int) -> None:
        self.data["asr_cpu_threads"] = val
        self.save()

    @property
    def mac_mlx_url(self) -> str:
        return self.data.get("mac_mlx_url", "http://192.168.0.88:9000")

    @mac_mlx_url.setter
    def mac_mlx_url(self, val: str) -> None:
        self.data["mac_mlx_url"] = val
        self.save()

    @property
    def groq_api_key(self) -> str:
        return self.data.get("groq_api_key", "")

    @groq_api_key.setter
    def groq_api_key(self, val: str) -> None:
        self.data["groq_api_key"] = val
        self.save()

    @property
    def openai_api_key(self) -> str:
        return self.data.get("openai_api_key", "")

    @openai_api_key.setter
    def openai_api_key(self, val: str) -> None:
        self.data["openai_api_key"] = val
        self.save()

    @property
    def gemini_api_key(self) -> str:
        return self.data.get("gemini_api_key", "")

    @gemini_api_key.setter
    def gemini_api_key(self, val: str) -> None:
        self.data["gemini_api_key"] = val
        self.save()

    @property
    def openrouter_api_key(self) -> str:
        return self.data.get("openrouter_api_key", "")

    @openrouter_api_key.setter
    def openrouter_api_key(self, val: str) -> None:
        self.data["openrouter_api_key"] = val
        self.save()

    @property
    def llm_provider(self) -> str:
        return self.data.get("llm_provider", "offline")

    @llm_provider.setter
    def llm_provider(self, val: str) -> None:
        self.data["llm_provider"] = val
        self.save()

    @property
    def llm_model(self) -> str:
        return self.data.get("llm_model", "openai/gpt-4o-mini")

    @llm_model.setter
    def llm_model(self, val: str) -> None:
        self.data["llm_model"] = val
        self.save()

    @property
    def ollama_endpoint(self) -> str:
        return self.data.get("ollama_endpoint", "http://localhost:11434/api/generate")

    @ollama_endpoint.setter
    def ollama_endpoint(self, val: str) -> None:
        self.data["ollama_endpoint"] = val
        self.save()

    @property
    def lm_studio_endpoint(self) -> str:
        return self.data.get("lm_studio_endpoint", "http://localhost:1234/v1")

    @lm_studio_endpoint.setter
    def lm_studio_endpoint(self, val: str) -> None:
        self.data["lm_studio_endpoint"] = val
        self.save()

    @property
    def lm_studio_server_type(self) -> str:
        return self.data.get("lm_studio_server_type", "local")

    @lm_studio_server_type.setter
    def lm_studio_server_type(self, val: str) -> None:
        self.data["lm_studio_server_type"] = val
        self.save()

    @property
    def lm_studio_model(self) -> str:
        return self.data.get("lm_studio_model", "local-model")

    @lm_studio_model.setter
    def lm_studio_model(self, val: str) -> None:
        self.data["lm_studio_model"] = val
        self.save()

    @property
    def privacy_mode(self) -> bool:
        return bool(self.data.get("privacy_mode", False))

    @privacy_mode.setter
    def privacy_mode(self, val: bool) -> None:
        self.data["privacy_mode"] = val
        self.save()

    @property
    def copilot_cadence_seconds(self) -> int:
        return int(self.data.get("copilot_cadence_seconds", 35))

    @copilot_cadence_seconds.setter
    def copilot_cadence_seconds(self, val: int) -> None:
        self.data["copilot_cadence_seconds"] = val
        self.save()

    @property
    def hud_opacity(self) -> float:
        return float(self.data.get("hud_opacity", 0.92))

    @hud_opacity.setter
    def hud_opacity(self, val: float) -> None:
        self.data["hud_opacity"] = val
        self.save()

    @property
    def hud_pinned(self) -> bool:
        return bool(self.data.get("hud_pinned", True))

    @hud_pinned.setter
    def hud_pinned(self, val: bool) -> None:
        self.data["hud_pinned"] = val
        self.save()

    @property
    def custom_quick_prompts(self) -> List[Dict[str, str]]:
        return self.data.get("custom_quick_prompts", [])

    @custom_quick_prompts.setter
    def custom_quick_prompts(self, val: List[Dict[str, str]]) -> None:
        self.data["custom_quick_prompts"] = val
        self.save()

