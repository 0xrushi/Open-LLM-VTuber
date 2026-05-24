import unittest

from src.open_llm_vtuber.config_manager.utils import read_yaml


class TestNamiJapaneseProfile(unittest.TestCase):
    def test_nami_japanese_profile_forces_japanese_and_uses_fish_tts(self):
        config = read_yaml("characters/Nami_Japanese.yaml")
        char = config["character_config"]

        self.assertEqual(char.get("conf_name"), "Nami Japanese")

        persona = char.get("persona_prompt", "")
        self.assertIn("Always reply in natural Japanese", persona)
        self.assertIn("Never reply in English unless the user explicitly asks for English", persona)

        tts_cfg = char.get("tts_config", {})
        self.assertEqual(tts_cfg.get("tts_model"), "fish_api_tts")
        fish = tts_cfg.get("fish_api_tts", {})
        self.assertTrue(bool(fish.get("reference_id")))

        tts_pre = char.get("tts_preprocessor_config", {})
        translator = tts_pre.get("translator_config", {})
        self.assertFalse(translator.get("translate_audio", True))

    def test_fish_audio_tts_engine_imports(self):
        from src.open_llm_vtuber.tts.fish_api_tts import TTSEngine  # noqa: F401


if __name__ == "__main__":
    unittest.main()
