import abc
import asyncio
from typing import List

from ..agent.input_types import ImageData


class VisionInterface(metaclass=abc.ABCMeta):
    """Base interface for vision models that summarize user images."""

    async def async_describe(self, images: List[ImageData], user_text: str) -> str:
        """Asynchronously summarize images for downstream LLM context."""
        return await asyncio.to_thread(self.describe, images, user_text)

    @abc.abstractmethod
    def describe(self, images: List[ImageData], user_text: str) -> str:
        """Summarize images for downstream LLM context."""
        raise NotImplementedError
