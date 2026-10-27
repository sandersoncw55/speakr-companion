import os
import sys
import tempfile
from pathlib import Path

# Isolate all tests to a temporary settings directory so user's real settings.json is untouched
_TEST_SETTINGS_DIR = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LOCALAPPDATA"] = _TEST_SETTINGS_DIR.name

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import numpy as np
from core.copilot.memory import CopilotMemory, SuggestedQuestion, FollowUpItem
from core.copilot.prompts import get_periodic_prompt, DEFAULT_QUICK_PROMPTS
from core.copilot.segmenter import VADSegmenter, AudioSegment
from core.asr.manager import ASRManager
from core.asr.local_whisper import LocalWhisperProvider
from core.asr.websocket_mlx import MacWhisperMLXProvider
from core.asr.cloud_provider import CloudWhisperProvider
from core.recorder import AudioRecorder

def test_memory_and_scratchpad():
    print("Testing CopilotMemory and Interactive Scratchpad...")
    mem = CopilotMemory(max_history_seconds=120.0)

    # 1. Add transcript turns
    t1 = mem.add_transcript("you", "Let's review the SAN firmware rollback plan.", time.time(), 1)
    t2 = mem.add_transcript("participants", "The snapshot was verified this morning.", time.time(), 2)
    assert len(mem.turns) == 2
    assert t1.speaker_label == "[You]"
    assert t2.speaker_label == "[Call Participants]"

    # 2. Set Rolling Summary
    mem.set_rolling_summary({
        "topic": "SAN Controller Firmware Rollback",
        "summary_bullets": ["The team is finalizing cutover precautions for SAN storage nodes before deploying firmware v3.4.1."],
        "executive_summary": "The team is finalizing cutover precautions for SAN storage nodes before deploying firmware v3.4.1.",
        "key_decisions": ["Proceed with snapshot validation at 2 AM maintenance window."]
    })
    assert mem.rolling_summary["topic"] == "SAN Controller Firmware Rollback"
    assert "cutover precautions" in mem.rolling_summary["executive_summary"]
    assert len(mem.rolling_summary["key_decisions"]) == 1
    assert len(mem.rolling_summary["summary_bullets"]) == 1

    # Verify rolling updates accumulate instead of wiping
    mem.set_rolling_summary({
        "summary_bullets": ["Verified secondary node snapshot consistency."]
    })
    assert len(mem.rolling_summary["summary_bullets"]) == 2
    assert "Verified secondary node" in mem.rolling_summary["summary_bullets"][1]

    # 3. Suggested questions & user interactive status
    mem.set_suggested_questions([
        {"question": "Who is the primary on-call engineer?", "rationale": "Accountability"},
        {"question": "What is the maintenance window cutover time?", "rationale": "SLA compliance"}
    ])
    assert len(mem.suggested_questions) == 2
    assert mem.suggested_questions[0].status == "pending"

    # 4. Follow-up suggestions / Action items
    mem.set_follow_up_suggestions([
        {"task": "Verify secondary SAN node heartbeat", "owner": "Chuck"},
        {"task": "Update Datadog alerting dashboard", "owner": "Dave"}
    ])
    assert len(mem.follow_up_suggestions) == 2
    assert mem.follow_up_suggestions[0].status == "pending"

    # 5. User marks question asked and action item done
    mem.mark_question_asked("Who is the primary on-call engineer?")
    assert mem.suggested_questions[0].status == "asked"

    mem.mark_followup_done("Verify secondary SAN node heartbeat")
    assert mem.follow_up_suggestions[0].status == "done"

    # 6. User adds manual note
    mem.add_user_note("Chuck confirmed firmware 3.4.1 snapshot ready.")
    assert len(mem.user_notes) >= 1

    # 7. Verify Markdown serialization
    md = mem.get_scratchpad_markdown()
    assert "SAN Controller Firmware Rollback" in md
    assert "The team is finalizing cutover precautions" in md
    assert "Proceed with snapshot validation" in md
    assert "- [x] Verify secondary SAN node heartbeat (@Chuck)" in md
    assert "- [ ] Update Datadog alerting dashboard (@Dave)" in md
    assert "Who is the primary on-call engineer?" in md
    assert "Chuck confirmed firmware 3.4.1 snapshot ready." in md

    print("[OK] CopilotMemory passed.")

def test_prompts_and_tag_personas():
    print("Testing Prompt Generator and Tag Personas...")
    cab_prompt = get_periodic_prompt("cab-meeting")
    assert "CHANGE ADVISORY BOARD" in cab_prompt
    assert "rollback" in cab_prompt.lower()
    assert "rolling_summary" in cab_prompt
    assert "follow_up_suggestions" in cab_prompt

    bridge_prompt = get_periodic_prompt("bridge-call-troubleshooting")
    assert "INCIDENT MANAGEMENT" in bridge_prompt
    assert "blast radius" in bridge_prompt.lower()

    assert "what_to_ask" in DEFAULT_QUICK_PROMPTS
    assert "catch_me_up" in DEFAULT_QUICK_PROMPTS
    print("[OK] Prompts & Tag Personas passed.")

def test_vad_channel_modes():
    print("Testing VADSegmenter channel routing...")
    emitted = []
    seg = VADSegmenter(on_segment_callback=lambda s: emitted.append(s), meeting_mode="virtual")
    assert "you" in seg.trackers
    assert "participants" in seg.trackers

    # Switch to In-Person Room Mode
    seg.set_meeting_mode("in_person")
    assert "room" in seg.trackers
    assert "you" not in seg.trackers

    print("[OK] VADSegmenter channel modes passed.")

def test_asr_provider_manager():
    print("Testing ASRManager and Provider Switching...")
    mgr = ASRManager(on_transcription_callback=lambda s, t: None)

    # Test switching
    mgr.configure_provider("local", {"model_size": "tiny.en", "cpu_threads": 2})
    assert isinstance(mgr.active_provider, LocalWhisperProvider)
    assert mgr.active_provider.model_size == "tiny.en"

    mgr.configure_provider("mac_lan", {"mac_mlx_url": "http://192.168.0.88:9000"})
    assert isinstance(mgr.active_provider, MacWhisperMLXProvider)

    mgr.configure_provider("groq", {"groq_api_key": "gsk_test123"})
    assert isinstance(mgr.active_provider, CloudWhisperProvider)
    assert mgr.active_provider.provider_type == "groq"
    assert mgr.active_provider.is_available() is True

    mgr.shutdown()
    print("[OK] ASRManager provider switching passed.")

def test_local_whisper_transcription():
    print("Testing LocalWhisperProvider on CPU (int8)...")
    provider = LocalWhisperProvider(model_size="tiny.en", cpu_threads=4)
    assert provider.is_available() is True
    
    # 1 second of silence
    silence_pcm = np.zeros(16000, dtype=np.int16).tobytes()
    text = provider.transcribe(silence_pcm)
    assert isinstance(text, str)
    print("[OK] Local Whisper transcribed chunk successfully.")

def test_audio_recorder_tap():
    print("Testing AudioRecorder tap callback integration...")
    rec = AudioRecorder()
    assert hasattr(rec, "audio_tap_callback")
    assert hasattr(rec, "meeting_mode")
    rec.meeting_mode = "in_person"
    assert rec.meeting_mode == "in_person"
    rec.terminate()
    print("[OK] AudioRecorder tap integration passed.")

def test_offline_copilot_engine():
    print("Testing OfflineExtractiveEngine and CopilotAgent offline fallback...")
    from core.copilot.agent import OfflineExtractiveEngine, CopilotAgent
    
    engine = OfflineExtractiveEngine()
    mem = CopilotMemory()
    mem.add_transcript("you", "Can we deploy the new firmware before Friday?", time.time(), 1)
    mem.add_transcript("participants", "I will take care of updating the staging cluster and verify the rollout.", time.time(), 2)
    mem.add_transcript("participants", "We might have a delay if the SAN controller fails over.", time.time(), 3)
    
    # 1. Periodic offline generation
    res = engine.generate_periodic(mem.turns, [])
    assert "rolling_summary" in res
    assert "summary_bullets" in res["rolling_summary"]
    assert len(res["rolling_summary"]["summary_bullets"]) > 0
    assert "suggested_questions" in res
    assert len(res["suggested_questions"]) > 0
    # Questions must be targeted technical questions citing dialogue entities
    probing_texts = [q["question"] for q in res["suggested_questions"]]
    assert any("SAN" in q or "controller" in q or "firmware" in q or "rollback" in q for q in probing_texts)
    assert "follow_up_suggestions" in res
    assert len(res["follow_up_suggestions"]) > 0
    
    # 2. Quick actions offline
    summary = engine.generate_quick_action("catch_me_up", mem.turns)
    assert "Recent Meeting Summary" in summary
    assert "deploy the new firmware" in summary

    questions_res = engine.generate_quick_action("what_to_ask", mem.turns)
    assert "Suggested Questions" in questions_res

    owners_res = engine.generate_quick_action("clarify_ownership", mem.turns)
    assert "Action & Ownership" in owners_res or "staging cluster" in owners_res

    risks_res = engine.generate_quick_action("spot_risks", mem.turns)
    assert "Risks" in risks_res

    custom_res = engine.generate_quick_action("SAN firmware", mem.turns)
    assert "Mentions relevant to" in custom_res or "context" in custom_res

    # 3. CopilotAgent with provider="offline" executes without API keys
    results_received = []
    agent = CopilotAgent(mem, on_results_callback=lambda r: results_received.append(r), cadence_seconds=1.0)
    agent.configure(provider="offline", api_key="")
    
    # Run immediate quick prompt
    agent.run_quick_prompt("catch_me_up")
    time.sleep(0.5)
    assert len(results_received) > 0
    assert results_received[0]["type"] == "quick_action"
    assert "Recent Meeting Summary" in results_received[0]["text"]
    print("[OK] OfflineExtractiveEngine and CopilotAgent offline fallback passed.")

