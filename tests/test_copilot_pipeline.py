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

if __name__ == "__main__":
    test_memory_and_scratchpad()
    test_prompts_and_tag_personas()
    test_vad_channel_modes()
    test_asr_provider_manager()
    test_local_whisper_transcription()
    test_audio_recorder_tap()
    print("\nALL PIPELINE INTEGRATION TESTS PASSED SUCCESSFULLY!")
