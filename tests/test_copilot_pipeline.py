import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from pathlib import Path
import numpy as np
from core.copilot.memory import CopilotMemory, SuggestedQuestion
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

    # 2. Suggested questions & user interactive status
    mem.set_suggested_questions([
        {"question": "Who is the primary on-call engineer?", "rationale": "Accountability"},
        {"question": "What is the maintenance window cutover time?", "rationale": "SLA compliance"}
    ])
    assert len(mem.suggested_questions) == 2
    assert mem.suggested_questions[0].status == "pending"

    # 3. User marks question asked
    mem.mark_question_asked("Who is the primary on-call engineer?")
    assert mem.suggested_questions[0].status == "asked"
    assert any("[Asked] Who is the primary on-call engineer?" in n for n in mem.live_notes)

    # 4. User adds manual note
    mem.add_user_note("Chuck confirmed firmware 3.4.1 snapshot ready.")
    assert len(mem.live_notes) >= 2

    # 5. Verify Markdown serialization
    md = mem.get_scratchpad_markdown()
    assert "Who is the primary on-call engineer?" in md
    assert "[x]" in md
    assert "Chuck confirmed firmware 3.4.1 snapshot ready." in md

    print("[OK] CopilotMemory passed.")

def test_prompts_and_tag_personas():
    print("Testing Prompt Generator and Tag Personas...")
    cab_prompt = get_periodic_prompt("cab-meeting")
    assert "CHANGE ADVISORY BOARD" in cab_prompt
    assert "rollback" in cab_prompt.lower()

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
    assert "suggested_questions" in res
    assert len(res["suggested_questions"]) > 0
    assert "live_notes" in res
    assert "action_items" in res
    assert len(res["action_items"]) > 0
    
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
    print("Testing FloatingCopilotHUD and 3-way resizable splitter...")
    from PySide6.QtWidgets import QApplication
    from gui.hud import FloatingCopilotHUD, TwoLineNoteEdit
    
    app = QApplication.instance() or QApplication([])
    mem = CopilotMemory()
    from core.copilot.agent import CopilotAgent
    agent = CopilotAgent(mem, on_results_callback=lambda r: None)
    
    hud = FloatingCopilotHUD(mem, agent, initial_opacity=0.85)
    
    # Opacity check
    assert abs(hud.windowOpacity() - 0.85) < 0.01
    
    # Mode combo check
    assert hud.mode_combo.count() == 3
    assert hud.mode_combo.findData("virtual") >= 0
    assert hud.mode_combo.findData("in_person") >= 0
    assert hud.mode_combo.findData("hybrid") >= 0
    
    # ASR combo check
    assert hud.asr_combo.count() == 4
    assert hud.asr_combo.findData("local") >= 0
    assert hud.asr_combo.findData("mac_lan") >= 0
    
    # 3-way Splitter check: 3 widgets (Questions, Scratchpad, Transcript)
    assert hud.splitter.count() == 3
    
    # TwoLineNoteEdit check
    assert isinstance(hud.add_note_input, TwoLineNoteEdit)
    hud.add_note_input.setPlainText("Test custom note item")
    hud._add_custom_note()
    assert "Test custom note item" in mem.live_notes
    
    # Pill mode toggle check
    hud.show()
    assert hud.is_pill_mode is False
    hud._toggle_pill_mode()
    assert hud.is_pill_mode is True
    assert hud.pill_widget.isVisible() is True
    assert hud.full_widget.isVisible() is False
    
    # Restore from pill mode
    hud._toggle_pill_mode()
    assert hud.is_pill_mode is False
    assert hud.full_widget.isVisible() is True
    
    # Test HUD questions count badge and clear button
    mem.set_suggested_questions([
        {"question": "HUD Question 1", "rationale": "r1"},
        {"question": "HUD Question 2", "rationale": "r2"}
    ])
    hud._render_questions()
    assert hud.q_count_badge.isVisible() is True
    assert hud.q_clear_btn.isVisible() is True
    assert "2 pending" in hud.q_count_badge.text()
    
    # Test Clear button
    hud._clear_suggested_questions()
    assert hud.q_count_badge.isVisible() is False
    assert hud.q_clear_btn.isVisible() is False
    assert len(mem.suggested_questions) == 0

    hud.close()
    print("[OK] FloatingCopilotHUD and 3-way resizable splitter passed.")

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
    # Asked question should remain!
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
    # Even in privacy mode, LM Studio is local/LAN, so _is_offline_mode must be False!
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
    # Restore defaults
    cfg.lm_studio_endpoint = "http://localhost:1234/v1"
    cfg.lm_studio_server_type = "local"

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

    with tempfile.TemporaryDirectory() as tmpdir:
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
            # Verify data payload passed to httpx.Client.post
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
        cfg.upload_mode = "api"
        storage = RecordingsManager(cfg)
        
        with tempfile.TemporaryDirectory() as tmpdir:
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

            # Mock SpeakrClient during _process_background
            with patch("core.uploader.SpeakrClient") as MockClientCls:
                mock_client_inst = MagicMock()
                mock_client_inst.upload_recording.return_value = "rec_789"
                mock_client_inst.replace_recording_notes.return_value = True
                mock_client_inst.add_recording_tags.return_value = True
                MockClientCls.return_value = mock_client_inst

                uploader._process_background(audio_path, [101], audio_path)

                # Verify upload_recording called with notes
                mock_client_inst.upload_recording.assert_called_once()
                call_args, call_kwargs = mock_client_inst.upload_recording.call_args
                assert "Key question answered" in call_kwargs["notes"]
                # Verify replace_recording_notes confirmed notes on Speakr
                mock_client_inst.replace_recording_notes.assert_called_with("rec_789", resolved_txt)

            # 3. Test AudioUploader Folder mode copies notes
            cfg.upload_mode = "folder"
            nas_dir = os.path.join(tmpdir, "NAS_Inbox")
            os.makedirs(nas_dir, exist_ok=True)
            cfg.nas_folder_path = nas_dir

            uploader._process_background(audio_path, [], audio_path)
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