def test_hud_controls_and_splitter():
    print("Testing CopilotDashboardWidget 3-Tier Resizable Layout & Stacked Views...")
    from PySide6.QtWidgets import QApplication
    from gui.hud import CopilotDashboardWidget, TwoLineNoteEdit
    
    app = QApplication.instance() or QApplication([])
    mem = CopilotMemory()
    from core.copilot.agent import CopilotAgent
    agent = CopilotAgent(mem, on_results_callback=lambda r: None)
    
    widget = CopilotDashboardWidget(mem, agent)
    
    # Mode combo check
    assert widget.mode_combo.count() == 3
    assert widget.mode_combo.findData("virtual") >= 0
    assert widget.mode_combo.findData("in_person") >= 0
    assert widget.mode_combo.findData("hybrid") >= 0
    
    # ASR combo check
    assert widget.asr_combo.count() == 4
    assert widget.asr_combo.findData("local") >= 0
    assert widget.asr_combo.findData("mac_lan") >= 0
    
    # 3-Tier Master Vertical Splitter check
    assert hasattr(widget, "main_v_splitter")
    assert widget.main_v_splitter.count() == 3
    
    # Tier 1: Horizontal Splitter (Questions + Follow-ups side-by-side)
    assert hasattr(widget, "top_h_splitter")
    assert widget.top_h_splitter.count() == 2
    assert hasattr(widget, "questions_list")
    assert hasattr(widget, "follow_ups_list")
    
    # Tier 2: Rolling Summary Browser & Scratchpad
    assert hasattr(widget, "summary_browser")
    assert hasattr(widget, "notes_list")
    assert hasattr(widget, "add_note_input")
    from PySide6.QtCore import Qt
    assert widget.notes_list.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert widget.summary_browser.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert widget.notes_list.wordWrap() is True
    
    # Tier 3: Bottom Live Transcript Feed
    assert hasattr(widget, "ticker_box")
    assert hasattr(widget, "auto_scroll_chk")
    
    # Quick action buttons check
    assert hasattr(widget, "btn_ask")
    assert hasattr(widget, "btn_catchup")
    assert hasattr(widget, "btn_owners")
    assert hasattr(widget, "btn_risks")
    assert hasattr(widget, "btn_jargon")
    assert hasattr(widget, "adhoc_input")
    assert hasattr(widget, "copy_md_btn")
    
    # TwoLineNoteEdit check
    assert isinstance(widget.add_note_input, TwoLineNoteEdit)
    widget.add_note_input.setPlainText("Test custom note item")
    widget._add_custom_note()
    assert "Test custom note item" in mem.user_notes
    
    # Test questions count badge and clear button
    widget.show()
    mem.set_suggested_questions([
        {"question": "HUD Question 1", "rationale": "r1"},
        {"question": "HUD Question 2", "rationale": "r2"}
    ])
    widget._render_questions()
    assert widget.q_count_badge.isVisible() is True
    assert widget.q_clear_btn.isVisible() is True
    assert "2 pending" in widget.q_count_badge.text()
    
    # Test follow-ups count badge and clear button
    mem.set_follow_up_suggestions([
        {"task": "HUD Action 1", "owner": "Chuck"}
    ])
    widget._render_follow_ups()
    assert widget.f_count_badge.isVisible() is True
    assert widget.f_clear_btn.isVisible() is True
    assert "1 pending" in widget.f_count_badge.text()

    # Test Clear buttons
    widget._clear_suggested_questions()
    assert widget.q_count_badge.isVisible() is False
    assert len([q for q in mem.suggested_questions if q.status == "pending"]) == 0

    widget._clear_follow_up_suggestions()
    assert widget.f_count_badge.isVisible() is False
    assert len([f for f in mem.follow_up_suggestions if f.status == "pending"]) == 0

    # Test Enabled / Disabled View Toggle
    widget.set_copilot_enabled(False)
    assert widget.stack.currentIndex() == 1  # Disabled view
    widget.set_copilot_enabled(True)
    assert widget.stack.currentIndex() == 0  # Active view

    widget.close()
    print("[OK] CopilotDashboardWidget 3-Tier Resizable Layout & Stacked Views passed.")

def test_suggested_questions_accumulation():
    print("Testing Suggested Questions Accumulation & Deduplication across cycles...")
    mem = CopilotMemory()

    # Cycle 1: 2 questions returned
    mem.set_suggested_questions([
        {"question": "Who is leading the migration?", "rationale": "Owner"},
        {"question": "What is the timeline?", "rationale": "Date"}
    ])
    assert len(mem.suggested_questions) == 2
    assert [q.question for q in mem.suggested_questions] == [
        "Who is leading the migration?",
        "What is the timeline?"
    ]

    # User marks the first question as asked
    mem.mark_question_asked("Who is leading the migration?")
    assert mem.suggested_questions[0].status == "asked"

    # Cycle 2: 2 questions (one existing, one new)
    mem.set_suggested_questions([
        {"question": "What is the timeline?", "rationale": "Date"},
        {"question": "Are there rollback procedures?", "rationale": "Safety"}
    ])
    # Should accumulate to 3 total questions (no duplicates, previous questions NOT lost!)
    assert len(mem.suggested_questions) == 3
    assert mem.suggested_questions[0].status == "asked"
    assert mem.suggested_questions[1].status == "pending"
    assert mem.suggested_questions[2].question == "Are there rollback procedures?"

    # Cycle 3: list of strings (from offline engine)
    mem.set_suggested_questions([
        "Are there rollback procedures?",  # duplicate - should not re-add
        "Who is approving the change request?"  # new question
    ])
    assert len(mem.suggested_questions) == 4
    assert mem.suggested_questions[3].question == "Who is approving the change request?"

    # Test clear_suggested_questions with "pending" filter
    mem.clear_suggested_questions(status="pending")
    assert len(mem.suggested_questions) == 1
    assert mem.suggested_questions[0].status == "asked"

    # Test total clear
    mem.clear_suggested_questions()
    assert len(mem.suggested_questions) == 0
    print("[OK] Suggested Questions Accumulation & Deduplication passed.")

def test_lm_studio_configuration():
    print("Testing LM Studio reasoning engine configuration & privacy mode...")
    from core.copilot.agent import CopilotAgent
    from core.config import Settings
    
    mem = CopilotMemory()
    agent = CopilotAgent(mem, on_results_callback=lambda r: None)

    # Configure LM Studio local
    agent.configure(
        provider="lm_studio",
        custom_endpoint="http://localhost:1234/v1",
        model_name="local-model",
        privacy_mode=True
    )
    assert agent.llm_provider == "lm_studio"
    assert agent.custom_endpoint == "http://localhost:1234/v1"
    assert agent._is_offline_mode() is False

    # Configure LM Studio remote server
    agent.configure(
        provider="lm_studio",
        custom_endpoint="http://192.168.0.88:1234/v1",
        model_name="qwen2.5-coder-7b",
        privacy_mode=True
    )
    assert agent.custom_endpoint == "http://192.168.0.88:1234/v1"
    assert agent._is_offline_mode() is False

    # Switch to offline mode
    agent.configure(provider="offline")
    assert agent._is_offline_mode() is True

    # Check Settings properties
    cfg = Settings()
    cfg.lm_studio_endpoint = "http://192.168.1.100:1234/v1"
    assert cfg.lm_studio_endpoint == "http://192.168.1.100:1234/v1"
    cfg.lm_studio_server_type = "remote"
    assert cfg.lm_studio_server_type == "remote"
    cfg.lm_studio_api_key = "test-token-123"
    assert cfg.lm_studio_api_key == "test-token-123"
    cfg.lm_studio_bypass_auth = False
    assert cfg.lm_studio_bypass_auth is False
    cfg.lm_studio_bypass_auth = True
    assert cfg.lm_studio_bypass_auth is True
    # Restore defaults
    cfg.lm_studio_endpoint = "http://localhost:1234/v1"
    cfg.lm_studio_server_type = "local"
    cfg.lm_studio_api_key = ""

    print("[OK] LM Studio configuration & privacy mode passed.")

def test_recordings_notes_linking_and_viewer():
    print("Testing Recordings Manager Notes Linking & NotesViewerDialog...")
    import tempfile
    from pathlib import Path
    from core.config import Settings
    from core.storage import RecordingsManager
    from gui.main_window import NotesViewerDialog
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    
    cfg = Settings()
    mgr = RecordingsManager(cfg)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        fake_rec = os.path.join(tmpdir, "Recording_2026-09-18_test.mp4")
        fake_notes = os.path.join(tmpdir, "Meeting_Notes_2026-09-18_test.md")
        
        with open(fake_rec, "w") as f:
            f.write("fake audio content")
        with open(fake_notes, "w", encoding="utf-8") as f:
            f.write("# Meeting Notes Test\n\n- [x] Question 1 asked\n- [ ] Question 2 pending\n- Follow up note")

        # 1. Add recording with notes_path
        rec = mgr.add_recording(
            file_path=fake_rec,
            trigger="manual",
            duration_seconds=42.0,
            status="Local Only",
            notes_path=fake_notes
        )
        assert rec["notes_path"] == str(Path(fake_notes).resolve())
        
        # 2. Update notes path
        another_notes = os.path.join(tmpdir, "Updated_Notes.md")
        mgr.update_notes_path(fake_rec, another_notes)
        all_recs = mgr.get_recordings()
        matched = [r for r in all_recs if r["file_path"] == str(Path(fake_rec).resolve())]
        assert len(matched) == 1
        assert matched[0]["notes_path"] == str(Path(another_notes).resolve())

        # 3. NotesViewerDialog instantiation
        dlg = NotesViewerDialog(fake_notes, "Recording_2026-09-18_test.mp4")
        assert "Meeting Notes Test" in dlg.browser.toPlainText()
        dlg.close()

    print("[OK] Recordings Manager Notes Linking & NotesViewerDialog passed.")

