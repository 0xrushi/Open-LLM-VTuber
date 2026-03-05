from abc import ABC, abstractmethod


class WakewordInterface(ABC):
    @abstractmethod
    def process_audio(self, audio_bytes: bytes) -> bool:
        """
        Process a chunk of int16 16kHz audio data.
        :param audio_bytes: Raw int16 PCM audio bytes at 16kHz
        :return: True if wakeword was detected
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state (e.g. consecutive hit counter)."""
        pass
