import threading
import numpy as np
from typing import Optional, Dict, Any
from core.asr.base import BaseASRProvider

class LocalWhisperProvider(BaseASRProvider):
    """Local offline ASR provider using faster-whisper on CPU with int8 quantization."""

    def __init__(self, model_size: str = "base.en", cpu_threads: int = 4):
        super().__init__(name="Local CPU (faster-whisper)")
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self.model = None
        self.lock = threading.Lock()
        self._is_loading = False
        self._load_error: Optional[str] = None

    def _ensure_loaded(self):
        """Lazy-loads the faster-whisper model on first use."""
        if self.model is not None or self._is_loading:
            return
        
        with self.lock:
            if self.model is not None:
                return
            self._is_loading = True
            try:
                from faster_whisper import WhisperModel
                print(f"[LocalWhisper] Loading model '{self.model_size}' on CPU (int8, {self.cpu_threads} threads)...")
                self.model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self.cpu_threads
                )
                self._load_error = None
                print(f"[LocalWhisper] Model '{self.model_size}' loaded successfully.")
            except Exception as e:
                self._load_error = str(e)
                print(f"[LocalWhisper] Error loading model: {e}")
            finally:
                self._is_loading = False

    def is_available(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribes raw 16kHz PCM bytes using the local Whisper model."""
        if not pcm_bytes:
            return ""

        self._ensure_loaded()
        if self.model is None:
            raise RuntimeError(f"Local Whisper model failed to load: {self._load_error}")

        # Convert int16 PCM bytes to float32 numpy array normalized to [-1.0, 1.0]
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        with self.lock:
            segments, info = self.model.transcribe(
                audio_np,
                beam_size=1,            # Greedy decoding for lowest real-time latency
                language="en",
                vad_filter=False,       # Audio already segmented by VADSegmenter
                condition_on_previous_text=False
            )
            text_parts = [segment.text.strip() for segment in segments if segment.text.strip()]
            return " ".join(text_parts).strip()

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "model_size": self.model_size,
            "cpu_threads": self.cpu_threads,
            "is_loaded": self.model is not None,
            "load_error": self._load_error
        })
        return info
