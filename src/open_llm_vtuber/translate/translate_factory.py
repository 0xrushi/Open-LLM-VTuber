from .gemini import GeminiTranslate
from .tencent import TencentTranslate
from .translate_interface import TranslateInterface


class TranslateFactory:
    @staticmethod
    def get_translator(
        translate_provider: str, translate_provider_config: dict
    ) -> TranslateInterface:
        translate_provider = translate_provider.lower()
        if translate_provider == "gemini":
            return GeminiTranslate(
                api_key=translate_provider_config.get("gemini_api_key"),
                model=translate_provider_config.get("model"),
                base_url=translate_provider_config.get("base_url"),
                target_lang=translate_provider_config.get("target_lang"),
            )
        elif translate_provider == "tencent":
            return TencentTranslate(
                secret_id=translate_provider_config.get("secret_id"),
                secret_key=translate_provider_config.get("secret_key"),
                region=translate_provider_config.get("region"),
                source_lang=translate_provider_config.get("source_lang"),
                target_lang=translate_provider_config.get("target_lang"),
            )
        else:
            raise ValueError(f"Unsupported translate provider: {translate_provider}")