def test_notes_upload_and_summarization_linkage():
    print("Testing Notes Upload and Summarization Linkage...")
    import tempfile
    from unittest.mock import MagicMock, patch
    from core.client import SpeakrClient
    from core.uploader import AudioUploader
    from core.config import Settings
    from core.storage import RecordingsManager

    # 1. Test SpeakrClient endpoints with mocks
    client = SpeakrClient("http://127.0.0.1:8899")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake mp4 audio data")
        temp_audio = f.name

    try:
        # Mock client.post for upload_recording
        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=201, json=lambda: {"id": "rec_456"})
            rec_id = client.upload_recording(
                temp_audio, 
                title="Test Call", 
                notes="# Test Notes\n- [x] Item 1",
                prompt_variables={"copilot_notes": "# Test Notes\n- [x] Item 1"}
            )
            assert rec_id == "rec_456"
            _, kwargs = mock_post.call_args
            assert "data" in kwargs
            assert kwargs["data"]["title"] == "Test Call"
            assert kwargs["data"]["notes"] == "# Test Notes\n- [x] Item 1"
            assert "copilot_notes" in kwargs["data"]["prompt_variables"]

        # Mock client.put for replace_recording_notes
        with patch("httpx.Client.put") as mock_put:
            mock_put.return_value = MagicMock(status_code=200, json=lambda: {"notes": "updated"})
            ok = client.replace_recording_notes("rec_456", "# Updated Notes")
            assert ok is True
            _, kwargs = mock_put.call_args
            assert kwargs["json"] == {"notes": "# Updated Notes"}

        # Mock client.post for trigger_summarization
        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "queued"})
            ok = client.trigger_summarization("rec_456", custom_prompt="Focus on SAN items")
            assert ok is True
            _, kwargs = mock_post.call_args
            assert kwargs["json"] == {"custom_prompt": "Focus on SAN items"}

        # 2. Test AudioUploader notes resolution & API mode
        cfg = Settings()
        cfg.servers = [{"name": "Test Speakr", "url": "http://localhost:8899", "api_key": "test_key_123"}]
        cfg.upload_mode = "api"
        storage = RecordingsManager(cfg)
        
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            audio_path = os.path.join(tmpdir, "Meeting_2026-09-18.mp4")
            notes_path = os.path.join(tmpdir, "Meeting_2026-09-18_Notes.md")
            with open(audio_path, "wb") as f:
                f.write(b"mp4 content")
            with open(notes_path, "w", encoding="utf-8") as f:
                f.write("# Copilot Live Notes\n- [x] Key question answered")

            storage.add_recording(
                file_path=audio_path,
                trigger="manual",
                duration_seconds=30.0,
                notes_path=notes_path
            )

            uploader = AudioUploader(cfg, storage=storage)
            resolved_p, resolved_txt = uploader._resolve_notes(audio_path, audio_path)
            assert resolved_p == str(Path(notes_path).resolve())
            assert "Key question answered" in resolved_txt

            with patch("core.uploader.SpeakrClient") as MockClientCls:
                mock_client_inst = MagicMock()
                mock_client_inst.upload_recording.return_value = "rec_789"
                mock_client_inst.replace_recording_notes.return_value = True
                mock_client_inst.add_recording_tags.return_value = True
                MockClientCls.return_value = mock_client_inst

                uploader._process_background(audio_path, [101], audio_path)

                mock_client_inst.upload_recording.assert_called_once()
                call_args, call_kwargs = mock_client_inst.upload_recording.call_args
                assert "Key question answered" in call_kwargs["notes"]
                mock_client_inst.replace_recording_notes.assert_called_with("rec_789", resolved_txt)

            # 3. Test AudioUploader Folder mode copies notes
            cfg.upload_mode = "folder"
            nas_dir = os.path.join(tmpdir, "NAS_Inbox")
            os.makedirs(nas_dir, exist_ok=True)
            cfg.nas_folder_path = nas_dir

            with patch.object(uploader, "_poll_and_tag") as mock_poll:
                uploader._process_background(audio_path, [], audio_path)
                assert mock_poll.called

            copied_audio = os.path.join(nas_dir, "Meeting_2026-09-18.mp4")
            copied_notes = os.path.join(nas_dir, "Meeting_2026-09-18_Notes.md")
            assert os.path.exists(copied_audio)
            assert os.path.exists(copied_notes)
            with open(copied_notes, "r", encoding="utf-8") as f:
                assert "Key question answered" in f.read()

    finally:
        if os.path.exists(temp_audio):
            os.remove(temp_audio)

    print("[OK] Notes Upload and Summarization Linkage passed.")

def test_static_control_bar_and_dashboard_tabs():
    print("Testing Static Control Bar, Copilot Toggle Button, and Dashboard Sub-Tabs...")
    from PySide6.QtWidgets import QApplication
    from core.config import Settings
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from core.storage import RecordingsManager
    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings()
    s.auto_record_enabled = False
    rec = AudioRecorder()
    stor = RecordingsManager(s)
    up = AudioUploader(s, stor)
    w = MainWindow(s, rec, up, stor)
    w.show()

    try:
        # 1. Top Static Control Bar & initial Idle state
        assert hasattr(w, "static_control_frame")
        assert hasattr(w, "copilot_toggle_btn")
        assert "Copilot" in w.copilot_toggle_btn.text()
        assert w.status_label.text() == "STATUS: IDLE"
        assert w.record_btn.isVisible() is True
        assert "Start Recording" in w.record_btn.text()
        assert w.pause_btn.isVisible() is False
        assert w.skip_cooldown_btn.isVisible() is False
        assert w.upload_last_btn.isVisible() is True

        # Test Copilot ON/OFF toggle in static bar
        initial_enabled = w.settings.copilot_enabled
        w.copilot_toggle_btn.click()
        assert w.settings.copilot_enabled == (not initial_enabled)
        w.copilot_toggle_btn.click()
        assert w.settings.copilot_enabled == initial_enabled

        # 2. Dashboard Sub-Tabs
        assert hasattr(w, "dashboard_subtabs")
        assert w.dashboard_subtabs.count() == 2
        assert w.dashboard_subtabs.tabText(0).replace("&&", "&") == "Audio & Session Monitor"
        assert w.dashboard_subtabs.tabText(1) == "Live Meeting Copilot"
        assert w.copilot_widget is not None
        assert w.hud is w.copilot_widget

        # 3. Simulate Recording state
        w.recorder.is_recording = True
        w.recorder.is_paused = False
        w._update_recording_controls_visibility()
        assert "Stop Recording" in w.record_btn.text()
        assert w.pause_btn.isVisible() is True
        assert "Pause" in w.pause_btn.text()
        assert w.upload_last_btn.isVisible() is False
        assert w.skip_cooldown_btn.isVisible() is False

        # 4. Simulate Paused state
        w.recorder.is_paused = True
        w._update_recording_controls_visibility()
        assert "Stop Recording" in w.record_btn.text()
        assert w.pause_btn.isVisible() is True
        assert "Resume" in w.pause_btn.text()
        assert w.upload_last_btn.isVisible() is False

        # 5. Simulate Cooldown state
        w.recorder.is_recording = False
        w.recorder.is_paused = False
        w.cooldown_remaining = 45
        w._update_recording_controls_visibility()
        assert w.record_btn.isEnabled() is False
        assert "Cooldown (45s)" in w.record_btn.text()
        assert w.pause_btn.isVisible() is False
        assert w.skip_cooldown_btn.isVisible() is True
        assert w.upload_last_btn.isVisible() is False

        # 6. Skip Cooldown -> Back to Idle
        w._skip_cooldown()
        assert w.status_label.text() == "STATUS: IDLE"
        assert w.record_btn.isEnabled() is True
        assert "Start Recording" in w.record_btn.text()
        assert w.pause_btn.isVisible() is False
        assert w.skip_cooldown_btn.isVisible() is False
        assert w.upload_last_btn.isVisible() is True

        # 7. Test _toggle_copilot_hud switches tab
        w._toggle_copilot_hud()
        assert w.dashboard_subtabs.currentWidget() == w.copilot_widget

        # 8. Test nested Auto-Upload toggle under Direct API Upload
        assert hasattr(w, "auto_upload_chk")
        assert hasattr(w, "api_nested_widget")
        assert hasattr(w, "folder_nested_widget")
        assert hasattr(w, "monitor_auto_upload_chk")
        
        # In API mode, api_nested_widget is visible and folder_nested_widget is hidden
        w.mode_api_radio.setChecked(True)
        assert not w.api_nested_widget.isHidden()
        assert w.folder_nested_widget.isHidden()
        
        # Toggle auto-upload and verify settings & sync
        w.auto_upload_chk.setChecked(False)
        assert w.settings.auto_upload_enabled is False
        assert w.monitor_auto_upload_chk.isChecked() is False
        
        # Switch to NAS folder mode -> api_nested_widget hides, folder_nested_widget shows
        w.mode_folder_radio.setChecked(True)
        assert w.api_nested_widget.isHidden()
        assert not w.folder_nested_widget.isHidden()
        
        # Switch back to API mode
        w.mode_api_radio.setChecked(True)
        assert not w.api_nested_widget.isHidden()
        assert w.folder_nested_widget.isHidden()
        
        # Toggle auto-upload via monitor checkbox -> syncs back to nested auto_upload_chk
        w.monitor_auto_upload_chk.setChecked(True)
        assert w.settings.auto_upload_enabled is True
        assert w.auto_upload_chk.isChecked() is True
    finally:
        w.close()

    print("[OK] Static Control Bar, Copilot Toggle Button, and Dashboard Sub-Tabs passed.")

