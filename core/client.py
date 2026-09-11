import os
from typing import Dict, Any, List, Optional
import httpx

class SpeakrClient:
    """Synchronous REST API Client for Speakr."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        # Normalize base URL to ensure /api/v1 prefix
        base = base_url.rstrip("/")
        if not base.endswith("/api/v1") and "/api/v1" not in base:
            base = f"{base}/api/v1"
        self.base_url = base
        self.api_key = api_key

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def list_tags(self) -> List[Dict[str, Any]]:
        """Fetch all tags from Speakr."""
        url = f"{self.base_url}/tags"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=self._get_headers())
                resp.raise_for_status()
                data = resp.json()
                # If server returns a dict, extract lists if present
                if isinstance(data, dict):
                    return data.get("tags", [])
                elif isinstance(data, list):
                    return data
                return []
        except Exception as e:
            print(f"[SpeakrClient] Error listing tags: {e}")
            return []

    def upload_recording(self, file_path: str, title: Optional[str] = None) -> Optional[str]:
        """
        Uploads an audio file via the POST /recordings/upload endpoint.
        Returns the recording ID if successful, else None.
        """
        url = f"{self.base_url}/recordings/upload"
        mime_type = "audio/mp4" if file_path.lower().endswith(".mp4") else "audio/wav"
        
        try:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, mime_type)}
                data = {}
                if title:
                    data["title"] = title

                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(url, files=files, data=data, headers=self._get_headers())
                    if resp.status_code in (200, 201, 202):
                        result = resp.json()
                        return result.get("id") or result.get("recording_id")
                    else:
                        print(f"[SpeakrClient] Upload HTTP {resp.status_code}: {resp.text}")
                        return None
        except Exception as e:
            print(f"[SpeakrClient] Upload failed: {e}")
            return None

    def add_recording_tags(self, recording_id: str, tag_ids: List[int]) -> bool:
        """Assign tags to a specific recording in Speakr."""
        url = f"{self.base_url}/recordings/{recording_id}/tags"
        payload = {"tag_ids": tag_ids}
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload, headers=self._get_headers())
                resp.raise_for_status()
                return True
        except Exception as e:
            print(f"[SpeakrClient] Error assigning tags to recording {recording_id}: {e}")
            return False

    def list_recordings(self) -> List[Dict[str, Any]]:
        """List recordings to match files in Syncthing mode."""
        url = f"{self.base_url}/recordings"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=self._get_headers())
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    return data.get("recordings", [])
                elif isinstance(data, list):
                    return data
                return []
        except Exception as e:
            print(f"[SpeakrClient] Error listing recordings: {e}")
            return []
