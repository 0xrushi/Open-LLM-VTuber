import re
import requests
from loguru import logger

from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    """
    TTS engine for Chatterbox Turbo API endpoints (e.g. Segmind).
    """

    def __init__(
        self,
        api_url: str = "https://api.segmind.com/v1/chatterbox-turbo-tts",
        api_key: str | None = None,
        reference_audio_url: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        min_p: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        repetition_penalty: float | None = None,
        norm_loudness: bool | None = None,
        timeout_sec: int = 300,
        **kwargs,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.reference_audio_url = reference_audio_url
        self.temperature = temperature
        self.seed = seed
        self.min_p = min_p
        self.top_p = top_p
        self.top_k = top_k
        self.repetition_penalty = repetition_penalty
        self.norm_loudness = norm_loudness
        self.timeout_sec = timeout_sec
        self.file_extension = "wav"

        logger.info(
            "Chatterbox Turbo API TTS initialized: api_url={}",
            self.api_url,
        )

        self.paralinguistic_tags = {
            "laugh",
            "chuckle",
            "sigh",
            "gasp",
            "cough",
            "clear throat",
            "sniff",
            "groan",
            "shush",
        }
        self.emotion_tags = {
            "neutral",
            "anger",
            "disgust",
            "fear",
            "joy",
            "smirk",
            "sadness",
            "surprise",
            "happy",
            "sad",
            "surprised",
        }

    def _sanitize_text(self, text: str) -> tuple[str, list[str], list[str]]:
        detected_emotions: list[str] = []
        kept_audio_tags: list[str] = []

        def _replace(match: re.Match) -> str:
            raw_tag = match.group(1).strip()
            normalized = re.sub(r"\s+", " ", raw_tag.lower())
            if normalized in self.paralinguistic_tags:
                kept_audio_tags.append(normalized)
                return f"[{normalized}]"
            if normalized in self.emotion_tags:
                detected_emotions.append(normalized)
                return ""
            return ""

        cleaned = re.sub(r"\[([^\]]+)\]", _replace, text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned, detected_emotions, kept_audio_tags

    def _content_type_to_ext(self, content_type: str) -> str:
        lowered = (content_type or "").lower()
        if "mpeg" in lowered or "mp3" in lowered:
            return "mp3"
        if "ogg" in lowered or "opus" in lowered:
            return "opus"
        if "wav" in lowered:
            return "wav"
        return "wav"

    def _build_payload(self, text: str) -> dict:
        payload = {
            "text": text,
            "reference_audio": self.reference_audio_url,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.min_p is not None:
            payload["min_p"] = self.min_p
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        if self.repetition_penalty is not None:
            payload["repetition_penalty"] = self.repetition_penalty
        if self.norm_loudness is not None:
            payload["norm_loudness"] = self.norm_loudness
        return payload

    def generate_audio(self, text: str, file_name_no_ext=None):
        if not self.api_key:
            raise RuntimeError("Chatterbox Turbo API key is required.")
        if not self.reference_audio_url:
            raise RuntimeError("Chatterbox Turbo reference_audio_url is required.")

        tts_text, emotion_tags, audio_tags = self._sanitize_text(text)
        payload = self._build_payload(tts_text)
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        logger.info(
            "[ChatterboxTurboAPI] sanitized_text='{}' emotions={} audio_tags={}",
            tts_text[:160],
            emotion_tags,
            audio_tags,
        )

        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_sec,
            )
        except Exception as e:
            logger.error(f"Chatterbox Turbo API request failed: {e}")
            raise RuntimeError(f"Chatterbox Turbo API request failed: {e}") from e

        if resp.status_code != 200:
            message = (
                f"Chatterbox Turbo API failed: status={resp.status_code}, body={resp.text[:500]}"
            )
            logger.error(message)
            raise RuntimeError(message)

        ext = self._content_type_to_ext(resp.headers.get("Content-Type", ""))
        file_name = self.generate_cache_file_name(file_name_no_ext, ext)
        try:
            with open(file_name, "wb") as f:
                f.write(resp.content)
            logger.success(f"Chatterbox Turbo API audio saved to {file_name}")
            return file_name
        except Exception as e:
            logger.error(f"Failed to save Chatterbox Turbo API audio: {e}")
            raise RuntimeError(f"Failed to save Chatterbox Turbo API audio: {e}") from e
