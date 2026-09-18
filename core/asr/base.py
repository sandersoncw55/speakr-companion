from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseASRProvider(ABC):
    """Abstract Base Class for pluggable ASR (Speech-to-Text) providers."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe raw 16kHz 16-bit mono PCM bytes into text."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if the provider is initialized, reachable, or configured."""
        pass

    def get_info(self) -> Dict[str, Any]:
        """Returns diagnostic metadata about the provider."""
        return {
            "name": self.name,
            "available": self.is_available()
        }
