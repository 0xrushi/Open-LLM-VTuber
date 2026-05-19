import unittest
from unittest.mock import MagicMock, patch
from src.open_llm_vtuber.translate.gemini import GeminiTranslate

class TestGeminiTranslate(unittest.TestCase):
    def setUp(self):
        self.api_key = "test_api_key"
        self.translator = GeminiTranslate(api_key=self.api_key)

    @patch("openai.OpenAI")
    def test_translate_success(self, mock_openai):
        # Setup mock
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="こんにちは"))
        ]
        mock_client.chat.completions.create.return_value = mock_response

        # Test
        # We need to re-instantiate or inject the mock client since it's created in __init__
        self.translator.client = mock_client
        result = self.translator.translate("Hello")

        self.assertEqual(result, "こんにちは")
        mock_client.chat.completions.create.assert_called_once()
        
    @patch("openai.OpenAI")
    def test_translate_with_quotes(self, mock_openai):
        # Setup mock to return text with quotes
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='"こんにちは"'))
        ]
        mock_client.chat.completions.create.return_value = mock_response

        # Test
        self.translator.client = mock_client
        result = self.translator.translate("Hello")

        self.assertEqual(result, "こんにちは")

    @patch("openai.OpenAI")
    def test_translate_failure(self, mock_openai):
        # Setup mock to raise exception
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        
        # Test
        self.translator.client = mock_client
        with self.assertRaises(Exception):
            self.translator.translate("Hello")

if __name__ == "__main__":
    unittest.main()
