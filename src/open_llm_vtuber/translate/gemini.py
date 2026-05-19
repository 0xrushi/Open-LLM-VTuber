import openai
from loguru import logger
from .translate_interface import TranslateInterface


class GeminiTranslate(TranslateInterface):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/",
        target_lang: str = "Japanese",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.target_lang = target_lang
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def translate(self, text: str) -> str:
        try:
            prompt = (
                f"Translate the following text to {self.target_lang}. "
                "Only return the translated text, no extra explanation or notes.\n\n"
                f"Text: {text}"
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            translated_text = response.choices[0].message.content.strip()
            # Remove potential quotes if the model wrapped the translation
            if (
                translated_text.startswith('"')
                and translated_text.endswith('"')
                and len(translated_text) > 1
            ):
                translated_text = translated_text[1:-1]
            return translated_text
        except Exception as e:
            logger.error(f"Gemini translation failed: {e}")
            raise e
