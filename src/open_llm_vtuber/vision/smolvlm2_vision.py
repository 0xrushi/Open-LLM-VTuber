import base64
import io
from typing import List

from loguru import logger

from ..agent.input_types import ImageData
from .vision_interface import VisionInterface


class SmolVLM2Vision(VisionInterface):
    """SmolVLM2 vision backend using Hugging Face transformers."""

    def __init__(
        self,
        model_id: str = "HuggingFaceTB/SmolVLM2-2.2B-Instruct",
        device: str = "auto",
        dtype: str = "auto",
        max_new_tokens: int = 160,
        prompt_template: str | None = None,
    ):
        try:
            import torch
            from transformers import AutoProcessor

            try:
                from transformers import AutoModelForImageTextToText

                model_cls = AutoModelForImageTextToText
            except ImportError:
                from transformers import AutoModelForVision2Seq

                model_cls = AutoModelForVision2Seq
        except ImportError as exc:
            raise ImportError(
                "SmolVLM2 vision requires `transformers` and `Pillow`. "
                "Install dependencies with `uv sync` after updating pyproject.toml."
            ) from exc

        self._torch = torch
        self._model_id = model_id
        self._device = self._resolve_device(device)
        self._dtype = self._resolve_dtype(dtype, self._device)
        self._max_new_tokens = max_new_tokens
        self._prompt_template = (
            prompt_template
            or "Describe the user's camera/screen image for conversational context."
        )

        logger.info(
            f"Loading SmolVLM2 model={self._model_id} device={self._device} dtype={self._dtype}"
        )
        self._processor = self._load_processor(AutoProcessor)
        self._model = self._load_model(model_cls)
        self._model.to(self._device)
        self._model.eval()

    def _load_processor(self, auto_processor_cls):
        try:
            return auto_processor_cls.from_pretrained(self._model_id)
        except Exception as exc:
            if "torchvision" in str(exc):
                raise ImportError(
                    "SmolVLM2 requires `torchvision` in addition to `torch` and "
                    "`transformers`. Install it with `uv add torchvision` or "
                    "`uv pip install torchvision`."
                ) from exc

            if "SmolVLMProcessor" not in str(exc):
                raise

            logger.warning(
                "SmolVLMProcessor is unavailable in the local transformers build; "
                "retrying with trust_remote_code=True"
            )
            try:
                return auto_processor_cls.from_pretrained(
                    self._model_id,
                    trust_remote_code=True,
                )
            except Exception as retry_exc:
                if "torchvision" in str(retry_exc):
                    raise ImportError(
                        "SmolVLM2 requires `torchvision` in addition to `torch` "
                        "and `transformers`. Install it with `uv add torchvision` "
                        "or `uv pip install torchvision`."
                    ) from retry_exc
                raise

    def _load_model(self, model_cls):
        try:
            return model_cls.from_pretrained(
                self._model_id,
                torch_dtype=self._dtype,
            )
        except Exception as exc:
            if "SmolVLMProcessor" not in str(exc):
                raise

            logger.warning(
                "SmolVLM model helpers are unavailable in the local transformers build; "
                "retrying with trust_remote_code=True"
            )
            return model_cls.from_pretrained(
                self._model_id,
                torch_dtype=self._dtype,
                trust_remote_code=True,
            )

    def _resolve_device(self, requested: str) -> str:
        if requested != "auto":
            return requested
        if self._torch.cuda.is_available():
            return "cuda"
        if (
            getattr(self._torch.backends, "mps", None)
            and self._torch.backends.mps.is_available()
        ):
            return "mps"
        return "cpu"

    def _resolve_dtype(self, requested: str, device: str):
        dtype_map = {
            "float16": self._torch.float16,
            "bfloat16": self._torch.bfloat16,
            "float32": self._torch.float32,
        }
        if requested != "auto":
            return dtype_map.get(requested, self._torch.float32)
        if device in {"cuda", "mps"}:
            return self._torch.float16
        return self._torch.float32

    def _decode_image_to_pil(self, image_data: str):
        from PIL import Image

        payload = image_data
        if image_data.startswith("data:"):
            _, payload = image_data.split(",", 1)
        binary = base64.b64decode(payload)
        return Image.open(io.BytesIO(binary)).convert("RGB")

    def _build_prompt(self, user_text: str) -> str:
        user_text = (user_text or "").strip()
        fallback_context = (
            "No explicit user request was provided. Describe the scene clearly for "
            "a conversational assistant."
        )
        if user_text:
            return (
                f"{self._prompt_template}\n"
                f"User request/context: {user_text}\n"
                "Return 2-4 concise sentences."
            )
        return (
            f"{self._prompt_template}\n"
            f"User request/context: {fallback_context}\n"
            "Return 2-4 concise sentences."
        )

    def describe(self, images: List[ImageData], user_text: str) -> str:
        if not images:
            return ""

        pil_images = []
        for img in images:
            try:
                pil_images.append(self._decode_image_to_pil(img.data))
            except Exception as exc:
                logger.warning(f"Failed to decode image input for vision model: {exc}")

        if not pil_images:
            return ""

        prompt = self._build_prompt(user_text)
        messages = [
            {
                "role": "user",
                "content": [
                    *[{"type": "image"} for _ in pil_images],
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self._processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=False,
        )

        inputs = self._processor(
            text=text,
            images=pil_images,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with self._torch.inference_mode():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
            )

        input_length = inputs["input_ids"].shape[-1]
        trimmed_ids = generated_ids[:, input_length:]
        text_out = self._processor.batch_decode(
            trimmed_ids,
            skip_special_tokens=True,
        )[0]
        return text_out.strip()
