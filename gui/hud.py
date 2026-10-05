import os
import time
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize, QRect
from PySide6.QtGui import QIcon, QFont, QColor, QClipboard, QAction, QKeyEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit, QPlainTextEdit,
    QFrame, QSplitter, QCheckBox, QSlider, QApplication, QComboBox,
    QAbstractItemView, QGroupBox
)
from core.config import get_app_icon, Settings
from core.copilot.memory import CopilotMemory, SuggestedQuestion

class CopilotSignals(QObject):
    """Thread-safe Qt signals bridging background audio/agent workers to GUI."""
    transcription_received = Signal(str, str, float, int)  # channel, text, timestamp, turn_id
    agent_results_received = Signal(dict)
    quick_action_received = Signal(str, str)               # title, text
    scratchpad_updated = Signal()


class TwoLineNoteEdit(QPlainTextEdit):
    """Multi-line note input that submits on Enter and inserts newline on Shift+Enter."""
    enter_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setPlaceholderText("+ Add custom note or context... (Enter to add, Shift+Enter for newline)")
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px 6px;
                color: #f8fafc;
                font-size: 12px;
                line-height: 1.2;
            }
            QPlainTextEdit:focus {
                border: 1px solid #10b981;
            }
        """)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not (event.modifiers() & Qt.ShiftModifier):
                event.accept()
                self.enter_pressed.emit()
                return
        super().keyPressEvent(event)


class QuestionItemWidget(QWidget):
    """Widget rendering an individual suggested question with Copy, Mark-Asked, and Dismiss actions."""

    def __init__(self, question: SuggestedQuestion, on_copy_cb, on_asked_cb, on_dismiss_cb):
        super().__init__()
        self.question = question
        self.on_copy_cb = on_copy_cb
        self.on_asked_cb = on_asked_cb
        self.on_dismiss_cb = on_dismiss_cb

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Question text
        self.label = QLabel(question.question)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 600; line-height: 1.3;")
        layout.addWidget(self.label)

        # Rationale sub-text if present
        if question.rationale:
            self.rationale_label = QLabel(f"💡 {question.rationale}")
            self.rationale_label.setWordWrap(True)
            self.rationale_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-style: italic;")
            layout.addWidget(self.rationale_label)

        # Actions Layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        # Copy button
        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setToolTip("Copy question to clipboard")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155; color: #f8fafc; border: 1px solid #475569;
                border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.copy_btn.clicked.connect(lambda: self.on_copy_cb(self.question.question))
        btn_layout.addWidget(self.copy_btn)

        # Mark Asked button
        self.asked_btn = QPushButton("✔ Asked")
        self.asked_btn.setToolTip("Mark as asked (moves to scratchpad as addressed)")
        self.asked_btn.setStyleSheet("""
            QPushButton {
                background-color: #065f46; color: #a7f3d0; border: 1px solid #059669;
                border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        self.asked_btn.clicked.connect(lambda: self.on_asked_cb(self.question.question))
        btn_layout.addWidget(self.asked_btn)

        btn_layout.addStretch()

        # Dismiss button
        self.dismiss_btn = QPushButton("✕ Dismiss")
        self.dismiss_btn.setToolTip("Dismiss this suggestion")
        self.dismiss_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #94a3b8; border: 1px solid #334155;
                border-radius: 4px; padding: 3px 8px; font-size: 11px;
            }
            QPushButton:hover { background-color: #1e293b; color: #ef4444; border-color: #7f1d1d; }
        """)
        self.dismiss_btn.clicked.connect(lambda: self.on_dismiss_cb(self.question.question))
        btn_layout.addWidget(self.dismiss_btn)

        layout.addLayout(btn_layout)


class CopilotDashboardWidget(QWidget):
    """Embedded, comprehensive in-app Live Meeting Intelligence & Copilot widget."""

    # Public Qt signals for synchronization with main window
    meeting_mode_changed = Signal(str)
    asr_provider_changed = Signal(str)
    opacity_changed = Signal(float)
    visibility_changed = Signal(bool)

    def __init__(self, memory: CopilotMemory, copilot_agent, initial_opacity: float = 0.92, parent=None):
        super().__init__(parent)
        self.memory = memory
        self.agent = copilot_agent
        self.signals = CopilotSignals()

        # Connect thread-safe signals
        self.signals.transcription_received.connect(self._on_transcription_gui)
        self.signals.agent_results_received.connect(self._on_agent_results_gui)
        self.signals.quick_action_received.connect(self._on_quick_action_gui)

        self._setup_ui()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # --- Top Header & Controls Bar ---
        header_frame = QFrame()
        header_frame.setObjectName("card")
        header_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(8)

        self.status_dot = QLabel("🟢")
        self.status_title = QLabel("LIVE MEETING COPILOT")
        self.status_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #38bdf8; letter-spacing: 0.5px;")
        header_layout.addWidget(self.status_dot)
        header_layout.addWidget(self.status_title)

        # Mode interactive dropdown
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("🌐 Virtual Call", "virtual")
        self.mode_combo.addItem("🎙️ In-Person Room", "in_person")
        self.mode_combo.addItem("🔀 Hybrid Room", "hybrid")
        self.mode_combo.setToolTip("Select Meeting Audio Mode")
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #0369a1; color: white; border: 1px solid #0284c7;
                border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold;
            }
            QComboBox:hover { background-color: #0284c7; }
        """)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo_changed)
        header_layout.addWidget(self.mode_combo)

        # ASR interactive dropdown
        self.asr_combo = QComboBox()
        self.asr_combo.addItem("Local CPU Whisper", "local")
        self.asr_combo.addItem("Mac LAN Whisper-MLX", "mac_lan")
        self.asr_combo.addItem("Groq Cloud Whisper", "groq")
        self.asr_combo.addItem("OpenAI Cloud Whisper", "openai")
        self.asr_combo.setToolTip("Speech-to-Text (ASR) Engine")
        self.asr_combo.setStyleSheet("""
            QComboBox {
                background-color: #334155; color: #cbd5e1; border: 1px solid #475569;
                border-radius: 4px; padding: 3px 8px; font-size: 11px;
            }
            QComboBox:hover { background-color: #475569; }
        """)
        self.asr_combo.currentIndexChanged.connect(self._on_asr_combo_changed)
        header_layout.addWidget(self.asr_combo)

        header_layout.addStretch()

        # Copy Full Notes Markdown button
        self.copy_md_btn = QPushButton("📋 Copy Markdown Notes")
        self.copy_md_btn.setToolTip("Copy the full scratchpad and notes markdown to clipboard")
        self.copy_md_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155; color: #f8fafc; border: 1px solid #475569;
                border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.copy_md_btn.clicked.connect(self._copy_markdown_notes)
        header_layout.addWidget(self.copy_md_btn)

        # Reset Session / Clear button
        self.reset_btn = QPushButton("🔄 Reset Session")
        self.reset_btn.setToolTip("Reset Copilot Session (Clear transcript, questions, & scratchpad)")
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #94a3b8; border: 1px solid #334155;
                border-radius: 4px; padding: 4px 10px; font-size: 11px;
            }
            QPushButton:hover { background-color: #334155; color: #f87171; border-color: #7f1d1d; }
        """)
        self.reset_btn.clicked.connect(self._on_manual_reset_clicked)
        header_layout.addWidget(self.reset_btn)

        root_layout.addWidget(header_frame)

        # --- Quick Actions Bar ---
        quick_frame = QFrame()
        quick_frame.setObjectName("card")
        quick_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        quick_layout = QVBoxLayout(quick_frame)
        quick_layout.setContentsMargins(6, 4, 6, 4)
        quick_layout.setSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        q_label = QLabel("⚡ QUICK ACTIONS:")
        q_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #94a3b8; letter-spacing: 0.5px;")
        btn_row.addWidget(q_label)

        self.btn_ask = QPushButton("💡 What to ask?")
        self.btn_ask.setStyleSheet(self._quick_btn_style("#2563eb"))
        self.btn_ask.clicked.connect(lambda: self.agent.run_quick_prompt("what_to_ask"))
        btn_row.addWidget(self.btn_ask)

        self.btn_catchup = QPushButton("⏱️ Catch up")
        self.btn_catchup.setStyleSheet(self._quick_btn_style("#0d9488"))
        self.btn_catchup.clicked.connect(lambda: self.agent.run_quick_prompt("catch_me_up"))
        btn_row.addWidget(self.btn_catchup)

        self.btn_owners = QPushButton("🎯 Owners")
        self.btn_owners.setStyleSheet(self._quick_btn_style("#4f46e5"))
        self.btn_owners.clicked.connect(lambda: self.agent.run_quick_prompt("clarify_ownership"))
        btn_row.addWidget(self.btn_owners)

        self.btn_risks = QPushButton("🚩 Risks")
        self.btn_risks.setStyleSheet(self._quick_btn_style("#b91c1c"))
        self.btn_risks.clicked.connect(lambda: self.agent.run_quick_prompt("spot_risks"))
        btn_row.addWidget(self.btn_risks)

        self.btn_jargon = QPushButton("🔍 Jargon")
        self.btn_jargon.setStyleSheet(self._quick_btn_style("#d97706"))
        self.btn_jargon.clicked.connect(lambda: self.agent.run_quick_prompt("explain_jargon"))
        btn_row.addWidget(self.btn_jargon)

        btn_row.addStretch()
        quick_layout.addLayout(btn_row)

        # Ad-hoc write-in query box
        self.adhoc_input = QLineEdit()
        self.adhoc_input.setPlaceholderText("Ask the copilot anything about this meeting... (Press Enter to query)")
        self.adhoc_input.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 4px;
                padding: 4px 8px; color: #f8fafc; font-size: 12px;
            }
            QLineEdit:focus { border: 1px solid #38bdf8; }
        """)
        self.adhoc_input.returnPressed.connect(self._submit_adhoc_query)
        quick_layout.addWidget(self.adhoc_input)

        root_layout.addWidget(quick_frame)

        # --- Main Splitter: Left (Live Transcript) vs Right (Questions & Scratchpad) ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #334155; width: 4px; border-radius: 2px; }")

        # --- Left Pane: Live Transcript Stream ---
        transcript_frame = QFrame()
        transcript_frame.setObjectName("card")
        transcript_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        transcript_layout = QVBoxLayout(transcript_frame)
        transcript_layout.setContentsMargins(8, 6, 8, 6)
        transcript_layout.setSpacing(4)

        tr_head = QHBoxLayout()
        tr_title = QLabel("💬 LIVE TRANSCRIPT STREAM")
        tr_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #a78bfa; letter-spacing: 0.5px;")
        tr_head.addWidget(tr_title)
        tr_head.addStretch()

        self.auto_scroll_chk = QCheckBox("Auto-scroll")
        self.auto_scroll_chk.setChecked(True)
        self.auto_scroll_chk.setStyleSheet("color: #94a3b8; font-size: 10px;")
        tr_head.addWidget(self.auto_scroll_chk)

        clear_tr_btn = QPushButton("Clear Feed")
        clear_tr_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #64748b; font-size: 10px; }
            QPushButton:hover { color: #cbd5e1; }
        """)
        clear_tr_btn.clicked.connect(self._clear_transcript_feed)
        tr_head.addWidget(clear_tr_btn)
        transcript_layout.addLayout(tr_head)

        self.ticker_box = QTextEdit()
        self.ticker_box.setReadOnly(True)
        self.ticker_box.setStyleSheet("""
            QTextEdit {
                background-color: #020617; border: 1px solid #0f172a; border-radius: 4px;
                color: #e2e8f0; font-size: 11px; font-family: 'Consolas', 'Courier New', monospace;
                line-height: 1.4;
            }
        """)
        transcript_layout.addWidget(self.ticker_box)
        self.splitter.addWidget(transcript_frame)

        # --- Right Container: Questions (Top) and Scratchpad (Bottom) ---
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setStyleSheet("QSplitter::handle { background-color: #334155; height: 4px; border-radius: 2px; }")

        # --- Section 1: Suggested Questions Card ---
        q_frame = QFrame()
        q_frame.setObjectName("card")
        q_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        q_card_layout = QVBoxLayout(q_frame)
        q_card_layout.setContentsMargins(8, 6, 8, 6)
        q_card_layout.setSpacing(4)

        q_head_layout = QHBoxLayout()
        q_head = QLabel("💡 SUGGESTED QUESTIONS & INTERVENTIONS")
        q_head.setStyleSheet("font-size: 11px; font-weight: bold; color: #38bdf8; letter-spacing: 0.5px;")
        q_head_layout.addWidget(q_head)

        self.q_count_badge = QLabel("0")
        self.q_count_badge.setStyleSheet("""
            QLabel {
                background-color: #0369a1;
                color: #e0f2fe;
                font-size: 10px;
                font-weight: bold;
                border-radius: 7px;
                padding: 1px 6px;
            }
        """)
        self.q_count_badge.setVisible(False)
        q_head_layout.addWidget(self.q_count_badge)
        q_head_layout.addStretch()

        self.q_clear_btn = QPushButton("Clear All")
        self.q_clear_btn.setToolTip("Clear all pending suggested questions")
        self.q_clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #94a3b8;
                font-size: 10px;
                padding: 1px 6px;
            }
            QPushButton:hover {
                background: #1e293b;
                color: #f87171;
                border-color: #7f1d1d;
            }
        """)
        self.q_clear_btn.clicked.connect(self._clear_suggested_questions)
        self.q_clear_btn.setVisible(False)
        q_head_layout.addWidget(self.q_clear_btn)
        q_card_layout.addLayout(q_head_layout)

        self.questions_list = QListWidget()
        self.questions_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.questions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.questions_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.questions_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;
                margin-bottom: 5px;
            }
        """)
        q_card_layout.addWidget(self.questions_list)
        right_splitter.addWidget(q_frame)

        # --- Section 2: Interactive Live Scratchpad ---
        notes_frame = QFrame()
        notes_frame.setObjectName("card")
        notes_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        notes_layout = QVBoxLayout(notes_frame)
        notes_layout.setContentsMargins(8, 6, 8, 6)
        notes_layout.setSpacing(4)

        notes_head = QHBoxLayout()
        notes_title = QLabel("📝 LIVE SCRATCHPAD (Notes & Addressed Points)")
        notes_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #34d399; letter-spacing: 0.5px;")
        notes_head.addWidget(notes_title)
        notes_head.addStretch()

        self.open_notes_folder_btn = QPushButton("📁 Notes Folder")
        self.open_notes_folder_btn.setToolTip("Open recordings and meeting notes directory")
        self.open_notes_folder_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #94a3b8;
                font-size: 10px;
                padding: 1px 6px;
            }
            QPushButton:hover {
                background: #1e293b;
                color: #34d399;
                border-color: #059669;
            }
        """)
        self.open_notes_folder_btn.clicked.connect(self._open_notes_folder)
        notes_head.addWidget(self.open_notes_folder_btn)
        notes_layout.addLayout(notes_head)

        # Notes list with checkboxes
        self.notes_list = QListWidget()
        self.notes_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;
                padding: 3px 6px; margin-bottom: 4px; color: #cbd5e1; font-size: 12px;
            }
            QListWidget::item:hover { background-color: #1e293b; }
        """)
        notes_layout.addWidget(self.notes_list)

        # 2-line Add custom note input
        add_note_box = QHBoxLayout()
        add_note_box.setSpacing(6)
        self.add_note_input = TwoLineNoteEdit()
        self.add_note_input.enter_pressed.connect(self._add_custom_note)
        add_note_box.addWidget(self.add_note_input, 1)

        add_btn = QPushButton("Add Note")
        add_btn.setFixedHeight(48)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: white; border: none; border-radius: 4px;
                padding: 4px 12px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        add_btn.clicked.connect(self._add_custom_note)
        add_note_box.addWidget(add_btn)
        notes_layout.addLayout(add_note_box)

        right_splitter.addWidget(notes_frame)

        # Balanced proportions for right vertical splitter
        right_splitter.setSizes([240, 220])
        self.splitter.addWidget(right_splitter)

        # Proportions: 45% Left (Transcript), 55% Right (Questions & Notes)
        self.splitter.setSizes([450, 550])
        root_layout.addWidget(self.splitter, 1)

    def _quick_btn_style(self, bg_color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg_color}; color: #ffffff; border: none; border-radius: 4px;
                padding: 4px 8px; font-size: 11px; font-weight: 600;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """

    def _on_mode_combo_changed(self, index: int):
        mode = self.mode_combo.currentData()
        if mode:
            self.meeting_mode_changed.emit(mode)

    def _on_asr_combo_changed(self, index: int):
        provider = self.asr_combo.currentData()
        if provider:
            self.asr_provider_changed.emit(provider)

    def _clear_transcript_feed(self):
        self.ticker_box.clear()

    def _open_notes_folder(self):
        try:
            cfg = Settings()
            rec_dir = cfg.resolved_recordings_dir
            if rec_dir.exists():
                os.startfile(str(rec_dir))
        except Exception as e:
            print(f"[CopilotWidget] Error opening notes folder: {e}")

    def _copy_markdown_notes(self):
        md = self.memory.get_scratchpad_markdown()
        clipboard = QApplication.clipboard()
        clipboard.setText(md)
        self.copy_md_btn.setText("✓ Copied!")
        QTimer.singleShot(1800, lambda: self.copy_md_btn.setText("📋 Copy Markdown Notes"))

    def _submit_adhoc_query(self):
        query = self.adhoc_input.text().strip()
        if query:
            self.adhoc_input.clear()
            self.agent.run_quick_prompt(query)

    def _add_custom_note(self):
        text = self.add_note_input.toPlainText().strip()
        if text:
            self.add_note_input.clear()
            self.memory.add_user_note(text)
            self._render_notes()

    def _on_copy_question(self, question_text: str):
        clipboard = QApplication.clipboard()
        clipboard.setText(question_text)
        self.status_title.setText("COPIED TO CLIPBOARD!")
        QTimer.singleShot(1500, lambda: self.status_title.setText("LIVE MEETING COPILOT"))

    def _on_mark_asked(self, question_text: str):
        self.memory.mark_question_asked(question_text)
        self._render_questions()
        self._render_notes()

    def _on_dismiss_question(self, question_text: str):
        self.memory.mark_question_dismissed(question_text)
        self._render_questions()

    def _on_transcription_gui(self, channel: str, text: str, timestamp: float, turn_id: int):
        """Append to memory and update ticker display."""
        turn = self.memory.add_transcript(channel, text, timestamp, turn_id)
        
        color = "#38bdf8" if channel == "you" else ("#a78bfa" if channel == "participants" else "#34d399")
        entry_html = f"<div style='margin-bottom: 4px;'><span style='color: {color}; font-weight: bold;'>{turn.speaker_label} ({turn.formatted_time}):</span> <span style='color: #e2e8f0;'>{turn.text}</span></div>"
        
        self.ticker_box.append(entry_html)
        if self.auto_scroll_chk.isChecked():
            scrollbar = self.ticker_box.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_agent_results_gui(self, results: dict):
        """Refreshes suggested questions and notes cards."""
        self._render_questions()
        self._render_notes()

    def _on_quick_action_gui(self, title: str, text: str):
        """Displays quick-action response in notes."""
        self.memory.add_user_note(f"⚡ [{title}] {text}")
        self._render_notes()

    def _clear_suggested_questions(self):
        """Clears pending questions from memory and updates display."""
        self.memory.clear_suggested_questions(status="pending")
        self._render_questions()

    def _render_questions(self):
        self.questions_list.clear()
        pending_questions = [q for q in self.memory.suggested_questions if q.status == "pending"]
        
        count = len(pending_questions)
        self.q_count_badge.setText(f"{count} pending" if count > 0 else "0")
        self.q_count_badge.setVisible(count > 0)
        self.q_clear_btn.setVisible(count > 0)

        for q in pending_questions:
            item = QListWidgetItem(self.questions_list)
            widget = QuestionItemWidget(
                q,
                on_copy_cb=self._on_copy_question,
                on_asked_cb=self._on_mark_asked,
                on_dismiss_cb=self._on_dismiss_question
            )
            item.setSizeHint(widget.sizeHint())
            self.questions_list.addItem(item)
            self.questions_list.setItemWidget(item, widget)

    def _render_notes(self):
        self.notes_list.blockSignals(True)
        self.notes_list.clear()
        
        # Render asked questions as checked items
        asked_q = [q for q in self.memory.suggested_questions if q.status == "asked"]
        for q in asked_q:
            item = QListWidgetItem(f"[Asked] {q.question}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.notes_list.addItem(item)

        # Render running notes
        for note in self.memory.live_notes:
            if not note.startswith("[Asked]"):
                item = QListWidgetItem(note)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.notes_list.addItem(item)

        self.notes_list.blockSignals(False)

    def _on_manual_reset_clicked(self):
        """Manually resets session memory and clears displays."""
        self.memory.clear()
        self.clear()

    def clear(self):
        """Clears all UI elements in the widget for a clean session."""
        self.ticker_box.clear()
        self.questions_list.clear()
        self.notes_list.clear()
        self.q_count_badge.setText("0")
        self.q_count_badge.setVisible(False)
        self.q_clear_btn.setVisible(False)
        self.add_note_input.clear()
        self.adhoc_input.clear()

    def update_status(self, recording: bool, paused: bool, meeting_mode: str, asr_name_or_key: str, notes_saved: bool = False):
        """Updates header dropdowns and status dot."""
        dot_str = "🟡" if paused else ("🔴" if recording else "🟢")
        self.status_dot.setText(dot_str)

        if paused:
            self.status_dot.setToolTip("Status: Paused")
        elif recording:
            self.status_dot.setToolTip("Status: Recording Active")
        else:
            status_text = "Status: Idle • Notes Saved 💾" if notes_saved else "Status: Idle"
            self.status_dot.setToolTip(status_text)

        # Sync meeting mode combo safely
        self.mode_combo.blockSignals(True)
        mode_idx = self.mode_combo.findData(meeting_mode)
        if mode_idx >= 0:
            self.mode_combo.setCurrentIndex(mode_idx)
        self.mode_combo.blockSignals(False)

        # Sync ASR combo safely
        self.asr_combo.blockSignals(True)
        asr_idx = self.asr_combo.findData(asr_name_or_key)
        if asr_idx < 0:
            asr_idx = self.asr_combo.findText(asr_name_or_key, Qt.MatchContains)
        if asr_idx >= 0:
            self.asr_combo.setCurrentIndex(asr_idx)
        self.asr_combo.blockSignals(False)


# Alias for backward compatibility
FloatingCopilotHUD = CopilotDashboardWidget