test_hud_toggle_visibility_button = test_static_control_bar_and_dashboard_tabs

def test_hud_clear_on_start_and_manual_reset():
    print("Testing HUD Clear on Start Recording & Manual Reset...")
    import tempfile
    from PySide6.QtWidgets import QApplication
    from core.config import Settings
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from core.storage import RecordingsManager
    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings()
    s.auto_record_enabled = False
    s.copilot_enabled = True
    rec = AudioRecorder()
    stor = RecordingsManager(s)
    up = AudioUploader(s, stor)
    w = MainWindow(s, rec, up, stor)

    try:
        w._ensure_copilot_session()
        hud = w.hud
        mem = w.copilot_memory

        # 1. Populate session data
        mem.add_transcript("you", "Let's test the HUD clear flow.", time.time(), 1)
        mem.set_suggested_questions([
            {"question": "Is the rollback ready?", "rationale": "Safety"}
        ])
        mem.set_follow_up_suggestions([
            {"task": "Run healthcheck", "owner": "Chuck"}
        ])
        mem.add_user_note("Chuck confirmed snapshot 1.")
        hud._render_questions()
        hud._render_follow_ups()
        hud._render_notes()
        hud.ticker_box.append("Test transcript line")

        assert hud.questions_list.count() == 1
        assert hud.follow_ups_list.count() == 1
        assert hud.notes_list.count() >= 1
        assert len(hud.ticker_box.toPlainText()) > 0
        assert len(mem.turns) == 1

        # 2. Stop session: content MUST persist for user review!
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            temp_rec = f.name

        try:
            saved_notes = w._stop_copilot_session(temp_rec)
            assert saved_notes is not None
            assert os.path.exists(saved_notes)
            assert hud.questions_list.count() == 1
            assert hud.follow_ups_list.count() == 1
            assert hud.notes_list.count() >= 1
            assert len(hud.ticker_box.toPlainText()) > 0
            assert "Notes Saved" in hud.status_dot.toolTip()
        finally:
            if os.path.exists(temp_rec):
                os.remove(temp_rec)

        # 3. Test Manual Reset button (clears immediately on demand)
        hud.reset_btn.click()
        assert hud.questions_list.count() == 0
        assert hud.follow_ups_list.count() == 0
        assert hud.notes_list.count() == 0
        assert hud.ticker_box.toPlainText() == ""
        assert len(mem.turns) == 0
        assert len(mem.suggested_questions) == 0

        # 4. Re-populate and verify automatic clear on Start Recording
        mem.add_transcript("participants", "New meeting discussion...", time.time(), 2)
        mem.set_suggested_questions([{"question": "Next step?", "rationale": "Action"}])
        mem.add_user_note("Another note.")
        hud._render_questions()
        hud._render_notes()
        hud.ticker_box.append("Second meeting speech")

        assert hud.questions_list.count() == 1
        assert len(hud.ticker_box.toPlainText()) > 0

        # Now start new session -> HUD and memory must be wiped clean!
        w._start_copilot_session()
        assert hud.questions_list.count() == 0
        assert hud.follow_ups_list.count() == 0
        assert hud.notes_list.count() == 0
        assert hud.ticker_box.toPlainText() == ""
        assert len(mem.turns) == 0
        assert len(mem.suggested_questions) == 0
        assert hud.status_dot.toolTip() == "Status: Recording Active"

    finally:
        w._stop_copilot_session()
        w.close()

    print("[OK] HUD Clear on Start Recording & Manual Reset passed.")

def test_fetch_lm_studio_models_function():
    print("Testing fetch_lm_studio_models utility...")
    from unittest.mock import patch, MagicMock
    from core.copilot.agent import fetch_lm_studio_models

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"id": "llama-3.2-3b-instruct"},
            {"id": "qwen2.5-coder-7b-instruct"},
            {"id": "deepseek-r1-distill-qwen-7b"}
        ]
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        models = fetch_lm_studio_models("http://localhost:1234/v1")
        assert len(models) == 3
        assert "llama-3.2-3b-instruct" in models
        assert "qwen2.5-coder-7b-instruct" in models

    # Test error handling
    err_resp = MagicMock()
    err_resp.status_code = 500
    err_resp.text = "Internal Server Error"
    with patch("httpx.Client.get", return_value=err_resp):
        try:
            fetch_lm_studio_models("http://localhost:1234/v1")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "HTTP 500" in str(e)

    print("[OK] fetch_lm_studio_models passed.")

def test_history_icon_buttons_and_model_fetch_ui():
    print("Testing History Table Icon Buttons and LM Studio Model Fetch UI...")
    import tempfile
    from PySide6.QtWidgets import QApplication, QPushButton
    from core.config import Settings
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from core.storage import RecordingsManager
    from gui.main_window import MainWindow
    from unittest.mock import patch, MagicMock

    app = QApplication.instance() or QApplication([])
    s = Settings()
    s.auto_record_enabled = False
    rec = AudioRecorder()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        s.local_recordings_dir = tmpdir
        stor = RecordingsManager(s)
        up = AudioUploader(s, stor)

        # Create dummy audio recording & notes sidecar
        dummy_audio = os.path.join(tmpdir, "Meeting_2026-10-05_Test.mp4")
        dummy_notes = os.path.join(tmpdir, "Meeting_2026-10-05_Test_Notes.md")
        with open(dummy_audio, "wb") as f:
            f.write(b"RIFF dummy audio data")
        with open(dummy_notes, "w", encoding="utf-8") as f:
            f.write("# Notes for testing")

        stor.add_recording(dummy_audio, "manual", 120.0, [1, 2], status="Local Only", notes_path=dummy_notes)

        w = MainWindow(s, rec, up, stor)
        try:
            w._refresh_history_table()
            assert w.history_table.rowCount() >= 1
            action_widget = w.history_table.cellWidget(0, 6)
            assert action_widget is not None

            buttons = action_widget.findChildren(QPushButton)
            btn_texts = [b.text() for b in buttons]
            assert "📝" in btn_texts, "Notes icon button must be present"
            assert "▶️" in btn_texts, "Play icon button must be present"
            assert "☁️" in btn_texts, "Re-Upload icon button must be present"
            assert "📁" in btn_texts, "Reveal in Explorer icon button must be present"
            assert "🗑️" in btn_texts, "Delete icon button must be present"

            for b in buttons:
                assert len(b.toolTip()) > 0, f"Button {b.text()} must have a tooltip"

            assert hasattr(w, "llm_model_combo")
            assert hasattr(w, "fetch_models_btn")
            assert hasattr(w, "lm_studio_bypass_auth_chk")
            assert hasattr(w, "lm_studio_key_input")
            assert w.llm_model_combo.isEditable() is True

            w.lm_studio_bypass_auth_chk.setChecked(True)
            assert w.lm_studio_key_input.isEnabled() is False
            w.lm_studio_bypass_auth_chk.setChecked(False)
            assert w.lm_studio_key_input.isEnabled() is True
            w.lm_studio_key_input.setText("secret-auth-token")
            assert w.settings.lm_studio_api_key == "secret-auth-token"
            assert w.settings.lm_studio_bypass_auth is False

            mock_models = ["model-alpha", "model-beta"]
            with patch("gui.main_window.fetch_lm_studio_models", return_value=mock_models) as mock_fetch:
                w.fetch_models_btn.click()
                time.sleep(0.1)
                QApplication.processEvents()
                assert mock_fetch.called
                _, kwargs = mock_fetch.call_args
                assert kwargs.get("api_key") == "secret-auth-token"

        finally:
            w.close()

    print("[OK] History Table Icon Buttons & Model Fetch UI passed.")


