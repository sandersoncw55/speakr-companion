# Speakr Windows Companion App

[![Release](https://img.shields.io/github/v/release/sandersoncw55/speakr-companion?color=blue&label=Latest%20Release)](https://github.com/sandersoncw55/speakr-companion/releases/latest)
[![Windows 11 / 10](https://img.shields.io/badge/Platform-Windows%2011%20%2F%2010%20(x64)-0078D6?logo=windows)](https://github.com/sandersoncw55/speakr-companion/releases/latest)
[![CI Release](https://github.com/sandersoncw55/speakr-companion/actions/workflows/release.yml/badge.svg)](https://github.com/sandersoncw55/speakr-companion/actions/workflows/release.yml)

A lightweight background desktop utility for Windows 11/10 designed to capture, manage, tag, and upload meeting recordings automatically to your self-hosted [**Speakr**](https://github.com/murtaza-nasir/speakr) instance.

---

## 📥 Quick Download & Installation

Download the latest version from [**GitHub Releases**](https://github.com/sandersoncw55/speakr-companion/releases/latest):

| Package | Description | Recommended For |
| :--- | :--- | :--- |
| 🚀 [**`SpeakrCompanion-Setup-v1.0.0.exe`**](https://github.com/sandersoncw55/speakr-companion/releases/download/v1.0.0/SpeakrCompanion-Setup-v1.0.0.exe) | Standard Windows Setup Wizard with Start Menu & Desktop shortcuts, optional auto-start on boot, and uninstaller. | **All Users (Standard Install)** |
| 🗜️ [**`SpeakrCompanion_Portable_v1.0.0.zip`**](https://github.com/sandersoncw55/speakr-companion/releases/download/v1.0.0/SpeakrCompanion_Portable_v1.0.0.zip) | Standalone portable archive containing `SpeakrCompanion.exe`. No installation required. | **USB Drives / Portable Use** |

> [!NOTE]
> The setup installer runs as a standard per-user installation in `%LOCALAPPDATA%\Programs\Speakr Companion` and does not require Administrator privileges or UAC elevation.

---

## ✨ Companion App Features

- **Dual-Stream Audio Capture:** Simultaneously records your microphone and system audio (speakers) via WASAPI loopback without requiring active window focus.
- **Dynamic Tagging:** Fetches your active tags directly from Speakr's REST API. Allows you to tag meetings before or during recording.
- **Live Recording Duration Timer:** Real-time timer display (`HH:MM:SS`) in the dashboard status card, status bar, and tray tooltip while active.
- **Context-Aware Level Meters:** Clear indicators (`Idle (Listening...)`, `Idle (Silent)`) when devices are quiet instead of confusing "Mute" text.
- **Dynamic System Tray Status Badges:** Color-coded status dots on the tray icon (🟢 Green = Ready, 🔴 Red = Recording, 🟡 Yellow = Paused, 🟠 Orange = Cooldown).
- **Post-Stop Cooldown Delay (1 Minute):** 60-second delay preventing accidental double-clicking of the stop button and rapid auto-retrigger loops.
- **Persistent Local Storage & 30-Day Retention:** Retains all manual and auto-uploaded recordings locally in a configurable folder with automated retention expiration pruning and a dedicated **Recordings History** library with one-click **Re-Upload** and playback.
- **Process Activity Monitor (Auto-Record):**
  - **Zoom:** Automatically starts recording when `CptHost.exe` launches and stops when it terminates.
  - **Teams:** Automatically captures call audio when Microsoft Teams (`Teams.exe` / `ms-teams.exe`) is active.
  - **Citrix (Audio-Gated):** Detects Citrix Viewer / Workspace / ICA Engine (`wfica32.exe`, `Citrix.DesktopViewer.App.exe`, `Receiver.exe`, `wfcrun32.exe`, `CitrixWorkspace.exe`, `MsTeamsVdi.exe`, `cdviewer.exe`).
    - **Continuous Metering:** Meters Citrix audio output in the background via Windows Core Audio (`pycaw`).
    - **2-Second Debounce:** Automatically triggers recording only when Citrix meeting audio consistently exceeds **−48 dB for at least 2.0 seconds**.
    - **5-Minute Silence Tolerance:** Stops recording when silence reaches 5 minutes (300s) and returns to audio-gated monitoring.
    - **Post-Record Filter:** Automatically discards recordings with < 30 seconds of active audio to eliminate notification dings.
- **Flexible Upload Ingestion:**
  - **API Upload:** Post recordings and tags directly to the Speakr server via REST API.
  - **Folder Copy:** Drop recordings into a local directory mapped to your Syncthing NAS Share (`Z:\AudioRecordings\Inbox`). The companion app automatically polls the Speakr API to match and tag the recording once ingested.
- **Live Closed Captions Hint & Shortcut:** Integrated dashboard card with one-click access and shortcut guidance (<kbd>Win</kbd> + <kbd>Ctrl</kbd> + <kbd>L</kbd>) to toggle Windows 11's hardware-accelerated, real-time Live Captions for any active meeting or playback.

---

## ⚙️ Configuration & Usage

1. **Server Setup:** Under the **Preferences** tab, click **Add** to configure your Speakr instance. Enter a friendly name, the API base URL (e.g. `http://192.168.0.88:8899/api/v1`), and your API Key.
2. **Upload Preference:**
   - Choose **Direct API Upload** if you want the app to handle file uploads over HTTP.
   - Choose **NAS Folder Copy** and browse to select your NAS Syncthing directory (e.g. `Z:\AudioRecordings\Inbox`) if you prefer local share synchronization.
3. **Devices Select:** Choose your default or specific Microphone and Speaker channels. The level meters on the **Dashboard** will immediately show sound waves indicating functionality.
4. **Auto-Record:** Toggle the checkbox to allow background process monitoring. The app will hide in the tray and start recording automatically whenever Zoom, Teams, or Citrix sessions begin!

---

## 🎙️ About the Speakr Server Backend

[**Speakr**](https://github.com/murtaza-nasir/speakr) is an open-source, self-hosted web application and API platform designed for automated speech-to-text transcription, speaker diarization, AI meeting summarization, and audio note-taking.

### Key Speakr Server Capabilities:
- **🔒 100% Self-Hosted & Private:** Runs entirely on your own local server or NAS using Docker with zero required cloud egress.
- **⚡ Local & Cloud ASR:** Integrates with local Whisper engines (e.g. WhisperX, Apple Silicon Whisper-MLX) or cloud speech APIs.
- **👥 Speaker Diarization:** Automatically identifies and labels distinct speakers throughout discussions.
- **🤖 Custom AI Prompts & Tagging:** Summarizes conversations into action items, meeting minutes, and structured notes based on customizable tag templates.

🔗 **Upstream Speakr Repository:** [https://github.com/murtaza-nasir/speakr](https://github.com/murtaza-nasir/speakr)  
📖 **Speakr Documentation:** [https://murtaza-nasir.github.io/speakr/](https://murtaza-nasir.github.io/speakr/)

---

## 💻 Building from Source

### Prerequisites
1. **Windows 11 or 10 OS (64-bit)**
2. **Python 3.12** (Check "Add Python to PATH" during installation)

### Steps
1. Clone the repository:
   ```powershell
   git clone https://github.com/sandersoncw55/speakr-companion.git
   cd speakr-companion
   ```
2. Create and activate a Python virtual environment:
   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. Run the application:
   ```powershell
   python main.py
   ```

---

## 📦 Packaging & Release Pipeline

### One-Click Local Build (`.zip` & `.exe`)

Run the bundled packaging script to run tests and compile both the portable package and Inno Setup installer:
```powershell
powershell -ExecutionPolicy Bypass -File .\package_release.ps1
```

### Automated CI/CD (GitHub Actions)

A GitHub Actions workflow (`.github/workflows/release.yml`) is included. Whenever you push a version tag, GitHub cloud runners automatically build and publish the release:
```powershell
git tag v1.0.1
git push origin v1.0.1
```
