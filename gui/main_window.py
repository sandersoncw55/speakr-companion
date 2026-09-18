import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QCheckBox, QComboBox, QLineEdit, QSpinBox,
    QFileDialog, QPlainTextEdit, QGroupBox, QRadioButton, 
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextBrowser
)
from PySide6.QtGui import QIcon, QFont, QColor

from core.config import Settings, get_app_icon, get_resource_path
from core.recorder import AudioRecorder
from core.monitor import ProcessMonitor
from core.client import SpeakrClient
from core.uploader import AudioUploader
from core.storage import RecordingsManager
from gui.widgets import VolumeMeter, TagSelector
from core.copilot.segmenter import VADSegmenter, AudioSegment
from core.copilot.memory import CopilotMemory
from core.copilot.agent import CopilotAgent
from core.asr.manager import ASRManager
from gui.hud import FloatingCopilotHUD

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


class NotesViewerDialog(QDialog):
    """Modal dialog to view, copy, and open meeting notes and Copilot scratchpad."""
    def __init__(self, notes_path: str, recording_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.notes_path = notes_path
        self.setWindowTitle(f"📝 Meeting Notes — {recording_name}")
        self.resize(750, 560)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
            }
            QTextBrowser {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 14px;
                font-size: 13px;
                line-height: 1.5;
            }
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        head_box = QHBoxLayout()
        icon_lbl = QLabel("📝")
        icon_lbl.setStyleSheet("font-size: 18px;")
        head_box.addWidget(icon_lbl)

        title_lbl = QLabel(f"Copilot Scratchpad & Notes: {os.path.basename(notes_path)}")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        head_box.addWidget(title_lbl, 1)

        layout.addLayout(head_box)

        # Content Browser
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        content = ""
        if os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                content = f"Error reading notes file: {e}"
        else:
            content = "*Notes file does not exist locally.*"

        self.browser.setMarkdown(content)
        self.raw_content = content
        layout.addWidget(self.browser)

        # Buttons footer
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        copy_btn = QPushButton("📋 Copy Markdown")
        copy_btn.clicked.connect(self._copy_markdown)
        btn_box.addWidget(copy_btn)

        open_file_btn = QPushButton("📂 Open in External App")
        open_file_btn.clicked.connect(self._open_external)
        btn_box.addWidget(open_file_btn)

        btn_box.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background-color: #0284c7; color: white; border: none; font-weight: bold; padding: 6px 18px;")
        close_btn.clicked.connect(self.accept)
        btn_box.addWidget(close_btn)

        layout.addLayout(btn_box)

    def _copy_markdown(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.raw_content)
        QMessageBox.information(self, "Copied", "Meeting notes copied to clipboard!")

    def _open_external(self):
        if os.path.exists(self.notes_path):
            try:
                os.startfile(self.notes_path)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not open file: {e}")


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
        
        # Live Copilot session state
        self.hud: Optional[FloatingCopilotHUD] = None
        self.copilot_memory: Optional[CopilotMemory] = None
        self.copilot_agent: Optional[CopilotAgent] = None
        self.vad_segmenter: Optional[VADSegmenter] = None
        self.asr_manager: Optional[ASRManager] = None
        
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

        # Meeting Mode & Live Copilot Bar
        copilot_bar = QHBoxLayout()
        copilot_bar.addWidget(QLabel("Meeting Mode:"))
        self.meeting_mode_combo = QComboBox(self)
        self.meeting_mode_combo.addItem("Virtual Call (Teams/Zoom/Citrix)", "virtual")
        self.meeting_mode_combo.addItem("In-Person Room (Conference Mic)", "in_person")
        self.meeting_mode_combo.addItem("Hybrid Room (Room Mic + Loopback)", "hybrid")
        
        current_mode = self.settings.meeting_mode
        mode_idx = self.meeting_mode_combo.findData(current_mode)
        if mode_idx >= 0:
            self.meeting_mode_combo.setCurrentIndex(mode_idx)
        self.meeting_mode_combo.currentIndexChanged.connect(self._meeting_mode_changed)
        copilot_bar.addWidget(self.meeting_mode_combo, 2)

        self.copilot_toggle_chk = QCheckBox("Enable Live Copilot HUD")
        self.copilot_toggle_chk.setChecked(self.settings.copilot_enabled)
        self.copilot_toggle_chk.toggled.connect(self._copilot_toggle_changed)
        copilot_bar.addWidget(self.copilot_toggle_chk)

        self.open_hud_btn = QPushButton("💡 Open HUD")
        self.open_hud_btn.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px;")
        self.open_hud_btn.clicked.connect(self._toggle_copilot_hud)
        copilot_bar.addWidget(self.open_hud_btn)

        layout.addLayout(copilot_bar)
        
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

                # Notes button (if notes file exists)
                notes_path = rec.get("notes_path", "")
                if not notes_path and file_path and os.path.exists(file_path):
                    parent_dir = Path(file_path).parent
                    rec_stem = Path(file_path).stem
                    clean_ts = rec_stem.replace("Recording_", "").replace("AutoRecord_", "")
                    matching_notes = list(parent_dir.glob(f"*{clean_ts}*.md"))
                    if matching_notes:
                        notes_path = str(matching_notes[0])
                        rec["notes_path"] = notes_path
                        self.storage.update_notes_path(file_path, notes_path)

                has_notes = bool(notes_path and os.path.exists(notes_path))
                if has_notes:
                    notes_btn = QPushButton("📝 Notes")
                    notes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 3px 8px;
                            font-size: 11px;
                            background-color: #065f46;
                            color: #a7f3d0;
                            border: 1px solid #059669;
                            border-radius: 4px;
                            font-weight: 500;
                        }
                        QPushButton:hover {
                            background-color: #047857;
                            color: #ffffff;
                        }
                    """)
                    notes_btn.setToolTip("View Copilot meeting notes, questions, and checklist")
                    notes_btn.clicked.connect(lambda _, np=notes_path, fn=filename: self._view_meeting_notes(np, fn))
                    action_layout.addWidget(notes_btn)

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

    def _view_meeting_notes(self, notes_path: str, filename: str) -> None:
        """Opens modal dialog to view and export Copilot notes."""
        dlg = NotesViewerDialog(notes_path, filename, parent=self)
        dlg.exec()

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
        layout.setContentsMargins(6, 6, 6, 6)

        self.pref_subtabs = QTabWidget(self.preferences_tab)
        layout.addWidget(self.pref_subtabs)

        # Tab 1: Server & Ingestion Sync
        tab_server = QWidget()
        tab_server_layout = QVBoxLayout(tab_server)
        
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
        tab_server_layout.addWidget(server_group)

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

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("NAS Ingestion Path:"))
        self.nas_path_input = QLineEdit(self.settings.nas_folder_path)
        self.nas_path_input.setReadOnly(True)
        folder_layout.addWidget(self.nas_path_input)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_nas_folder)
        folder_layout.addWidget(self.browse_btn)
        upload_layout.addLayout(folder_layout)
        tab_server_layout.addWidget(upload_group)
        tab_server_layout.addStretch()

        self.pref_subtabs.addTab(tab_server, "Server & Ingestion")

        # Tab 2: Audio Hardware & Auto-Record
        tab_audio = QWidget()
        tab_audio_layout = QVBoxLayout(tab_audio)

        # Audio Devices
        audio_group = QGroupBox("Audio Hardware Selection")
        audio_layout = QFormLayout(audio_group)
        self.mic_combo = QComboBox(self)
        self.spk_combo = QComboBox(self)
        audio_layout.addRow("Microphone Capture:", self.mic_combo)
        audio_layout.addRow("Speakers (Loopback):", self.spk_combo)
        refresh_dev_btn = QPushButton("Refresh Devices")
        refresh_dev_btn.clicked.connect(self._refresh_audio_devices)
        audio_layout.addRow("", refresh_dev_btn)
        tab_audio_layout.addWidget(audio_group)

        # Recording Audio Format
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
        tab_audio_layout.addWidget(format_group)

        # Local Storage & Retention
        storage_group = QGroupBox("Local Recording Storage & Retention")
        storage_layout = QFormLayout(storage_group)
        storage_folder_box = QHBoxLayout()
        self.storage_path_input = QLineEdit(self.settings.local_recordings_dir or str(self.settings.resolved_recordings_dir))
        self.storage_path_input.setReadOnly(True)
        storage_folder_box.addWidget(self.storage_path_input)
        browse_storage_btn = QPushButton("Browse...")
        browse_storage_btn.clicked.connect(self._browse_local_storage_dir)
        storage_folder_box.addWidget(browse_storage_btn)
        storage_layout.addRow("Storage Folder:", storage_folder_box)

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
        tab_audio_layout.addWidget(storage_group)

        # Auto-Record Processes
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
        tab_audio_layout.addWidget(rules_group)

        # System Tray Behavior
        tray_group = QGroupBox("Window & System Tray Behavior")
        tray_layout = QVBoxLayout(tray_group)
        self.min_to_tray_chk = QCheckBox("Minimize to System Tray (hide window when minimized)")
        self.min_to_tray_chk.setChecked(self.settings.minimize_to_tray)
        self.min_to_tray_chk.toggled.connect(self._tray_prefs_changed)
        tray_layout.addWidget(self.min_to_tray_chk)
        self.close_to_tray_chk = QCheckBox("Close to System Tray (keep running in background when closed)")
        self.close_to_tray_chk.setChecked(self.settings.close_to_tray)
        self.close_to_tray_chk.toggled.connect(self._tray_prefs_changed)
        tray_layout.addWidget(self.close_to_tray_chk)
        tab_audio_layout.addWidget(tray_group)

        self.pref_subtabs.addTab(tab_audio, "Audio Hardware & Rules")

        # Tab 3: Live Copilot & ASR
        tab_copilot = QWidget()
        tab_copilot_layout = QVBoxLayout(tab_copilot)

        # Speech Recognition (ASR) Engine Group
        asr_group = QGroupBox("Live Speech Recognition (ASR) Engine")
        self.asr_form = QFormLayout(asr_group)

        # Row 0: ASR Provider
        self.asr_provider_combo = QComboBox(self)
        self.asr_provider_combo.addItem("Local CPU (faster-whisper int8 - Zero Cloud)", "local")
        self.asr_provider_combo.addItem("Mac LAN Whisper-MLX (Apple Silicon Host)", "mac_lan")
        self.asr_provider_combo.addItem("Cloud: Groq (Whisper-Large-v3 Turbo ~200ms)", "groq")
        self.asr_provider_combo.addItem("Cloud: OpenAI (Whisper)", "openai")
        asr_idx = self.asr_provider_combo.findData(self.settings.asr_provider)
        if asr_idx >= 0:
            self.asr_provider_combo.setCurrentIndex(asr_idx)
        self.asr_provider_combo.currentIndexChanged.connect(self._asr_settings_changed)
        self.asr_form.addRow("Speech-to-Text (ASR) Engine:", self.asr_provider_combo)

        # Row 1: Local Model Size
        self.asr_model_combo = QComboBox(self)
        self.asr_model_combo.addItem("base.en (~140MB - Balanced)", "base.en")
        self.asr_model_combo.addItem("tiny.en (~75MB - Ultra Fast)", "tiny.en")
        self.asr_model_combo.addItem("small.en (~460MB - High Accuracy)", "small.en")
        model_idx = self.asr_model_combo.findData(self.settings.asr_model_size)
        if model_idx >= 0:
            self.asr_model_combo.setCurrentIndex(model_idx)
        self.asr_model_combo.currentIndexChanged.connect(self._asr_settings_changed)
        self.asr_form.addRow("Local Whisper Model:", self.asr_model_combo)

        # Row 2: Local CPU Threads
        self.asr_threads_spin = QSpinBox(self)
        self.asr_threads_spin.setRange(1, 16)
        self.asr_threads_spin.setValue(self.settings.asr_cpu_threads)
        self.asr_threads_spin.valueChanged.connect(self._asr_settings_changed)
        self.asr_form.addRow("CPU Threads:", self.asr_threads_spin)

        # Row 3: Mac MLX URL
        self.mac_mlx_input = QLineEdit(self.settings.mac_mlx_url)
        self.mac_mlx_input.setPlaceholderText("http://192.168.0.88:9000")
        self.mac_mlx_input.textChanged.connect(self._asr_settings_changed)
        self.asr_form.addRow("Mac MLX URL:", self.mac_mlx_input)

        # Row 4: Groq API Key
        self.groq_key_input = QLineEdit(self.settings.groq_api_key)
        self.groq_key_input.setEchoMode(QLineEdit.Password)
        self.groq_key_input.setPlaceholderText("gsk_...")
        self.groq_key_input.textChanged.connect(self._asr_settings_changed)
        self.asr_form.addRow("Groq API Key:", self.groq_key_input)

        # Row 5: OpenAI API Key
        self.openai_key_input = QLineEdit(self.settings.openai_api_key)
        self.openai_key_input.setEchoMode(QLineEdit.Password)
        self.openai_key_input.setPlaceholderText("sk-...")
        self.openai_key_input.textChanged.connect(self._asr_settings_changed)
        self.asr_form.addRow("OpenAI API Key:", self.openai_key_input)

        tab_copilot_layout.addWidget(asr_group)

        # Live Copilot Reasoning Engine Group
        llm_group = QGroupBox("Live Copilot Reasoning & Synthesis")
        self.llm_form = QFormLayout(llm_group)

        # Row 0: LLM Provider
        self.llm_provider_combo = QComboBox(self)
        self.llm_provider_combo.addItem("Offline Extractive (Zero Config / Free / Private)", "offline")
        self.llm_provider_combo.addItem("LM Studio (Local / Remote Server)", "lm_studio")
        self.llm_provider_combo.addItem("OpenRouter Cloud (GPT-4o-mini, Claude, etc.)", "openrouter")
        self.llm_provider_combo.addItem("Google Gemini Cloud (Flash 2.0)", "gemini")
        self.llm_provider_combo.addItem("Local Ollama (via HTTP)", "ollama")
        llm_idx = self.llm_provider_combo.findData(self.settings.llm_provider)
        if llm_idx >= 0:
            self.llm_provider_combo.setCurrentIndex(llm_idx)
        self.llm_provider_combo.currentIndexChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("Reasoning Engine:", self.llm_provider_combo)

        # Row 1: LM Studio Server Type
        self.lm_studio_type_combo = QComboBox(self)
        self.lm_studio_type_combo.addItem("Local Server (localhost:1234)", "local")
        self.lm_studio_type_combo.addItem("Remote Server (Custom URL / LAN Host)", "remote")
        lm_type_idx = self.lm_studio_type_combo.findData(self.settings.lm_studio_server_type)
        if lm_type_idx >= 0:
            self.lm_studio_type_combo.setCurrentIndex(lm_type_idx)
        self.lm_studio_type_combo.currentIndexChanged.connect(self._on_lm_studio_type_changed)
        self.llm_form.addRow("LM Studio Server:", self.lm_studio_type_combo)

        # Row 2: LM Studio Endpoint
        self.lm_studio_url_input = QLineEdit(self.settings.lm_studio_endpoint)
        self.lm_studio_url_input.setPlaceholderText("http://localhost:1234/v1 or http://192.168.0.88:1234/v1")
        self.lm_studio_url_input.textChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("LM Studio URL:", self.lm_studio_url_input)

        # Row 3: OpenRouter Key
        self.openrouter_key_input = QLineEdit(self.settings.openrouter_api_key)
        self.openrouter_key_input.setEchoMode(QLineEdit.Password)
        self.openrouter_key_input.setPlaceholderText("sk-or-v1-...")
        self.openrouter_key_input.textChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("OpenRouter Key:", self.openrouter_key_input)

        # Row 4: Gemini Key
        self.gemini_key_input = QLineEdit(self.settings.gemini_api_key)
        self.gemini_key_input.setEchoMode(QLineEdit.Password)
        self.gemini_key_input.setPlaceholderText("AIzaSy...")
        self.gemini_key_input.textChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("Gemini API Key:", self.gemini_key_input)

        # Row 5: Ollama Endpoint
        self.ollama_endpoint_input = QLineEdit(self.settings.ollama_endpoint)
        self.ollama_endpoint_input.setPlaceholderText("http://localhost:11434/api/generate")
        self.ollama_endpoint_input.textChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("Ollama Endpoint:", self.ollama_endpoint_input)

        # Row 6: LLM Model Name
        self.llm_model_input = QLineEdit(self.settings.llm_model)
        self.llm_model_input.setPlaceholderText("openai/gpt-4o-mini, llama3.2, or local-model")
        self.llm_model_input.textChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("Model Name:", self.llm_model_input)

        # Row 7: Cadence
        self.cadence_combo = QComboBox(self)
        self.cadence_combo.addItem("20 Seconds", 20)
        self.cadence_combo.addItem("35 Seconds (Default)", 35)
        self.cadence_combo.addItem("45 Seconds", 45)
        self.cadence_combo.addItem("60 Seconds", 60)
        c_idx = self.cadence_combo.findData(self.settings.copilot_cadence_seconds)
        if c_idx >= 0:
            self.cadence_combo.setCurrentIndex(c_idx)
        else:
            self.cadence_combo.setCurrentIndex(1)
        self.cadence_combo.currentIndexChanged.connect(self._asr_settings_changed)
        self.llm_form.addRow("Analysis Cadence:", self.cadence_combo)

        # Row 8: Air-Gap / Privacy Mode
        self.privacy_mode_chk = QCheckBox("Air-Gap / Privacy Mode (Blocks cloud APIs, forces local ASR & Offline/Ollama/LM Studio)")
        self.privacy_mode_chk.setChecked(self.settings.privacy_mode)
        self.privacy_mode_chk.toggled.connect(self._asr_settings_changed)
        self.llm_form.addRow("", self.privacy_mode_chk)

        tab_copilot_layout.addWidget(llm_group)
        tab_copilot_layout.addStretch()

        self.pref_subtabs.addTab(tab_copilot, "Live Copilot & ASR")

        # Initial dynamic visibility adjustment
        self._update_dynamic_copilot_settings_visibility()

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

    def _tray_prefs_changed(self) -> None:
        self.settings.minimize_to_tray = self.min_to_tray_chk.isChecked()
        self.settings.close_to_tray = self.close_to_tray_chk.isChecked()
        self._log(f"Tray preferences updated: minimize_to_tray={self.settings.minimize_to_tray}, close_to_tray={self.settings.close_to_tray}")

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
                    speaker_name=self.settings.selected_speaker,
                    meeting_mode=self.settings.meeting_mode
                )
                self._start_copilot_session()
                
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
                
                notes_path = self._stop_copilot_session(file_path)
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
                        status="Local Only",
                        notes_path=notes_path
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
        self._start_copilot_session()
        self._log(f"[Monitor] Auto-recording started ({trigger.upper()})")
        self.statusBar().showMessage(f"Auto-recording started ({trigger.upper()}).")

    def _on_auto_record_finished(self, file_path: str, tags: List[int]) -> None:
        self.signaler.auto_record_finish_signal.emit(file_path, tags)

    def _handle_auto_record_finished(self, file_path: str, tags: List[int]) -> None:
        notes_path = self._stop_copilot_session(file_path)
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
                status="Local Only",
                notes_path=notes_path
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

    # Copilot & Meeting Mode Handlers
    def _meeting_mode_changed(self) -> None:
        mode = self.meeting_mode_combo.currentData()
        if mode:
            self.settings.meeting_mode = mode
            if self.vad_segmenter:
                self.vad_segmenter.set_meeting_mode(mode)
            if self.hud:
                self.hud.update_status(
                    recording=self.recorder.is_recording,
                    paused=self.recorder.is_paused,
                    meeting_mode=self.settings.meeting_mode,
                    asr_name_or_key=self.settings.asr_provider
                )
            self._log(f"Meeting mode set to: {mode.capitalize()}")

    def _copilot_toggle_changed(self, checked: bool) -> None:
        self.settings.copilot_enabled = checked
        self._log(f"Live Copilot HUD enabled: {checked}")

    def _on_lm_studio_type_changed(self, index: int) -> None:
        stype = self.lm_studio_type_combo.currentData()
        current_url = self.lm_studio_url_input.text().strip()
        if stype == "local":
            if not current_url or "192.168." in current_url or "10." in current_url:
                self.lm_studio_url_input.setText("http://localhost:1234/v1")
        elif stype == "remote":
            if current_url in ("", "http://localhost:1234/v1"):
                self.lm_studio_url_input.setText("http://192.168.0.88:1234/v1")
        self._asr_settings_changed()

    def _update_dynamic_copilot_settings_visibility(self) -> None:
        """Dynamically shows only fields relevant to selected ASR and LLM engines."""
        if not hasattr(self, "asr_form") or not hasattr(self, "llm_form"):
            return

        asr = self.asr_provider_combo.currentData()
        is_local = (asr == "local")
        is_mac = (asr == "mac_lan")
        is_groq = (asr == "groq")
        is_openai = (asr == "openai")

        # ASR rows:
        # 0: provider, 1: local model, 2: cpu threads, 3: mac mlx, 4: groq key, 5: openai key
        self.asr_form.setRowVisible(1, is_local)
        self.asr_form.setRowVisible(2, is_local)
        self.asr_form.setRowVisible(3, is_mac)
        self.asr_form.setRowVisible(4, is_groq)
        self.asr_form.setRowVisible(5, is_openai)

        # LLM rows:
        # 0: provider, 1: lm studio type, 2: lm studio url, 3: openrouter key, 4: gemini key, 5: ollama endpoint, 6: model name, 7: cadence, 8: privacy
        llm = self.llm_provider_combo.currentData()
        is_offline = (llm == "offline")
        is_lm_studio = (llm == "lm_studio")
        is_openrouter = (llm == "openrouter")
        is_gemini = (llm == "gemini")
        is_ollama = (llm == "ollama")

        self.llm_form.setRowVisible(1, is_lm_studio)
        self.llm_form.setRowVisible(2, is_lm_studio)
        self.llm_form.setRowVisible(3, is_openrouter)
        self.llm_form.setRowVisible(4, is_gemini)
        self.llm_form.setRowVisible(5, is_ollama)
        self.llm_form.setRowVisible(6, not is_offline)

    def _asr_settings_changed(self) -> None:
        provider = self.asr_provider_combo.currentData()
        if provider:
            self.settings.asr_provider = provider
        model_size = self.asr_model_combo.currentData()
        if model_size:
            self.settings.asr_model_size = model_size
        self.settings.asr_cpu_threads = self.asr_threads_spin.value()
        self.settings.mac_mlx_url = self.mac_mlx_input.text().strip()
        self.settings.groq_api_key = self.groq_key_input.text().strip()
        self.settings.openai_api_key = self.openai_key_input.text().strip()

        llm_provider = self.llm_provider_combo.currentData()
        if llm_provider:
            self.settings.llm_provider = llm_provider
        if hasattr(self, "lm_studio_type_combo"):
            lm_type = self.lm_studio_type_combo.currentData()
            if lm_type:
                self.settings.lm_studio_server_type = lm_type
        if hasattr(self, "lm_studio_url_input"):
            self.settings.lm_studio_endpoint = self.lm_studio_url_input.text().strip()
        self.settings.openrouter_api_key = self.openrouter_key_input.text().strip()
        self.settings.gemini_api_key = self.gemini_key_input.text().strip()
        self.settings.ollama_endpoint = self.ollama_endpoint_input.text().strip()
        self.settings.llm_model = self.llm_model_input.text().strip()
        cadence = self.cadence_combo.currentData()
        if cadence:
            self.settings.copilot_cadence_seconds = int(cadence)
        self.settings.privacy_mode = self.privacy_mode_chk.isChecked()

        self._update_dynamic_copilot_settings_visibility()

        if self.asr_manager:
            self.asr_manager.configure_provider(
                self.settings.asr_provider,
                {
                    "model_size": self.settings.asr_model_size,
                    "mac_mlx_url": self.settings.mac_mlx_url,
                    "groq_api_key": self.settings.groq_api_key,
                    "openai_api_key": self.settings.openai_api_key,
                    "cpu_threads": self.settings.asr_cpu_threads
                }
            )

        if self.copilot_agent:
            api_key = ""
            if self.settings.llm_provider == "openrouter":
                api_key = self.settings.openrouter_api_key
            elif self.settings.llm_provider == "gemini":
                api_key = self.settings.gemini_api_key

            endpoint = None
            if self.settings.llm_provider == "ollama":
                endpoint = self.settings.ollama_endpoint
            elif self.settings.llm_provider == "lm_studio":
                endpoint = self.settings.lm_studio_endpoint

            self.copilot_agent.configure(
                provider=self.settings.llm_provider,
                api_key=api_key,
                model_name=self.settings.llm_model,
                custom_endpoint=endpoint,
                privacy_mode=self.settings.privacy_mode
            )

        if self.hud:
            self.hud.update_status(
                recording=self.recorder.is_recording,
                paused=self.recorder.is_paused,
                meeting_mode=self.settings.meeting_mode,
                asr_name_or_key=self.settings.asr_provider
            )
        self._log("Copilot & ASR settings updated.")

    def _toggle_copilot_hud(self) -> None:
        """Toggles the visibility of the floating Copilot HUD."""
        if self.hud and self.hud.isVisible():
            self.hud.hide()
        else:
            self._ensure_copilot_session()
            if self.hud:
                self.hud.show()
                self.hud.raise_()
                self.hud.activateWindow()

    # Alias for backward compatibility
    _open_copilot_hud = _toggle_copilot_hud

    def _on_hud_visibility_changed(self, visible: bool) -> None:
        """Updates button label and styling based on HUD visibility."""
        if hasattr(self, "open_hud_btn"):
            if visible:
                self.open_hud_btn.setText("💡 Hide HUD")
                self.open_hud_btn.setStyleSheet("background-color: #475569; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px;")
            else:
                self.open_hud_btn.setText("💡 Open HUD")
                self.open_hud_btn.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px;")

    def _ensure_copilot_session(self) -> None:
        if self.copilot_memory is None:
            self.copilot_memory = CopilotMemory()
        
        if self.asr_manager is None:
            self.asr_manager = ASRManager(on_transcription_callback=self._on_copilot_transcription)
            self.asr_manager.configure_provider(
                self.settings.asr_provider,
                {
                    "model_size": self.settings.asr_model_size,
                    "mac_mlx_url": self.settings.mac_mlx_url,
                    "groq_api_key": self.settings.groq_api_key,
                    "openai_api_key": self.settings.openai_api_key,
                    "cpu_threads": self.settings.asr_cpu_threads
                }
            )

        if self.copilot_agent is None:
            self.copilot_agent = CopilotAgent(
                memory=self.copilot_memory,
                on_results_callback=self._on_copilot_agent_results,
                cadence_seconds=self.settings.copilot_cadence_seconds
            )

        if self.vad_segmenter is None:
            self.vad_segmenter = VADSegmenter(
                on_segment_callback=self.asr_manager.enqueue_segment,
                meeting_mode=self.settings.meeting_mode
            )

        if self.hud is None:
            self.hud = FloatingCopilotHUD(
                self.copilot_memory, 
                self.copilot_agent,
                initial_opacity=self.settings.hud_opacity
            )
            self.hud.meeting_mode_changed.connect(self._on_hud_meeting_mode_changed)
            self.hud.asr_provider_changed.connect(self._on_hud_asr_provider_changed)
            self.hud.opacity_changed.connect(self._on_hud_opacity_changed)
            self.hud.visibility_changed.connect(self._on_hud_visibility_changed)

    def _on_hud_meeting_mode_changed(self, mode: str) -> None:
        """Handle meeting mode switch initiated directly from HUD header badge."""
        self.settings.meeting_mode = mode
        if self.vad_segmenter:
            self.vad_segmenter.set_meeting_mode(mode)
        self.meeting_mode_combo.blockSignals(True)
        idx = self.meeting_mode_combo.findData(mode)
        if idx >= 0:
            self.meeting_mode_combo.setCurrentIndex(idx)
        self.meeting_mode_combo.blockSignals(False)
        self._log(f"[HUD] Switched meeting mode to: {mode.capitalize()}")

    def _on_hud_asr_provider_changed(self, provider: str) -> None:
        """Handle ASR engine switch initiated directly from HUD header badge."""
        self.settings.asr_provider = provider
        self.asr_provider_combo.blockSignals(True)
        idx = self.asr_provider_combo.findData(provider)
        if idx >= 0:
            self.asr_provider_combo.setCurrentIndex(idx)
        self.asr_provider_combo.blockSignals(False)
        self._update_dynamic_copilot_settings_visibility()
        if self.asr_manager:
            self.asr_manager.configure_provider(
                self.settings.asr_provider,
                {
                    "model_size": self.settings.asr_model_size,
                    "mac_mlx_url": self.settings.mac_mlx_url,
                    "groq_api_key": self.settings.groq_api_key,
                    "openai_api_key": self.settings.openai_api_key,
                    "cpu_threads": self.settings.asr_cpu_threads
                }
            )
        self._log(f"[HUD] Switched ASR engine to: {provider}")

    def _on_hud_opacity_changed(self, opacity: float) -> None:
        """Handle HUD opacity slider change."""
        self.settings.hud_opacity = opacity

    def _start_copilot_session(self) -> None:
        """Starts real-time transcription tap and Copilot agent."""
        if not self.settings.copilot_enabled:
            return

        self._ensure_copilot_session()
        self.copilot_memory.clear()
        self.vad_segmenter.reset()
        self.vad_segmenter.set_meeting_mode(self.settings.meeting_mode)

        active_tags = self.tag_selector.selected_tag_names()
        tag_name = active_tags[0] if active_tags else None
        
        api_key = ""
        if self.settings.llm_provider == "openrouter":
            api_key = self.settings.openrouter_api_key
        elif self.settings.llm_provider == "gemini":
            api_key = self.settings.gemini_api_key

        endpoint = None
        if self.settings.llm_provider == "ollama":
            endpoint = self.settings.ollama_endpoint
        elif self.settings.llm_provider == "lm_studio":
            endpoint = self.settings.lm_studio_endpoint

        self.copilot_agent.configure(
            provider=self.settings.llm_provider,
            api_key=api_key,
            model_name=self.settings.llm_model,
            custom_endpoint=endpoint,
            privacy_mode=self.settings.privacy_mode,
            active_tag=tag_name
        )

        self.recorder.audio_tap_callback = self.vad_segmenter.push_audio
        self.copilot_agent.start()

        self.hud.update_status(
            recording=True, 
            paused=False, 
            meeting_mode=self.settings.meeting_mode, 
            asr_name_or_key=self.settings.asr_provider
        )
        self.hud.show()
        self._log(f"[Copilot] Live session started (Mode: {self.settings.meeting_mode}, ASR: {self.settings.asr_provider}, LLM: {self.settings.llm_provider})")

    def _stop_copilot_session(self, associated_file_path: Optional[str] = None) -> Optional[str]:
        """Stops copilot agent, flushes notes to Markdown, and unhooks tap."""
        self.recorder.audio_tap_callback = None

        if self.copilot_agent:
            self.copilot_agent.stop()

        if self.hud:
            self.hud.update_status(
                recording=False, 
                paused=False, 
                meeting_mode=self.settings.meeting_mode, 
                asr_name_or_key=self.settings.asr_provider
            )

        notes_saved_path: Optional[str] = None
        if self.copilot_memory and (self.copilot_memory.live_notes or self.copilot_memory.suggested_questions):
            notes_md = self.copilot_memory.get_scratchpad_markdown()
            rec_dir = self.settings.resolved_recordings_dir
            timestamp_str = time.strftime("%Y-%m-%d_%H%M%S")
            if associated_file_path:
                stem = Path(associated_file_path).stem
                notes_filename = f"{stem}_Notes.md"
            else:
                notes_filename = f"Meeting_Notes_{timestamp_str}.md"
            notes_path = rec_dir / notes_filename
            try:
                with open(notes_path, "w", encoding="utf-8") as f:
                    f.write(f"# Meeting Live Notes ({timestamp_str})\n\n")
                    f.write(f"**Meeting Mode:** {self.settings.meeting_mode.capitalize()}\n\n")
                    f.write(notes_md)
                self._log(f"[Copilot] Live notes saved to: {notes_path.name}")
                notes_saved_path = str(notes_path.resolve())
                if associated_file_path:
                    self.storage.update_notes_path(associated_file_path, notes_saved_path)
            except Exception as ex:
                self._log(f"[Copilot] Error saving live notes: {ex}")

        return notes_saved_path

    def _on_copilot_transcription(self, segment: AudioSegment, text: str) -> None:
        if self.hud:
            self.hud.signals.transcription_received.emit(
                segment.channel,
                text,
                segment.timestamp,
                segment.turn_id
            )

    def _on_copilot_agent_results(self, results: dict) -> None:
        if self.hud:
            if results.get("type") == "quick_action":
                self.hud.signals.quick_action_received.emit(
                    results.get("title", "Quick Action"),
                    results.get("text", "")
                )
            else:
                self.hud.signals.agent_results_received.emit(results)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized() and self.settings.minimize_to_tray:
                event.ignore()
                QTimer.singleShot(0, self.hide)
                self._log("Application minimized to system tray.")
                return
            super().changeEvent(event)

    def closeEvent(self, event) -> None:
        if self.settings.close_to_tray:
            event.ignore()
            self.hide()
            self._log("Application hidden to system tray on window close.")
        else:
            self.duration_timer.stop()
            self.cooldown_timer.stop()
            self.monitor.stop()
            self.recorder.terminate()
            if self.copilot_agent:
                self.copilot_agent.stop()
            if self.asr_manager:
                self.asr_manager.shutdown()
            if self.hud:
                self.hud.close()
            event.accept()
            QApplication.quit()
