import os
import shutil
import time
import threading
from pathlib import Path
from typing import List, Optional, Callable
from core.config import Settings
from core.client import SpeakrClient
from core.storage import RecordingsManager

class AudioUploader:
    """Handles uploading finished recordings via Speakr API or copying to NAS folder."""

    def __init__(
        self, 
        settings: Settings, 
        storage: Optional[RecordingsManager] = None,
        status_callback: Optional[Callable[[str, bool], None]] = None
    ):
        self.settings = settings
        self.storage = storage
        self.status_callback = status_callback  # callback(message, success_flag)

    def process_file(self, file_path: str, tag_ids: List[int]) -> None:
        """Entry point to process a finished recording in a background thread."""
        abs_path = str(Path(file_path).resolve())
        if not os.path.exists(abs_path):
            # Try finding it relative to settings.resolved_recordings_dir
            candidate = str((self.settings.resolved_recordings_dir / os.path.basename(file_path)).resolve())
            if os.path.exists(candidate):
                abs_path = candidate
            else:
                self._notify(f"Recording file not found: {os.path.basename(file_path)}", False)
                if self.storage:
                    self.storage.update_status(file_path, "File Missing")
                return

        if self.storage:
            self.storage.update_status(file_path, "Uploading...")

        thread = threading.Thread(target=self._process_background, args=(abs_path, tag_ids, file_path), daemon=True)
        thread.start()

    def _notify(self, message: str, success: bool) -> None:
        """Helper to invoke status callback safely."""
        if self.status_callback:
            try:
                self.status_callback(message, success)
            except Exception as e:
                print(f"[Uploader] Callback error: {e}")

    def _resolve_notes(self, abs_path: str, original_ref_path: str) -> tuple[Optional[str], Optional[str]]:
        """
        Locates the associated notes file (if any) and returns (notes_path, notes_content).
        """
        notes_path: Optional[str] = None
        if self.storage:
            rec = self.storage.get_recording(original_ref_path) or self.storage.get_recording(abs_path)
            if rec and rec.get("notes_path"):
                cand = rec["notes_path"]
                if os.path.exists(cand):
                    notes_path = cand

        if not notes_path:
            stem = Path(abs_path).stem
            cand = Path(abs_path).with_name(f"{stem}_Notes.md")
            if cand.exists():
                notes_path = str(cand.resolve())

        notes_content: Optional[str] = None
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    notes_content = f.read()
            except Exception as e:
                print(f"[Uploader] Error reading notes file {notes_path}: {e}")

        return notes_path, notes_content

    def _process_background(self, abs_path: str, tag_ids: List[int], original_ref_path: str) -> None:
        """Background thread execution."""
        try:
            mode = self.settings.upload_mode
            server_conf = self.settings.active_server
            client = SpeakrClient(base_url=server_conf["url"], api_key=server_conf["api_key"])
            
            filename = os.path.basename(abs_path)
            title = os.path.splitext(filename)[0]

            notes_path, notes_text = self._resolve_notes(abs_path, original_ref_path)
            if notes_text:
                print(f"[Uploader] Found associated Copilot notes for '{filename}' ({len(notes_text)} chars)")

            if mode == "api":
                size_str = RecordingsManager.format_size(os.path.getsize(abs_path)) if os.path.exists(abs_path) else ""
                has_notes_msg = " with live notes" if notes_text else ""
                self._notify(f"Uploading '{filename}' ({size_str}){has_notes_msg} via Speakr API...", True)
                
                prompt_vars = {"copilot_notes": notes_text} if notes_text else None
                rec_id = client.upload_recording(
                    abs_path, 
                    title=title, 
                    notes=notes_text, 
                    prompt_variables=prompt_vars
                )
                
                if rec_id:
                    print(f"[Uploader] Upload successful. Recording ID: {rec_id}")
                    if self.storage:
                        self.storage.update_status(original_ref_path, "Uploaded", str(rec_id))
                        self.storage.update_status(abs_path, "Uploaded", str(rec_id))

                    # Ensure notes are attached via PUT /notes
                    if notes_text:
                        client.replace_recording_notes(str(rec_id), notes_text)

                    if tag_ids:
                        self._notify("Applying tags to recording...", True)
                        tagged = client.add_recording_tags(str(rec_id), tag_ids)
                        if tagged:
                            self._notify(f"Successfully uploaded and tagged recording '{title}'!", True)
                        else:
                            self._notify(f"Uploaded '{title}', but failed to apply tags.", False)
                    else:
                        self._notify(f"Successfully uploaded recording '{title}'!", True)
                else:
                    if self.storage:
                        self.storage.update_status(original_ref_path, "Upload Failed")
                        self.storage.update_status(abs_path, "Upload Failed")
                    self._notify(f"API upload failed for '{filename}'. Check server URL and key.", False)

            elif mode == "folder":
                dest_dir = self.settings.nas_folder_path
                if not os.path.exists(dest_dir):
                    if self.storage:
                        self.storage.update_status(original_ref_path, "NAS Path Missing")
                        self.storage.update_status(abs_path, "NAS Path Missing")
                    self._notify(f"NAS folder path not found: {dest_dir}", False)
                    return

                dest_path = os.path.join(dest_dir, filename)
                self._notify(f"Copying '{filename}' to NAS folder...", True)
                
                try:
                    shutil.copy2(abs_path, dest_path)
                    
                    # Also copy notes file alongside audio if present
                    if notes_path and os.path.exists(notes_path):
                        try:
                            notes_dest = os.path.join(dest_dir, os.path.basename(notes_path))
                            shutil.copy2(notes_path, notes_dest)
                            print(f"[Uploader] Copied notes to NAS folder: {notes_dest}")
                        except Exception as ne:
                            print(f"[Uploader] Warning: Could not copy notes to NAS: {ne}")

                    if self.storage:
                        self.storage.update_status(original_ref_path, "Copied to NAS")
                        self.storage.update_status(abs_path, "Copied to NAS")
                    self._notify(f"Copied '{filename}' to NAS share.", True)
                    
                    # If tags or notes need to be applied on Speakr server, start polling
                    if (tag_ids or notes_text) and server_conf.get("api_key"):
                        polling_thread = threading.Thread(
                            target=self._poll_and_tag,
                            args=(client, filename, tag_ids, abs_path, original_ref_path, notes_text),
                            daemon=True
                        )
                        polling_thread.start()
                    else:
                        self._notify(f"Recording '{title}' saved to NAS.", True)
                except Exception as e:
                    if self.storage:
                        self.storage.update_status(original_ref_path, "Copy Failed")
                        self.storage.update_status(abs_path, "Copy Failed")
                    self._notify(f"Failed to copy to NAS: {e}", False)
        except Exception as ex:
            print(f"[Uploader] Exception during processing: {ex}")
            if self.storage:
                self.storage.update_status(original_ref_path, "Upload Failed")
                self.storage.update_status(abs_path, "Upload Failed")
            self._notify(f"Upload error: {ex}", False)

    def _poll_and_tag(
        self, 
        client: SpeakrClient, 
        filename: str, 
        tag_ids: List[int], 
        file_path: str, 
        original_ref_path: str, 
        notes_text: Optional[str] = None,
        timeout_mins: int = 10
    ) -> None:
        """Polls the Speakr API to match the ingested folder file and apply tags / notes."""
        self._notify(f"Waiting for Speakr to process Syncthing file...", True)
        title = os.path.splitext(filename)[0]
        start_time = time.time()
        timeout_secs = timeout_mins * 60
        poll_interval = 15.0  # seconds

        while time.time() - start_time < timeout_secs:
            print(f"[Uploader] Polling Speakr API for file: {filename}...")
            recordings = client.list_recordings()
            
            # Look for matching recording in Speakr
            match_id = None
            for rec in recordings:
                rec_orig = str(rec.get("original_filename") or "")
                rec_file = str(rec.get("file_path") or rec.get("filename") or "")
                rec_title = str(rec.get("title") or "")
                
                # Check for match (case-insensitive)
                if (filename.lower() == rec_orig.lower() or 
                    filename.lower() in rec_file.lower() or 
                    title.lower() == rec_title.lower() or 
                    title.lower() == os.path.splitext(rec_orig)[0].lower()):
                    match_id = rec.get("id") or rec.get("recording_id")
                    break

            if match_id:
                print(f"[Uploader] Matched recording ID: {match_id} for file {filename}")
                if self.storage:
                    self.storage.update_status(original_ref_path, "Uploaded", str(match_id))
                    self.storage.update_status(file_path, "Uploaded", str(match_id))

                if notes_text:
                    client.replace_recording_notes(str(match_id), notes_text)
                    print(f"[Uploader] Attached Copilot notes to matched recording {match_id}")

                if tag_ids:
                    self._notify("Applying tags to processed recording...", True)
                    tagged = client.add_recording_tags(str(match_id), tag_ids)
                    if tagged:
                        self._notify(f"Successfully tagged NAS recording '{title}'!", True)
                    else:
                        self._notify(f"Failed to apply tags to NAS recording '{title}'.", False)
                else:
                    self._notify(f"Matched and updated NAS recording '{title}' in Speakr!", True)
                return

            time.sleep(poll_interval)

        self._notify(f"Polling timeout. Could not tag NAS recording '{title}'.", False)
