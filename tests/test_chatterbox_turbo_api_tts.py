import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlencode

from src.open_llm_vtuber.tts.chatterbox_turbo_api_tts import TTSEngine


class DummyResponse:
    def __init__(self, status_code=200, content=b"audio", headers=None, text=""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "audio/mpeg"}
        self.text = text


class TestChatterboxTurboAPITTS(unittest.TestCase):
    def test_generate_audio_uses_x_api_key_and_saves_file(self):
        calls = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls["url"] = url
            calls["headers"] = headers
            calls["json"] = json
            calls["timeout"] = timeout
            return DummyResponse(
                status_code=200,
                content=b"abc",
                headers={"Content-Type": "audio/mpeg"},
            )

        with patch(
            "src.open_llm_vtuber.tts.chatterbox_turbo_api_tts.requests.post",
            side_effect=fake_post,
        ):
            cwd = os.getcwd()
            cache_dir = os.path.join(cwd, "cache")
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            try:
                engine = TTSEngine(
                    api_key="SG_TEST_KEY",
                    reference_audio_url="https://example.com/ref.mp3",
                    timeout_sec=42,
                )
                output_path = engine.generate_audio(
                    "[joy] [laugh] hello", file_name_no_ext="sample_test"
                )

                self.assertEqual(
                    calls["url"],
                    "https://api.segmind.com/v1/chatterbox-turbo-tts",
                )
                self.assertEqual(calls["headers"]["x-api-key"], "SG_TEST_KEY")
                self.assertEqual(calls["headers"]["Content-Type"], "application/json")
                self.assertEqual(calls["json"]["text"], "[laugh] hello")
                self.assertEqual(
                    calls["json"]["reference_audio"], "https://example.com/ref.mp3"
                )
                self.assertEqual(calls["timeout"], 42)
                self.assertTrue(output_path.endswith(".mp3"))
                self.assertTrue(os.path.exists(output_path))
                with open(output_path, "rb") as f:
                    self.assertEqual(f.read(), b"abc")
            finally:
                test_file = os.path.join(cache_dir, "sample_test.mp3")
                if os.path.exists(test_file):
                    os.remove(test_file)

    def test_generate_audio_requires_api_key_and_reference_url(self):
        engine = TTSEngine(api_key=None, reference_audio_url=None)
        with self.assertRaisesRegex(RuntimeError, "API key is required"):
            engine.generate_audio("hello")

        engine = TTSEngine(api_key="SG_TEST_KEY", reference_audio_url=None)
        with self.assertRaisesRegex(RuntimeError, "reference_audio_url is required"):
            engine.generate_audio("hello")

    def test_generate_audio_raises_on_http_error(self):
        def fake_post(*args, **kwargs):
            return DummyResponse(status_code=401, text='{"error":"Unauthorized"}')

        with patch(
            "src.open_llm_vtuber.tts.chatterbox_turbo_api_tts.requests.post",
            side_effect=fake_post,
        ):
            engine = TTSEngine(
                api_key="SG_TEST_KEY",
                reference_audio_url="https://example.com/ref.mp3",
            )
            with self.assertRaisesRegex(RuntimeError, "status=401"):
                engine.generate_audio("hello")

    def test_generate_audio_rejects_expired_signed_reference_url(self):
        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
        signed_at = expired_at - timedelta(seconds=60)
        query = urlencode(
            {
                "X-Amz-Date": signed_at.strftime("%Y%m%dT%H%M%SZ"),
                "X-Amz-Expires": "60",
            }
        )
        engine = TTSEngine(
            api_key="SG_TEST_KEY",
            reference_audio_url=f"https://example.com/ref.mp3?{query}",
        )

        with patch(
            "src.open_llm_vtuber.tts.chatterbox_turbo_api_tts.requests.post"
        ) as post:
            with self.assertRaisesRegex(RuntimeError, "expired signed URL"):
                engine.generate_audio("hello")

        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
