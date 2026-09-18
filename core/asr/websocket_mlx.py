import io
import wave
import httpx
from typing import Optional, Dict, Any
from core.asr.base import BaseASRProvider

class MacWhisperMLXProvider(BaseASRProvider):
    """ASR Provider connecting over LAN to Apple Silicon Whisper-MLX server."""

    def __init__(self, endpoint_url: str = "http://192.168.0.88:9000", timeout_seconds: float = 4.0):
        super().__init__(name="Mac Whisper-MLX (LAN)")
        self.endpoint_url = endpoint_url.rstrip("/")
        self.timeout = timeout_seconds

    def is_available(self) -> bool:
        """Tests if the LAN endpoint is reachable."""
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(f"{self.endpoint_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Packages PCM bytes into a temporary WAV container and sends to Whisper-MLX /asr."""
        if not pcm_bytes:
            return ""

        # Wrap PCM into in-memory WAV
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        wav_bytes = wav_io.getvalue()

        # Post to /asr endpoint
        files = {"audio_file": ("chunk.wav", wav_bytes, "audio/wav")}
        data = {"task": "transcribe", "language": "en", "diarize": "false"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.endpoint_url}/asr", files=files, data=data)
                if resp.status_code == 200:
                    payload = resp.json()
                    # Parse standard whisper output
                    if isinstance(payload, dict):
                        return payload.get("text", "").strip()
                    elif isinstance(payload, list) and len(payload) > 0:
                        return payload[0].get("text", "").strip()
                    return str(payload).strip()
                else:
                    raise RuntimeError(f"Whisper-MLX returned HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            raise RuntimeError(f"Failed connecting to Mac Whisper-MLX ({self.endpoint_url}): {e}")

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({"endpoint_url": self.endpoint_url})
        return info
