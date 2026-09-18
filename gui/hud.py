import time
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize
from PySide6.QtGui import QIcon, QFont, QColor, QClipboard, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit, QFrame,
    QScrollArea, QSplitter, QCheckBox, QMenu, QSlider, QApplication
)
from core.config import get_app_icon
from core.copilot.memory import CopilotMemory, SuggestedQuestion

class CopilotSignals(QObject):
    """Thread-safe Qt signals bridging background audio/agent workers to GUI."""
    transcription_received = Signal(str, str, float, int)  # channel, text, timestamp, turn_id
    agent_results_received = Signal(dict)
    quick_action_received = Signal(str, str)               # title, text
    scratchpad_updated = Signal()

class QuestionItemWidget(QWidget):
    """Widget rendering an individual suggested question with Copy and Mark-Asked actions."""

    def __init__(self, question: SuggestedQuestion, on_copy_cb, on_asked_cb, on_dismiss_cb):
        super().__init__()
        self.question = question
        self.on_copy_cb = on_copy_cb
        self.on_asked_cb = on_asked_cb
        self.on_dismiss_cb = on_dismiss_cb

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        # Question label
        self.label = QLabel(question.question)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #e2e8f0; font-size: 13px; font-weight: 500;")
        layout.addWidget(self.label, 1)

        # Actions Layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        # Copy button
        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setToolTip("Copy question to clipboard")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155; color: #f8fafc; border: 1px solid #475569;
                border-radius: 4px; padding: 3px 8px; font-size: 11px;
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

        # Dismiss button
        self.dismiss_btn = QPushButton("✕")
        self.dismiss_btn.setToolTip("Dismiss this suggestion")
        self.dismiss_btn.setFixedSize(22, 22)
        self.dismiss_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #94a3b8; border: none; font-size: 12px;
            }
            QPushButton:hover { color: #ef4444; }
        """)
        self.dismiss_btn.clicked.connect(lambda: self.on_dismiss_cb(self.question.question))
        btn_layout.addWidget(self.dismiss_btn)

        layout.addLayout(btn_layout)


class FloatingCopilotHUD(QWidget):
    """Always-on-top, translucent in-call meeting intelligence HUD."""

    def __init__(self, memory: CopilotMemory, copilot_agent, parent=None):
        super().__init__(parent)
        self.memory = memory
        self.agent = copilot_agent
        self.signals = CopilotSignals()

        # Connect thread-safe signals
        self.signals.transcription_received.connect(self._on_transcription_gui)
        self.signals.agent_results_received.connect(self._on_agent_results_gui)
        self.signals.quick_action_received.connect(self._on_quick_action_gui)

        # Window properties
        self.setWindowTitle("Speakr Copilot HUD")
        self.setWindowIcon(get_app_icon())
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowMinMaxButtonsHint)
        self.resize(460, 680)
        self.setMinimumSize(380, 480)

        # Overall styling (dark translucent glassmorphism)
        self.setStyleSheet("""
            QWidget {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QScrollBar:vertical {
                border: none; background: #0f172a; width: 6px; margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #475569; min-height: 20px; border-radius: 3px;
            }
        """)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)

        # --- Header Bar ---
        header = QHBoxLayout()
        self.status_dot = QLabel("🟢")
        self.status_title = QLabel("LIVE COPILOT")
        self.status_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #38bdf8; letter-spacing: 0.5px;")
        
        self.mode_badge = QLabel("Virtual")
        self.mode_badge.setStyleSheet("background: #0284c7; color: white; border-radius: 4px; padding: 2px 6px; font-size: 11px;")

        self.asr_badge = QLabel("Local CPU")
        self.asr_badge.setStyleSheet("background: #334155; color: #cbd5e1; border-radius: 4px; padding: 2px 6px; font-size: 11px;")

        header.addWidget(self.status_dot)
        header.addWidget(self.status_title)
        header.addWidget(self.mode_badge)
        header.addWidget(self.asr_badge)
        header.addStretch()

        # Pin On Top toggle button
        self.pin_btn = QPushButton("📌")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(True)
        self.pin_btn.setFixedSize(28, 24)
        self.pin_btn.setToolTip("Toggle Always on Top")
        self.pin_btn.setStyleSheet("""
            QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 4px; font-size: 12px; }
            QPushButton:checked { background: #0284c7; border: 1px solid #38bdf8; }
        """)
        self.pin_btn.clicked.connect(self._toggle_pin)
        header.addWidget(self.pin_btn)

        main_layout.addLayout(header)

        # --- Quick Action Bar ---
        quick_frame = QFrame()
        quick_frame.setObjectName("card")
        quick_layout = QVBoxLayout(quick_frame)
        quick_layout.setContentsMargins(8, 8, 8, 8)
        quick_layout.setSpacing(6)

        q_label = QLabel("⚡ QUICK ACTIONS")
        q_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #94a3b8; letter-spacing: 0.5px;")
        quick_layout.addWidget(q_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

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

        quick_layout.addLayout(btn_row)

        # Ad-hoc write-in query box
        self.adhoc_input = QLineEdit()
        self.adhoc_input.setPlaceholderText("Ask the copilot anything about this call... (Press Enter)")
        self.adhoc_input.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 4px;
                padding: 4px 8px; color: #f8fafc; font-size: 12px;
            }
            QLineEdit:focus { border: 1px solid #38bdf8; }
        """)
        self.adhoc_input.returnPressed.connect(self._submit_adhoc_query)
        quick_layout.addWidget(self.adhoc_input)

        main_layout.addWidget(quick_frame)

        # --- Splitter between Questions and Scratchpad ---
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background-color: #334155; height: 3px; }")

        # --- Section 1: Suggested Questions Card ---
        q_frame = QFrame()
        q_frame.setObjectName("card")
        q_card_layout = QVBoxLayout(q_frame)
        q_card_layout.setContentsMargins(10, 10, 10, 10)
        q_card_layout.setSpacing(6)

        q_head = QLabel("💡 SUGGESTED QUESTIONS & FOLLOW-UPS")
        q_head.setStyleSheet("font-size: 11px; font-weight: bold; color: #38bdf8; letter-spacing: 0.5px;")
        q_card_layout.addWidget(q_head)

        self.questions_list = QListWidget()
        self.questions_list.setStyleSheet("""
            QListWidget {
                background: transparent; border: none;
            }
            QListWidget::item {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;
                margin-bottom: 6px;
            }
        """)
        q_card_layout.addWidget(self.questions_list)
        splitter.addWidget(q_frame)

        # --- Section 2: Interactive Live Scratchpad ---
        notes_frame = QFrame()
        notes_frame.setObjectName("card")
        notes_layout = QVBoxLayout(notes_frame)
        notes_layout.setContentsMargins(10, 10, 10, 10)
        notes_layout.setSpacing(6)

        notes_head = QHBoxLayout()
        notes_title = QLabel("📝 LIVE SCRATCHPAD (Checklist & Notes)")
        notes_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #34d399; letter-spacing: 0.5px;")
        notes_head.addWidget(notes_title)
        notes_head.addStretch()

        notes_layout.addLayout(notes_head)

        # Notes list with checkboxes
        self.notes_list = QListWidget()
        self.notes_list.setStyleSheet("""
            QListWidget {
                background: transparent; border: none;
            }
            QListWidget::item {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;
                padding: 4px 6px; margin-bottom: 4px; color: #cbd5e1; font-size: 12px;
            }
            QListWidget::item:hover { background-color: #1e293b; }
        """)
        self.notes_list.itemChanged.connect(self._on_note_item_changed)
        notes_layout.addWidget(self.notes_list)

        # Add custom note input
        add_note_box = QHBoxLayout()
        self.add_note_input = QLineEdit()
        self.add_note_input.setPlaceholderText("+ Add your own note or context...")
        self.add_note_input.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 4px;
                padding: 4px 8px; color: #f8fafc; font-size: 12px;
            }
            QLineEdit:focus { border: 1px solid #10b981; }
        """)
        self.add_note_input.returnPressed.connect(self._add_custom_note)
        add_note_box.addWidget(self.add_note_input)

        add_btn = QPushButton("Add")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: white; border: none; border-radius: 4px;
                padding: 4px 10px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        add_btn.clicked.connect(self._add_custom_note)
        add_note_box.addWidget(add_btn)
        notes_layout.addLayout(add_note_box)

        splitter.addWidget(notes_frame)
        main_layout.addWidget(splitter, 1)

        # --- Section 3: Live Transcript Ticker (Collapsible) ---
        self.ticker_toggle_btn = QPushButton("▼ Live Transcript Feed")
        self.ticker_toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; color: #94a3b8; font-size: 11px;
                text-align: left; padding: 2px 0px; font-weight: 500;
            }
            QPushButton:hover { color: #f8fafc; }
        """)
        self.ticker_toggle_btn.clicked.connect(self._toggle_ticker)
        main_layout.addWidget(self.ticker_toggle_btn)

        self.ticker_box = QTextEdit()
        self.ticker_box.setReadOnly(True)
        self.ticker_box.setFixedHeight(90)
        self.ticker_box.setStyleSheet("""
            QTextEdit {
                background-color: #020617; border: 1px solid #1e293b; border-radius: 6px;
                color: #94a3b8; font-size: 11px; font-family: monospace;
            }
        """)
        main_layout.addWidget(self.ticker_box)

    def _quick_btn_style(self, bg_color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg_color}; color: #ffffff; border: none; border-radius: 4px;
                padding: 5px 8px; font-size: 11px; font-weight: 600;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """

    def _toggle_pin(self):
        pinned = self.pin_btn.isChecked()
        if pinned:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _toggle_ticker(self):
        visible = self.ticker_box.isVisible()
        self.ticker_box.setVisible(not visible)
        self.ticker_toggle_btn.setText("▼ Live Transcript Feed" if not visible else "▲ Hide Transcript Feed")

    def _submit_adhoc_query(self):
        query = self.adhoc_input.text().strip()
        if query:
            self.adhoc_input.clear()
            self.agent.run_quick_prompt(query)

    def _add_custom_note(self):
        text = self.add_note_input.text().strip()
        if text:
            self.add_note_input.clear()
            self.memory.add_user_note(text)
            self._render_notes()

    def _on_copy_question(self, question_text: str):
        clipboard = QApplication.clipboard()
        clipboard.setText(question_text)
        self.status_title.setText("COPIED TO CLIPBOARD!")
        QTimer.singleShot(1500, lambda: self.status_title.setText("LIVE COPILOT"))

    def _on_mark_asked(self, question_text: str):
        self.memory.mark_question_asked(question_text)
        self._render_questions()
        self._render_notes()

    def _on_dismiss_question(self, question_text: str):
        self.memory.mark_question_dismissed(question_text)
        self._render_questions()

    def _on_note_item_changed(self, item: QListWidgetItem):
        # User checked/unchecked a note item
        pass

    def _on_transcription_gui(self, channel: str, text: str, timestamp: float, turn_id: int):
        """Append to memory and update ticker."""
        turn = self.memory.add_transcript(channel, text, timestamp, turn_id)
        
        # Format ticker entry
        color = "#38bdf8" if channel == "you" else ("#a78bfa" if channel == "participants" else "#34d399")
        entry_html = f"<div style='margin-bottom: 3px;'><span style='color: {color}; font-weight: bold;'>{turn.speaker_label} ({turn.formatted_time}):</span> <span style='color: #e2e8f0;'>{turn.text}</span></div>"
        
        self.ticker_box.append(entry_html)
        # Scroll to bottom
        scrollbar = self.ticker_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_agent_results_gui(self, results: dict):
        """Refreshes suggested questions and notes cards."""
        self._render_questions()
        self._render_notes()

    def _on_quick_action_gui(self, title: str, text: str):
        """Displays quick-action response in notes or popout."""
        self.memory.add_user_note(f"⚡ [{title}] {text}")
        self._render_notes()

    def _render_questions(self):
        self.questions_list.clear()
        pending_questions = [q for q in self.memory.suggested_questions if q.status == "pending"]
        
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

    def update_status(self, recording: bool, paused: bool, meeting_mode: str, asr_name: str):
        """Updates header badges and status dot."""
        if recording:
            if paused:
                self.status_dot.setText("🟡")
            else:
                self.status_dot.setText("🔴")
        else:
            self.status_dot.setText("🟢")

        self.mode_badge.setText(meeting_mode.capitalize())
        self.asr_badge.setText(asr_name)
