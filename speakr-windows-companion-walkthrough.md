---
title: "Speakr Windows Companion Walkthrough"
type: synthesis
tags:
  - synthesis
  - speakr
  - windows
  - walkthrough
updated: "2026-09-01"
---

# Speakr Windows Companion App Walkthrough

We have designed, implemented, debugged, and verified the **Speakr Windows Companion App**. The app runs in the system tray and taskbar with custom artwork, capturing microphone and system audio via WASAPI Loopback, monitoring meeting processes (Zoom, Teams, Citrix), and uploading recordings.

---

## Project Structure & File Index

The application files are organized under `c:\Temp\Google_Antigravity\speakr_compainion\`:

- [**`requirements.txt`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/requirements.txt): Third-party dependencies (PySide6, pyaudiowpatch, psutil, httpx, av, Pillow).
- [**`main.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/main.py): Main entry point configuring QApplication, Windows AppUserModelID, system tray settings, and signaling.
- **`core/`**:
  - [**`config.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/core/config.py): Configuration manager reading and writing `settings.json` under AppData. Contains `recording_format` preference (`"mp4"` or `"wav"`), `get_resource_path()`, and `get_app_icon()`.
  - [**`client.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/core/client.py): Speakr REST API Client. Handles `/recordings/upload`, `/tags`, and `/recordings/{id}/tags` with dynamic MIME type resolution (`audio/mp4` vs `audio/wav`).
  - [**`recorder.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/core/recorder.py): Audio capture backend combining Microphone (MME) and WASAPI Loopback into 16kHz mono audio. Encodes to MP4 (AAC @ 64 kbps) via PyAV or writes uncompressed PCM WAV.
  - [**`monitor.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/core/monitor.py): Polling daemon monitoring process triggers (Zoom, Teams, Citrix Viewer) with dynamic format file generation and manual recording collision protection.
  - [**`uploader.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/core/uploader.py): Controls API multi-part uploads and folder synchronization (polling `original_filename` to apply tags).
- **`gui/`**:
  - [**`widgets.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/gui/widgets.py): Custom PySide6 components (`VolumeMeter` with peak decay and `TagSelector`).
  - [**`main_window.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/gui/main_window.py): Tabbed layout, dashboard, preferences (including real-time Audio Format selector), status bar, and upload buttons.
  - [**`tray_icon.py`**](file:///c:/Temp/Google_Antigravity/speakr_compainion/gui/tray_icon.py): Windows tray Actions, custom icon integration, state synchronization, and notifications.

---

## 🔍 Feature Implementations & Root Cause Fixes

### 1. MP4 (AAC) Format Support & Dynamic Real-Time Format Switching
- **Feature:** Added native AAC compression in an MP4 container (`64 kbps mono AAC @ 16kHz`) using PyAV.
- **Dynamic Preference:** Added an **Audio Encoding** dropdown in the Preferences tab (`MP4 (AAC Compressed - Recommended)` / `WAV (Uncompressed PCM)`). Changing this setting takes effect immediately on all subsequent recordings without requiring an application restart.
- **Benefits:**
  - **~5x–10x smaller file sizes** (~25 MB/hr for MP4 vs ~115 MB/hr for WAV).
  - Faster API and NAS sync uploads.
  - Fully self-contained inside the executable without requiring external `ffmpeg.exe` binaries on user systems.

### 2. Speakr API Upload Route Resolution
- **Root Cause:** `upload_recording()` attempted to POST to `/api/upload` (which returned 404), whereas Speakr's audio ingestion route is `/api/v1/recordings/upload` (accepts multipart forms and returns HTTP 202 Accepted).
- **Fix:** Corrected endpoint to `{self.base_url}/recordings/upload`, added automatic `/api/v1` URL normalization, and dynamic MIME types.

### 3. Syncthing NAS Folder Tagging Resolution
- **Root Cause:** Ingested files were stored by Speakr under `rec.get("original_filename")`, but the uploader only checked `rec.get("file_path")` or `rec.get("filename")`.
- **Fix:** Updated `_poll_and_tag()` to check `original_filename`, `filename`, and `title` case-insensitively.

### 4. Auto/Manual Recording State Synchronization
- **Fix:** Added thread-safe Qt signals (`auto_record_start_signal`, `auto_record_finish_signal`) to bridge background monitor events directly into the main GUI thread, and protected manual recordings from being hijacked by process triggers.

### 6. Live Duration Timer & Context-Aware Meters
- **Live Elapsed Timer:** Real-time timer (`HH:MM:SS`) in the dashboard status card, status bar, and tray tooltip while recording is active.
- **Context-Aware Meters:** Replaced "Mute" with intuitive statuses (`Microphone: Idle (Listening...)`, `Speakers: Idle (Silent)`).

### 7. Dynamic Status Badging on System Tray
- Dynamic status indicator dots rendered over the application icon:
  - 🟢 **Green:** Ready / Idle
  - 🔴 **Red:** Recording active (with live timer in tooltip)
  - 🟡 **Yellow:** Recording paused
  - 🟠 **Orange:** Cooldown active

### 8. Post-Stop Cooldown Delay (1 Minute)
- 60-second cooldown timer prevents accidental double-clicking of the stop button and rapid auto-retrigger loops (with manual skip option).

### 9. Persistent Local Storage, Retention Auto-Pruning & Recordings History Tab
- **Local Retention Policy:** Retains all manual and auto-uploaded recordings locally in a configurable folder with automated retention expiration pruning (default: 30 days).
- **Non-Destructive Ingestion:** Recordings are preserved on disk after upload and never prematurely wiped.
- **Recordings History Tab:** Comprehensive library with recording metadata (date, duration, size, trigger, upload status) and one-click **Re-Upload**, **Play**, and **Open Folder** actions.

### 10. Local Closed Captioning (On-Device ASR)
- **Local Architecture:** Faster-Whisper on CPU/DirectML with zero external network transmission.

---

## 🛠️ Verification Results

### 1. Storage & Retention Pruning Tests (`test_storage_and_retention.py`)
- **Metadata Management:** Verified adding, updating status, and loading history items.
- **Formatters:** Verified `HH:MM:SS` and human-readable byte size formatters.
- **Retention Pruning:** Verified that files older than 30 days are automatically pruned while preserving recent recordings.

### 2. Post-Stop Cooldown Tests (`test_cooldown.py`)
- **Cooldown Arming & Countdown:** Verified cooldown activation and callback dispatch.
- **Trigger Blocking:** Verified that manual start and auto-triggers are blocked during cooldown.
- **Cooldown Skip:** Verified instant re-arming when skipped.

### 3. UI Widgets & Badged Tray Tests (`test_widgets_and_tray.py`)
- **Volume Meters:** Verified context-aware idle labels (`Idle (Listening...)`, `Idle (Silent)`).
- **Badged Tray Icons:** Verified rendering of ready (green), recording (red), paused (yellow), and cooldown (orange) icon pixmaps.

### 4. Citrix Audio-Gating & Debounce Tests (`test_citrix_monitor.py` & `test_citrix_full_simulation.py`)
- Verified all 7 unit and lifecycle simulation tests covering process matching (`wfica32.exe`, `MsTeamsVdi.exe`, etc.), peak meter range validation, 2s debounce gating, 5-minute silence stop, and <30s discard filter.

---

## 📦 Distribution Guide (Windows 11)

To compile the companion application into a single standalone `.exe` executable for deployment:

```powershell
.venv\Scripts\pyinstaller.exe --clean SpeakrCompanion.spec
```
Standalone executable location:
`c:\Temp\Google_Antigravity\speakr_compainion\dist\SpeakrCompanion.exe`


