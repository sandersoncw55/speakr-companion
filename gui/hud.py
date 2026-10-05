import os
import time
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize, QRect
from PySide6.QtGui import QIcon, QFont, QColor, QClipboard, QAction, QKeyEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit, QPlainTextEdit,
    QFrame, QSplitter, QCheckBox, QSlider, QApplication, QComboBox,
    QAbstractItemView, QGroupBox, QTextBrowser, QStackedWidget
)
from core.config import get_app_icon, Settings
from core.copilot.memory import CopilotMemory, SuggestedQuestion, FollowUpItem

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
        self.setFixedHeight(44)
        self.setPlaceholderText("+ Add custom note or context... (Enter to submit, Shift+Enter for newline)")
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
                border: 1px solid #38bdf8;
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
        self.label.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 600; line-height: 1.3;")
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
                border-radius: 4px; padding: 2px 7px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.copy_btn.clicked.connect(lambda: self.on_copy_cb(self.question.question))
        btn_layout.addWidget(self.copy_btn)

        # Mark Asked button
        self.asked_btn = QPushButton("✔ Asked")
        self.asked_btn.setToolTip("Mark as asked during meeting")
        self.asked_btn.setStyleSheet("""
            QPushButton {
                background-color: #065f46; color: #a7f3d0; border: 1px solid #059669;
                border-radius: 4px; padding: 2px 7px; font-size: 11px; font-weight: bold;
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
                border-radius: 4px; padding: 2px 6px; font-size: 11px;
            }
            QPushButton:hover { background-color: #1e293b; color: #ef4444; border-color: #7f1d1d; }
        """)
        self.dismiss_btn.clicked.connect(lambda: self.on_dismiss_cb(self.question.question))
        btn_layout.addWidget(self.dismiss_btn)

        layout.addLayout(btn_layout)


class FollowUpItemWidget(QWidget):
    """Widget rendering an individual action item / follow-up with Copy, Done, and Dismiss actions."""

    def __init__(self, item: FollowUpItem, on_copy_cb, on_done_cb, on_dismiss_cb):
        super().__init__()
        self.item = item
        self.on_copy_cb = on_copy_cb
        self.on_done_cb = on_done_cb
        self.on_dismiss_cb = on_dismiss_cb

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Task text
        self.label = QLabel(item.task)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 600; line-height: 1.3;")
        layout.addWidget(self.label)

        # Owner tag
        owner_str = item.owner if item.owner and item.owner != "Unassigned" else "Unassigned"
        self.owner_label = QLabel(f"👤 Owner: {owner_str}")
        self.owner_label.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.owner_label)

        # Actions Layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        # Copy button
        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setToolTip("Copy action item to clipboard")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155; color: #f8fafc; border: 1px solid #475569;
                border-radius: 4px; padding: 2px 7px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.copy_btn.clicked.connect(lambda: self.on_copy_cb(self.item.task))
        btn_layout.addWidget(self.copy_btn)

        # Done button
        self.done_btn = QPushButton("✔ Done")
        self.done_btn.setToolTip("Mark as completed")
        self.done_btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7; color: #e0f2fe; border: 1px solid #0369a1;
                border-radius: 4px; padding: 2px 7px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #0369a1; }
        """)
        self.done_btn.clicked.connect(lambda: self.on_done_cb(self.item.task))
        btn_layout.addWidget(self.done_btn)

        btn_layout.addStretch()

        # Dismiss button
        self.dismiss_btn = QPushButton("✕ Dismiss")
        self.dismiss_btn.setToolTip("Dismiss this item")
        self.dismiss_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #94a3b8; border: 1px solid #334155;
                border-radius: 4px; padding: 2px 6px; font-size: 11px;
            }
            QPushButton:hover { background-color: #1e293b; color: #ef4444; border-color: #7f1d1d; }
        """)
        self.dismiss_btn.clicked.connect(lambda: self.on_dismiss_cb(self.item.task))
        btn_layout.addWidget(self.dismiss_btn)

        layout.addLayout(btn_layout)


