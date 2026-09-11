import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QCheckBox, QComboBox, QLineEdit, 
    QFileDialog, QPlainTextEdit, QGroupBox, QRadioButton, 
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtGui import QIcon, QFont, QColor

from core.config import Settings, get_app_icon, get_resource_path
from core.recorder import AudioRecorder
from core.monitor import ProcessMonitor
from core.client import SpeakrClient
from core.uploader import AudioUploader
from core.storage import RecordingsManager
from gui.widgets import VolumeMeter, TagSelector

class Signaler(QObject):
    """Bridge object to emit thread-safe signals for GUI updates."""
    level_signal = Signal(float, float)
    status_signal = Signal(str, bool)
    auto_record_start_signal = Signal(str)
    auto_record_finish_signal = Signal(str, list)
    cooldown_signal = Signal(float)
    history_updated_signal = Signal()

class ServerDialog(QDialog):
    """Dialog to add or edit Speakr server details."""
    def __init__(self, server_data: Optional[Dict[str, str]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Speakr Server Configuration")
        self.setMinimumWidth(350)
        
        layout = QFormLayout(self)
        
        self.name_input = QLineEdit()
        self.url_input = QLineEdit()
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        
        layout.addRow("Friendly Name:", self.name_input)
        layout.addRow("Base URL:", self.url_input)
        layout.addRow("API Key:", self.key_input)
        
        if server_data:
            self.name_input.setText(server_data.get("name", ""))
            self.url_input.setText(server_data.get("url", ""))
            self.key_input.setText(server_data.get("api_key", ""))
        else:
            self.name_input.setText("My Speakr")
            self.url_input.setText("http://192.168.0.88:8899/api/v1")
            
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_data(self) -> Dict[str, str]:
        return {
            "name": self.name_input.text().strip(),
            "url": self.url_input.text().strip().rstrip("/"),
            "api_key": self.key_input.text().strip()
        }


class MainWindow(QMainWindow):
    """Main application window for Speakr Windows Companion."""

    def __init__(
        self, 
        settings: Settings, 
        recorder: AudioRecorder, 
        uploader: AudioUploader,
        storage: Optional[RecordingsManager] = None
    ):
        super().__init__()
        self.settings = settings
        self.recorder = recorder
        self.storage = storage or RecordingsManager(self.settings)
        self.uploader = uploader
        self.uploader.storage = self.storage
        
        self.last_recording_path: Optional[str] = None
        self.tray_manager = None  # Injected from main.py if available
        self.current_recording_mode: str = "manual"
        
        self.setWindowTitle("Speakr Windows Companion")
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(550, 650)
        
        # Thread-safe signaler
        self.signaler = Signaler()
        self.signaler.level_signal.connect(self._update_level_meters)
        self.signaler.status_signal.connect(self._handle_status_update)
        self.signaler.auto_record_start_signal.connect(self._handle_auto_record_started)
        self.signaler.auto_record_finish_signal.connect(self._handle_auto_record_finished)
        self.signaler.cooldown_signal.connect(self._handle_cooldown_started)
        self.signaler.history_updated_signal.connect(self._refresh_history_table)
        
        # Timers
        self.duration_timer = QTimer(self)
        self.duration_timer.timeout.connect(self._update_duration_display)
        
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self._update_cooldown_display)
        self.cooldown_remaining: int = 0
        
        # Bind callbacks
        self.recorder.level_callback = self._recorder_level_callback
        self.uploader.status_callback = self._uploader_status_callback
        
        # Setup process monitor
        self.monitor = ProcessMonitor(
            settings=self.settings, 
            recorder=self.recorder, 
            upload_callback=self._on_auto_record_finished,
            start_callback=self._on_auto_record_started,
            cooldown_callback=self._on_cooldown_started
        )
        
        # Setup UI layout
        self._init_ui()
        
        # Initial device and tag loading
        self._refresh_audio_devices()
        self._load_active_tags()
        self._refresh_history_table()
        
        # Execute startup retention pruning
        self._run_retention_pruning()
        
        # Start background process monitor
        self.monitor.start()
        self.statusBar().showMessage("Ready")

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        self.tabs = QTabWidget(self)
        main_layout.addWidget(self.tabs)
        
        # Create tabs
        self.dashboard_tab = QWidget()
        self.history_tab = QWidget()
        self.preferences_tab = QWidget()
        self.logs_tab = QWidget()
        
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.history_tab, "Recordings History")
        self.tabs.addTab(self.preferences_tab, "Preferences")
        self.tabs.addTab(self.logs_tab, "Status Logs")
        
        # Setup layouts
        self._setup_dashboard_tab()
        self._setup_history_tab()
        self._setup_preferences_tab()
        self._setup_logs_tab()

    def _setup_dashboard_tab(self) -> None:
        layout = QVBoxLayout(self.dashboard_tab)
        
        # Recording Status Card
        status_group = QGroupBox("Recording Status")
        status_layout = QHBoxLayout(status_group)
        self.status_label = QLabel("STATUS: IDLE")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2ecc71;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addWidget(status_group)
        
        # Recording controls
        ctrl_layout = QHBoxLayout()
        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
        self.record_btn.clicked.connect(self._toggle_recording)
        ctrl_layout.addWidget(self.record_btn, 2)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setStyleSheet("background-color: #f1c40f; color: white; font-weight: bold; padding: 10px;")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        ctrl_layout.addWidget(self.pause_btn, 1)
        
        self.upload_last_btn = QPushButton("Upload Last")
        self.upload_last_btn.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 10px;")
        self.upload_last_btn.setEnabled(False)
        self.upload_last_btn.clicked.connect(self._upload_last_recording)
        ctrl_layout.addWidget(self.upload_last_btn, 1)
        
        self.skip_cooldown_btn = QPushButton("Skip Cooldown")
        self.skip_cooldown_btn.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold; padding: 10px;")
        self.skip_cooldown_btn.setVisible(False)
        self.skip_cooldown_btn.clicked.connect(self._skip_cooldown)
        ctrl_layout.addWidget(self.skip_cooldown_btn, 1)
        
        layout.addLayout(ctrl_layout)
        
        # Level Meters
        meters_group = QGroupBox("Live Audio Input Levels")
        meters_layout = QVBoxLayout(meters_group)
        
        self.mic_meter = VolumeMeter("Microphone", self)
        self.spk_meter = VolumeMeter("Speakers (Loopback)", self)
        
        meters_layout.addWidget(self.mic_meter)
        meters_layout.addWidget(self.spk_meter)
        layout.addWidget(meters_group)
        
        # Switches Group
        switches_layout = QHBoxLayout()
        self.auto_record_chk = QCheckBox("Enable Auto-Record")
        self.auto_record_chk.setChecked(self.settings.auto_record_enabled)
        self.auto_record_chk.toggled.connect(self._auto_record_toggled)
        switches_layout.addWidget(self.auto_record_chk)
        
        self.auto_upload_chk = QCheckBox("Auto-Upload Completed")
        self.auto_upload_chk.setChecked(self.settings.auto_upload_enabled)
        self.auto_upload_chk.toggled.connect(self._auto_upload_toggled)
        switches_layout.addWidget(self.auto_upload_chk)
        layout.addLayout(switches_layout)
        
        # Tagging widget
        tag_group = QGroupBox("Assign Meeting Tags")
        tag_layout = QVBoxLayout(tag_group)
        
        self.tag_selector = TagSelector(self)
        tag_layout.addWidget(self.tag_selector)
        
        # Fetch tags button
        self.refresh_tags_btn = QPushButton("Reload Tags from Server")
        self.refresh_tags_btn.clicked.connect(self._load_active_tags)
        tag_layout.addWidget(self.refresh_tags_btn)
        
        layout.addWidget(tag_group)
        
        # Windows Live Captions Hint Card
        captions_card = QGroupBox("Live Subtitles & Closed Captions")
        captions_layout = QHBoxLayout(captions_card)
        
        captions_hint_label = QLabel(
            "💡 <b>Windows Live Captions:</b> Press <b>Win + Ctrl + L</b> anytime to toggle Windows 11's built-in real-time subtitles across any meeting or video."
        )
        captions_hint_label.setWordWrap(True)
        captions_hint_label.setStyleSheet("color: #ecf0f1; font-size: 11px;")
        captions_layout.addWidget(captions_hint_label, 1)
        
        open_captions_btn = QPushButton("Open Captions Settings")
        open_captions_btn.setStyleSheet("""
            QPushButton {
                background-color: #34495e;
                color: #ecf0f1;
                border: 1px solid #4a6278;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a6278;
                color: white;
            }
        """)
        open_captions_btn.clicked.connect(self._open_windows_captions_settings)
        captions_layout.addWidget(open_captions_btn)
        
        layout.addWidget(captions_card)

    def _setup_history_tab(self) -> None:
        layout = QVBoxLayout(self.history_tab)
        
        # Header Info Banner
        header_group = QGroupBox("Local Storage & Retention")
        header_layout = QHBoxLayout(header_group)
        
        self.history_info_label = QLabel()
        self._update_history_info_label()
        header_layout.addWidget(self.history_info_label)
        header_layout.addStretch()
        
        open_folder_btn = QPushButton("Open Storage Folder")
        open_folder_btn.clicked.connect(self._open_storage_folder)
        header_layout.addWidget(open_folder_btn)
        
        prune_btn = QPushButton("Prune Expired")
        prune_btn.clicked.connect(self._manual_prune)
        header_layout.addWidget(prune_btn)
        
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self._refresh_history_table)
        header_layout.addWidget(refresh_btn)
        
        layout.addWidget(header_group)
        
        # Table of recordings
        self.history_table = QTableWidget(self)
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "Date & Time", "File Name", "Trigger", "Duration", "Size", "Upload Status", "Actions"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        layout.addWidget(self.history_table)

    def _update_history_info_label(self) -> None:
        rec_dir = str(self.settings.resolved_recordings_dir)
        ret_days = self.settings.retention_days
        ret_str = f"{ret_days} Days" if ret_days > 0 else "Keep Forever"
        self.history_info_label.setText(f"📁 Folder: {rec_dir}\n⏱️ Retention Period: {ret_str}")

    def _refresh_history_table(self) -> None:
        """Populates or updates the recordings history table from storage safely in-place."""
        self._update_history_info_label()
        recordings = self.storage.get_recordings()
        
        # If row count is different, adjust the rows
        if self.history_table.rowCount() != len(recordings):
            self.history_table.setRowCount(len(recordings))
            rebuild_widgets = True
        else:
            rebuild_widgets = False
        
        for row, rec in enumerate(recordings):
            file_path = rec.get("file_path", "")
            filename = rec.get("filename", os.path.basename(file_path))
            created_str = rec.get("created_str", "")
            trigger = rec.get("trigger", "manual").upper()
            duration_str = RecordingsManager.format_duration(rec.get("duration_seconds", 0))
            size_str = RecordingsManager.format_size(rec.get("size_bytes", 0))
            status = rec.get("status", "Local Only")
            exists = rec.get("exists_locally", True)
            
            # 0. Date
            item0 = self.history_table.item(row, 0)
            if not item0:
                self.history_table.setItem(row, 0, QTableWidgetItem(created_str))
            else:
                item0.setText(created_str)
            
            # 1. Filename
            file_title = filename if exists else f"{filename} (Deleted)"
            item1 = self.history_table.item(row, 1)
            if not item1:
                item1 = QTableWidgetItem(file_title)
                self.history_table.setItem(row, 1, item1)
            else:
                item1.setText(file_title)
            item1.setForeground(QColor("#f5f6fa" if exists else "#7f8c8d"))
            
            # 2. Trigger
            item2 = self.history_table.item(row, 2)
            if not item2:
                self.history_table.setItem(row, 2, QTableWidgetItem(trigger))
            else:
                item2.setText(trigger)
            
            # 3. Duration
            item3 = self.history_table.item(row, 3)
            if not item3:
                self.history_table.setItem(row, 3, QTableWidgetItem(duration_str))
            else:
                item3.setText(duration_str)
            
            # 4. Size
            display_size = size_str if exists else "-"
            item4 = self.history_table.item(row, 4)
            if not item4:
                self.history_table.setItem(row, 4, QTableWidgetItem(display_size))
            else:
                item4.setText(display_size)
            
            # 5. Status
            item5 = self.history_table.item(row, 5)
            if not item5:
                item5 = QTableWidgetItem(status)
                self.history_table.setItem(row, 5, item5)
            else:
                item5.setText(status)
                
            if "Uploaded" in status or "Copied" in status:
                item5.setForeground(QColor("#2ecc71"))
            elif "Failed" in status or "Missing" in status:
                item5.setForeground(QColor("#e74c3c"))
            else:
                item5.setForeground(QColor("#f39c12"))
            
            # 6. Action buttons container (only instantiate if needed)
            if rebuild_widgets or self.history_table.cellWidget(row, 6) is None:
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(4, 2, 4, 2)
                action_layout.setSpacing(4)
                
                # Re-upload button
                reup_btn = QPushButton("Re-Upload")
                reup_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
                reup_btn.setEnabled(exists)
                reup_btn.clicked.connect(lambda _, p=file_path, t=rec.get("tag_ids", []): self._reupload_file(p, t))
                action_layout.addWidget(reup_btn)
                
                # Play / Open button
                open_btn = QPushButton("Play")
                open_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
                open_btn.setEnabled(exists)
                open_btn.clicked.connect(lambda _, p=file_path: self._play_file(p))
                action_layout.addWidget(open_btn)
                
                # Delete button
                del_btn = QPushButton("Delete")
                del_btn.setStyleSheet("padding: 3px 8px; font-size: 11px; color: #e74c3c;")
                del_btn.clicked.connect(lambda _, p=file_path: self._delete_history_file(p))
                action_layout.addWidget(del_btn)
                
                self.history_table.setCellWidget(row, 6, action_widget)

    def _reupload_file(self, file_path: str, tag_ids: List[int]) -> None:
        filename = os.path.basename(file_path)
        self._log(f"Re-uploading '{filename}'...")
        self.statusBar().showMessage(f"Re-uploading '{filename}' in background...")
        self.uploader.process_file(file_path, tag_ids)

    def _play_file(self, file_path: str) -> None:
        if os.path.exists(file_path):
            try:
                os.startfile(file_path)
            except Exception as e:
                QMessageBox.warning(self, "Playback Error", f"Could not open file: {e}")

    def _delete_history_file(self, file_path: str) -> None:
        confirm = QMessageBox.question(
            self, 
            "Delete Recording", 
            f"Are you sure you want to delete this recording from disk and history?\n{os.path.basename(file_path)}",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.storage.delete_recording(file_path)
            self._refresh_history_table()
            self._log(f"Deleted recording: {os.path.basename(file_path)}")

    def _open_storage_folder(self) -> None:
        rec_dir = str(self.settings.resolved_recordings_dir)
        if os.path.exists(rec_dir):
            os.startfile(rec_dir)

    def _manual_prune(self) -> None:
        count = self.storage.prune_expired_recordings()
        self._refresh_history_table()
        QMessageBox.information(self, "Pruning Complete", f"Retention policy executed. Pruned {count} expired recording(s).")
        self._log(f"Manual retention prune executed. Pruned {count} files.")

    def _run_retention_pruning(self) -> None:
        try:
            count = self.storage.prune_expired_recordings()
            if count > 0:
                self._log(f"[Retention] Auto-pruned {count} expired recording(s) older than {self.settings.retention_days} days.")
        except Exception as e:
            print(f"[Retention] Pruning error: {e}")

    def _setup_preferences_tab(self) -> None:
        layout = QVBoxLayout(self.preferences_tab)
        
        # 1. Server Configuration
        server_group = QGroupBox("Speakr Server Endpoints")
        server_layout = QHBoxLayout(server_group)
        
        self.server_combo = QComboBox(self)
        self._populate_server_combo()
        self.server_combo.currentIndexChanged.connect(self._server_selection_changed)
        server_layout.addWidget(self.server_combo, 3)
        
        add_srv_btn = QPushButton("Add")
        add_srv_btn.clicked.connect(self._add_server)
        server_layout.addWidget(add_srv_btn, 1)
        
        edit_srv_btn = QPushButton("Edit")
        edit_srv_btn.clicked.connect(self._edit_server)
        server_layout.addWidget(edit_srv_btn, 1)
        
        del_srv_btn = QPushButton("Delete")
        del_srv_btn.clicked.connect(self._delete_server)
        server_layout.addWidget(del_srv_btn, 1)
        
        layout.addWidget(server_group)
        
        # 2. Upload Preferences
        upload_group = QGroupBox("Upload Preference")
        upload_layout = QVBoxLayout(upload_group)
        
        self.mode_api_radio = QRadioButton("Direct API Upload (transmits file directly via REST API)")
        self.mode_folder_radio = QRadioButton("NAS Folder Copy (saves file to NAS_Share, tagged asynchronously)")
        
        if self.settings.upload_mode == "api":
            self.mode_api_radio.setChecked(True)
        else:
            self.mode_folder_radio.setChecked(True)
            
        self.mode_api_radio.toggled.connect(self._upload_mode_changed)
        self.mode_folder_radio.toggled.connect(self._upload_mode_changed)
        
        upload_layout.addWidget(self.mode_api_radio)
        upload_layout.addWidget(self.mode_folder_radio)
        
        # Folder browser
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("NAS Ingestion Path:"))
        self.nas_path_input = QLineEdit(self.settings.nas_folder_path)
        self.nas_path_input.setReadOnly(True)
        folder_layout.addWidget(self.nas_path_input)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_nas_folder)
        folder_layout.addWidget(self.browse_btn)
        upload_layout.addLayout(folder_layout)
        layout.addWidget(upload_group)

        # 3. Local Storage & Retention Settings
        storage_group = QGroupBox("Local Recording Storage & Retention")
        storage_layout = QFormLayout(storage_group)
        
        # Storage folder selection
        storage_folder_box = QHBoxLayout()
        self.storage_path_input = QLineEdit(self.settings.local_recordings_dir or str(self.settings.resolved_recordings_dir))
        self.storage_path_input.setReadOnly(True)
        storage_folder_box.addWidget(self.storage_path_input)
        
        browse_storage_btn = QPushButton("Browse...")
        browse_storage_btn.clicked.connect(self._browse_local_storage_dir)
        storage_folder_box.addWidget(browse_storage_btn)
        storage_layout.addRow("Storage Folder:", storage_folder_box)
        
        # Retention dropdown
        self.retention_combo = QComboBox(self)
        self.retention_combo.addItem("7 Days", 7)
        self.retention_combo.addItem("14 Days", 14)
        self.retention_combo.addItem("30 Days (Default)", 30)
        self.retention_combo.addItem("60 Days", 60)
        self.retention_combo.addItem("90 Days", 90)
        self.retention_combo.addItem("Keep Forever (0 Days)", 0)
        
        current_ret = self.settings.retention_days
        idx = self.retention_combo.findData(current_ret)
        if idx >= 0:
            self.retention_combo.setCurrentIndex(idx)
        else:
            self.retention_combo.setCurrentIndex(2)
        self.retention_combo.currentIndexChanged.connect(self._retention_changed)
        storage_layout.addRow("Retention Expiration:", self.retention_combo)
        
        # Cooldown dropdown
        self.cooldown_combo = QComboBox(self)
        self.cooldown_combo.addItem("30 Seconds", 30)
        self.cooldown_combo.addItem("60 Seconds (Default - 1 Min)", 60)
        self.cooldown_combo.addItem("120 Seconds (2 Min)", 120)
        self.cooldown_combo.addItem("Disabled (0s)", 0)
        
        current_cd = self.settings.cooldown_seconds
        idx = self.cooldown_combo.findData(current_cd)
        if idx >= 0:
            self.cooldown_combo.setCurrentIndex(idx)
        else:
            self.cooldown_combo.setCurrentIndex(1)
        self.cooldown_combo.currentIndexChanged.connect(self._cooldown_changed)
        storage_layout.addRow("Post-Stop Cooldown Delay:", self.cooldown_combo)
        
        layout.addWidget(storage_group)
        
        # 4. Recording Format Selection
        format_group = QGroupBox("Recording Audio Format")
        format_layout = QFormLayout(format_group)
        
        self.format_combo = QComboBox(self)
        self.format_combo.addItem("MP4 (AAC Compressed - Recommended, ~5x smaller)", "mp4")
        self.format_combo.addItem("WAV (Uncompressed PCM)", "wav")
        
        current_fmt = self.settings.recording_format.lower()
        if current_fmt == "wav":
            self.format_combo.setCurrentIndex(1)
        else:
            self.format_combo.setCurrentIndex(0)
            
        self.format_combo.currentIndexChanged.connect(self._recording_format_changed)
        format_layout.addRow("Audio Encoding:", self.format_combo)
        layout.addWidget(format_group)

        # 5. Audio Device Selection
        audio_group = QGroupBox("Audio Hardware Selection")
        audio_layout = QFormLayout(audio_group)
        
        self.mic_combo = QComboBox(self)
        self.spk_combo = QComboBox(self)
        
        audio_layout.addRow("Microphone Capture:", self.mic_combo)
        audio_layout.addRow("Speakers (Loopback):", self.spk_combo)
        
        refresh_dev_btn = QPushButton("Refresh Devices")
        refresh_dev_btn.clicked.connect(self._refresh_audio_devices)
        audio_layout.addRow("", refresh_dev_btn)
        
        layout.addWidget(audio_group)
        
        # 6. Auto-Record Rules
        rules_group = QGroupBox("Auto-Record Processes")
        rules_layout = QVBoxLayout(rules_group)
        
        self.zoom_chk = QCheckBox("Record Zoom Meetings (CptHost.exe)")
        self.zoom_chk.setChecked(self.settings.zoom_auto_record)
        self.zoom_chk.toggled.connect(self._rules_changed)
        rules_layout.addWidget(self.zoom_chk)
        
        self.teams_chk = QCheckBox("Record Microsoft Teams Calls (Teams.exe)")
        self.teams_chk.setChecked(self.settings.teams_auto_record)
        self.teams_chk.toggled.connect(self._rules_changed)
        rules_layout.addWidget(self.teams_chk)
        
        self.citrix_chk = QCheckBox("Record Citrix Meetings (Audio-gated wfica / Workspace)")
        self.citrix_chk.setChecked(self.settings.citrix_auto_record)
        self.citrix_chk.toggled.connect(self._rules_changed)
        rules_layout.addWidget(self.citrix_chk)
        
        layout.addWidget(rules_group)
        
        # 7. Local Closed Captions Group
        # Devices event bindings
        self.mic_combo.currentIndexChanged.connect(self._audio_devices_changed)
        self.spk_combo.currentIndexChanged.connect(self._audio_devices_changed)

    def _setup_logs_tab(self) -> None:
        layout = QVBoxLayout(self.logs_tab)
        self.log_area = QPlainTextEdit(self)
        self.log_area.setReadOnly(True)
        self.log_area.appendPlainText(f"[{time.strftime('%H:%M:%S')}] App initialized.")
        layout.addWidget(self.log_area)
        
        clear_btn = QPushButton("Clear Logs")
        clear_btn.clicked.connect(self.log_area.clear)
        layout.addWidget(clear_btn)

    # Status Logs Updates
    def _log(self, text: str) -> None:
        self.log_area.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")
        self.statusBar().showMessage(text, 5000)

    # Audio Devices
    def _refresh_audio_devices(self) -> None:
        self.mic_combo.blockSignals(True)
        self.spk_combo.blockSignals(True)
        
        self.mic_combo.clear()
        self.spk_combo.clear()
        
        mics, speakers = AudioRecorder.get_devices()
        
        self.mic_combo.addItem("Default")
        for idx, name in mics:
            self.mic_combo.addItem(name)
            
        self.spk_combo.addItem("Default")
        for idx, name in speakers:
            self.spk_combo.addItem(name)
            
        mic_idx = self.mic_combo.findText(self.settings.selected_mic)
        if mic_idx >= 0:
            self.mic_combo.setCurrentIndex(mic_idx)
        else:
            self.mic_combo.setCurrentIndex(0)
            
        spk_idx = self.spk_combo.findText(self.settings.selected_speaker)
        if spk_idx >= 0:
            self.spk_combo.setCurrentIndex(spk_idx)
        else:
            self.spk_combo.setCurrentIndex(0)
            
        self.mic_combo.blockSignals(False)
        self.spk_combo.blockSignals(False)
        self._log("Audio devices refreshed.")

    def _audio_devices_changed(self) -> None:
        self.settings.selected_mic = self.mic_combo.currentText()
        self.settings.selected_speaker = self.spk_combo.currentText()
        self._log(f"Devices updated. Mic: {self.settings.selected_mic}, Speaker: {self.settings.selected_speaker}")

    # Server Endpoints dropdown
    def _populate_server_combo(self) -> None:
        self.server_combo.clear()
        for s in self.settings.servers:
            self.server_combo.addItem(s["name"])
        self.server_combo.setCurrentIndex(self.settings.active_server_idx)

    def _server_selection_changed(self, idx: int) -> None:
        if idx >= 0:
            self.settings.active_server_idx = idx
            self._log(f"Active server changed to: {self.settings.active_server['name']}")
            self._load_active_tags()

    def _add_server(self) -> None:
        dialog = ServerDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            servers = self.settings.servers.copy()
            servers.append(data)
            self.settings.servers = servers
            self._populate_server_combo()
            self.server_combo.setCurrentIndex(len(servers) - 1)
            self._log(f"Added server: {data['name']}")

    def _edit_server(self) -> None:
        idx = self.server_combo.currentIndex()
        if idx < 0:
            return
        dialog = ServerDialog(self.settings.servers[idx], parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            servers = self.settings.servers.copy()
            servers[idx] = data
            self.settings.servers = servers
            self._populate_server_combo()
            self.server_combo.setCurrentIndex(idx)
            self._log(f"Edited server: {data['name']}")

    def _delete_server(self) -> None:
        if len(self.settings.servers) <= 1:
            QMessageBox.warning(self, "Warning", "You must keep at least one server configured.")
            return
        idx = self.server_combo.currentIndex()
        if idx >= 0:
            name = self.settings.servers[idx]["name"]
            confirm = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete server '{name}'?", QMessageBox.Yes | QMessageBox.No)
            if confirm == QMessageBox.Yes:
                servers = self.settings.servers.copy()
                servers.pop(idx)
                self.settings.servers = servers
                self.settings.active_server_idx = 0
                self._populate_server_combo()
                self._log(f"Deleted server: {name}")

    # Tag Loader
    def _load_active_tags(self) -> None:
        server_conf = self.settings.active_server
        self._log(f"Loading tags from {server_conf['name']}...")
        
        def fetch_tags():
            client = SpeakrClient(base_url=server_conf["url"], api_key=server_conf["api_key"])
            tags = client.list_tags()
            
            class TagsSignal(QObject):
                sig = Signal(list)
            
            self._tags_bridge = TagsSignal()
            self._tags_bridge.sig.connect(self._populate_tags_ui)
            self._tags_bridge.sig.emit(tags)
            
        threading.Thread(target=fetch_tags, daemon=True).start()

    def _populate_tags_ui(self, tags: List[Dict[str, Any]]) -> None:
        self.tag_selector.set_tags(tags)
        self._log(f"Loaded {len(tags)} tags from server.")

    # Preferences Handlers
    def _recording_format_changed(self) -> None:
        fmt = self.format_combo.currentData()
        if fmt:
            self.settings.recording_format = fmt
            self._log(f"Recording format set to: {fmt.upper()}")

    def _upload_mode_changed(self) -> None:
        if self.mode_api_radio.isChecked():
            self.settings.upload_mode = "api"
        else:
            self.settings.upload_mode = "folder"
        self._log(f"Upload preference set to: {self.settings.upload_mode.upper()}")

    def _browse_nas_folder(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select NAS Share Inbox Folder", self.settings.nas_folder_path)
        if dir_path:
            self.settings.nas_folder_path = dir_path.replace("/", "\\")
            self.nas_path_input.setText(self.settings.nas_folder_path)
            self._log(f"NAS Inbox folder set to: {self.settings.nas_folder_path}")

    def _browse_local_storage_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select Local Recordings Storage Folder", str(self.settings.resolved_recordings_dir))
        if dir_path:
            self.settings.local_recordings_dir = dir_path.replace("/", "\\")
            self.storage_path_input.setText(self.settings.local_recordings_dir)
            self._update_history_info_label()
            self._log(f"Local storage directory set to: {self.settings.local_recordings_dir}")

    def _retention_changed(self) -> None:
        days = self.retention_combo.currentData()
        if days is not None:
            self.settings.retention_days = int(days)
            self._update_history_info_label()
            self._log(f"Retention period set to: {days} days")

    def _cooldown_changed(self) -> None:
        secs = self.cooldown_combo.currentData()
        if secs is not None:
            self.settings.cooldown_seconds = int(secs)
            self._log(f"Cooldown delay set to: {secs} seconds")

    def _open_windows_captions_settings(self) -> None:
        """Opens Windows Accessibility Captions settings or launches Live Captions."""
        try:
            import subprocess
            subprocess.Popen(["cmd", "/c", "start", "ms-settings:easeofaccess-closedcaptioning"], shell=True)
            self.statusBar().showMessage("Opened Windows Captions settings. Shortcut: Win + Ctrl + L", 5000)
            self._log("Opened Windows Captions settings (Win + Ctrl + L).")
        except Exception as e:
            self._log(f"[Error] Failed to open Windows Captions settings: {e}")

    # Recording control methods
    def _toggle_recording(self) -> None:
        if not self.recorder.is_recording:
            # Check if in cooldown
            if self.cooldown_remaining > 0:
                self.statusBar().showMessage(f"In cooldown delay ({self.cooldown_remaining}s remaining).", 3000)
                return

            self.record_btn.setEnabled(False)
            self.record_btn.setText("Starting...")
            self.pause_btn.setEnabled(False)
            self.upload_last_btn.setEnabled(False)
            QApplication.processEvents()
            
            try:
                rec_dir = self.settings.resolved_recordings_dir
                rec_dir.mkdir(parents=True, exist_ok=True)
                ext = self.settings.recording_format.lower().lstrip(".")
                timestamp_str = time.strftime("%Y-%m-%d_%H%M%S")
                file_name = f"Meeting_{timestamp_str}_Manual.{ext}"
                output_path = str(rec_dir / file_name)
                
                self.current_recording_mode = "manual"
                self.recorder.start_recording(
                    output_path=output_path,
                    mic_name=self.settings.selected_mic,
                    speaker_name=self.settings.selected_speaker
                )
                
                self.status_label.setText("STATUS: RECORDING (MANUAL) • 00:00")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")
                self.record_btn.setText("Stop Recording")
                self.record_btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px;")
                self.pause_btn.setEnabled(True)
                self.pause_btn.setText("Pause")
                
                self.duration_timer.start(1000)
                if self.tray_manager:
                    self.tray_manager.set_state("recording", "00:00")
                self.statusBar().showMessage("Recording started.")
            except Exception as e:
                self._log(f"[Error] Failed to start recording: {e}")
                self.recorder.is_recording = False
                self.duration_timer.stop()
                self.status_label.setText("STATUS: ERROR")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")
                self.record_btn.setText("Start Recording")
                self.record_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
                self.pause_btn.setEnabled(False)
                self.statusBar().showMessage(f"Error starting recording: {e}", 5000)
                if self.tray_manager:
                    self.tray_manager.set_state("ready")
                QTimer.singleShot(3000, self._reset_status_to_idle)
            finally:
                self.record_btn.setEnabled(True)
        else:
            self.record_btn.setEnabled(False)
            self.record_btn.setText("Stopping...")
            self.pause_btn.setEnabled(False)
            QApplication.processEvents()
            
            try:
                file_path = self.recorder.output_file_path
                duration = self.recorder.elapsed_seconds
                selected_tags = self.tag_selector.selected_tag_ids()
                
                self.duration_timer.stop()
                self.recorder.stop_recording()
                
                # Arm cooldown in process monitor and GUI
                self.monitor.trigger_cooldown()
                
                # Add to persistent local storage
                if file_path and os.path.exists(file_path):
                    self.last_recording_path = file_path
                    self.storage.add_recording(
                        file_path=file_path,
                        trigger="manual",
                        duration_seconds=duration,
                        tag_ids=selected_tags,
                        status="Local Only"
                    )
                    self._refresh_history_table()
                    
                    if self.settings.auto_upload_enabled:
                        self.statusBar().showMessage("Uploading recording in background...")
                        self.uploader.process_file(file_path, selected_tags)
                        self.upload_last_btn.setEnabled(False)
                    else:
                        self.statusBar().showMessage("Recording saved locally. Click 'Upload Last' to send.")
                        self.upload_last_btn.setEnabled(True)
                else:
                    self.statusBar().showMessage("Recording stopped (no file generated).")
                
                self.tag_selector.clear_selection()
            except Exception as e:
                self._log(f"[Error] Error stopping recording: {e}")
                self.statusBar().showMessage(f"Error stopping recording: {e}", 5000)
            finally:
                self.pause_btn.setEnabled(False)

    def _upload_last_recording(self) -> None:
        if self.last_recording_path and os.path.exists(self.last_recording_path):
            filename = os.path.basename(self.last_recording_path)
            self.statusBar().showMessage(f"Uploading '{filename}' in background...")
            selected_tags = self.tag_selector.selected_tag_ids()
            self.uploader.process_file(self.last_recording_path, selected_tags)
            self.upload_last_btn.setEnabled(False)
            self.tag_selector.clear_selection()
        else:
            self.statusBar().showMessage("Error: No completed recording available to upload.", 5000)

    def _toggle_pause(self) -> None:
        if not self.recorder.is_paused:
            self.recorder.pause_recording()
            dur_str = RecordingsManager.format_duration(self.recorder.elapsed_seconds)
            self.status_label.setText(f"STATUS: PAUSED • {dur_str}")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f1c40f;")
            self.pause_btn.setText("Resume")
            if self.tray_manager:
                self.tray_manager.set_state("paused", dur_str)
        else:
            self.recorder.resume_recording()
            dur_str = RecordingsManager.format_duration(self.recorder.elapsed_seconds)
            mode_str = self.current_recording_mode.upper()
            self.status_label.setText(f"STATUS: RECORDING ({mode_str}) • {dur_str}")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")
            self.pause_btn.setText("Pause")
            if self.tray_manager:
                self.tray_manager.set_state("recording", dur_str)

    def _update_duration_display(self) -> None:
        """Invoked every 1 second while recording."""
        if self.recorder.is_recording:
            elapsed = self.recorder.elapsed_seconds
            dur_str = RecordingsManager.format_duration(elapsed)
            mode_str = self.current_recording_mode.upper()
            
            if not self.recorder.is_paused:
                self.status_label.setText(f"STATUS: RECORDING ({mode_str}) • {dur_str}")
                self.statusBar().showMessage(f"● Recording in progress [{dur_str}]")
                if self.tray_manager:
                    self.tray_manager.set_state("recording", dur_str)

    # Cooldown handlers
    def _on_cooldown_started(self, seconds: float) -> None:
        """Background callback from ProcessMonitor, emit signal to GUI."""
        self.signaler.cooldown_signal.emit(seconds)

    def _handle_cooldown_started(self, seconds: float) -> None:
        """Main thread: start cooldown timer & lock record button."""
        self.cooldown_remaining = int(seconds)
        if self.cooldown_remaining > 0:
            self.cooldown_timer.start(1000)
            self.record_btn.setEnabled(False)
            self.record_btn.setText(f"Cooldown ({self.cooldown_remaining}s)")
            self.record_btn.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; padding: 10px;")
            self.status_label.setText(f"STATUS: COOLDOWN ({self.cooldown_remaining}s)")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e67e22;")
            self.skip_cooldown_btn.setVisible(True)
            if self.tray_manager:
                self.tray_manager.set_state("cooldown", f"{self.cooldown_remaining}s")
        else:
            self._end_cooldown()

    def _update_cooldown_display(self) -> None:
        """Ticks every 1s during post-recording cooldown."""
        self.cooldown_remaining -= 1
        if self.cooldown_remaining > 0:
            self.record_btn.setText(f"Cooldown ({self.cooldown_remaining}s)")
            self.status_label.setText(f"STATUS: COOLDOWN ({self.cooldown_remaining}s)")
            if self.tray_manager:
                self.tray_manager.set_state("cooldown", f"{self.cooldown_remaining}s")
        else:
            self._end_cooldown()

    def _end_cooldown(self) -> None:
        self.cooldown_timer.stop()
        self.cooldown_remaining = 0
        self.record_btn.setEnabled(True)
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
        self.status_label.setText("STATUS: IDLE")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2ecc71;")
        self.skip_cooldown_btn.setVisible(False)
        if self.tray_manager:
            self.tray_manager.set_state("ready")

    def _skip_cooldown(self) -> None:
        self.monitor.cancel_cooldown()
        self._end_cooldown()
        self._log("Cooldown skipped by user.")

    # Switches and Checkboxes updates
    def _auto_record_toggled(self, checked: bool) -> None:
        self.settings.auto_record_enabled = checked
        self._log(f"Auto-record: {checked}")

    def _auto_upload_toggled(self, checked: bool) -> None:
        self.settings.auto_upload_enabled = checked
        self._log(f"Auto-upload: {checked}")

    def _rules_changed(self) -> None:
        self.settings.zoom_auto_record = self.zoom_chk.isChecked()
        self.settings.teams_auto_record = self.teams_chk.isChecked()
        self.settings.citrix_auto_record = self.citrix_chk.isChecked()
        self._log("Auto-record triggers updated.")

    # Callbacks and bridge signals (Thread-safe)
    def _recorder_level_callback(self, mic_db: float, spk_db: float) -> None:
        try:
            if hasattr(self, 'signaler') and self.signaler:
                self.signaler.level_signal.emit(mic_db, spk_db)
        except Exception:
            pass

    def _update_level_meters(self, mic_db: float, spk_db: float) -> None:
        self.mic_meter.set_level(mic_db)
        self.spk_meter.set_level(spk_db)

    def _uploader_status_callback(self, message: str, success: bool) -> None:
        self.signaler.status_signal.emit(message, success)

    def _handle_status_update(self, message: str, success: bool) -> None:
        self._log(f"[Uploader] {message}")
        self.statusBar().showMessage(message, 5000)
        self._refresh_history_table()
        
        if success:
            if "Successfully" in message or "Copied" in message:
                self.last_recording_path = None
                self.upload_last_btn.setEnabled(False)
        else:
            if not self.recorder.is_recording and self.cooldown_remaining <= 0:
                self.status_label.setText("STATUS: UPLOAD ERROR")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")
                QTimer.singleShot(5000, self._reset_status_to_idle)

    def _reset_status_to_idle(self) -> None:
        if not self.recorder.is_recording and self.cooldown_remaining <= 0:
            self.status_label.setText("STATUS: IDLE")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2ecc71;")

    # Auto-Record callbacks
    def _on_auto_record_started(self, trigger: str) -> None:
        self.signaler.auto_record_start_signal.emit(trigger)

    def _handle_auto_record_started(self, trigger: str) -> None:
        self.current_recording_mode = f"auto - {trigger}"
        self.status_label.setText(f"STATUS: RECORDING (AUTO - {trigger.upper()}) • 00:00")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")
        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px;")
        self.pause_btn.setEnabled(True)
        self.upload_last_btn.setEnabled(False)
        self.skip_cooldown_btn.setVisible(False)
        
        self.duration_timer.start(1000)
        if self.tray_manager:
            self.tray_manager.set_state("recording", "00:00")
        self._log(f"[Monitor] Auto-recording started ({trigger.upper()})")
        self.statusBar().showMessage(f"Auto-recording started ({trigger.upper()}).")

    def _on_auto_record_finished(self, file_path: str, tags: List[int]) -> None:
        self.signaler.auto_record_finish_signal.emit(file_path, tags)

    def _handle_auto_record_finished(self, file_path: str, tags: List[int]) -> None:
        self.duration_timer.stop()
        self.pause_btn.setEnabled(False)
        self._log(f"[Monitor] Auto-recording finished: {os.path.basename(file_path)}")
        self.statusBar().showMessage("Auto-recording finished.")
        
        if file_path and os.path.exists(file_path):
            self.last_recording_path = file_path
            ui_tags = self.tag_selector.selected_tag_ids()
            combined_tags = list(set(tags + ui_tags))
            
            # Save to storage
            trigger_type = self.current_recording_mode.replace("auto - ", "")
            self.storage.add_recording(
                file_path=file_path,
                trigger=trigger_type,
                duration_seconds=self.recorder.elapsed_seconds,
                tag_ids=combined_tags,
                status="Local Only"
            )
            self._refresh_history_table()
            
            if self.settings.auto_upload_enabled:
                self.statusBar().showMessage("Uploading auto-recording in background...")
                self.uploader.process_file(file_path, combined_tags)
                self.upload_last_btn.setEnabled(False)
            else:
                self.upload_last_btn.setEnabled(True)
                self.statusBar().showMessage("Auto-recording saved locally. Click 'Upload Last' to send.")
        
        self.tag_selector.clear_selection()

    def closeEvent(self, event) -> None:
        if self.isVisible():
            event.ignore()
            self.hide()
            self._log("Application minimized to system tray.")
        else:
            self.duration_timer.stop()
            self.cooldown_timer.stop()
            self.monitor.stop()
            self.recorder.terminate()
            event.accept()
