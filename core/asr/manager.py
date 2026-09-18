import queue
import threading
from typing import Optional, Callable, Dict, Any
from core.copilot.segmenter import AudioSegment
from core.asr.base import BaseASRProvider
from core.asr.local_whisper import LocalWhisperProvider
from core.asr.websocket_mlx import MacWhisperMLXProvider
from core.asr.cloud_provider import CloudWhisperProvider

class ASRManager:
    """Manages active ASR provider, worker queues, and graceful fallbacks."""

    def __init__(self, on_transcription_callback: Callable[[AudioSegment, str], None]):
        self.on_transcription_callback = on_transcription_callback
        
        # Default providers
        self.local_provider = LocalWhisperProvider(model_size="base.en", cpu_threads=4)
        self.active_provider: BaseASRProvider = self.local_provider
        self.active_type = "local"
        
        # Audio queue and worker thread
        self.segment_queue: queue.Queue = queue.Queue(maxsize=100)
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def configure_provider(self, provider_type: str, settings: Optional[Dict[str, Any]] = None):
        """Switches active provider based on UI settings."""
        settings = settings or {}
        self.active_type = provider_type

        if provider_type == "local":
            model_size = settings.get("model_size", "base.en")
            cpu_threads = settings.get("cpu_threads", 4)
            self.local_provider = LocalWhisperProvider(model_size=model_size, cpu_threads=cpu_threads)
            self.active_provider = self.local_provider
            print(f"[ASRManager] Switched to Local CPU Whisper ({model_size})")

        elif provider_type == "mac_lan":
            endpoint = settings.get("mac_mlx_url", "http://192.168.0.88:9000")
            self.active_provider = MacWhisperMLXProvider(endpoint_url=endpoint)
            print(f"[ASRManager] Switched to Mac LAN Whisper-MLX ({endpoint})")

        elif provider_type == "groq":
            api_key = settings.get("groq_api_key", "")
            self.active_provider = CloudWhisperProvider(api_key=api_key, provider_type="groq")
            print("[ASRManager] Switched to Cloud: Groq Whisper-Large-v3")

        elif provider_type == "openai":
            api_key = settings.get("openai_api_key", "")
            self.active_provider = CloudWhisperProvider(api_key=api_key, provider_type="openai")
            print("[ASRManager] Switched to Cloud: OpenAI Whisper")

    def enqueue_segment(self, segment: AudioSegment):
        """Enqueue an audio segment for background transcription."""
        try:
            self.segment_queue.put_nowait(segment)
        except queue.Full:
            print("[ASRManager] Warning: Segment queue is full. Dropping oldest segment.")
            try:
                self.segment_queue.get_nowait()
                self.segment_queue.put_nowait(segment)
            except:
                pass

    def _worker_loop(self):
        """Dedicated background worker consuming audio segments and running ASR."""
        while self.is_running:
            try:
                segment: AudioSegment = self.segment_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            text = ""
            try:
                text = self.active_provider.transcribe(segment.pcm_bytes)
            except Exception as e:
                print(f"[ASRManager] Provider '{self.active_provider.name}' failed: {e}")
                
                # Automatic fallback to Local CPU if active provider is not local
                if self.active_provider != self.local_provider:
                    print("[ASRManager] Attempting fallback to Local CPU Whisper...")
                    try:
                        text = self.local_provider.transcribe(segment.pcm_bytes)
                    except Exception as fe:
                        print(f"[ASRManager] Local CPU fallback also failed: {fe}")

            if text and text.strip():
                try:
                    self.on_transcription_callback(segment, text.strip())
                except Exception as cb_err:
                    print(f"[ASRManager] Transcription callback error: {cb_err}")

            self.segment_queue.task_done()

    def shutdown(self):
        """Stops background ASR worker."""
        self.is_running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