def test_light_and_dark_theme_system():
    """Verifies color tokens, stylesheet generation, VolumeMeter channels, and dynamic theme switching."""
    print("Testing Light & Dark Theme System and Palettes...")
    import tempfile
    from PySide6.QtWidgets import QApplication
    from core.config import Settings
    from core.storage import RecordingsManager
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from gui.main_window import MainWindow
    from gui.theme import get_theme_palette, get_theme_stylesheet, DARK_PALETTE, LIGHT_PALETTE
    from gui.widgets import VolumeMeter, TagSelector
    
    # 1. Palette tokens
    dark_p = get_theme_palette("dark")
    light_p = get_theme_palette("light")
    assert dark_p["accent_cyan"] == "#22d3ee"
    assert dark_p["accent_purple"] == "#c084fc"
    assert light_p["accent_cyan"] == "#0284c7"
    assert light_p["accent_purple"] == "#7c3aed"
    assert dark_p["bg_window"] == "#0e1015"
    assert light_p["bg_window"] == "#f8fafc"
    
    # 2. Stylesheet generation
    dark_qss = get_theme_stylesheet("dark")
    light_qss = get_theme_stylesheet("light")
    assert "#0e1015" in dark_qss
    assert "#22d3ee" in dark_qss
    assert "#f8fafc" in light_qss
    assert "#0284c7" in light_qss
    
    # 3. Widget theme switching
    app = QApplication.instance() or QApplication([])
    mic_meter = VolumeMeter("Microphone", channel_type="mic", theme="dark")
    spk_meter = VolumeMeter("Speakers", channel_type="system", theme="dark")
    tag_sel = TagSelector(theme="dark")
    
    assert mic_meter.channel_type == "mic"
    assert spk_meter.channel_type == "system"
    assert mic_meter.theme == "dark"
    
    mic_meter.set_theme("light")
    spk_meter.set_theme("light")
    tag_sel.set_theme("light")
    assert mic_meter.theme == "light"
    assert spk_meter.theme == "light"
    assert tag_sel.theme == "light"
    
    # 4. MainWindow dynamic theme toggle
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        cfg = Settings()
        cfg.settings_file = Path(tmpdir) / "settings.json"
        cfg.data = dict(Settings.DEFAULT_SETTINGS)
        cfg.data["local_recordings_dir"] = tmpdir
        cfg.data["auto_record_enabled"] = False
        cfg.theme = "dark"
        
        storage = RecordingsManager(cfg)
        rec = AudioRecorder()
        upl = AudioUploader(cfg, storage)
        w = MainWindow(cfg, rec, upl, storage)
        
        try:
            assert w.settings.theme == "dark"
            assert "Dark" in w.theme_toggle_btn.text()
            
            # Click quick theme toggle
            w.theme_toggle_btn.click()
            assert w.settings.theme == "light"
            assert "Light" in w.theme_toggle_btn.text()
            assert w.mic_meter.theme == "light"
            assert w.hud.theme == "light"
            
            # Click toggle again back to dark
            w.theme_toggle_btn.click()
            assert w.settings.theme == "dark"
            assert "Dark" in w.theme_toggle_btn.text()
            assert w.mic_meter.theme == "dark"
            assert w.hud.theme == "dark"
        finally:
            w.close()

    print("[OK] Light & Dark Theme System passed.")


def test_open_speakr_web_instance_button():
    """Verifies the Open Speakr button in top static bar correctly parses server URL and invokes browser."""
    print("Testing Open Speakr Web Instance Button...")
    import tempfile
    from unittest.mock import patch
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication
    from core.config import Settings
    from core.storage import RecordingsManager
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        cfg = Settings()
        cfg.settings_file = Path(tmpdir) / "settings.json"
        cfg.data = dict(Settings.DEFAULT_SETTINGS)
        cfg.data["local_recordings_dir"] = tmpdir
        cfg.data["auto_record_enabled"] = False
        cfg.data["servers"] = [
            {"name": "Local Speakr", "url": "http://192.168.0.88:8899/api/v1", "api_key": "key123"},
            {"name": "Cloud Speakr", "url": "https://speakr.example.com", "api_key": "cloud123"}
        ]
        cfg.data["active_server_idx"] = 0
        
        storage = RecordingsManager(cfg)
        rec = AudioRecorder()
        upl = AudioUploader(cfg, storage)
        w = MainWindow(cfg, rec, upl, storage)
        
        try:
            assert hasattr(w, "open_web_btn")
            assert "Open Speakr" in w.open_web_btn.text()
            assert "192.168.0.88:8899" in w.open_web_btn.toolTip()
            
            with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
                w.open_web_btn.click()
                assert mock_open.called
                opened_qurl = mock_open.call_args[0][0]
                assert opened_qurl.toString() == "http://192.168.0.88:8899"
                
            # Switch to cloud server
            w._server_selection_changed(1)
            assert "speakr.example.com" in w.open_web_btn.toolTip()
            
            with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
                w._open_speakr_web_instance()
                assert mock_open.called
                opened_qurl = mock_open.call_args[0][0]
                assert opened_qurl.toString() == "https://speakr.example.com"
        finally:
            w.close()
    print("[OK] Open Speakr Web Instance Button passed.")


def test_noise_filtering_and_topic_cards():
    """Verifies that casual conversational banter and filler quotes are filtered out, and topics are structured."""
    print("Testing Noise Filtering and Structured Topic Cards...")
    from core.copilot.agent import OfflineExtractiveEngine
    from core.copilot.memory import CopilotMemory

    engine = OfflineExtractiveEngine()
    mem = CopilotMemory()

    # Mix technical engineering dialogue with the exact casual filler from trans.md
    mem.add_transcript("participants", "I mean, it didn't hurt.", time.time(), 1)
    mem.add_transcript("participants", "I like it, but I mean, dude, we could never do that here.", time.time(), 2)
    mem.add_transcript("participants", "We tested the thin provisioning script on BCP storage clusters yesterday.", time.time(), 3)
    mem.add_transcript("participants", "Surprisingly, it was Milwaukee and I was not looking forward to going to Milwaukee at all.", time.time(), 4)
    mem.add_transcript("participants", "I may have drink a few liters, it's about the boot dude.", time.time(), 5)
    mem.add_transcript("you", "We confirmed each VM conversion takes approximately fifteen minutes.", time.time(), 6)
    mem.add_transcript("participants", "I was going to assign him that Jira story for storage vMotion.", time.time(), 7)
    mem.add_transcript("participants", "We'll see you in the next video.", time.time(), 8)
    mem.add_transcript("participants", "Casey was the one that convinced me to cancel it.", time.time(), 9)

    res = engine.generate_periodic(mem.turns, [])
    rolling = res["rolling_summary"]

    # 1. Verify structured topics are generated
    assert "topics" in rolling
    assert len(rolling["topics"]) > 0
    top = rolling["topics"][0]
    assert "title" in top
    assert "summary" in top
    assert "Storage & VDI Infrastructure" in [t["title"] for t in rolling["topics"]] or "Technical" in [t["title"] for t in rolling["topics"]]

    # 2. Verify all noise is strictly excluded from topics, summary_bullets, and follow-ups
    combined_summary_text = " ".join(rolling.get("summary_bullets", [])) + " " + rolling.get("executive_summary", "")
    for t in rolling.get("topics", []):
        combined_summary_text += " " + t.get("summary", "") + " " + " ".join(t.get("key_points", []))

    follow_up_tasks = [item["task"] for item in res.get("follow_up_suggestions", [])]

    banned_phrases = [
        "milwaukee", "drink a few liters", "boot dude", "next video",
        "could never do that here", "dude, we could never", "it didn't hurt"
    ]
    for banned in banned_phrases:
        assert banned not in combined_summary_text.lower(), f"Banned noise '{banned}' leaked into summary!"
        for task in follow_up_tasks:
            assert banned not in task.lower(), f"Banned noise '{banned}' leaked into follow-up task: {task}!"

    # 3. Valid technical deliverable (Jira story) should be captured
    assert any("jira" in task.lower() or "story" in task.lower() for task in follow_up_tasks)
    print("[OK] Noise filtering and structured topic cards passed.")


def test_dynamic_topic_derivation_and_no_vdi_bias():
    """Verifies that everyday conversation with 'think', 'thousands', 'something' does NOT produce false VDI/Storage topics."""
    print("Testing Dynamic Topic Derivation & Absence of False VDI/Storage Bias...")
    from core.copilot.agent import OfflineExtractiveEngine
    from core.copilot.memory import CopilotMemory

    engine = OfflineExtractiveEngine()

    # Case 1: Sprint planning and checkout roadmap (contains words: 'think', 'thousands', 'something', 'within')
    mem1 = CopilotMemory()
    mem1.add_transcript("you", "I think we should align on the sprint roadmap and milestone schedule for Q4.", time.time(), 1)
    mem1.add_transcript("participants", "We have thousands of users waiting for the new checkout page design.", time.time(), 2)
    mem1.add_transcript("participants", "The team agreed that the payment gateway integration will be finalized by Friday.", time.time(), 3)
    mem1.add_transcript("you", "Within this sprint, something needs to be delivered for the mobile checkout flow.", time.time(), 4)

    res1 = engine.generate_periodic(mem1.turns, [])
    rolling1 = res1["rolling_summary"]
    topics1 = [t["title"] for t in rolling1.get("topics", [])]
    summary_text1 = " ".join(rolling1.get("summary_bullets", [])) + " " + rolling1.get("executive_summary", "")

    # Storage & VDI must NOT appear in titles or summary
    for t_title in topics1:
        assert "storage & vdi" not in t_title.lower(), f"Unexpected VDI bias in topic title: {t_title}"
    assert "storage & vdi" not in summary_text1.lower(), f"Unexpected VDI bias in summary text: {summary_text1}"

    # Must contain dynamic topic matching sprint/roadmap/checkout/payment
    assert any(
        any(k in t.lower() for k in ["sprint", "roadmap", "checkout", "payment", "milestone", "product"])
        for t in topics1
    ), f"Expected dynamic sprint/roadmap topic, got: {topics1}"

    # Case 2: Budget and licensing
    mem2 = CopilotMemory()
    mem2.add_transcript("you", "We need to review the quarterly budget allocation and vendor licensing contract.", time.time(), 1)
    mem2.add_transcript("participants", "The committee approved thirty thousand dollars for software procurement.", time.time(), 2)
    res2 = engine.generate_periodic(mem2.turns, [])
    rolling2 = res2["rolling_summary"]
    topics2 = [t["title"] for t in rolling2.get("topics", [])]

    for t_title in topics2:
        assert "storage & vdi" not in t_title.lower(), f"Unexpected VDI bias in budget meeting: {t_title}"
    assert any(
        any(k in t.lower() for k in ["budget", "licensing", "procurement", "finance", "contract", "vendor"])
        for t in topics2
    ), f"Expected dynamic budget/procurement topic, got: {topics2}"

    # Case 3: Verify CopilotMemory doesn't merge distinct topics due to common single-word substring
    mem3 = CopilotMemory()
    mem3.set_rolling_summary({
        "topics": [
            {"title": "Frontend Architecture Review", "summary": "Discussed client React performance.", "status": "in_progress"},
            {"title": "Backend Architecture Review", "summary": "Discussed server gRPC endpoints.", "status": "in_progress"}
        ]
    })
    stored_titles = [t["title"] for t in mem3.rolling_summary["topics"]]
    assert len(stored_titles) == 2, f"Distinct topics collapsed unexpectedly: {stored_titles}"
    assert "Frontend Architecture Review" in stored_titles
    assert "Backend Architecture Review" in stored_titles

    print("[OK] Dynamic Topic Derivation & No VDI Bias passed.")


