#!/usr/bin/env python3
import base64
import sys
from pathlib import Path


CACTUS_IMAGE_PATH = Path("/home/alpha/Documents/Open-LLM-VTuber/free-photo-of-portrait-of-woman-eating-donut.jpeg")


def _image_file_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def main() -> int:
    sys.path.append("src")

    from open_llm_vtuber.agent.input_types import ImageData, ImageSource
    from open_llm_vtuber.config_manager import Config, read_yaml
    from open_llm_vtuber.vision.vision_factory import VisionFactory

    config_path = "conf.yaml"
    config_data = read_yaml(config_path)
    config = Config.model_validate(config_data)

    vision_cfg = config.character_config.agent_config.agent_settings.basic_memory_agent.vision_config
    vision_model_name = vision_cfg.vision_model
    vision_model_cfg = getattr(vision_cfg, vision_model_name)

    print(f"Loaded config from: {config_path}")
    print(f"Vision enabled: {vision_cfg.enabled}")
    print(f"Vision model: {vision_model_name}")

    if not vision_cfg.enabled:
        print("vision_config.enabled is False; set it to True in conf.yaml first.")
        return 1

    engine = VisionFactory.get_vision_engine(
        vision_model_name,
        **vision_model_cfg.model_dump(),
    )

    if not CACTUS_IMAGE_PATH.exists():
        print(f"Image not found: {CACTUS_IMAGE_PATH}")
        return 1

    image_data = ImageData(
        source=ImageSource.CAMERA,
        data=_image_file_to_data_url(CACTUS_IMAGE_PATH),
        mime_type="image/jpeg",
    )

    description = engine.describe(
        [image_data],
        "Briefly describe the main subject, setting, and mood of this image.",
    )
    print("\nVision output:\n")
    print(description)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
