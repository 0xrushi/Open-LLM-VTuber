from typing import ClassVar, Dict, Literal

from pydantic import BaseModel, Field

from .i18n import Description, I18nMixin


class SmolVLM2VisionConfig(I18nMixin, BaseModel):
    """Configuration for SmolVLM2 vision inference."""

    model_id: str = Field(
        default="HuggingFaceTB/SmolVLM2-2.2B-Instruct", alias="model_id"
    )
    device: str = Field(default="auto", alias="device")
    dtype: Literal["auto", "float16", "bfloat16", "float32"] = Field(
        default="auto", alias="dtype"
    )
    max_new_tokens: int = Field(default=160, alias="max_new_tokens")
    prompt_template: str = Field(
        default=(
            "Describe the user's camera/screen image for conversational context. "
            "Focus on people, actions, objects, and scene details that are useful "
            "for a voice assistant. Keep it concise and factual."
        ),
        alias="prompt_template",
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "model_id": Description(
            en="Hugging Face model ID for SmolVLM2",
            zh="SmolVLM2 的 Hugging Face 模型 ID",
        ),
        "device": Description(
            en="Inference device: auto/cpu/cuda/mps",
            zh="推理设备：auto/cpu/cuda/mps",
        ),
        "dtype": Description(
            en="Torch dtype for inference",
            zh="推理使用的 torch 精度类型",
        ),
        "max_new_tokens": Description(
            en="Maximum generated tokens for vision caption",
            zh="视觉描述生成的最大 token 数",
        ),
        "prompt_template": Description(
            en="Instruction prompt sent to the vision model",
            zh="发送给视觉模型的指令提示词",
        ),
    }


class VisionConfig(I18nMixin, BaseModel):
    """Vision module settings for image/camera understanding."""

    enabled: bool = Field(default=False, alias="enabled")
    vision_model: Literal["smolvlm2"] = Field(default="smolvlm2", alias="vision_model")
    smolvlm2: SmolVLM2VisionConfig = Field(
        default_factory=SmolVLM2VisionConfig,
        alias="smolvlm2",
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "enabled": Description(
            en="Enable a dedicated vision model for camera/screen input",
            zh="启用独立视觉模型处理摄像头/屏幕图像输入",
        ),
        "vision_model": Description(
            en="Vision backend type",
            zh="视觉后端类型",
        ),
        "smolvlm2": Description(
            en="SmolVLM2 model settings",
            zh="SmolVLM2 模型设置",
        ),
    }