def test_reasoning_engine_healthcheck_and_badge():
    """Verifies agent check_health() and HUD reasoning engine badge and status dot."""
    print("Testing Reasoning Engine Healthcheck and Status Badge...")
    from PySide6.QtWidgets import QApplication
    from core.copilot.memory import CopilotMemory
    from core.copilot.agent import CopilotAgent
    from gui.hud import CopilotDashboardWidget

    app = QApplication.instance() or QApplication([])
    mem = CopilotMemory()
    agent = CopilotAgent(mem, on_results_callback=lambda r: None)

    # 1. Offline healthcheck
    agent.configure(provider="offline")
    h_offline = agent.check_health()
    assert h_offline["ok"] is True
    assert h_offline["status"] == "offline"
    assert "Offline extractive" in h_offline["message"]

    # 2. Unconfigured cloud healthcheck
    agent.configure(provider="openrouter", api_key="")
    h_unconf = agent.check_health()
    assert h_unconf["ok"] is False
    assert h_unconf["status"] == "unconfigured"

    # 3. HUD widgets presence & update
    hud = CopilotDashboardWidget(mem, agent)
    try:
        assert hasattr(hud, "engine_badge")
        assert hasattr(hud, "engine_status_lbl")
        assert hasattr(hud, "healthcheck_btn")

        hud.update_engine_status({
            "provider": "lm_studio",
            "model": "qwen2.5-coder",
            "status": "online",
            "latency_ms": 42.0
        })
        assert "LM Studio" in hud.engine_badge.text()
        assert "qwen2.5-coder" in hud.engine_badge.text()
        assert "Online" in hud.engine_status_lbl.text()
        assert "42ms" in hud.engine_status_lbl.text()
    finally:
        hud.close()

    print("[OK] Reasoning Engine Healthcheck and Status Badge passed.")


def test_configurable_quick_action_prompts():
    """Verifies that configurable prompts can be retrieved, edited, saved, and reset."""
    print("Testing Configurable Quick Action Prompts...")
    import tempfile
    from core.config import Settings
    from core.copilot.memory import CopilotMemory
    from core.copilot.agent import CopilotAgent

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        cfg = Settings()
        cfg.settings_file = Path(tmpdir) / "settings.json"
        cfg.data = dict(Settings.DEFAULT_SETTINGS)
        cfg.data["auto_record_enabled"] = False

        # Check default prompt retrieval
        prompt1 = cfg.get_quick_action_instruction("what_to_ask")
        assert "Principal Systems Architect" in prompt1

        # Customize prompt
        custom_instructions = dict(cfg.quick_action_prompts)
        custom_instructions["what_to_ask"] = "Focus specifically on Kubernetes pod security policies and Cilium CNI."
        cfg.quick_action_prompts = custom_instructions
        cfg.save()

        # Reload from disk
        cfg2 = Settings()
        cfg2.settings_file = cfg.settings_file
        cfg2.load()
        assert cfg2.get_quick_action_instruction("what_to_ask") == "Focus specifically on Kubernetes pod security policies and Cilium CNI."

        # Reset to defaults
        cfg2.reset_quick_action_prompts()
        assert "Principal Systems Architect" in cfg2.get_quick_action_instruction("what_to_ask")

        # Test agent execution with custom prompt parameter
        mem = CopilotMemory()
        mem.add_transcript("participants", "We are debugging the Cilium CNI network policies.", time.time(), 1)
        results = []
        agent = CopilotAgent(mem, on_results_callback=lambda r: results.append(r))
        agent.run_quick_prompt("what_to_ask", custom_instruction="Identify Cilium CNI network drop reasons.")
        time.sleep(0.3)
        assert len(results) > 0
        assert results[0]["type"] == "quick_action"

        # Test GUI layout: Dedicated Copilot Prompts subtab, scroll areas, and button navigation
        from PySide6.QtWidgets import QApplication
        from core.storage import RecordingsManager
        from core.recorder import AudioRecorder
        from core.uploader import AudioUploader
        from gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        storage = RecordingsManager(cfg)
        rec = AudioRecorder()
        upl = AudioUploader(cfg, storage)
        win = MainWindow(cfg, rec, upl, storage)
        try:
            assert hasattr(win, "tab_copilot_scroll")
            assert hasattr(win, "tab_prompts_scroll")
            assert hasattr(win, "open_prompts_tab_btn")
            assert hasattr(win, "prompt_inputs")
            assert len(win.prompt_inputs) == 5

            # Test navigation from button to Prompts subtab
            win.open_prompts_tab_btn.click()
            assert win.pref_subtabs.currentWidget() == win.tab_prompts_scroll

            # Test prompt inputs editing and save via UI
            win.prompt_inputs["what_to_ask"].setPlainText("Customized via UI test.")
            win._save_quick_action_prompts_clicked()
            assert win.settings.get_quick_action_instruction("what_to_ask") == "Customized via UI test."

            # Test reset via UI
            win._reset_quick_action_prompts_clicked()
            assert "Principal Systems Architect" in win.settings.get_quick_action_instruction("what_to_ask")

            # Test HUD gear button navigation to prompts tab
            win._ensure_copilot_session()
            assert hasattr(win.hud, "btn_cfg_prompts")
            win.hud.btn_cfg_prompts.click()
            assert win.tabs.currentWidget() == win.preferences_tab
            assert win.pref_subtabs.currentWidget() == win.tab_prompts_scroll
        finally:
            win.close()

    print("[OK] Configurable Quick Action Prompts passed.")


def test_rolling_summary_prompt_and_popout():
    print("Testing Rolling Summary Prompt Configuration and Pop-out Window...")
    from core.config import Settings, DEFAULT_ROLLING_SUMMARY_PROMPT
    import tempfile
    from PySide6.QtWidgets import QApplication
    from core.storage import RecordingsManager
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from gui.main_window import MainWindow

    # 1. Config tests
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings_file = Path(tmp_dir) / "settings.json"
        s = Settings(settings_file=settings_file)
        s.save()
        assert s.get_rolling_summary_instruction() == DEFAULT_ROLLING_SUMMARY_PROMPT

        # Customization and save
        custom_instr = "Focus strictly on root-cause failure analysis and deployment timeline."
        s.rolling_summary_prompt = custom_instr
        s.save()

        # Reload
        s2 = Settings(settings_file=settings_file)
        s2.load()
        assert s2.rolling_summary_prompt == custom_instr
        assert s2.get_rolling_summary_instruction() == custom_instr

        # Prompt formatting verification
        prompt_text = get_periodic_prompt(tag_name="Tech Review", custom_summary_instruction=custom_instr)
        assert "USER-SPECIFIED ROLLING SUMMARY INSTRUCTION" in prompt_text
        assert custom_instr in prompt_text

        # Reset
        s2.reset_rolling_summary_prompt()
        assert s2.rolling_summary_prompt == DEFAULT_ROLLING_SUMMARY_PROMPT

    # 2. UI and Pop-out tests
    app = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings_file = Path(tmp_dir) / "settings.json"
        s = Settings(settings_file=settings_file)
        s.data["auto_record_enabled"] = False
        s.save()
        storage = RecordingsManager(s)
        rec = AudioRecorder()
        upl = AudioUploader(s, storage)
        win = MainWindow(s, rec, upl, storage)
        try:
            win.show()
            # Verify UI input element exists in Prompts tab
            assert hasattr(win, "summary_prompt_input")
            assert DEFAULT_ROLLING_SUMMARY_PROMPT in win.summary_prompt_input.toPlainText()

            # Verify editing & saving via UI
            test_prompt = "Keep summaries under 3 sentences focusing on Kubernetes microservices."
            win.summary_prompt_input.setPlainText(test_prompt)
            win._save_quick_action_prompts_clicked()
            assert win.settings.rolling_summary_prompt == test_prompt

            # Verify reset via UI
            win._reset_quick_action_prompts_clicked()
            assert win.settings.rolling_summary_prompt == DEFAULT_ROLLING_SUMMARY_PROMPT
            assert DEFAULT_ROLLING_SUMMARY_PROMPT in win.summary_prompt_input.toPlainText()

            # Ensure HUD session initialized
            win._ensure_copilot_session()
            hud = win.hud
            assert hud is not None
            assert hasattr(hud, "popout_summary_btn")
            assert hasattr(hud, "summary_popped_placeholder")
            assert hud.is_summary_popped_out is False
            assert hud.summary_popped_placeholder.isHidden()

            # Trigger pop out
            hud.popout_summary_btn.click()
            assert hud.is_summary_popped_out is True
            assert hud.popout_dialog is not None
            assert not hud.summary_popped_placeholder.isHidden()
            assert "popped out in an external window" in hud.placeholder_label.text()

            # Trigger dock in via dialog dock button
            hud.popout_dialog.dock_btn.click()
            assert hud.is_summary_popped_out is False
            assert hud.summary_popped_placeholder.isHidden()

            # Trigger pop out again, then dock in via placeholder dock button
            hud.popout_summary_btn.click()
            assert hud.is_summary_popped_out is True
            hud.placeholder_dock_btn.click()
            assert hud.is_summary_popped_out is False
            assert hud.summary_popped_placeholder.isHidden()

        finally:
            win.close()


