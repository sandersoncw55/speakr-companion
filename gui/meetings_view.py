import os
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QTimer, QDateTime
from PySide6.QtGui import QIcon, QFont, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTextBrowser, QFrame, QSplitter,
    QTabWidget, QApplication, QMessageBox, QProgressBar
)
from core.client import SpeakrClient
from core.config import Settings
from gui.theme import get_theme_palette


class ServerMeetingCardWidget(QWidget):
    """Custom widget for rendering a meeting item in the left meeting feed."""

    def __init__(self, meeting: Dict[str, Any], theme: str = "dark", parent=None):
        super().__init__(parent)
        self.meeting = meeting
        self.theme = theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Top row: Title
        title_text = meeting.get("title") or meeting.get("original_filename") or "Untitled Meeting"
        self.title_lbl = QLabel(title_text)
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.title_lbl.setWordWrap(True)
        layout.addWidget(self.title_lbl)

        # Meta row: Date/Time & Duration
        created_at = meeting.get("created_at") or meeting.get("timestamp") or ""
        duration_sec = meeting.get("duration") or meeting.get("audio_duration") or 0
        dur_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60)}s" if duration_sec else ""

        meta_parts = []
        if created_at:
            meta_parts.append(str(created_at)[:16].replace("T", " "))
        if dur_str:
            meta_parts.append(dur_str)

        self.meta_lbl = QLabel(" • ".join(meta_parts))
        self.meta_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.meta_lbl)

        # Participants if any
        raw_participants = meeting.get("participants") or []
        if isinstance(raw_participants, str):
            participants = [p.strip() for p in raw_participants.split(",") if p.strip()]
        elif isinstance(raw_participants, list):
            participants = raw_participants
        else:
            participants = []

        if participants:
            part_str = "👥 " + ", ".join(participants[:3])
            if len(participants) > 3:
                part_str += f" (+{len(participants)-3})"
            part_lbl = QLabel(part_str)
            part_lbl.setStyleSheet("font-size: 10px; font-style: italic;")
            layout.addWidget(part_lbl)

        # Tags row
        tags = meeting.get("tags") or []
        if tags:
            tag_box = QHBoxLayout()
            tag_box.setSpacing(4)
            for t in tags[:3]:
                t_name = t.get("name") if isinstance(t, dict) else str(t)
                t_color = t.get("color", "#0284c7") if isinstance(t, dict) else "#0284c7"
                badge = QLabel(f"● {t_name}")
                badge.setStyleSheet(f"""
                    background-color: #1e293b; color: {t_color}; border: 1px solid #334155;
                    border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;
                """)
                tag_box.addWidget(badge)
            tag_box.addStretch()
            layout.addLayout(tag_box)

        self.set_theme(theme)

    def set_theme(self, theme: str):
        self.theme = theme
        p = get_theme_palette(theme)
        is_light = (theme == "light")
        self.title_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {p['text_primary']};")
        self.meta_lbl.setStyleSheet(f"font-size: 11px; color: {p['text_muted']};")


