import os
import sys
import unittest

from tests.test_copilot_pipeline import (
    test_memory_and_scratchpad,
    test_prompts_and_tag_personas,
    test_vad_channel_modes,
    test_asr_provider_manager,
    test_local_whisper_transcription,
    test_audio_recorder_tap,
    test_offline_copilot_engine,
    test_hud_controls_and_splitter,
    test_suggested_questions_accumulation,
    test_lm_studio_configuration,
    test_recordings_notes_linking_and_viewer,
    test_notes_upload_and_summarization_linkage,
    test_hud_toggle_visibility_button,
    test_hud_clear_on_start_and_manual_reset,
    test_fetch_lm_studio_models_function,
    test_history_icon_buttons_and_model_fetch_ui,
    test_dynamic_topic_derivation_and_no_vdi_bias,
    test_gui_makeover_components,
    test_meeting_title_renaming_and_tag_persistence,
    test_dynamic_keyphrase_extraction_and_title_tag_reset,
)

class TestCopilotSuite(unittest.TestCase):
    def test_01_memory_and_scratchpad(self):
        test_memory_and_scratchpad()

    def test_02_prompts_and_tag_personas(self):
        test_prompts_and_tag_personas()

    def test_03_vad_channel_modes(self):
        test_vad_channel_modes()

    def test_04_asr_provider_manager(self):
        test_asr_provider_manager()

    def test_05_local_whisper_transcription(self):
        test_local_whisper_transcription()

    def test_06_audio_recorder_tap(self):
        test_audio_recorder_tap()

    def test_07_offline_copilot_engine(self):
        test_offline_copilot_engine()

    def test_08_hud_controls_and_splitter(self):
        test_hud_controls_and_splitter()

    def test_09_suggested_questions_accumulation(self):
        test_suggested_questions_accumulation()

    def test_10_lm_studio_configuration(self):
        test_lm_studio_configuration()

    def test_11_recordings_notes_linking_and_viewer(self):
        test_recordings_notes_linking_and_viewer()

    def test_12_notes_upload_and_summarization_linkage(self):
        test_notes_upload_and_summarization_linkage()

    def test_13_hud_toggle_visibility_button(self):
        test_hud_toggle_visibility_button()

    def test_14_hud_clear_on_start_and_manual_reset(self):
        test_hud_clear_on_start_and_manual_reset()

    def test_15_fetch_lm_studio_models_function(self):
        test_fetch_lm_studio_models_function()

    def test_16_history_icon_buttons_and_model_fetch_ui(self):
        test_history_icon_buttons_and_model_fetch_ui()

    def test_17_dynamic_topic_derivation_and_no_vdi_bias(self):
        test_dynamic_topic_derivation_and_no_vdi_bias()

    def test_18_gui_makeover_components(self):
        test_gui_makeover_components()

    def test_19_meeting_title_renaming_and_tag_persistence(self):
        test_meeting_title_renaming_and_tag_persistence()

    def test_20_dynamic_keyphrase_extraction_and_title_tag_reset(self):
        test_dynamic_keyphrase_extraction_and_title_tag_reset()

if __name__ == "__main__":
    unittest.main()
