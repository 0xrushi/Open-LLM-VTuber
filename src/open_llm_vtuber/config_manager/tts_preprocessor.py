# config_manager/translate.py
from typing import Literal, Optional, Dict, ClassVar
from pydantic import ValidationInfo, Field, model_validator
from .i18n import I18nMixin, Description

# --- Sub-models for specific Translator providers ---


class GeminiTranslateConfig(I18nMixin):
    """Configuration for Gemini translation service."""

    gemini_api_key: str = Field(..., alias="gemini_api_key")
    model: str = Field("gemini-1.5-flash", alias="model")
    base_url: str = Field(
        "https://generativelanguage.googleapis.com/v1beta/openai/", alias="base_url"
    )
    target_lang: str = Field("Japanese", alias="target_lang")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "gemini_api_key": Description(
            en="API key for Gemini translation",
            zh="Gemini 翻译的 API 密钥",
        ),
        "model": Description(
            en="Model to use for translation (e.g., gemini-1.5-flash)",
            zh="用于翻译的模型（例如 gemini-1.5-flash）",
        ),
        "base_url": Description(
            en="Base URL for Gemini API",
            zh="Gemini API 的基础 URL",
        ),
        "target_lang": Description(
            en="Target language for translation",
            zh="翻译的目标语言",
        ),
    }


class TencentConfig(I18nMixin):
    """Configuration for tencent translation service."""

    secret_id: str = Field(..., description="Tencent Secret ID")
    secret_key: str = Field(..., description="Tencent Secret Key")
    region: str = Field(..., description="Region for Tencent Service")
    source_lang: str = Field(
        ..., description="Source language code for tencent translation"
    )
    target_lang: str = Field(
        ..., description="Target language code for tencent translation"
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "secret_id": Description(en="Tencent Secret ID", zh="腾讯服务的Secret ID"),
        "secret_key": Description(en="Tencent Secret Key", zh="腾讯服务的Secret Key"),
        "region": Description(en="Region for Tencent Service", zh="腾讯服务使用的区域"),
        "source_lang": Description(
            en="Source language code for tencent translation", zh="腾讯翻译的源语言代码"
        ),
        "target_lang": Description(
            en="Target language code for tencent translation",
            zh="腾讯翻译的目标语言代码",
        ),
    }


# --- Main TranslatorConfig model ---


class TranslatorConfig(I18nMixin):
    """Configuration for translation services."""

    translate_audio: bool = Field(..., alias="translate_audio")
    translate_provider: Literal["gemini", "tencent"] = Field(
        ..., alias="translate_provider"
    )
    gemini: Optional[GeminiTranslateConfig] = Field(None, alias="gemini")
    tencent: Optional[TencentConfig] = Field(None, alias="tencent")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "translate_audio": Description(
            en="Enable audio translation (using Gemini or Tencent)",
            zh="启用音频翻译（使用 Gemini 或腾讯）",
        ),
        "translate_provider": Description(
            en="Translation service provider to use", zh="要使用的翻译服务提供者"
        ),
        "gemini": Description(
            en="Configuration for Gemini translation service", zh="Gemini 翻译服务配置"
        ),
        "tencent": Description(
            en="Configuration for TenCent translation service", zh="腾讯 翻译服务配置"
        ),
    }

    @model_validator(mode="after")
    def check_translator_config(cls, values: "TranslatorConfig", info: ValidationInfo):
        translate_audio = values.translate_audio
        translate_provider = values.translate_provider

        if translate_audio:
            if translate_provider == "gemini" and values.gemini is None:
                raise ValueError(
                    "Gemini configuration must be provided when translate_audio is True and translate_provider is 'gemini'"
                )
            elif translate_provider == "tencent" and values.tencent is None:
                raise ValueError(
                    "Tencent configuration must be provided when translate_audio is True and translate_provider is 'tencent'"
                )

        return values


class TTSPreprocessorConfig(I18nMixin):
    """Configuration for TTS preprocessor."""

    remove_special_char: bool = Field(..., alias="remove_special_char")
    ignore_brackets: bool = Field(default=True, alias="ignore_brackets")
    ignore_parentheses: bool = Field(default=True, alias="ignore_parentheses")
    ignore_asterisks: bool = Field(default=True, alias="ignore_asterisks")
    ignore_angle_brackets: bool = Field(default=True, alias="ignore_angle_brackets")
    translator_config: TranslatorConfig = Field(..., alias="translator_config")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "remove_special_char": Description(
            en="Remove special characters from the input text",
            zh="从输入文本中删除特殊字符",
        ),
        "translator_config": Description(
            en="Configuration for translation services", zh="翻译服务的配置"
        ),
    }
