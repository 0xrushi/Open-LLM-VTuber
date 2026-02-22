import requests
import os
import re
from loguru import logger
from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    def __init__(
        self,
        api_url: str = "http://localhost:5000/synthesize",
        voice_id: str = "voice_01.wav",
        emo_text: str = None,
        use_streaming: bool = False,
        **kwargs
    ):
        """
        Custom TTS Engine for Open LLM VTuber using IndexTTS API.

        Args:
            api_url (str): The URL of the IndexTTS API server.
            voice_id (str): The filename of the speaker reference audio (e.g., 'voice_01.wav').
            emo_text (str): Optional default emotion description text.
            use_streaming (bool): Use streaming endpoint if available.
        """
        self.api_url = api_url
        self.voice_id = voice_id
        self.default_emo_text = emo_text
        self.use_streaming = use_streaming

        # Emotion mapping from keywords to IndexTTS format
        self.emotion_map = {
            "smirk": "Use sassy and smug tone",
            "joy": "Use happy and playful tone",
            "happy": "Use happy and excited tone",
            "anger": "Use annoyed and frustrated tone",
            "sad": "Use sad and disappointed tone",
            "sadness": "Use sad and melancholic tone",
            "surprise": "Use surprised and shocked tone",
            "surprised": "Use surprised and amazed tone",
            "fear": "Use nervous and worried tone",
            "neutral": "Use calm and normal tone",
            "disgust": "Use disgusted tone",
        }

        logger.info(f"IndexTTS Engine initialized with URL: {api_url}, Voice: {voice_id}")

    def _extract_emotion(self, text):
        """
        Extract emotion keywords from text and return cleaned text + emotion.

        Args:
            text (str): Text with possible emotion keywords like [happy], [smirk]

        Returns:
            tuple: (cleaned_text, emotion_description)
        """
        # Find all emotion keywords in brackets
        emotion_matches = re.findall(r'\[(\w+)\]', text.lower())

        # Remove emotion keywords from text
        cleaned_text = re.sub(r'\[\w+\]', '', text).strip()

        # Get the first emotion found, or use default
        emotion_description = None
        if emotion_matches:
            first_emotion = emotion_matches[0]
            emotion_description = self.emotion_map.get(first_emotion, first_emotion)
            logger.debug(f"Extracted emotion: [{first_emotion}] -> '{emotion_description}'")

        return cleaned_text, emotion_description

    def generate_audio(self, text, file_name_no_ext=None):
        """
        Generates audio from text using the IndexTTS API.
        Automatically extracts emotions from [keyword] tags.
        """
        # Extract emotion from text
        cleaned_text, detected_emotion = self._extract_emotion(text)

        # Use detected emotion, or fall back to default, or use neutral
        emo_text = detected_emotion or self.default_emo_text or "Use calm and normal tone"

        # Log what we're extracting
        logger.info(f"TTS Input: '{text[:80]}...' -> Detected: {detected_emotion}, Using: {emo_text}")

        # Generate output file path via the interface's helper method
        file_name = self.generate_cache_file_name(
            file_name_no_ext,
            file_extension="wav"
        )

        # Make API request
        try:
            payload = {
                "text": cleaned_text,  # Use cleaned text without emotion tags
                "voice_id": self.voice_id
            }
            if emo_text:
                payload["emo_text"] = emo_text
                logger.debug(f"Sending to TTS - Text: '{cleaned_text[:50]}...', Emotion: '{emo_text}'")

            # Use streaming endpoint if enabled
            endpoint = self.api_url
            if self.use_streaming and not endpoint.endswith('_stream'):
                # Try streaming endpoint first
                stream_endpoint = endpoint.replace('/synthesize', '/synthesize_stream')
                try:
                    response = requests.post(
                        stream_endpoint,
                        json=payload,
                        timeout=120,
                        stream=True  # Enable streaming
                    )
                    if response.status_code == 200:
                        # Save streamed audio
                        with open(file_name, "wb") as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        logger.success(f"TTS audio (streamed) saved to {file_name}")
                        return file_name
                except Exception as stream_error:
                    logger.warning(f"Streaming failed, falling back to regular: {stream_error}")

            # Regular non-streaming request
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=120
            )

            if response.status_code == 200:
                # Save audio file
                with open(file_name, "wb") as f:
                    f.write(response.content)
                logger.success(f"TTS audio saved to {file_name}")
                return file_name
            else:
                logger.error(f"TTS API failed with status {response.status_code}: {response.text}")
                return None

        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            return None