def test_hud_toggle_visibility_button():
    print("Testing Open/Hide HUD Visibility Toggle Button...")
    from PySide6.QtWidgets import QApplication
    from core.config import Settings
    from core.recorder import AudioRecorder
    from core.uploader import AudioUploader
    from core.storage import RecordingsManager
    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings()
    rec = AudioRecorder()
    stor = RecordingsManager(s)
    up = AudioUploader(s, stor)
    w = MainWindow(s, rec, up, stor)

    try:
        # Initial state: HUD not opened yet, button says Open HUD
        assert "Open HUD" in w.open_hud_btn.text()
        assert w.hud is None or not w.hud.isVisible()

        # 1. Click / trigger toggle: should open HUD and button text becomes Hide HUD
        w._toggle_copilot_hud()
        assert w.hud is not None
        assert w.hud.isVisible() is True
        assert "Hide HUD" in w.open_hud_btn.text()

        # 2. Click / trigger toggle again: should hide HUD and button text becomes Open HUD
        w._toggle_copilot_hud()
        assert w.hud.isVisible() is False
        assert "Open HUD" in w.open_hud_btn.text()

        # 3. Direct show / hide on HUD: button updates reactively
        w.hud.show()
        assert "Hide HUD" in w.open_hud_btn.text()

        w.hud.hide()
        assert "Open HUD" in w.open_hud_btn.text()
    finally:
        if w.hud:
            w.hud.close()
        rec.terminate()
        w.close()

    print("[OK] Open/Hide HUD Visibility Toggle Button passed.")

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
        mem.add_user_note("Chuck confirmed snapshot 1.")
        hud._render_questions()
        hud._render_notes()
        hud.ticker_box.append("Test transcript line")

        assert hud.questions_list.count() == 1
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
            # HUD content must remain intact for post-meeting reading
            assert hud.questions_list.count() == 1
            assert hud.notes_list.count() >= 1
            assert len(hud.ticker_box.toPlainText()) > 0
            assert "Notes Saved" in hud.status_dot.toolTip()
        finally:
            if os.path.exists(temp_rec):
                os.remove(temp_rec)

        # 3. Test Manual Reset button (clears immediately on demand)
        hud.reset_btn.click()
        assert hud.questions_list.count() == 0
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
        assert hud.notes_list.count() == 0
        assert hud.ticker_box.toPlainText() == ""
        assert len(mem.turns) == 0
        assert len(mem.suggested_questions) == 0
        assert hud.status_dot.toolTip() == "Status: Recording Active"

    finally:
        if w.hud:
            w.hud.close()
        rec.terminate()
        w.close()

    print("[OK] HUD Clear on Start Recording & Manual Reset passed.")

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
    print("\nALL PIPELINE INTEGRATION TESTS PASSED SUCCESSFULLY!")