class ServerMeetingsView(QWidget):
    """Meetings View pulling and displaying cloud meetings directly from the Speakr server."""
    meetings_loaded = Signal(list)
    details_loaded = Signal(str, dict)

    def __init__(self, settings: Settings, client: Optional[SpeakrClient] = None, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.settings = settings
        self.client = client
        self.theme = theme
        self.meetings_data: List[Dict[str, Any]] = []
        self.selected_meeting: Optional[Dict[str, Any]] = None
        self._current_detail_id: Optional[str] = None

        self.meetings_loaded.connect(self._on_meetings_loaded)
        self.details_loaded.connect(self._on_details_loaded)
        self._setup_ui()
        self.set_theme(theme)

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # Horizontal Splitter: Left Meeting Feed, Right Detail Browser
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #334155; width: 4px; border-radius: 2px; }")

        # --- LEFT COLUMN: Meeting List ---
        left_frame = QFrame()
        left_frame.setObjectName("leftPane")
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        # Header with Search and Refresh
        head_row = QHBoxLayout()
        title_lbl = QLabel("Meetings (Speakr Server)")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        head_row.addWidget(title_lbl)

        head_row.addStretch()

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setToolTip("Reload recordings from Speakr server")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #334155; border-radius: 4px;
                padding: 3px 8px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #1e293b; color: #38bdf8; }
        """)
        self.refresh_btn.clicked.connect(self.refresh_meetings)
        head_row.addWidget(self.refresh_btn)
        left_layout.addLayout(head_row)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search meetings by title or tag...")
        self.search_input.textChanged.connect(self._filter_meetings)
        left_layout.addWidget(self.search_input)

        # List Widget
        self.meetings_list = QListWidget()
        self.meetings_list.setSelectionMode(QListWidget.SingleSelection)
        self.meetings_list.currentRowChanged.connect(self._on_meeting_selected)
        left_layout.addWidget(self.meetings_list, 1)

        splitter.addWidget(left_frame)

        # --- RIGHT COLUMN: Selected Meeting Details ---
        right_frame = QFrame()
        right_frame.setObjectName("rightPane")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(8)

        # Top Detail Meta Bar
        meta_bar = QHBoxLayout()
        self.detail_title_lbl = QLabel("Select a meeting to view details")
        self.detail_title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        self.detail_title_lbl.setWordWrap(True)
        meta_bar.addWidget(self.detail_title_lbl, 1)

        self.open_portal_btn = QPushButton("↗ Open in Speakr")
        self.open_portal_btn.setToolTip("Open this meeting in the Speakr Web portal")
        self.open_portal_btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7; color: white; border: none;
                border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background-color: #0369a1; }
        """)
        self.open_portal_btn.clicked.connect(self._open_in_speakr_web)
        self.open_portal_btn.setVisible(False)
        meta_bar.addWidget(self.open_portal_btn)
        right_layout.addLayout(meta_bar)

        self.detail_meta_sub = QLabel("")
        self.detail_meta_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
        right_layout.addWidget(self.detail_meta_sub)

        # Actions toolbar: Copy Summary, Regenerate Summary
        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)

        self.copy_summary_btn = QPushButton("📋 Copy Summary")
        self.copy_summary_btn.clicked.connect(self._copy_summary)
        action_bar.addWidget(self.copy_summary_btn)

        self.regen_summary_btn = QPushButton("✨ Regenerate Summary")
        self.regen_summary_btn.clicked.connect(self._regenerate_summary)
        action_bar.addWidget(self.regen_summary_btn)

        action_bar.addStretch()
        right_layout.addLayout(action_bar)

        # Tab Widget: Summary Tab vs Transcript Tab
        self.detail_tabs = QTabWidget()

        # Tab 1: Summary Browser
        self.summary_browser = QTextBrowser()
        self.summary_browser.setOpenExternalLinks(True)
        self.detail_tabs.addTab(self.summary_browser, "Summary & Notes")

        # Tab 2: Transcript Browser
        self.transcript_browser = QTextBrowser()
        self.transcript_browser.setOpenExternalLinks(True)
        self.detail_tabs.addTab(self.transcript_browser, "Transcript")

        right_layout.addWidget(self.detail_tabs, 1)
        splitter.addWidget(right_frame)

        splitter.setSizes([380, 620])
        root_layout.addWidget(splitter)

    def set_client(self, client: SpeakrClient):
        self.client = client
        self.refresh_meetings()

    def refresh_meetings(self):
        """Asynchronously load meeting records from Speakr."""
        if not self.client:
            return

        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("⏳ Loading...")

        import threading
        def _worker():
            data = []
            try:
                data = self.client.list_recordings(limit=100)
            except Exception as e:
                print(f"[ServerMeetingsView] Error listing recordings: {e}")

            self.meetings_loaded.emit(data or [])

        threading.Thread(target=_worker, daemon=True).start()

    def _on_meetings_loaded(self, data: List[Dict[str, Any]]):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("🔄 Refresh")
        self.meetings_data = data or []
        self._populate_list(self.meetings_data)

    def _populate_list(self, meetings: List[Dict[str, Any]]):
        self.meetings_list.clear()
        p = get_theme_palette(self.theme)

        for m in meetings:
            item = QListWidgetItem(self.meetings_list)
            card = ServerMeetingCardWidget(m, theme=self.theme)
            item.setSizeHint(card.sizeHint())
            self.meetings_list.addItem(item)
            self.meetings_list.setItemWidget(item, card)

        if meetings and self.meetings_list.count() > 0:
            self.meetings_list.setCurrentRow(0)

    def _filter_meetings(self, text: str):
        query = text.strip().lower()
        if not query:
            self._populate_list(self.meetings_data)
            return

        filtered = []
        for m in self.meetings_data:
            title = (m.get("title") or m.get("original_filename") or "").lower()
            tags = " ".join([t.get("name", "") if isinstance(t, dict) else str(t) for t in m.get("tags", [])]).lower()
            if query in title or query in tags:
                filtered.append(m)
        self._populate_list(filtered)

    def _on_meeting_selected(self, row: int):
        if row < 0 or row >= len(self.meetings_data):
            return

        meeting = self.meetings_data[row]
        self.selected_meeting = meeting
        rec_id = str(meeting.get("id") or meeting.get("recording_id") or "")
        self._current_detail_id = rec_id

        self._render_meeting_details(meeting)

        # If summary or transcription is missing and we have a valid client, fetch details in background
        has_full = meeting.get("full_loaded") or (meeting.get("summary") and (meeting.get("transcription") or meeting.get("transcript")))
        if not has_full and rec_id and self.client:
            # Set loading indicators if content is empty
            if not meeting.get("summary") and not meeting.get("notes"):
                self.summary_browser.setMarkdown("*⏳ Fetching meeting summary and notes from Speakr server...*")
            if not meeting.get("transcription") and not meeting.get("transcript"):
                self.transcript_browser.setPlainText("⏳ Fetching transcript from Speakr server...")

            import threading
            def _fetch_details_worker(rid: str):
                details = None
                try:
                    details = self.client.get_recording(rid)
                except Exception as e:
                    print(f"[ServerMeetingsView] Error fetching recording {rid}: {e}")
                self.details_loaded.emit(rid, details or {})

            threading.Thread(target=_fetch_details_worker, args=(rec_id,), daemon=True).start()

    def _on_details_loaded(self, rec_id: str, details: Dict[str, Any]):
        if not details or self._current_detail_id != rec_id:
            return

        # Update cache in meetings_data
        for m in self.meetings_data:
            m_id = str(m.get("id") or m.get("recording_id") or "")
            if m_id == rec_id:
                m.update(details)
                m["full_loaded"] = True
                break

        if self.selected_meeting and str(self.selected_meeting.get("id") or self.selected_meeting.get("recording_id") or "") == rec_id:
            self.selected_meeting.update(details)
            self.selected_meeting["full_loaded"] = True
            self._render_meeting_details(self.selected_meeting)

    def _render_meeting_details(self, meeting: Dict[str, Any]):
        title = meeting.get("title") or meeting.get("original_filename") or "Untitled Meeting"
        self.detail_title_lbl.setText(title)

        created_at = str(meeting.get("created_at") or meeting.get("timestamp") or "")[:16].replace("T", " ")
        duration_sec = meeting.get("duration") or meeting.get("audio_duration") or 0
        dur_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60)}s" if duration_sec else ""
        
        meta_parts = []
        if created_at:
            meta_parts.append(f"Date: {created_at}")
        if dur_str:
            meta_parts.append(f"Duration: {dur_str}")

        raw_participants = meeting.get("participants") or []
        if isinstance(raw_participants, str):
            participants = [p.strip() for p in raw_participants.split(",") if p.strip()]
        elif isinstance(raw_participants, list):
            participants = raw_participants
        else:
            participants = []

        if participants:
            meta_parts.append(f"Participants: {', '.join(participants)}")

        self.detail_meta_sub.setText(" • ".join(meta_parts))
        self.open_portal_btn.setVisible(True)

        # 1. Summary & Notes
        summary_raw = meeting.get("summary") or ""
        notes_raw = meeting.get("notes") or ""

        content_blocks = []
        if summary_raw.strip():
            content_blocks.append(summary_raw.strip())
        if notes_raw.strip():
            content_blocks.append(f"---\n### 📝 Attached Notes\n{notes_raw.strip()}")

        if content_blocks:
            full_summary_md = "\n\n".join(content_blocks)
            self.summary_browser.setMarkdown(full_summary_md)
        else:
            self.summary_browser.setMarkdown("*No summary generated yet for this recording.*")

        # 2. Transcript
        tr_raw = meeting.get("transcription") or meeting.get("transcript") or ""
        if isinstance(tr_raw, list):
            lines = []
            for seg in tr_raw:
                if isinstance(seg, dict):
                    spk = seg.get("speaker") or seg.get("speaker_name") or "Unknown"
                    txt = seg.get("text") or seg.get("transcription") or ""
                    ts = seg.get("start")
                    ts_prefix = f"[{int(ts//60):02d}:{int(ts%60):02d}] " if ts is not None else ""
                    lines.append(f"{ts_prefix}{spk}: {txt}")
                else:
                    lines.append(str(seg))
            tr_text = "\n\n".join(lines)
        elif isinstance(tr_raw, str) and tr_raw.strip():
            tr_text = tr_raw.strip()
        else:
            tr_text = "*Transcript text not available.*"

        self.transcript_browser.setPlainText(tr_text)

    def _copy_summary(self):
        text = self.summary_browser.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.copy_summary_btn.setText("✓ Copied!")
            QTimer.singleShot(1500, lambda: self.copy_summary_btn.setText("📋 Copy Summary"))

    def _regenerate_summary(self):
        if not self.selected_meeting or not self.client:
            return
        rec_id = str(self.selected_meeting.get("id") or self.selected_meeting.get("recording_id") or "")
        if not rec_id:
            return

        self.regen_summary_btn.setEnabled(False)
        self.regen_summary_btn.setText("⏳ Regenerating...")

        import threading
        def _worker():
            ok = self.client.trigger_summarization(rec_id)
            QTimer.singleShot(0, lambda: self._on_summary_regen_finished(ok))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_summary_regen_finished(self, ok: bool):
        self.regen_summary_btn.setEnabled(True)
        self.regen_summary_btn.setText("✨ Regenerate Summary")
        if ok:
            QMessageBox.information(self, "Summary Requested", "Summarization triggered successfully on the Speakr server.")
            self.refresh_meetings()
        else:
            QMessageBox.warning(self, "Error", "Failed to trigger summarization on Speakr server.")

    def _open_in_speakr_web(self):
        if not self.selected_meeting or not self.settings:
            return
        base = self.settings.speakr_url.rstrip("/")
        if base.endswith("/api/v1"):
            base = base[:-7]
        rec_id = self.selected_meeting.get("id") or self.selected_meeting.get("recording_id")
        target_url = f"{base}/recordings/{rec_id}" if rec_id else base
        QDesktopServices.openUrl(target_url)

    def set_theme(self, theme: str):
        self.theme = theme
        p = get_theme_palette(theme)
        is_light = (theme == "light")

        card_bg = "#ffffff" if is_light else "#1e293b"
        border_col = p['border_subtle']

        self.setStyleSheet(f"""
            QFrame#leftPane, QFrame#rightPane {{
                background-color: {card_bg};
                border: 1px solid {border_col};
                border-radius: 6px;
            }}
            QListWidget {{
                background-color: {p['bg_input']};
                border: 1px solid {border_col};
                border-radius: 4px;
            }}
            QListWidget::item {{
                border-bottom: 1px solid {border_col};
            }}
            QListWidget::item:selected {{
                background-color: {'#e0f2fe' if is_light else '#0369a1'};
            }}
            QLineEdit {{
                background-color: {p['bg_input']};
                border: 1px solid {border_col};
                border-radius: 4px;
                padding: 6px;
                color: {p['text_primary']};
            }}
            QTextBrowser {{
                background-color: {p['bg_input']};
                border: 1px solid {border_col};
                border-radius: 4px;
                color: {p['text_primary']};
            }}
        """)
