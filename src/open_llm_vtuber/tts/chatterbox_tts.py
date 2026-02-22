import requests
import re
from loguru import logger

from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    """
    TTS engine for devnen/Chatterbox-TTS-Server custom endpoint (/tts).
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8004/tts",
        voice_mode: str = "predefined",
        predefined_voice_id: str | None = "default_sample.wav",
        reference_audio_filename: str | None = None,
        output_format: str = "wav",
        split_text: bool = True,
        chunk_size: int = 120,
        temperature: float | None = None,
        exaggeration: float | None = None,
        cfg_weight: float | None = None,
        seed: int | None = None,
        speed_factor: float | None = None,
        language: str | None = None,
        timeout_sec: int = 300,
        **kwargs,
    ):
        self.api_url = api_url
        self.voice_mode = voice_mode
        self.predefined_voice_id = predefined_voice_id
        self.reference_audio_filename = reference_audio_filename
        self.output_format = output_format
        self.split_text = split_text
        self.chunk_size = chunk_size
        self.temperature = temperature
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        self.seed = seed
        self.speed_factor = speed_factor
        self.language = language
        self.timeout_sec = timeout_sec

        # Align cached extension with desired response format.
        self.file_extension = output_format if output_format in {"wav", "mp3", "opus"} else "wav"

        logger.info(
            f"Chatterbox TTS initialized: api_url={self.api_url}, "
            f"voice_mode={self.voice_mode}, output_format={self.output_format}"
        )

        # Chatterbox Turbo paralinguistic tags that should be preserved in audio text.
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

        # Emotion tags used by the avatar/UI that should NOT be sent to Chatterbox.
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

    def _sanitize_text_for_chatterbox(self, text: str) -> tuple[str, list[str], list[str]]:
        """
        Keep only supported paralinguistic bracket tags in the TTS text.
        Strip emotion tags (e.g. [smirk]) from audio text but return them for logging.
        """
        detected_emotions: list[str] = []
        kept_audio_tags: list[str] = []

        def _replace(match: re.Match) -> str:
            raw_tag = match.group(1).strip()
            normalized = re.sub(r"\s+", " ", raw_tag.lower())
            if normalized in self.paralinguistic_tags:
                kept_audio_tags.append(normalized)
                # Normalize spacing/casing in outgoing tag.
                return f"[{normalized}]"
            if normalized in self.emotion_tags:
                detected_emotions.append(normalized)
                return ""
            # Unknown tags are dropped for safety.
            return ""

        cleaned = re.sub(r"\[([^\]]+)\]", _replace, text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned, detected_emotions, kept_audio_tags

    def _build_payload(self, text: str) -> dict:
        payload = {
            "text": text,
            "voice_mode": self.voice_mode,
            "output_format": self.output_format,
            "split_text": self.split_text,
            "chunk_size": self.chunk_size,
        }

        if self.voice_mode == "clone":
            if self.reference_audio_filename:
                payload["reference_audio_filename"] = self.reference_audio_filename
        else:
            if self.predefined_voice_id:
                payload["predefined_voice_id"] = self.predefined_voice_id

        # Optional advanced params supported by Chatterbox server.
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.exaggeration is not None:
            payload["exaggeration"] = self.exaggeration
        if self.cfg_weight is not None:
            payload["cfg_weight"] = self.cfg_weight
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.speed_factor is not None:
            payload["speed_factor"] = self.speed_factor
        if self.language is not None:
            payload["language"] = self.language

        return payload

    def generate_audio(self, text: str, file_name_no_ext=None):
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)
        tts_text, emotion_tags, audio_tags = self._sanitize_text_for_chatterbox(text)
        payload = self._build_payload(tts_text)

        logger.info(
            "[ChatterboxTTS] sanitized_text='{}' emotions={} audio_tags={}",
            tts_text[:160],
            emotion_tags,
            audio_tags,
        )

        try:
            resp = requests.post(self.api_url, json=payload, timeout=self.timeout_sec)
        except Exception as e:
            logger.error(f"Chatterbox TTS request failed: {e}")
            raise RuntimeError(f"Chatterbox TTS request failed: {e}") from e

        if resp.status_code != 200:
            message = (
                f"Chatterbox TTS failed: status={resp.status_code}, body={resp.text[:500]}"
            )
            logger.error(message)
            raise RuntimeError(message)

        try:
            with open(file_name, "wb") as f:
                f.write(resp.content)
            logger.success(f"Chatterbox audio saved to {file_name}")
            return file_name
        except Exception as e:
            logger.error(f"Failed to save Chatterbox audio: {e}")
            raise RuntimeError(f"Failed to save Chatterbox audio: {e}") from e
