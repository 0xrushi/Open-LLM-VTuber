from .vision_interface import VisionInterface


class VisionFactory:
    @staticmethod
    def get_vision_engine(vision_model: str, **kwargs) -> VisionInterface:
        if vision_model == "smolvlm2":
            from .smolvlm2_vision import SmolVLM2Vision

            return SmolVLM2Vision(
                model_id=kwargs.get("model_id"),
                device=kwargs.get("device", "auto"),
                dtype=kwargs.get("dtype", "auto"),
                max_new_tokens=kwargs.get("max_new_tokens", 160),
                prompt_template=kwargs.get("prompt_template"),
            )

        raise ValueError(f"Unsupported vision model: {vision_model}")
