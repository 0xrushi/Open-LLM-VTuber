import numpy as np
from loguru import logger
from .wakeword_interface import WakewordInterface


class OpenWakeWordEngine(WakewordInterface):
    """Wakeword detection using the openwakeword library."""

    def __init__(
        self,
        wakeword_models: list[str],
        inference_framework: str = "onnx",
        model_threshold: float = 0.5,
        trigger_level: int = 3,
        chunk_size: int = 1280,
    ):
        from openwakeword.model import Model

        self.model_threshold = model_threshold
        self.trigger_level = trigger_level
        self.chunk_size = chunk_size  # samples per frame (1280 = 80ms at 16kHz)

        logger.info(
            f"Initializing openWakeWord with models={wakeword_models}, "
            f"framework={inference_framework}, threshold={model_threshold}, "
            f"trigger_level={trigger_level}"
        )

        self.oww_model = Model(
            wakeword_models=wakeword_models,
            inference_framework=inference_framework,
        )

        self._consecutive_hits: dict[str, int] = {
            mdl: 0 for mdl in self.oww_model.models.keys()
        }
        self._audio_buffer = np.array([], dtype=np.int16)

        logger.info(
            f"openWakeWord initialized. Listening for: "
            f"{list(self.oww_model.models.keys())}"
        )

    def process_audio(self, audio_bytes: bytes) -> bool:
        """Feed int16 PCM audio. Returns True when wakeword is detected."""
        chunk = np.frombuffer(audio_bytes, dtype=np.int16)
        self._audio_buffer = np.append(self._audio_buffer, chunk)

        triggered = False

        while len(self._audio_buffer) >= self.chunk_size:
            frame = self._audio_buffer[: self.chunk_size]
            self._audio_buffer = self._audio_buffer[self.chunk_size :]

            prediction = self.oww_model.predict(frame)

            for model_name, score in prediction.items():
                if score >= self.model_threshold:
                    self._consecutive_hits[model_name] += 1
                    if self._consecutive_hits[model_name] >= self.trigger_level:
                        logger.info(
                            f"Wakeword '{model_name}' detected! "
                            f"(score={score:.3f}, hits={self._consecutive_hits[model_name]})"
                        )
                        triggered = True
                        self._consecutive_hits[model_name] = 0
                else:
                    self._consecutive_hits[model_name] = 0

        return triggered

    def reset(self) -> None:
        """Reset detection state."""
        for key in self._consecutive_hits:
            self._consecutive_hits[key] = 0
        self._audio_buffer = np.array([], dtype=np.int16)
        self.oww_model.reset()
