import os
import time
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize
from PySide6.QtGui import QIcon, QFont, QColor, QClipboard, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit, QPlainTextEdit,
    QFrame, QSplitter, QCheckBox, QComboBox, QAbstractItemView,
    QTextBrowser, QStackedWidget, QTabWidget, QApplication
)
from core.config import Settings
from core.copilot.memory import CopilotMemory, SuggestedQuestion, FollowUpItem
from gui.theme import get_theme_palette
from gui.hud import (
    CopilotSignals, TwoLineNoteEdit, QuestionItemWidget,
    FollowUpItemWidget, RollingSummaryPopoutDialog
)


class RecordView(QWidget):
    """Modern 2-Column Workstation for Live Recording, Note-Taking, and Copilot Intelligence.
    
    Layout:
      - Sub-header: Meeting Title, Tag Selector (auto-loaded), Audio Mode, ASR Engine, Reasoning Health, Session Reset
      - Left Column: Open Notes Markdown Editor with rich text formatting bar and auto-sync into AI memory
      - Right Column (Tabbed Section):
          * Tab 0: Chat (Rolling Meeting Summary topics, executive summary, decisions + Pop-out)
          * Tab 1: Live Q&A (Suggested Questions & Action Items with interactive actions)
          * Tab 2: Summary (On-demand Catch Up, Action Items, Risks, Jargon buttons & result browser)
          * Tab 3: Transcript (Live dual-channel speaker stream with auto-scroll)
    """

    meeting_mode_changed = Signal(str)
    asr_provider_changed = Signal(str)
    meeting_title_changed = Signal(str)
    tag_changed = Signal(str)
    enable_copilot_requested = Signal()
    open_prompts_settings_requested = Signal()
    reset_session_requested = Signal()

    def __init__(
        self,
        memory: CopilotMemory,
        copilot_agent,
        theme: str = "dark",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.memory = memory
        self.agent = copilot_agent
        self.theme = theme
        self.signals = CopilotSignals()

        # Connect signals
        self.signals.transcription_received.connect(self._on_transcription_gui)
        self.signals.agent_results_received.connect(self._on_agent_results_gui)
        self.signals.quick_action_received.connect(self._on_quick_action_gui)

        self.popout_dialog: Optional[RollingSummaryPopoutDialog] = None

        # Debounce timer for Open Notes auto-sync
        self._notes_debounce_timer = QTimer(self)
        self._notes_debounce_timer.setSingleShot(True)
        self._notes_debounce_timer.setInterval(400)
        self._notes_debounce_timer.timeout.connect(self._sync_notes_to_memory)

        self._setup_ui()
        self.set_theme(theme)

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # Stacked view: Active intelligence vs Disabled banner
        self.stack = QStackedWidget(self)
        root_layout.addWidget(self.stack)

        self.active_page = QWidget()
        self._setup_active_page()
        self.stack.addWidget(self.active_page)

        self.disabled_page = QWidget()
        self._setup_disabled_page()
        self.stack.addWidget(self.disabled_page)

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
        enable_btn.clicked.connect(self.enable_copilot_requested.emit)
        card_layout.addWidget(enable_btn, alignment=Qt.AlignCenter)

        layout.addWidget(card)

    def _setup_active_page(self):
        page_layout = QVBoxLayout(self.active_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)

        # =========================================================================
        # 1. TOP SUB-HEADER: Meeting Title, Tag, Audio Mode, ASR, Reasoning Health
        # =========================================================================
        header_frame = QFrame()
        header_frame.setObjectName("subHeaderCard")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(8)

        # Status Dot indicator
        self.status_dot = QLabel("🟢")
        self.status_dot.setToolTip("Status: Live Copilot Ready")
        header_layout.addWidget(self.status_dot)

        # Meeting Title input
        title_box = QHBoxLayout()
        title_box.setSpacing(4)
        title_icon = QLabel("🏷️")
        title_icon.setStyleSheet("font-size: 13px;")
        title_box.addWidget(title_icon)

        default_date_str = time.strftime("%b %d, %Y")
        self.meeting_title_edit = QLineEdit()
        self.meeting_title_edit.setPlaceholderText(f"Meeting — {default_date_str}")
        self.meeting_title_edit.setText(f"Meeting — {default_date_str}")
        self.meeting_title_edit.setMinimumWidth(180)
        self.meeting_title_edit.textChanged.connect(self.meeting_title_changed.emit)
        self.meeting_name_input = self.meeting_title_edit
        title_box.addWidget(self.meeting_title_edit)
        header_layout.addLayout(title_box, 2)

        # Tag Dropdown selector (auto-loaded from Speakr server)
        self.tag_combo = QComboBox()
        self.tag_combo.addItem("🏷️ No Tag", None)
        self.tag_combo.setToolTip("Assign Speakr meeting tag (auto-loads on startup)")
        self.tag_combo.setMinimumWidth(120)
        self.tag_combo.currentIndexChanged.connect(self._on_tag_combo_changed)
        header_layout.addWidget(self.tag_combo, 1)

        # Meeting Mode selector
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("🌐 Virtual Call", "virtual")
        self.mode_combo.addItem("🎙️ In-Person", "in_person")
        self.mode_combo.addItem("🔀 Hybrid Room", "hybrid")
        self.mode_combo.setToolTip("Select Meeting Audio Mode")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo_changed)
        header_layout.addWidget(self.mode_combo)

        # ASR Engine selector
        self.asr_combo = QComboBox()
        self.asr_combo.addItem("Local CPU Whisper", "local")
        self.asr_combo.addItem("Mac LAN Whisper-MLX", "mac_lan")
        self.asr_combo.addItem("Groq Cloud Whisper", "groq")
        self.asr_combo.addItem("OpenAI Cloud Whisper", "openai")
        self.asr_combo.setToolTip("Speech-to-Text (ASR) Engine")
        self.asr_combo.currentIndexChanged.connect(self._on_asr_combo_changed)
        header_layout.addWidget(self.asr_combo)

        # Reasoning Engine Badge & Healthcheck
        self.engine_badge = QLabel("🧠 Reasoning Engine: Offline")
        self.engine_badge.setToolTip("Active reasoning engine for synthesis & live probing")
        header_layout.addWidget(self.engine_badge)

        self.engine_status_lbl = QLabel("⚪ Offline")
        self.engine_status_lbl.setToolTip("Engine health status")
        header_layout.addWidget(self.engine_status_lbl)

        self.healthcheck_btn = QPushButton("⚡ Check")
        self.healthcheck_btn.setToolTip("Test connection and latency to configured reasoning engine")
        self.healthcheck_btn.clicked.connect(self._run_engine_healthcheck)
        header_layout.addWidget(self.healthcheck_btn)

        # Copy Markdown Notes button
        self.copy_md_btn = QPushButton("📋 Copy Notes")
        self.copy_md_btn.setToolTip("Copy the full scratchpad, notes, and summary to clipboard")
        self.copy_md_btn.clicked.connect(self._copy_markdown_notes)
        header_layout.addWidget(self.copy_md_btn)

        # Reset Session button
        self.reset_btn = QPushButton("🔄 Reset")
        self.reset_btn.setToolTip("Reset Copilot Session (Clear transcript, questions, & scratchpad)")
        self.reset_btn.clicked.connect(self._on_manual_reset_clicked)
        header_layout.addWidget(self.reset_btn)

        page_layout.addWidget(header_frame)

        # =========================================================================
        # 2. MASTER 2-COLUMN HORIZONTAL SPLITTER
        # =========================================================================
        self.col_splitter = QSplitter(Qt.Horizontal)
        self.col_splitter.setChildrenCollapsible(False)

        # -------------------------------------------------------------------------
        # LEFT COLUMN: Open Notes Markdown Editor
        # -------------------------------------------------------------------------
        left_col = QFrame()
        left_col.setObjectName("leftColFrame")
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        # Left Column Header + Formatting Toolbar
        notes_bar = QHBoxLayout()
        notes_bar.setSpacing(4)

        notes_title = QLabel("📝 OPEN NOTES")
        notes_title.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        notes_bar.addWidget(notes_title)

        notes_bar.addStretch()

        # Formatting quick buttons
        self.btn_bold = QPushButton("B")
        self.btn_bold.setToolTip("Bold (**selection**)")
        self.btn_bold.setFixedSize(24, 24)
        self.btn_bold.clicked.connect(lambda: self._wrap_selection("**", "**"))
        notes_bar.addWidget(self.btn_bold)

        self.btn_italic = QPushButton("I")
        self.btn_italic.setToolTip("Italic (*selection*)")
        self.btn_italic.setFixedSize(24, 24)
        self.btn_italic.clicked.connect(lambda: self._wrap_selection("*", "*"))
        notes_bar.addWidget(self.btn_italic)

        self.btn_bullet = QPushButton("•")
        self.btn_bullet.setToolTip("Bullet list (- )")
        self.btn_bullet.setFixedSize(24, 24)
        self.btn_bullet.clicked.connect(self._insert_bullet)
        notes_bar.addWidget(self.btn_bullet)

        self.btn_heading = QPushButton("H")
        self.btn_heading.setToolTip("Heading (### )")
        self.btn_heading.setFixedSize(24, 24)
        self.btn_heading.clicked.connect(lambda: self._wrap_selection("### ", ""))
        notes_bar.addWidget(self.btn_heading)

        # AI Enhance Notes button
        self.btn_enhance_notes = QPushButton("✨ Enhance Notes")
        self.btn_enhance_notes.setToolTip("Clean up, structure, and polish rough notes using AI reasoning")
        self.btn_enhance_notes.clicked.connect(self._enhance_notes_clicked)
        notes_bar.addWidget(self.btn_enhance_notes)

        # Clear Notes button
        self.btn_clear_notes = QPushButton("🗑️ Clear")
        self.btn_clear_notes.setToolTip("Clear open notes field")
        self.btn_clear_notes.clicked.connect(self._clear_notes)
        notes_bar.addWidget(self.btn_clear_notes)

        left_layout.addLayout(notes_bar)

        # Open Notes Editor
        self.notes_editor = QPlainTextEdit()
        self.notes_editor.setPlaceholderText(
            "Type meeting notes, thoughts, or context here...\n"
            "• Markdown formatting is supported\n"
            "• Notes entered here are automatically indexed and fed into live AI summarization\n"
            "• Click ✨ Enhance Notes to organize and refine rough bullets"
        )
        self.notes_editor.textChanged.connect(self._on_notes_text_changed)
        left_layout.addWidget(self.notes_editor, 1)

        # Bottom info hint
        notes_footer = QLabel("⚡ Auto-synced with Live Copilot context & saved sidecars")
        notes_footer.setStyleSheet("font-size: 10px; font-style: italic;")
        left_layout.addWidget(notes_footer)

        self.col_splitter.addWidget(left_col)

        # -------------------------------------------------------------------------
        # RIGHT COLUMN: 4-Tab Workspace (Chat, Live Q&A, Summary, Transcript)
        # -------------------------------------------------------------------------
        right_col = QFrame()
        right_col.setObjectName("rightColFrame")
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.right_tabs = QTabWidget()
        self.right_tabs.setObjectName("rightTabs")

        # 1. Chat Tab (Rolling Meeting Summary)
        self.chat_tab = QWidget()
        self._setup_chat_tab()
        self.right_tabs.addTab(self.chat_tab, "💬 Chat (Summary)")

        # 2. Live Q&A Tab (Suggested Questions & Follow-ups)
        self.qa_tab = QWidget()
        self._setup_qa_tab()
        self.right_tabs.addTab(self.qa_tab, "💡 Live Q&A")

        # 3. Summary Tab (Quick Actions: Catch Up, Action Items, Risks, Jargon)
        self.summary_tab = QWidget()
        self._setup_summary_tab()
        self.right_tabs.addTab(self.summary_tab, "📊 Summary")

        # 4. Transcript Tab (Live dual-channel ticker)
        self.transcript_tab = QWidget()
        self._setup_transcript_tab()
        self.right_tabs.addTab(self.transcript_tab, "💬 Transcript")

        right_layout.addWidget(self.right_tabs)
        self.col_splitter.addWidget(right_col)

        # Proportions: 40% Left (Open Notes), 60% Right (Intelligence Tabs)
        self.col_splitter.setSizes([450, 650])
        page_layout.addWidget(self.col_splitter, 1)

        # Compatibility aliases for legacy tests and references
        self.main_v_splitter = self.col_splitter
        self.top_h_splitter = self.col_splitter
        self.splitter = self.col_splitter
        self.notes_list = QListWidget()  # Fallback widget
        self.notes_list.setVisible(False)
        self.add_note_input = TwoLineNoteEdit()
        self.add_note_input.setVisible(False)

    def _on_manual_refresh_summary_clicked(self):
        """Immediately triggers periodic analysis in the background on demand."""
        if hasattr(self, "agent") and self.agent:
            self.refresh_summary_btn.setEnabled(False)
            self.refresh_summary_btn.setText("⚡ Refreshing...")
            self.chat_status_lbl.setText("🟡 Analyzing latest dialogue...")
            p = get_theme_palette(self.theme)
            self.chat_status_lbl.setStyleSheet("font-size: 10px; font-weight: 500; color: #38bdf8;")
            self.agent.trigger_immediate_periodic_analysis()
            QTimer.singleShot(2500, lambda: [
                self.refresh_summary_btn.setEnabled(True),
                self.refresh_summary_btn.setText("⚡ Refresh Now"),
                self._update_summary_browser_text()
            ])

    def reset_title_and_tags(self):
        """Resets meeting title edit to default placeholder and tag selector to No Tag."""
        default_title = f"Meeting — {time.strftime('%b %d, %Y')}"
        if hasattr(self, "meeting_title_edit") and self.meeting_title_edit:
            self.meeting_title_edit.setText(default_title)
            self.meeting_title_edit.setPlaceholderText(default_title)
        if hasattr(self, "tag_combo") and self.tag_combo:
            self.tag_combo.setCurrentIndex(0)

    def _setup_chat_tab(self):
        """Sets up Tab 0: Rolling Meeting Summary cards + Pop-out option."""
        layout = QVBoxLayout(self.chat_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        self.chat_topic_lbl = QLabel("📌 LIVE ROLLING SUMMARY")
        self.chat_topic_lbl.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        hdr.addWidget(self.chat_topic_lbl)

        self.chat_status_lbl = QLabel("")
        self.chat_status_lbl.setStyleSheet("font-size: 10px; font-weight: 500;")
        hdr.addWidget(self.chat_status_lbl)

        hdr.addStretch()

        self.refresh_summary_btn = QPushButton("⚡ Refresh Now")
        self.refresh_summary_btn.setToolTip("Immediately synthesize latest conversation turns into rolling summary")
        self.refresh_summary_btn.clicked.connect(self._on_manual_refresh_summary_clicked)
        hdr.addWidget(self.refresh_summary_btn)

        self.open_notes_folder_btn = QPushButton("📁 Notes Folder")
        self.open_notes_folder_btn.setToolTip("Open recordings and meeting notes directory")
        self.open_notes_folder_btn.clicked.connect(self._open_notes_folder)
        hdr.addWidget(self.open_notes_folder_btn)

        self.popout_summary_btn = QPushButton("⧉ Pop Out")
        self.popout_summary_btn.setToolTip("Pop out Meeting Rolling Summary into an independent floating window")
        self.popout_summary_btn.clicked.connect(self._toggle_summary_popout)
        hdr.addWidget(self.popout_summary_btn)
        layout.addLayout(hdr)

        self.summary_container = QWidget()
        sum_container_layout = QVBoxLayout(self.summary_container)
        sum_container_layout.setContentsMargins(0, 0, 0, 0)
        sum_container_layout.setSpacing(4)

        self.summary_browser = QTextBrowser()
        self.summary_browser.setOpenExternalLinks(True)
        self.summary_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sum_container_layout.addWidget(self.summary_browser)

        layout.addWidget(self.summary_container, 1)

        # Placeholder card shown when Rolling Summary is popped out
        self.summary_popped_placeholder = QFrame()
        self.summary_popped_placeholder.setObjectName("placeholderCard")
        ph_layout = QVBoxLayout(self.summary_popped_placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        ph_layout.setSpacing(8)

        self.placeholder_label = QLabel("📝 <b>Meeting Rolling Summary</b> is currently popped out in an external window.")
        ph_layout.addWidget(self.placeholder_label)

        self.placeholder_dock_btn = QPushButton("⬇️ Re-dock into Record Tab")
        self.placeholder_dock_btn.clicked.connect(self._dock_summary_in)
        ph_layout.addWidget(self.placeholder_dock_btn)
        self.summary_popped_placeholder.setVisible(False)
        layout.addWidget(self.summary_popped_placeholder)

        self._update_summary_browser_text()

    def _setup_qa_tab(self):
        """Sets up Tab 1: Live Q&A Suggested Questions and Action Items."""
        layout = QVBoxLayout(self.qa_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        v_split = QSplitter(Qt.Vertical)
        v_split.setStyleSheet("QSplitter::handle { height: 4px; border-radius: 2px; }")

        # Top half: Suggested Questions
        q_frame = QFrame()
        q_frame.setObjectName("card")
        q_layout = QVBoxLayout(q_frame)
        q_layout.setContentsMargins(6, 6, 6, 6)
        q_layout.setSpacing(4)

        q_head = QHBoxLayout()
        q_lbl = QLabel("💡 QUESTIONS TO ASK (IN-THE-MOMENT)")
        q_lbl.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        q_head.addWidget(q_lbl)

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
        q_head.addWidget(self.q_count_badge)
        q_head.addStretch()

        self.q_clear_btn = QPushButton("Clear All")
        self.q_clear_btn.setToolTip("Clear all pending suggested questions")
        self.q_clear_btn.clicked.connect(self._clear_suggested_questions)
        self.q_clear_btn.setVisible(False)
        q_head.addWidget(self.q_clear_btn)
        q_layout.addLayout(q_head)

        self.questions_list = QListWidget()
        self.questions_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.questions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.questions_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        q_layout.addWidget(self.questions_list)
        v_split.addWidget(q_frame)

        # Bottom half: Action Items / Follow-up suggestions
        f_frame = QFrame()
        f_frame.setObjectName("card")
        f_layout = QVBoxLayout(f_frame)
        f_layout.setContentsMargins(6, 6, 6, 6)
        f_layout.setSpacing(4)

        f_head = QHBoxLayout()
        f_lbl = QLabel("🎯 FOLLOW-UP SUGGESTIONS & ACTION ITEMS")
        f_lbl.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        f_head.addWidget(f_lbl)

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
        f_head.addWidget(self.f_count_badge)
        f_head.addStretch()

        self.f_clear_btn = QPushButton("Clear All")
        self.f_clear_btn.setToolTip("Clear all pending follow-up suggestions")
        self.f_clear_btn.clicked.connect(self._clear_follow_up_suggestions)
        self.f_clear_btn.setVisible(False)
        f_head.addWidget(self.f_clear_btn)
        f_layout.addLayout(f_head)

        self.follow_ups_list = QListWidget()
        self.follow_ups_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.follow_ups_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.follow_ups_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        f_layout.addWidget(self.follow_ups_list)
        v_split.addWidget(f_frame)

        v_split.setSizes([300, 300])
        layout.addWidget(v_split)

    def _setup_summary_tab(self):
        """Sets up Tab 2: Quick Action triggers (Catch Up, Action Items, Risks, Jargon) and results."""
        layout = QVBoxLayout(self.summary_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Quick Actions Bar
        quick_frame = QFrame()
        quick_frame.setObjectName("card")
        quick_layout = QVBoxLayout(quick_frame)
        quick_layout.setContentsMargins(6, 6, 6, 6)
        quick_layout.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        q_label = QLabel("⚡ QUICK ACTIONS:")
        q_label.setStyleSheet("font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
        btn_row.addWidget(q_label)

        self.btn_catchup = QPushButton("⏱️ Catch up")
        self.btn_catchup.clicked.connect(lambda: self._trigger_quick_action("catch_me_up"))
        btn_row.addWidget(self.btn_catchup)

        self.btn_owners = QPushButton("🎯 Action Items")
        self.btn_owners.clicked.connect(lambda: self._trigger_quick_action("clarify_ownership"))
        btn_row.addWidget(self.btn_owners)

        self.btn_risks = QPushButton("🚩 Risks")
        self.btn_risks.clicked.connect(lambda: self._trigger_quick_action("spot_risks"))
        btn_row.addWidget(self.btn_risks)

        self.btn_jargon = QPushButton("🔍 Jargon")
        self.btn_jargon.clicked.connect(lambda: self._trigger_quick_action("explain_jargon"))
        btn_row.addWidget(self.btn_jargon)

        self.btn_ask = QPushButton("💡 What to ask?")
        self.btn_ask.clicked.connect(lambda: self._trigger_quick_action("what_to_ask"))
        btn_row.addWidget(self.btn_ask)

        self.btn_catch_up = self.btn_catchup
        self.btn_action_items = self.btn_owners

        btn_row.addStretch()

        self.btn_cfg_prompts = QPushButton("⚙️ Prompts")
        self.btn_cfg_prompts.setToolTip("Customize Live Copilot Quick Action instructions in Preferences")
        self.btn_cfg_prompts.clicked.connect(self.open_prompts_settings_requested.emit)
        btn_row.addWidget(self.btn_cfg_prompts)
        quick_layout.addLayout(btn_row)

        # Ad-hoc write-in query box
        self.adhoc_input = QLineEdit()
        self.adhoc_input.setPlaceholderText("Ask the copilot anything about this meeting... (Press Enter to query)")
        self.adhoc_input.returnPressed.connect(self._submit_adhoc_query)
        quick_layout.addWidget(self.adhoc_input)

        layout.addWidget(quick_frame)

        # Quick Action Results Browser
        res_hdr = QHBoxLayout()
        res_lbl = QLabel("📋 ON-DEMAND SYNTHESIS RESULTS")
        res_lbl.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        res_hdr.addWidget(res_lbl)
        res_hdr.addStretch()

        clear_res_btn = QPushButton("Clear Results")
        clear_res_btn.clicked.connect(self._clear_quick_action_results)
        res_hdr.addWidget(clear_res_btn)
        layout.addLayout(res_hdr)

        self.quick_action_browser = QTextBrowser()
        self.quick_action_browser.setOpenExternalLinks(True)
        self.quick_action_browser.setPlaceholderText("Click any Quick Action button above to generate on-demand synthesis.")
        layout.addWidget(self.quick_action_browser, 1)

    def _setup_transcript_tab(self):
        """Sets up Tab 3: Dual-channel live transcript ticker stream."""
        layout = QVBoxLayout(self.transcript_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        tr_head = QHBoxLayout()
        tr_title = QLabel("💬 LIVE TRANSCRIPT STREAM")
        tr_title.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        tr_head.addWidget(tr_title)
        tr_head.addStretch()

        self.auto_scroll_chk = QCheckBox("Auto-scroll")
        self.auto_scroll_chk.setChecked(True)
        tr_head.addWidget(self.auto_scroll_chk)

        clear_tr_btn = QPushButton("Clear Feed")
        clear_tr_btn.clicked.connect(self._clear_transcript_feed)
        tr_head.addWidget(clear_tr_btn)
        layout.addLayout(tr_head)

        self.ticker_box = QTextEdit()
        self.ticker_box.setReadOnly(True)
        layout.addWidget(self.ticker_box)

    # =========================================================================
    # OPEN NOTES FORMATTING & SYNC
    # =========================================================================

    def _wrap_selection(self, prefix: str, suffix: str):
        cursor = self.notes_editor.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(f"{prefix}{selected_text}{suffix}")
        else:
            cursor.insertText(f"{prefix}{suffix}")
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, len(suffix))
            self.notes_editor.setTextCursor(cursor)

    def _insert_bullet(self):
        cursor = self.notes_editor.textCursor()
        cursor.insertText("- ")

    def _clear_notes(self):
        self.notes_editor.clear()
        self.memory.set_notes_markdown("")

    def _on_notes_text_changed(self):
        # Debounce writing to memory to minimize CPU churn
        self._notes_debounce_timer.start()

    def _sync_notes_to_memory(self):
        text = self.notes_editor.toPlainText().strip()
        self.memory.set_notes_markdown(text)

    def _enhance_notes_clicked(self):
        """Polishes rough user notes using the AI agent."""
        raw_notes = self.notes_editor.toPlainText().strip()
        if not raw_notes:
            return
        self.btn_enhance_notes.setEnabled(False)
        self.btn_enhance_notes.setText("✨ Refining...")
        
        prompt = (
            f"Please review, clean up, and structure the following rough user meeting notes into a concise, professional markdown format:\n\n{raw_notes}"
        )
        self.agent.run_quick_prompt(prompt)
        QTimer.singleShot(2500, lambda: [
            self.btn_enhance_notes.setEnabled(True),
            self.btn_enhance_notes.setText("✨ Enhance Notes")
        ])

    # =========================================================================
    # POPULATING TAGS & CONTROLS
    # =========================================================================

    def populate_tags(self, tags: List[Dict[str, Any]]):
        """Auto-loads tags from Speakr server into tag selector dropdown."""
        current_data = self.tag_combo.currentData()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("🏷️ No Tag", None)

        self._tag_id_to_name: Dict[int, str] = {}
        for tag in tags:
            tag_name = tag.get("name", "")
            raw_id = tag.get("id")
            try:
                tag_id = int(raw_id) if raw_id is not None else None
            except (ValueError, TypeError):
                tag_id = None

            if tag_id is not None:
                self._tag_id_to_name[tag_id] = tag_name
            icon_str = f"🏷️ {tag_name}"
            # Store numeric tag_id in item userData
            self.tag_combo.addItem(icon_str, tag_id)

        if current_data is not None:
            idx = self.tag_combo.findData(current_data)
            if idx >= 0:
                self.tag_combo.setCurrentIndex(idx)

        self.tag_combo.blockSignals(False)

    def _on_tag_combo_changed(self, index: int):
        tag_id = self.tag_combo.currentData()
        tag_name = ""
        if tag_id is not None:
            if hasattr(self, "_tag_id_to_name") and tag_id in self._tag_id_to_name:
                tag_name = self._tag_id_to_name[tag_id]
            else:
                tag_name = str(tag_id)
        self.tag_changed.emit(tag_name)

    def get_selected_tag(self) -> Optional[str]:
        """Returns the name of the selected tag for display/persona purposes."""
        tag_id = self.tag_combo.currentData()
        if tag_id is not None:
            if hasattr(self, "_tag_id_to_name") and tag_id in self._tag_id_to_name:
                return self._tag_id_to_name[tag_id]
            return str(tag_id)
        return None

    def get_selected_tag_id(self) -> Optional[int]:
        """Returns the integer tag ID of the selected tag, or None if no tag selected."""
        data = self.tag_combo.currentData()
        if data is not None:
            try:
                return int(data)
            except (ValueError, TypeError):
                return None
        return None


    def get_meeting_title(self) -> str:
        return self.meeting_title_edit.text().strip()

    def set_meeting_title(self, title: str):
        self.meeting_title_edit.setText(title)

    def set_meeting_mode(self, mode: str):
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)

    def set_asr_provider(self, provider: str):
        idx = self.asr_combo.findData(provider)
        if idx >= 0:
            self.asr_combo.blockSignals(True)
            self.asr_combo.setCurrentIndex(idx)
            self.asr_combo.blockSignals(False)

    def sync_settings_state(self, settings: Settings):
        """Synchronizes header selectors and engine badge with persistent settings."""
        if hasattr(settings, "meeting_mode"):
            self.set_meeting_mode(settings.meeting_mode)
        if hasattr(settings, "asr_provider"):
            self.set_asr_provider(settings.asr_provider)
        self._sync_engine_badge_from_settings(settings)

    def _sync_engine_badge_from_settings(self, settings: Settings):
        """Synchronizes engine badge text and tooltip directly from persistent settings."""
        if not hasattr(self, "engine_badge"):
            return
        prov = getattr(settings, "llm_provider", "offline")
        model = getattr(settings, "llm_model", "")
        provider_labels = {
            "offline": "Offline Engine",
            "lm_studio": "LM Studio",
            "ollama": "Ollama",
            "openrouter": "OpenRouter",
            "gemini": "Google Gemini"
        }
        prov_name = provider_labels.get(prov, prov.upper())
        if model and prov != "offline":
            self.engine_badge.setText(f"🧠 {prov_name} ({model})")
        else:
            self.engine_badge.setText(f"🧠 {prov_name}")

        endpoint_info = ""
        if prov == "lm_studio":
            endpoint_info = f"\nServer: {getattr(settings, 'lm_studio_server_type', 'local').title()}\nEndpoint: {getattr(settings, 'lm_studio_endpoint', '')}"
        elif prov == "ollama":
            endpoint_info = f"\nEndpoint: {getattr(settings, 'ollama_endpoint', '')}"
        self.engine_badge.setToolTip(f"Active reasoning engine: {prov_name} ({model or 'default'}){endpoint_info}")

    # =========================================================================
    # REASONING HEALTH & STATE
    # =========================================================================

    def update_engine_status(self, engine_info: Optional[Dict[str, Any]] = None):
        """Updates reasoning badge and health dot."""
        if not hasattr(self, "engine_badge") or not hasattr(self, "engine_status_lbl"):
            return

        if engine_info is None:
            engine_info = self.agent.get_engine_info() if hasattr(self.agent, "get_engine_info") else {}

        provider = engine_info.get("provider", "offline")
        model = engine_info.get("model", "")
        status = engine_info.get("status", "idle")
        latency = engine_info.get("latency_ms", 0.0)
        err = engine_info.get("error_message", "")

        provider_labels = {
            "offline": "Offline Engine",
            "lm_studio": "LM Studio",
            "ollama": "Ollama",
            "openrouter": "OpenRouter",
            "gemini": "Google Gemini"
        }
        prov_name = provider_labels.get(provider, provider.upper())
        if model and provider != "offline":
            self.engine_badge.setText(f"🧠 {prov_name} ({model})")
        else:
            self.engine_badge.setText(f"🧠 {prov_name}")

        p = get_theme_palette(self.theme)
        if status in ("online", "success"):
            lat_str = f" ({latency:.0f}ms)" if latency > 0 else ""
            self.engine_status_lbl.setText(f"🟢 Online{lat_str}")
            self.engine_status_lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {p['accent_emerald']};")
            self.engine_status_lbl.setToolTip(f"Engine connected and active ({latency:.0f} ms)")
        elif status == "offline":
            self.engine_status_lbl.setText("⚪ Offline")
            self.engine_status_lbl.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {p['text_muted']};")
            self.engine_status_lbl.setToolTip("100% Offline Heuristic Engine active")
        elif status == "offline_fallback":
            self.engine_status_lbl.setText("🟡 Fallback")
            self.engine_status_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #f59e0b;")
            self.engine_status_lbl.setToolTip(f"Remote LLM unreachable; operating in offline fallback.\nError: {err}")
        elif status == "analyzing":
            self.engine_status_lbl.setText("🟡 Analyzing...")
            self.engine_status_lbl.setStyleSheet("font-size: 11px; font-weight: 500; color: #38bdf8;")
            self.engine_status_lbl.setToolTip("Reasoning engine processing...")
        elif status in ("error", "failed"):
            self.engine_status_lbl.setText("🔴 Error")
            self.engine_status_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #ef4444;")
            self.engine_status_lbl.setToolTip(f"Reasoning engine error: {err}")
        else:
            self.engine_status_lbl.setText("⚪ Ready")
            self.engine_status_lbl.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {p['text_muted']};")
            self.engine_status_lbl.setToolTip(f"Reasoning engine configured ({prov_name})")

    def _run_engine_healthcheck(self):
        """Executes non-blocking health check against the active reasoning engine."""
        if not hasattr(self, "healthcheck_btn") or not hasattr(self, "agent"):
            return

        self.healthcheck_btn.setEnabled(False)
        self.healthcheck_btn.setText("⚡ Testing...")
        self.engine_status_lbl.setText("🟡 Checking...")
        self.engine_status_lbl.setStyleSheet("font-size: 11px; font-weight: 500; color: #38bdf8;")

        class HealthSignal(QObject):
            done = Signal(dict)

        bridge = HealthSignal()

        def _worker():
            try:
                res = self.agent.check_health()
                bridge.done.emit(res)
            except Exception as e:
                bridge.done.emit({"ok": False, "status": "error", "message": str(e), "latency_ms": 0.0})

        def _on_done(res: dict):
            self.healthcheck_btn.setEnabled(True)
            self.healthcheck_btn.setText("⚡ Check")
            ok = res.get("ok", False)
            status = res.get("status", "unknown")
            msg = res.get("message", "")
            lat = res.get("latency_ms", 0.0)

            p = get_theme_palette(self.theme)
            if ok and status == "online":
                lat_str = f" ({lat:.0f}ms)" if lat > 0 else ""
                self.engine_status_lbl.setText(f"🟢 Online{lat_str}")
                self.engine_status_lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {p['accent_emerald']};")
                self.engine_status_lbl.setToolTip(msg)
            elif status == "offline":
                self.engine_status_lbl.setText("⚪ Offline")
                self.engine_status_lbl.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {p['text_muted']};")
                self.engine_status_lbl.setToolTip(msg)
            else:
                self.engine_status_lbl.setText("🔴 Offline / Error")
                self.engine_status_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #ef4444;")
                self.engine_status_lbl.setToolTip(f"Healthcheck failed: {msg}")

        bridge.done.connect(_on_done)
        self._health_bridge = bridge
        import threading
        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # QUICK ACTIONS & AD-HOC QUERIES
    # =========================================================================

    def _trigger_quick_action(self, key: str):
        """Dispatches quick action prompt using user-customized instructions from Settings."""
        instruction = Settings().get_quick_action_instruction(key)
        self.agent.run_quick_prompt(key, custom_instruction=instruction)

    def _submit_adhoc_query(self):
        query = self.adhoc_input.text().strip()
        if query:
            self.adhoc_input.clear()
            self.agent.run_quick_prompt(query)

    def _on_quick_action_gui(self, title: str, text: str):
        """Displays quick-action response in the Summary Tab browser formatted in rich Markdown."""
        ts = time.strftime("%H:%M:%S")
        entry_md = f"### ⚡ {title} *({ts})*\n\n{text.strip()}\n\n---\n"
        
        if not hasattr(self, "_quick_action_markdown_entries"):
            self._quick_action_markdown_entries = []
        
        self._quick_action_markdown_entries.append(entry_md)
        full_md = "\n".join(self._quick_action_markdown_entries)
        self.quick_action_browser.setMarkdown(full_md)

        # Scroll to bottom to view newest synthesis
        scrollbar = self.quick_action_browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # Automatically bring Summary Tab into focus
        self.right_tabs.setCurrentWidget(self.summary_tab)

    def _clear_quick_action_results(self):
        self._quick_action_markdown_entries = []
        self.quick_action_browser.clear()

    # =========================================================================
    # TRANSCRIPTION FEED & RESULTS RENDERING
    # =========================================================================

    def _on_transcription_gui(self, channel: str, text: str, timestamp: float, turn_id: int):
        turn = self.memory.add_transcript(channel, text, timestamp, turn_id)
        p = get_theme_palette(self.theme)
        
        color = p['accent_cyan'] if channel == "you" else (p['accent_purple'] if channel == "participants" else p['accent_emerald'])
        entry_html = f"<div style='margin-bottom: 4px;'><span style='color: {color}; font-weight: bold;'>{turn.speaker_label} ({turn.formatted_time}):</span> <span style='color: {p['text_primary']};'>{turn.text}</span></div>"
        
        self.ticker_box.append(entry_html)
        if self.auto_scroll_chk.isChecked():
            scrollbar = self.ticker_box.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _clear_transcript_feed(self):
        self.ticker_box.clear()

    def _on_agent_results_gui(self, results: dict):
        self._render_questions()
        self._render_follow_ups()
        self._update_summary_browser_text()
        if "engine_info" in results:
            self.update_engine_status(results["engine_info"])

    def _render_questions(self):
        self.questions_list.clear()
        pending_questions = [q for q in self.memory.suggested_questions if q.status == "pending"]
        
        count = len(pending_questions)
        self.q_count_badge.setText(f"{count} pending" if count > 0 else "0")
        self.q_count_badge.setVisible(count > 0)
        self.q_clear_btn.setVisible(count > 0)

        for q in pending_questions:
            item = QListWidgetItem()
            widget = QuestionItemWidget(
                question=q,
                on_copy_cb=self._on_copy_text,
                on_asked_cb=self._on_mark_asked,
                on_dismiss_cb=self._on_dismiss_question,
                theme=self.theme
            )
            item.setSizeHint(widget.sizeHint())
            self.questions_list.addItem(item)
            self.questions_list.setItemWidget(item, widget)

    def _render_follow_ups(self):
        self.follow_ups_list.clear()
        pending_followups = [f for f in self.memory.follow_up_suggestions if f.status == "pending"]
        
        count = len(pending_followups)
        self.f_count_badge.setText(f"{count} pending" if count > 0 else "0")
        self.f_count_badge.setVisible(count > 0)
        self.f_clear_btn.setVisible(count > 0)

        for f in pending_followups:
            item = QListWidgetItem()
            widget = FollowUpItemWidget(
                item=f,
                on_copy_cb=self._on_copy_text,
                on_done_cb=self._on_mark_followup_done,
                on_dismiss_cb=self._on_dismiss_followup,
                theme=self.theme
            )
            item.setSizeHint(widget.sizeHint())
            self.follow_ups_list.addItem(item)
            self.follow_ups_list.setItemWidget(item, widget)

    def _render_notes(self):
        """Renders notes in both the editor and compatibility list."""
        self.notes_list.clear()
        for note in self.memory.user_notes:
            self.notes_list.addItem(note)
        if not self.notes_editor.toPlainText().strip() and self.memory.user_notes:
            self.notes_editor.blockSignals(True)
            self.notes_editor.setPlainText("\n".join(self.memory.user_notes))
            self.notes_editor.blockSignals(False)

    def _add_custom_note(self):
        """Backward compatibility helper for tests."""
        text = self.add_note_input.toPlainText().strip()
        if text:
            self.add_note_input.clear()
            self.memory.add_user_note(text)

    def _clear_suggested_questions(self):
        self.memory.clear_suggested_questions(status="pending")
        self._render_questions()

    def _clear_follow_up_suggestions(self):
        self.memory.clear_follow_up_suggestions(status="pending")
        self._render_follow_ups()

    def _on_copy_text(self, text_to_copy: str):
        clipboard = QApplication.clipboard()
        clipboard.setText(text_to_copy)

    def _on_mark_asked(self, question_text: str):
        self.memory.mark_question_asked(question_text)
        self._render_questions()

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

    def _update_summary_browser_text(self):
        p = get_theme_palette(self.theme)
        is_light = (self.theme == "light")
        
        sum_data = self.memory.rolling_summary
        topic = sum_data.get("topic", "")
        topics_list = sum_data.get("topics", [])
        bullets = sum_data.get("summary_bullets", [])
        exec_sum = sum_data.get("executive_summary", "")
        decisions = sum_data.get("key_decisions", [])
        
        if topic:
            self.chat_topic_lbl.setText(f"📌 TOPIC: {topic.upper()}")
        else:
            self.chat_topic_lbl.setText("📌 LIVE ROLLING SUMMARY")

        html_parts = []
        
        if not topic and not exec_sum and not topics_list and not bullets and not decisions:
            is_active = hasattr(self, "agent") and getattr(self.agent, "is_analyzing", False)
            hint_text = (
                "⚡ Analyzing meeting dialogue... Synthesizing conversation topic and executive summary..."
                if is_active else
                "Listening to meeting audio... Conversation topics, executive summaries, and key decisions will dynamically populate here."
            )
            html_parts.append(
                f"<div style='color: {p['accent_cyan'] if is_active else p['text_muted']}; font-style: italic; padding: 12px; text-align: center;'>"
                f"{hint_text}"
                f"</div>"
            )
            if hasattr(self, "chat_status_lbl"):
                self.chat_status_lbl.setText("🟡 Warmup listening..." if is_active else "")
        else:
            if hasattr(self, "chat_status_lbl"):
                self.chat_status_lbl.setText(f"🟢 {len(topics_list)} active topic(s)")
                self.chat_status_lbl.setStyleSheet(f"font-size: 10px; font-weight: 500; color: {p['accent_emerald']};")
            if topic:
                html_parts.append(
                    f"<div style='background-color: {p['accent_cyan_bg'] if is_light else '#082f49'}; "
                    f"border-left: 4px solid {p['accent_cyan']}; padding: 6px 10px; margin-bottom: 8px; border-radius: 4px;'>"
                    f"<span style='color: {p['accent_cyan']}; font-weight: bold; font-size: 11px;'>CURRENT AGENDA:</span><br>"
                    f"<span style='color: {p['text_primary']}; font-size: 13px; font-weight: 600;'>{topic}</span>"
                    f"</div>"
                )

            if exec_sum:
                html_parts.append(
                    f"<div style='background-color: {p['bg_surface']}; border: 1px solid {p['border_subtle']}; border-radius: 6px; padding: 10px; margin-bottom: 8px;'>"
                    f"<div style='color: {p['accent_emerald']}; font-weight: bold; font-size: 11px; margin-bottom: 4px;'>📌 EXECUTIVE SUMMARY</div>"
                    f"<div style='color: {p['text_primary']}; font-size: 12px; line-height: 1.4;'>{exec_sum}</div>"
                    f"</div>"
                )

            if topics_list:
                for top in topics_list:
                    t_title = top.get("title", "Discussion Thread")
                    t_summary = top.get("summary", "")
                    t_status = top.get("status", "in_progress").replace("_", " ").title()
                    status_badge = f"<span style='font-size: 10px; color: {p['accent_cyan']}; font-weight: normal; margin-left: 6px;'>({t_status})</span>"
                    
                    html_parts.append(
                        f"<div style='background-color: {p['bg_surface']}; border: 1px solid {p['border_subtle']}; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px;'>"
                        f"<div style='color: {p['text_primary']}; font-weight: bold; font-size: 12px; margin-bottom: 4px;'>🔹 {t_title} {status_badge}</div>"
                        f"<div style='color: {p['text_secondary']}; font-size: 11px; line-height: 1.5;'>{t_summary}</div>"
                        f"</div>"
                    )

            if decisions:
                html_parts.append(
                    f"<div style='background-color: {p['accent_emerald_bg'] if is_light else '#064e3b'}; border: 1px solid {p['accent_emerald']}; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px;'>"
                    f"<div style='color: {'#065f46' if is_light else '#a7f3d0'}; font-weight: bold; font-size: 11px; margin-bottom: 4px;'>✅ KEY DECISIONS & CONSENSUS</div>"
                    f"<ul style='margin: 0px 0px 0px 16px; padding: 0px;'>"
                )
                for dec in decisions:
                    html_parts.append(f"<li style='color: {p['text_primary']}; font-size: 11px; font-weight: 500; margin-bottom: 2px;'>{dec}</li>")
                html_parts.append("</ul></div>")

        self.summary_browser.setHtml("".join(html_parts))

    # =========================================================================
    # POPOUT & RE-DOCKING
    # =========================================================================

    def _ensure_popout_dialog(self) -> RollingSummaryPopoutDialog:
        if self.popout_dialog is None:
            self.popout_dialog = RollingSummaryPopoutDialog(theme=self.theme, parent=self.window())
            self.popout_dialog.dock_in_requested.connect(self._dock_summary_in)
        return self.popout_dialog

    @property
    def is_summary_popped_out(self) -> bool:
        return bool(self.popout_dialog and self.popout_dialog.isVisible())

    def _toggle_summary_popout(self):
        if self.is_summary_popped_out:
            self._dock_summary_in()
        else:
            self._popout_summary_out()

    def _popout_summary_out(self):
        dialog = self._ensure_popout_dialog()
        if hasattr(self, "summary_container") and self.summary_container:
            dialog.set_content_widget(self.summary_container)
            self.summary_popped_placeholder.setVisible(True)
            self.popout_summary_btn.setText("⬇️ Dock In")
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    def _dock_summary_in(self):
        if self.popout_dialog and hasattr(self, "summary_container") and self.summary_container:
            w = self.popout_dialog.take_content_widget()
            if w:
                self.chat_tab.layout().insertWidget(1, w)
            self.summary_popped_placeholder.setVisible(False)
            self.popout_summary_btn.setText("⧉ Pop Out")
            self.popout_dialog.hide()

    def _open_notes_folder(self):
        try:
            cfg = Settings()
            rec_dir = cfg.resolved_recordings_dir
            if rec_dir.exists():
                os.startfile(str(rec_dir))
        except Exception as e:
            print(f"[RecordView] Error opening notes folder: {e}")

    def _copy_markdown_notes(self):
        md = self.memory.get_scratchpad_markdown()
        clipboard = QApplication.clipboard()
        clipboard.setText(md)
        self.copy_md_btn.setText("✓ Copied!")
        QTimer.singleShot(1800, lambda: self.copy_md_btn.setText("📋 Copy Notes"))

    def _on_manual_reset_clicked(self):
        self.memory.clear()
        self.ticker_box.clear()
        self.notes_editor.clear()
        self.notes_list.clear()
        self.questions_list.clear()
        self.follow_ups_list.clear()
        self._quick_action_markdown_entries = []
        self.quick_action_browser.clear()
        self.q_count_badge.setVisible(False)
        self.f_count_badge.setVisible(False)
        self.q_clear_btn.setVisible(False)
        self.f_clear_btn.setVisible(False)
        self.reset_title_and_tags()
        self._update_summary_browser_text()
        self.reset_session_requested.emit()

    def _on_mode_combo_changed(self, index: int):
        mode = self.mode_combo.currentData()
        if mode:
            self.meeting_mode_changed.emit(mode)

    def _on_asr_combo_changed(self, index: int):
        provider = self.asr_combo.currentData()
        if provider:
            self.asr_provider_changed.emit(provider)

    def set_copilot_enabled(self, enabled: bool):
        self.stack.setCurrentIndex(0 if enabled else 1)

    # =========================================================================
    # THEME STYLING
    # =========================================================================

    def set_theme(self, theme: str):
        self.theme = theme
        p = get_theme_palette(theme)
        is_light = (theme == "light")

        # Sub-header styling
        sub_card_bg = "#f8fafc" if is_light else "#1e293b"
        border_col = p['border_subtle']
        input_bg = p['bg_input']
        text_col = p['text_primary']

        self.setStyleSheet(f"""
            QFrame#subHeaderCard {{
                background-color: {sub_card_bg};
                border: 1px solid {border_col};
                border-radius: 6px;
            }}
            QFrame#leftColFrame, QFrame#card {{
                background-color: {sub_card_bg};
                border: 1px solid {border_col};
                border-radius: 6px;
            }}
            QLineEdit, QComboBox {{
                background-color: {input_bg};
                border: 1px solid {p['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {text_col};
                font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border-color: {p['accent_cyan']};
            }}
            QPushButton {{
                background-color: {p['bg_surface']};
                border: 1px solid {p['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {text_col};
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {p['bg_hover']};
            }}
            QPlainTextEdit, QTextBrowser, QTextEdit {{
                background-color: {input_bg};
                border: 1px solid {border_col};
                border-radius: 4px;
                color: {text_col};
                font-size: 12px;
                padding: 6px;
            }}
            QTabWidget::pane {{
                border: 1px solid {border_col};
                background: {sub_card_bg};
                border-radius: 4px;
            }}
            QTabBar::tab {{
                background: {p['bg_surface']};
                color: {p['text_muted']};
                padding: 6px 12px;
                border: 1px solid {border_col};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {sub_card_bg};
                color: {p['accent_cyan']};
                border-bottom: 2px solid {p['accent_cyan']};
            }}
            QSplitter::handle {{
                background-color: {border_col};
                width: 4px;
                border-radius: 2px;
            }}
        """)

        # Engine badge style
        self.engine_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {input_bg};
                color: {p['accent_cyan']};
                border: 1px solid {border_col};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
        """)

        # Update lists and browser
        self._render_questions()
        self._render_follow_ups()
        self._update_summary_browser_text()

        if self.popout_dialog:
            self.popout_dialog.set_theme(theme)

    def update_status(self, recording: bool, paused: bool, meeting_mode: str, asr_name_or_key: str, notes_saved: bool = False):
        """Updates meeting mode and ASR combo dropdowns and status dot tooltip."""
        if hasattr(self, "status_dot"):
            if recording:
                self.status_dot.setText("🔴" if not paused else "⏸️")
                self.status_dot.setToolTip("Status: Recording Active" if not paused else "Status: Recording Paused")
            else:
                self.status_dot.setText("🟢")
                status_text = "Status: Notes Saved & Standby" if notes_saved else "Status: Live Copilot Ready"
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

    def clear(self):
        """Clears memory and interface components for a new session."""
        self._on_manual_reset_clicked()

    def closeEvent(self, event):
        """Ensures popout dialog is docked in or closed when widget closes."""
        if self.popout_dialog:
            self._dock_summary_in()
            self.popout_dialog.close()
        event.accept()
