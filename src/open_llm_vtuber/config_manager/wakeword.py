# config_manager/wakeword.py
from pydantic import Field
from typing import Literal, Optional, Dict, ClassVar, List
from .i18n import I18nMixin, Description


class OpenWakeWordConfig(I18nMixin):
    """Configuration for openWakeWord engine."""

    wakeword_models: List[str] = Field(
        default_factory=lambda: ["hey_jarvis_v0.1"],
        alias="wakeword_models",
    )
    inference_framework: str = Field(default="onnx", alias="inference_framework")
    model_threshold: float = Field(default=0.5, alias="model_threshold")
    trigger_level: int = Field(default=3, alias="trigger_level")
    chunk_size: int = Field(default=1280, alias="chunk_size")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "wakeword_models": Description(
            en="List of wakeword model names to load",
            zh="要加载的唤醒词模型名称列表",
        ),
        "inference_framework": Description(
            en="Inference framework to use (onnx or tflite)",
            zh="推理框架（onnx 或 tflite）",
        ),
        "model_threshold": Description(
            en="Confidence threshold for wakeword detection",
            zh="唤醒词检测的置信度阈值",
        ),
        "trigger_level": Description(
            en="Number of consecutive detections required to trigger",
            zh="触发所需的连续检测次数",
        ),
        "chunk_size": Description(
            en="Audio chunk size in samples (16kHz int16)",
            zh="音频块大小（16kHz int16 采样数）",
        ),
    }


class WakewordConfig(I18nMixin):
    """Configuration for wakeword detection."""

    enabled: bool = Field(default=False, alias="enabled")
    wakeword_model: Optional[Literal["openwakeword"]] = Field(
        default="openwakeword", alias="wakeword_model"
    )
    activation_timeout_sec: float = Field(default=15.0, alias="activation_timeout_sec")
    openwakeword: Optional[OpenWakeWordConfig] = Field(
        default_factory=OpenWakeWordConfig, alias="openwakeword"
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "enabled": Description(en="Enable wakeword detection", zh="启用唤醒词检测"),
        "wakeword_model": Description(
            en="Wakeword detection engine to use",
            zh="要使用的唤醒词检测引擎",
        ),
        "activation_timeout_sec": Description(
            en="Seconds of silence before requiring wakeword again",
            zh="静音多少秒后需要再次唤醒",
        ),
        "openwakeword": Description(
            en="Configuration for openWakeWord engine",
            zh="openWakeWord 引擎配置",
        ),
    }