def test_gui_makeover_components():
    """Verifies VerticalSidebar, RecordView 2-column workstation, and ServerMeetingsView."""
    print("Testing GUI Makeover Components (Sidebar, RecordView Workstation, ServerMeetingsView)...")
    from PySide6.QtWidgets import QApplication
    from gui.sidebar import VerticalSidebar
    from gui.record_view import RecordView
    from gui.meetings_view import ServerMeetingsView
    from core.copilot.memory import CopilotMemory
    from core.copilot.agent import CopilotAgent
    from core.config import Settings

    app = QApplication.instance() or QApplication([])

    # 1. VerticalSidebar
    sidebar = VerticalSidebar(theme="dark")
    nav_events = []
    sidebar.page_changed.connect(lambda p: nav_events.append(p))

    assert "record" in sidebar.nav_buttons
    assert "meetings" in sidebar.nav_buttons
    assert "history" in sidebar.nav_buttons

    sidebar.nav_buttons["meetings"].click()
    assert len(nav_events) == 1
    assert nav_events[-1] == "meetings"
    assert sidebar.current_page == "meetings"

    sidebar.update_history_badge(7)
    assert sidebar.history_badge.text() == "7"
    assert not sidebar.history_badge.isHidden()
    sidebar.close()

    # 2. RecordView Workstation
    mem = CopilotMemory()
    agent = CopilotAgent(mem, on_results_callback=lambda r: None)
    record_view = RecordView(mem, agent, theme="dark")
    try:
        # Check meeting name input
        assert hasattr(record_view, "meeting_name_input")
        record_view.meeting_name_input.setText("Cloud Migration Review")
        assert record_view.get_meeting_title() == "Cloud Migration Review"

        # Check tag selector auto-population
        tags = [
            {"id": 1, "name": "Cloud Infra", "color": "#38bdf8"},
            {"id": 2, "name": "Security Audit", "color": "#f87171"}
        ]
        record_view.populate_tags(tags)
        assert record_view.tag_combo.count() == 3  # (No Tag) + 2 tags
        assert "Cloud Infra" in record_view.tag_combo.itemText(1)
        assert record_view.tag_combo.itemData(1) == 1
        record_view.tag_combo.setCurrentIndex(1)
        assert record_view.get_selected_tag() == "Cloud Infra"
        assert record_view.get_selected_tag_id() == 1

        # Check Open Notes markdown editor & auto-sync to CopilotMemory
        assert hasattr(record_view, "notes_editor")
        test_notes = "## Deployment Plan\n- Roll out cluster canary pods\n- Monitor Datadog latency metric"
        record_view.notes_editor.setPlainText(test_notes)
        record_view._sync_notes_to_memory()  # Flush sync immediately
        assert mem.get_notes_markdown() == test_notes
        prompt_ctx = mem.get_prompt_context()
        assert "Deployment Plan" in prompt_ctx
        assert "cluster canary pods" in prompt_ctx

        # Check markdown formatting tools
        record_view.notes_editor.selectAll()
        record_view._wrap_selection("**", "**")
        assert "**" in record_view.notes_editor.toPlainText()

        # Check Right Column Tabbed Section
        assert hasattr(record_view, "right_tabs")
        assert record_view.right_tabs.count() == 4
        tab_names = [record_view.right_tabs.tabText(i) for i in range(4)]
        assert any("Chat" in t for t in tab_names)
        assert any("Live Q&A" in t for t in tab_names)
        assert any("Summary" in t for t in tab_names)
        assert any("Transcript" in t for t in tab_names)

        # Check Quick Action triggers in Summary tab
        assert hasattr(record_view, "btn_catch_up")
        assert hasattr(record_view, "btn_action_items")
        assert hasattr(record_view, "btn_risks")
        assert hasattr(record_view, "btn_jargon")

        # Test Markdown formatting in Summary tab
        record_view._on_quick_action_gui("Catch Up", "### Key Highlights\n- Point A\n- Point B\n\n**Decision**: Verified.")
        assert "Key Highlights" in record_view.quick_action_browser.toPlainText()
        assert "Point A" in record_view.quick_action_browser.toPlainText()
        assert "Decision: Verified" in record_view.quick_action_browser.toPlainText() or "Verified" in record_view.quick_action_browser.toPlainText()

        # Test Settings synchronization
        test_settings = Settings()
        test_settings.meeting_mode = "in_person"
        test_settings.asr_provider = "mac_lan"
        record_view.sync_settings_state(test_settings)
        assert record_view.mode_combo.currentData() == "in_person"
        assert record_view.asr_combo.currentData() == "mac_lan"
    finally:
        record_view.close()

    # 3. ServerMeetingsView
    cfg = Settings()
    meetings_view = ServerMeetingsView(settings=cfg, client=None, theme="dark")
    try:
        sample_meetings = [
            {"id": 101, "title": "SAN Storage Cutover", "timestamp": "2026-10-12T10:00:00", "summary": "Storage migration completed."},
            {"id": 102, "title": "API Gateway Refactor", "timestamp": "2026-10-12T11:00:00", "summary": "Kong ingress routes configured."}
        ]
        meetings_view._on_meetings_loaded(sample_meetings)
        assert meetings_view.meetings_list.count() == 2

        # Test search filtering
        meetings_view.search_input.setText("SAN")
        visible_items = [
            meetings_view.meetings_list.item(i) 
            for i in range(meetings_view.meetings_list.count()) 
            if not meetings_view.meetings_list.item(i).isHidden()
        ]
        assert len(visible_items) == 1

        # Clear search
        meetings_view.search_input.setText("")

        # Select meeting and inspect detail view
        meetings_view.meetings_list.setCurrentRow(0)
        assert meetings_view.selected_meeting is not None
        assert "SAN Storage Cutover" in meetings_view.detail_title_lbl.text()
        assert "Storage migration completed." in meetings_view.summary_browser.toPlainText()

        # Test details_loaded signal and markdown with notes + transcription
        detailed_payload = {
            "id": 101,
            "title": "SAN Storage Cutover",
            "summary": "Full SAN Migration Summary",
            "notes": "Action items: reboot switch A",
            "transcription": [
                {"speaker": "Alice", "text": "Starting fiber channel switch.", "start": 12.0},
                {"speaker": "Bob", "text": "Confirmed failover path.", "start": 25.5}
            ],
            "audio_duration": 185.0,
            "participants": "Alice, Bob, Charlie"
        }
        meetings_view.details_loaded.emit("101", detailed_payload)
        assert "Full SAN Migration Summary" in meetings_view.summary_browser.toPlainText()
        assert "Attached Notes" in meetings_view.summary_browser.toPlainText()
        assert "Action items: reboot switch A" in meetings_view.summary_browser.toPlainText()
        assert "Alice: Starting fiber channel switch." in meetings_view.transcript_browser.toPlainText()
        assert "Bob: Confirmed failover path." in meetings_view.transcript_browser.toPlainText()
        assert "Duration: 3m 5s" in meetings_view.detail_meta_sub.text()
        assert "Alice, Bob, Charlie" in meetings_view.detail_meta_sub.text()
    finally:
        meetings_view.close()

    print("[OK] GUI Makeover Components passed.")


