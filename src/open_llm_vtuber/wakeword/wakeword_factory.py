from .wakeword_interface import WakewordInterface


class WakewordFactory:
    @staticmethod
    def get_wakeword_engine(engine_type: str, **kwargs) -> WakewordInterface:
        if engine_type == "openwakeword":
            from .openwakeword_engine import OpenWakeWordEngine

            return OpenWakeWordEngine(
                wakeword_models=kwargs.get("wakeword_models", ["hey_jarvis_v0.1"]),
                inference_framework=kwargs.get("inference_framework", "onnx"),
                model_threshold=kwargs.get("model_threshold", 0.5),
                trigger_level=kwargs.get("trigger_level", 3),
                chunk_size=kwargs.get("chunk_size", 1280),
            )
        raise ValueError(f"Unknown wakeword engine type: {engine_type}")
