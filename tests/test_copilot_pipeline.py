import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
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
    
    hud.close()
    print("[OK] FloatingCopilotHUD and 3-way resizable splitter passed.")

if __name__ == "__main__":
    test_memory_and_scratchpad()
    test_prompts_and_tag_personas()
    test_vad_channel_modes()
    test_asr_provider_manager()
    test_local_whisper_transcription()
    test_audio_recorder_tap()
    test_offline_copilot_engine()
    test_hud_controls_and_splitter()
    print("\nALL PIPELINE INTEGRATION TESTS PASSED SUCCESSFULLY!")