def test_meeting_title_renaming_and_tag_persistence():
    print("Testing Meeting Title Renaming and Integer Tag Persistence on Upload...")
    from unittest.mock import MagicMock, patch
    from core.client import SpeakrClient
    from core.config import Settings
    from core.uploader import AudioUploader
    from core.storage import RecordingsManager
    from gui.record_view import RecordView
    from core.copilot.memory import CopilotMemory

    # 1. Test SpeakrClient.update_recording
    client = SpeakrClient("http://localhost:8899")
    with patch("httpx.Client") as mock_httpx:
        mock_ctx = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_ctx.patch.return_value = mock_resp
        mock_httpx.return_value.__enter__.return_value = mock_ctx

        res = client.update_recording("rec_123", title="Sprint Architecture Review")
        assert res is True
        mock_ctx.patch.assert_called_once()
        patch_url, patch_kwargs = mock_ctx.patch.call_args
        assert patch_kwargs["json"] == {"title": "Sprint Architecture Review"}

    # 2. Test RecordView tag combo stores int IDs and returns get_selected_tag_id()
    mem = CopilotMemory()
    rv = RecordView(mem, None)
    try:
        sample_tags = [
            {"id": 42, "name": "Sprint Review", "color": "#10b981"},
            {"id": 99, "name": "Architecture", "color": "#6366f1"}
        ]
        rv.populate_tags(sample_tags)
        assert rv.tag_combo.count() == 3  # "No Tag" + 2 tags

        # Select second tag (id 42)
        rv.tag_combo.setCurrentIndex(1)
        assert rv.get_selected_tag_id() == 42
        assert rv.get_selected_tag() == "Sprint Review"

        # Select third tag (id 99)
        rv.tag_combo.setCurrentIndex(2)
        assert rv.get_selected_tag_id() == 99
        assert rv.get_selected_tag() == "Architecture"

        # Select No Tag
        rv.tag_combo.setCurrentIndex(0)
        assert rv.get_selected_tag_id() is None
        assert rv.get_selected_tag() is None
    finally:
        rv.close()

    # 3. Test AudioUploader processes custom_title and sanitizes string/int tags
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Settings()
        cfg.settings_dir = Path(tmpdir)
        cfg.recordings_dir = Path(tmpdir)
        cfg.upload_mode = "api"
        cfg.servers = [{"name": "Test Server", "url": "http://localhost:8899", "api_key": "sec_key"}]
        cfg.active_server_index = 0

        storage = RecordingsManager(cfg)
        audio_file = os.path.join(tmpdir, "Meeting_2026-10-13_120000_Manual.mp4")
        with open(audio_file, "wb") as f:
            f.write(b"dummy audio")

        uploader = AudioUploader(cfg, storage=storage)

        storage.add_recording(
            file_path=audio_file,
            trigger="manual",
            duration_seconds=45.0,
            tag_ids=[42],
            custom_title="Quarterly SAN Roadmap"
        )

        with patch("core.uploader.SpeakrClient") as MockClientCls:
            mock_client = MagicMock()
            mock_client.upload_recording.return_value = "rec_555"
            mock_client.update_recording.return_value = True
            mock_client.add_recording_tags.return_value = True
            MockClientCls.return_value = mock_client

            # Pass mixed string and int tags to verify sanitization
            uploader.process_file(
                audio_file, 
                tag_ids=[42, "99", "invalid", None], 
                custom_title="Quarterly SAN Roadmap"
            )

            # Wait briefly for daemon thread execution
            time.sleep(0.5)

            # Verify upload_recording called with custom title
            mock_client.upload_recording.assert_called_once()
            _, up_kwargs = mock_client.upload_recording.call_args
            assert up_kwargs["title"] == "Quarterly SAN Roadmap"

            # Verify explicit update_recording called on Speakr API to ensure title persists
            mock_client.update_recording.assert_called_with("rec_555", title="Quarterly SAN Roadmap")

            # Verify tags were sanitized to clean integer IDs [42, 99]
            mock_client.add_recording_tags.assert_called_with("rec_555", [42, 99])

        # Verify storage stored custom_title
        saved = storage.get_recording(audio_file)
        assert saved is not None
        assert saved.get("status") == "Uploaded"
        assert saved.get("server_id") == "rec_555"
        assert saved.get("custom_title") == "Quarterly SAN Roadmap"

    print("[OK] Meeting Title Renaming and Integer Tag Persistence passed.")


def test_dynamic_keyphrase_extraction_and_title_tag_reset():
    print("Testing Dynamic Keyphrase Extraction, Corpus Mining, and Title/Tag Reset...")
    from core.copilot.agent import OfflineExtractiveEngine, CopilotAgent
    from core.copilot.corpus import DynamicDomainCorpus
    from core.copilot.memory import CopilotMemory
    from gui.record_view import RecordView
    from gui.widgets import TagSelector
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    # 1. Test live dynamic entity & acronym extraction
    dialogue = (
        "We configured the Intune application packaging pipeline with PSADT, MSI wrappers, "
        "and custom registry entries set by Group Policy for W365 and Autopilot."
    )
    ents = OfflineExtractiveEngine.extract_dynamic_entities(dialogue)
    assert any("PSADT" in e for e in ents), f"Expected PSADT in {ents}"
    assert any("MSI" in e for e in ents), f"Expected MSI in {ents}"
    assert any("W365" in e for e in ents), f"Expected W365 in {ents}"
    assert any("Intune" in e or "Packaging" in e for e in ents), f"Expected packaging/intune in {ents}"

    # 2. Test DynamicDomainCorpus note mining
    corpus = DynamicDomainCorpus.get_instance()
    sample_md = """
    CURRENT AGENDA: Microsoft Graph & Autopilot Deployment
    ### 🔹 Intune Application Packaging (Win32 & PSADT)
    - Confirmed RBAC delegated permissions
    - Fixed GPO registry key overrides
    """
    corpus._extract_terms_from_markdown(sample_md)
    assert corpus.is_known_domain_term("rbac") is True
    assert corpus.is_known_domain_term("gpo") is True
    assert corpus.is_known_domain_term("autopilot") is True

    # 3. Test dynamic clustering and topic synthesis on packaging dialogue
    mem = CopilotMemory()
    mem.add_transcript("participants", "Some packages rely on registry entries set by group policy to detect workstation type.", time.time(), 1)
    mem.add_transcript("participants", "This avoids the need to repackage applications with environment variables.", time.time(), 2)
    mem.add_transcript("you", "We agreed to explore injecting registry-based detection logic into existing packages.", time.time(), 3)
    mem.add_transcript("participants", "The Oracle package requires full re-creation due to VBScript and .NET version incompatibility.", time.time(), 4)

    engine = OfflineExtractiveEngine()
    res = engine.generate_periodic(mem.turns, [])
    rolling = res["rolling_summary"]
    topics = rolling.get("topics", [])
    assert len(topics) > 0
    # Topics should capture packaging or registry detection
    topic_titles = [t["title"] for t in topics]
    assert any("Packaging" in t or "Registry" in t or "Detection" in t or "Policy" in t for t in topic_titles), f"Expected dynamic packaging/registry topic in {topic_titles}"

    # Suggested questions should cite extracted entities (e.g. Oracle, Registry, or Packaging)
    q_texts = [q["question"] for q in res.get("suggested_questions", [])]
    assert any("Oracle" in q or "Registry" in q or "Detection" in q or "Package" in q or "Policy" in q for q in q_texts), f"Expected entity citations in questions: {q_texts}"

    # 4. Test RecordView meeting title and tag reset
    agent = CopilotAgent(mem, lambda r: None)
    rv = RecordView(mem, agent)
    rv.populate_tags([{"id": 101, "name": "Architecture"}, {"id": 102, "name": "Packaging"}])
    rv.tag_combo.setCurrentIndex(2)  # Select Packaging
    rv.set_meeting_title("Custom Pilot Review")
    assert rv.get_meeting_title() == "Custom Pilot Review"
    assert rv.get_selected_tag() == "Packaging"
    assert rv.get_selected_tag_id() == 102

    # Reset title and tags
    rv.reset_title_and_tags()
    assert rv.get_meeting_title().startswith("Meeting — ")
    assert rv.get_selected_tag_id() is None
    assert rv.tag_combo.currentIndex() == 0

    # Manual reset triggers reset signal and clears interface
    signal_fired = []
    rv.reset_session_requested.connect(lambda: signal_fired.append(True))
    rv.set_meeting_title("Another Meeting")
    rv.tag_combo.setCurrentIndex(1)
    rv._on_manual_reset_clicked()
    assert len(signal_fired) == 1
    assert rv.get_meeting_title().startswith("Meeting — ")
    assert rv.get_selected_tag_id() is None

    # TagSelector clear selection
    ts = TagSelector()
    ts.set_tags([{"id": 1, "name": "DevOps"}, {"id": 2, "name": "Packaging"}])
    # Check first item
    first_cb = ts.list_widget.itemWidget(ts.list_widget.item(0)).findChild(type(rv.tag_combo))
    ts.clear_selection()
    assert ts.selected_tag_ids() == []

    # 5. Fast-start warmup and refresh button
    assert hasattr(rv, "refresh_summary_btn")
    assert hasattr(rv, "chat_status_lbl")
    assert hasattr(agent, "trigger_immediate_periodic_analysis")
    print("[OK] Dynamic Keyphrase Extraction, Corpus Mining, and Title/Tag Reset passed.")


if __name__ == "__main__":
    test_memory_and_scratchpad()
    test_prompts_and_tag_personas()
    test_vad_channel_modes()
    test_asr_provider_manager()
    test_local_whisper_transcription()
    test_audio_recorder_tap()
    test_offline_copilot_engine()
    test_hud_controls_and_splitter()
    test_suggested_questions_accumulation()
    test_lm_studio_configuration()
    test_recordings_notes_linking_and_viewer()
    test_notes_upload_and_summarization_linkage()
    test_hud_toggle_visibility_button()
    test_hud_clear_on_start_and_manual_reset()
    test_fetch_lm_studio_models_function()
    test_history_icon_buttons_and_model_fetch_ui()
    test_light_and_dark_theme_system()
    test_open_speakr_web_instance_button()
    test_noise_filtering_and_topic_cards()
    test_dynamic_topic_derivation_and_no_vdi_bias()
    test_reasoning_engine_healthcheck_and_badge()
    test_configurable_quick_action_prompts()
    test_rolling_summary_prompt_and_popout()
    test_gui_makeover_components()
    test_meeting_title_renaming_and_tag_persistence()
    test_dynamic_keyphrase_extraction_and_title_tag_reset()
    print("\nALL PIPELINE INTEGRATION TESTS PASSED SUCCESSFULLY!")


