import io
import wave
import httpx
from typing import Optional, Dict, Any
from core.asr.base import BaseASRProvider

class CloudWhisperProvider(BaseASRProvider):
    """Cloud-accelerated Whisper provider (e.g. Groq, OpenAI, or custom OpenAI-compatible API)."""

    def __init__(
        self,
        api_key: str = "",
        provider_type: str = "groq",  # "groq", "openai", "custom"
        endpoint_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        name = "Cloud: Groq (Whisper-Large-v3)" if provider_type == "groq" else f"Cloud: {provider_type.capitalize()}"
        super().__init__(name=name)
        
        self.api_key = api_key
        self.provider_type = provider_type
        
        if provider_type == "groq":
            self.endpoint = endpoint_url or "https://api.groq.com/openai/v1/audio/transcriptions"
            self.model = model_name or "whisper-large-v3-turbo"
        elif provider_type == "openai":
            self.endpoint = endpoint_url or "https://api.openai.com/v1/audio/transcriptions"
            self.model = model_name or "whisper-1"
        else:
            self.endpoint = endpoint_url or "https://api.groq.com/openai/v1/audio/transcriptions"
            self.model = model_name or "whisper-large-v3-turbo"

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Uploads WAV PCM chunk to cloud transcription API."""
        if not pcm_bytes:
            return ""

        if not self.is_available():
            raise RuntimeError(f"Missing API key for {self.name}")

        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        wav_bytes = wav_io.getvalue()

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}"
        }
        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav")
        }
        data = {
            "model": self.model,
            "response_format": "json",
            "language": "en"
        }

        try:
            with httpx.Client(timeout=6.0) as client:
                resp = client.post(self.endpoint, headers=headers, files=files, data=data)
                if resp.status_code == 200:
                    result = resp.json()
                    return result.get("text", "").strip()
                else:
                    raise RuntimeError(f"Cloud ASR error (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            raise RuntimeError(f"Cloud transcription request failed: {e}")

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "provider_type": self.provider_type,
            "model": self.model,
            "endpoint": self.endpoint,
            "has_key": self.is_available()
        })
        return info