class CopilotDashboardWidget(QWidget):
    """Embedded, comprehensive 3-Tier Resizable Live Meeting Intelligence & Copilot widget."""

    # Public Qt signals for synchronization with main window
    meeting_mode_changed = Signal(str)
    asr_provider_changed = Signal(str)
    enable_copilot_requested = Signal()

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

        # --- Stacked Widget: Active Intelligence vs Disabled Banner ---
        self.stack = QStackedWidget(self)
        root_layout.addWidget(self.stack)

        # View 0: Active Copilot Interface
        self.active_page = QWidget()
        self._setup_active_page()
        self.stack.addWidget(self.active_page)

        # View 1: Disabled Overlay Page
        self.disabled_page = QWidget()
        self._setup_disabled_page()
        self.stack.addWidget(self.disabled_page)

        # Default to active page
        self.stack.setCurrentIndex(0)

    def _setup_disabled_page(self):
        layout = QVBoxLayout(self.disabled_page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 30px;
                max-width: 480px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel("🤖")
        icon_lbl.setStyleSheet("font-size: 36px;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(icon_lbl)

        title_lbl = QLabel("Live Copilot is Turned Off")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        title_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Live speech-to-text and AI synthesis are suspended to save system resources.\n"
            "Turn on Copilot to receive live in-the-moment dialogue questions, rolling meeting summaries, and action item extraction."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        desc_lbl.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(desc_lbl)

        enable_btn = QPushButton("▶ Turn On Copilot")
        enable_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 24px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        enable_btn.clicked.connect(self._request_enable_copilot)
        card_layout.addWidget(enable_btn, alignment=Qt.AlignCenter)

        layout.addWidget(card)

    def _setup_active_page(self):
        page_layout = QVBoxLayout(self.active_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)

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

        page_layout.addWidget(header_frame)

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

        self.btn_owners = QPushButton("🎯 Action Items")
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

        page_layout.addWidget(quick_frame)

        # --- 3-Tier Master Vertical Resizable Splitter ---
        self.main_v_splitter = QSplitter(Qt.Vertical)
        self.main_v_splitter.setStyleSheet("QSplitter::handle { background-color: #334155; height: 4px; border-radius: 2px; }")

        # =========================================================================
        # TIER 1 (TOP): Side-by-Side Horizontal Splitter (Questions & Follow-ups)
        # =========================================================================
        self.top_h_splitter = QSplitter(Qt.Horizontal)
        self.top_h_splitter.setStyleSheet("QSplitter::handle { background-color: #334155; width: 4px; border-radius: 2px; }")

        # Pane 1 (Left 50%): Suggested Questions
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
        q_head = QLabel("💡 QUESTIONS TO ASK (IN-THE-MOMENT)")
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
        self.top_h_splitter.addWidget(q_frame)

        # Pane 2 (Right 50%): Follow-up Suggestions & Action Items
        f_frame = QFrame()
        f_frame.setObjectName("card")
        f_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        f_card_layout = QVBoxLayout(f_frame)
        f_card_layout.setContentsMargins(8, 6, 8, 6)
        f_card_layout.setSpacing(4)

        f_head_layout = QHBoxLayout()
        f_head = QLabel("🎯 FOLLOW-UP SUGGESTIONS & ACTION ITEMS")
        f_head.setStyleSheet("font-size: 11px; font-weight: bold; color: #a78bfa; letter-spacing: 0.5px;")
        f_head_layout.addWidget(f_head)

        self.f_count_badge = QLabel("0")
        self.f_count_badge.setStyleSheet("""
            QLabel {
                background-color: #6b21a8;
                color: #f3e8ff;
                font-size: 10px;
                font-weight: bold;
                border-radius: 7px;
                padding: 1px 6px;
            }
        """)
        self.f_count_badge.setVisible(False)
        f_head_layout.addWidget(self.f_count_badge)
        f_head_layout.addStretch()

        self.f_clear_btn = QPushButton("Clear All")
        self.f_clear_btn.setToolTip("Clear all pending follow-up suggestions")
        self.f_clear_btn.setStyleSheet("""
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
        self.f_clear_btn.clicked.connect(self._clear_follow_up_suggestions)
        self.f_clear_btn.setVisible(False)
        f_head_layout.addWidget(self.f_clear_btn)
        f_card_layout.addLayout(f_head_layout)

        self.follow_ups_list = QListWidget()
        self.follow_ups_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.follow_ups_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.follow_ups_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.follow_ups_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;
                margin-bottom: 5px;
            }
        """)
        f_card_layout.addWidget(self.follow_ups_list)
        self.top_h_splitter.addWidget(f_frame)

        # Equal 50/50 proportion on top row
        self.top_h_splitter.setSizes([500, 500])
        self.main_v_splitter.addWidget(self.top_h_splitter)

        # =========================================================================
        # TIER 2 (MIDDLE): Full-Width Rolling Meeting Summary & Custom Scratchpad
        # =========================================================================
        summary_frame = QFrame()
        summary_frame.setObjectName("card")
        summary_frame.setStyleSheet("""
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(8, 6, 8, 6)
        summary_layout.setSpacing(4)

        sum_head = QHBoxLayout()
        sum_title = QLabel("📝 MEETING ROLLING SUMMARY & SCRATCHPAD")
        sum_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #34d399; letter-spacing: 0.5px;")
        sum_head.addWidget(sum_title)
        sum_head.addStretch()

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
        sum_head.addWidget(self.open_notes_folder_btn)
        summary_layout.addLayout(sum_head)

        # Content horizontal split: Executive Synthesis Browser on left, Custom User Notes on right
        middle_sub_splitter = QSplitter(Qt.Horizontal)
        middle_sub_splitter.setStyleSheet("QSplitter::handle { background-color: #334155; width: 4px; border-radius: 2px; }")

        # 1. Rolling Executive Summary Browser
        self.summary_browser = QTextBrowser()
        self.summary_browser.setOpenExternalLinks(True)
        self.summary_browser.setStyleSheet("""
            QTextBrowser {
                background-color: #020617;
                border: 1px solid #0f172a;
                border-radius: 4px;
                color: #f8fafc;
                font-size: 12px;
                line-height: 1.4;
                padding: 6px;
            }
        """)
        self._update_summary_browser_text()
        middle_sub_splitter.addWidget(self.summary_browser)

        # 2. Custom User Notes container
        user_notes_container = QWidget()
        un_layout = QVBoxLayout(user_notes_container)
        un_layout.setContentsMargins(0, 0, 0, 0)
        un_layout.setSpacing(4)

        self.notes_list = QListWidget()
        self.notes_list.setStyleSheet("""
            QListWidget { background-color: #020617; border: 1px solid #0f172a; border-radius: 4px; }
            QListWidget::item {
                background-color: #0f172a; border: 1px solid #334155; border-radius: 4px;
                padding: 3px 6px; margin: 2px; color: #cbd5e1; font-size: 11px;
            }
        """)
        un_layout.addWidget(self.notes_list, 1)

        # Add custom note row
        add_note_box = QHBoxLayout()
        add_note_box.setSpacing(6)
        self.add_note_input = TwoLineNoteEdit()
        self.add_note_input.enter_pressed.connect(self._add_custom_note)
        add_note_box.addWidget(self.add_note_input, 1)

        add_btn = QPushButton("Add Note")
        add_btn.setFixedHeight(44)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; color: white; border: none; border-radius: 4px;
                padding: 4px 12px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #047857; }
        """)
        add_btn.clicked.connect(self._add_custom_note)
        add_note_box.addWidget(add_btn)
        un_layout.addLayout(add_note_box)

        middle_sub_splitter.addWidget(user_notes_container)
        middle_sub_splitter.setSizes([550, 450])
        summary_layout.addWidget(middle_sub_splitter)

        self.main_v_splitter.addWidget(summary_frame)

        # =========================================================================
        # TIER 3 (BOTTOM): Full-Width Live Transcript Stream on the very bottom
        # =========================================================================
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
        tr_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #38bdf8; letter-spacing: 0.5px;")
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
        self.main_v_splitter.addWidget(transcript_frame)

        # Initial vertical sizes: Tier 1 (220px), Tier 2 (200px), Tier 3 (160px)
        self.main_v_splitter.setSizes([220, 200, 160])
        page_layout.addWidget(self.main_v_splitter, 1)

        # Backwards compatibility reference
        self.splitter = self.top_h_splitter

    def _quick_btn_style(self, bg_color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg_color}; color: #ffffff; border: none; border-radius: 4px;
                padding: 4px 8px; font-size: 11px; font-weight: 600;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """

    def set_copilot_enabled(self, enabled: bool):
        """Switches between active intelligence view and disabled placeholder banner."""
        self.stack.setCurrentIndex(0 if enabled else 1)

    def _request_enable_copilot(self):
        self.enable_copilot_requested.emit()

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

    def _on_copy_text(self, text_to_copy: str):
        clipboard = QApplication.clipboard()
        clipboard.setText(text_to_copy)
        self.status_title.setText("COPIED TO CLIPBOARD!")
        QTimer.singleShot(1500, lambda: self.status_title.setText("LIVE MEETING COPILOT"))

    def _on_mark_asked(self, question_text: str):
        self.memory.mark_question_asked(question_text)
        self._render_questions()
        self._render_notes()

    def _on_dismiss_question(self, question_text: str):
        self.memory.mark_question_dismissed(question_text)
        self._render_questions()

    def _on_mark_followup_done(self, task_text: str):
        self.memory.mark_followup_done(task_text)
        self._render_follow_ups()
        self._update_summary_browser_text()

    def _on_dismiss_followup(self, task_text: str):
        self.memory.mark_followup_dismissed(task_text)
        self._render_follow_ups()

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
        """Refreshes suggested questions, follow-ups, and summary."""
        self._render_questions()
        self._render_follow_ups()
        self._render_notes()
        self._update_summary_browser_text()

    def _on_quick_action_gui(self, title: str, text: str):
        """Displays quick-action response in notes."""
        self.memory.add_user_note(f"⚡ [{title}] {text}")
        self._render_notes()

    def _clear_suggested_questions(self):
        """Clears pending questions from memory and updates display."""
        self.memory.clear_suggested_questions(status="pending")
        self._render_questions()

    def _clear_follow_up_suggestions(self):
        """Clears pending follow-up suggestions from memory."""
        self.memory.clear_follow_up_suggestions(status="pending")
        self._render_follow_ups()

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
                on_copy_cb=self._on_copy_text,
                on_asked_cb=self._on_mark_asked,
                on_dismiss_cb=self._on_dismiss_question
            )
            item.setSizeHint(widget.sizeHint())
            self.questions_list.addItem(item)
            self.questions_list.setItemWidget(item, widget)

    def _render_follow_ups(self):
        self.follow_ups_list.clear()
        pending_items = [f for f in self.memory.follow_up_suggestions if f.status == "pending"]
        
        count = len(pending_items)
        self.f_count_badge.setText(f"{count} pending" if count > 0 else "0")
        self.f_count_badge.setVisible(count > 0)
        self.f_clear_btn.setVisible(count > 0)

        for it in pending_items:
            item = QListWidgetItem(self.follow_ups_list)
            widget = FollowUpItemWidget(
                it,
                on_copy_cb=self._on_copy_text,
                on_done_cb=self._on_mark_followup_done,
                on_dismiss_cb=self._on_dismiss_followup
            )
            item.setSizeHint(widget.sizeHint())
            self.follow_ups_list.addItem(item)
            self.follow_ups_list.setItemWidget(item, widget)

    def _render_notes(self):
        self.notes_list.clear()
        # Custom user notes (no checkboxes on regular notes)
        for note in self.memory.user_notes:
            item = QListWidgetItem(f"• {note}")
            self.notes_list.addItem(item)

    def _update_summary_browser_text(self):
        topic = self.memory.rolling_summary.get("topic", "")
        exec_sum = self.memory.rolling_summary.get("executive_summary", "")
        decisions = self.memory.rolling_summary.get("key_decisions", [])

        html_parts = []
        if topic:
            html_parts.append(f"<div style='font-size: 13px; font-weight: bold; color: #38bdf8; margin-bottom: 6px;'>📌 Agenda: {topic}</div>")
        
        html_parts.append("<div style='font-size: 12px; font-weight: bold; color: #94a3b8; margin-bottom: 3px;'>EXECUTIVE SUMMARY:</div>")
        if exec_sum:
            html_parts.append(f"<div style='color: #f8fafc; font-size: 12px; line-height: 1.4; margin-bottom: 8px;'>{exec_sum}</div>")
        else:
            html_parts.append("<div style='color: #64748b; font-style: italic; font-size: 11px; margin-bottom: 8px;'>Summary will synthesize as conversation progresses...</div>")

        if decisions:
            html_parts.append("<div style='font-size: 12px; font-weight: bold; color: #34d399; margin-bottom: 3px;'>KEY DECISIONS & CONSENSUS:</div>")
            html_parts.append("<ul style='margin-top: 2px; margin-bottom: 6px; padding-left: 18px; color: #cbd5e1;'>")
            for d in decisions:
                html_parts.append(f"<li style='margin-bottom: 2px;'>{d}</li>")
            html_parts.append("</ul>")

        self.summary_browser.setHtml("".join(html_parts))

    def _on_manual_reset_clicked(self):
        """Manually resets session memory and clears displays."""
        self.memory.clear()
        self.clear()

    def clear(self):
        """Clears all UI elements in the widget for a clean session."""
        self.ticker_box.clear()
        self.questions_list.clear()
        self.follow_ups_list.clear()
        self.notes_list.clear()
        self.q_count_badge.setText("0")
        self.q_count_badge.setVisible(False)
        self.q_clear_btn.setVisible(False)
        self.f_count_badge.setText("0")
        self.f_count_badge.setVisible(False)
        self.f_clear_btn.setVisible(False)
        self.add_note_input.clear()
        self.adhoc_input.clear()
        self._update_summary_browser_text()

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

        self.mode_combo.blockSignals(True)
        mode_idx = self.mode_combo.findData(meeting_mode)
        if mode_idx >= 0:
            self.mode_combo.setCurrentIndex(mode_idx)
        self.mode_combo.blockSignals(False)

        self.asr_combo.blockSignals(True)
        asr_idx = self.asr_combo.findData(asr_name_or_key)
        if asr_idx < 0:
            asr_idx = self.asr_combo.findText(asr_name_or_key, Qt.MatchContains)
        if asr_idx >= 0:
            self.asr_combo.setCurrentIndex(asr_idx)
        self.asr_combo.blockSignals(False)


# Alias for backward compatibility
FloatingCopilotHUD = CopilotDashboardWidget
