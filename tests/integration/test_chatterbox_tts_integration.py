import os
import unittest
from unittest.mock import patch

from src.open_llm_vtuber.config_manager import read_yaml, validate_config
from src.open_llm_vtuber.tts.chatterbox_tts import TTSEngine as ChatterboxTTSEngine
from src.open_llm_vtuber.tts.tts_factory import TTSFactory

CHATTERBOX_URL = "http://192.168.1.166:8004/tts"


class DummyResponse:
    def __init__(self, status_code=200, content=b"RIFFtestWAVE", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text


class TestChatterboxTTSIntegration(unittest.TestCase):
    def _load_config_with_local_chatterbox(self):
        config_data = read_yaml("config_templates/conf.default.yaml")
        tts_config = config_data["character_config"]["tts_config"]
        tts_config["tts_model"] = "chatterbox_tts"
        tts_config["chatterbox_tts"]["api_url"] = CHATTERBOX_URL
        return validate_config(config_data)

    def test_config_uses_local_chatterbox_tts(self):
        config = self._load_config_with_local_chatterbox()
        tts_config = config.character_config.tts_config

        self.assertEqual(tts_config.tts_model, "chatterbox_tts")

        engine = TTSFactory.get_tts_engine(
            tts_config.tts_model,
            **getattr(tts_config, tts_config.tts_model).model_dump(),
        )

        self.assertIsInstance(engine, ChatterboxTTSEngine)
        self.assertEqual(engine.api_url, tts_config.chatterbox_tts.api_url)
        self.assertEqual(engine.api_url, CHATTERBOX_URL)

    def test_configured_local_chatterbox_generation_request(self):
        config = self._load_config_with_local_chatterbox()
        tts_config = config.character_config.tts_config
        calls = {}

        def fake_post(url, json=None, timeout=None):
            calls["url"] = url
            calls["json"] = json
            calls["timeout"] = timeout
            return DummyResponse()

        with patch(
            "src.open_llm_vtuber.tts.chatterbox_tts.requests.post",
            side_effect=fake_post,
        ):
            engine = TTSFactory.get_tts_engine(
                tts_config.tts_model,
                **getattr(tts_config, tts_config.tts_model).model_dump(),
            )
            output_path = engine.generate_audio(
                "[smirk] [laugh] hello", file_name_no_ext="chatterbox_integration"
            )

        try:
            self.assertEqual(calls["url"], CHATTERBOX_URL)
            self.assertEqual(calls["timeout"], 300)
            self.assertEqual(calls["json"]["text"], "[laugh] hello")
            self.assertEqual(calls["json"]["voice_mode"], "predefined")
            self.assertEqual(calls["json"]["predefined_voice_id"], "default_sample.wav")
            self.assertEqual(calls["json"]["output_format"], "wav")
            self.assertTrue(output_path.endswith(".wav"))
            self.assertTrue(os.path.exists(output_path))
            with open(output_path, "rb") as f:
                self.assertEqual(f.read(), b"RIFFtestWAVE")
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


if __name__ == "__main__":
    unittest.main()
