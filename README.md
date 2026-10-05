# Speakr Windows Companion App

[![Release](https://img.shields.io/github/v/release/sandersoncw55/speakr-companion?color=blue&label=Latest%20Release)](https://github.com/sandersoncw55/speakr-companion/releases/latest)
[![Windows 11 / 10](https://img.shields.io/badge/Platform-Windows%2011%20%2F%2010%20(x64)-0078D6?logo=windows)](https://github.com/sandersoncw55/speakr-companion/releases/latest)
[![CI Release](https://github.com/sandersoncw55/speakr-companion/actions/workflows/release.yml/badge.svg)](https://github.com/sandersoncw55/speakr-companion/actions/workflows/release.yml)

A lightweight, intelligent background desktop utility for Windows 11/10 designed to capture, transcribe, assist in real-time, manage, tag, and upload meeting recordings automatically to your self-hosted [**Speakr**](https://github.com/murtaza-nasir/speakr) instance.

---

## 📥 Quick Download & Installation

Download the latest version from [**GitHub Releases**](https://github.com/sandersoncw55/speakr-companion/releases/latest):

| Package | Description | Recommended For |
| :--- | :--- | :--- |
| 🚀 [**`SpeakrCompanion-Setup-v1.2.0.exe`**](https://github.com/sandersoncw55/speakr-companion/releases/download/v1.2.0/SpeakrCompanion-Setup-v1.2.0.exe) | Standard Windows Setup Wizard with Start Menu & Desktop shortcuts, optional auto-start on boot, and uninstaller. | **All Users (Standard Install)** |
| 🗜️ [**`SpeakrCompanion_Portable_v1.2.0.zip`**](https://github.com/sandersoncw55/speakr-companion/releases/download/v1.2.0/SpeakrCompanion_Portable_v1.2.0.zip) | Standalone portable archive containing `SpeakrCompanion.exe`. No installation required. | **USB Drives / Portable Use** |

> [!NOTE]
> The setup installer runs as a standard per-user installation in `%LOCALAPPDATA%\Programs\Speakr Companion` and does not require Administrator privileges or UAC elevation.

---

## ✨ Companion App Features

### 🧠 Live Meeting Copilot & Floating HUD (Enhanced in v1.2.0)
- **Always-on-Top 3-Pane Floating HUD:** Compact, resizable, translucent floating HUD with collapsible panes for:
  - **Live Transcript Ticker:** Real-time conversational speech stream separating speaker channels (`[You]` vs `[Call Participants]`).
  - **Suggested Questions Checklist:** Real-time AI-generated questions, clarifying inquiries, and technical prompts tailored to the ongoing discussion.
  - **Scratchpad & Notes:** Live editable markdown notes and action items automatically synced to meeting sidecar files.
- **LM Studio Model Auto-Discovery (New in v1.2.0):** Asynchronously pull loaded models from local or LAN LM Studio instances (`GET /v1/models`) with one click via `[🔄 Fetch Models]` without freezing the UI.
- **Multi-Provider Live Speech Recognition (ASR):**
  - **Local CPU (`faster-whisper`):** Offline, quantized INT8 Whisper models (`tiny.en`, `base.en`, `small.en`) running locally on CPU.
  - **LAN Mac MLX (`Whisper-MLX`):** Offload real-time streaming transcription across your local network to an Apple Silicon Mac.
  - **Cloud Providers:** High-speed cloud transcription via Groq (`whisper-large-v3`), OpenAI, Deepgram, or self-hosted Speakr backend.
- **Local & Remote LM Studio Reasoning:**
  - Connects to local or LAN [LM Studio](https://lmstudio.ai/) instances (`http://localhost:1234/v1` or remote IP) for 100% private, on-premise LLM reasoning with model auto-discovery.
  - Periodic intelligent analysis cycling every 10–30 seconds to extract action items, open questions, and risks.
- **Offline Extractive Engine:** Fallback rule-based heuristic extractor for completely air-gapped environments without any external LLM.
- **Interactive Checklist Actions:** One-click actions to mark suggested questions as asked, copy to clipboard, or discard, with automatic retention and deduplication across cycles.
- **Sidecar Markdown Notes & History Viewer:** Automatically generates `<MeetingName>_Notes.md` alongside recordings. Review markdown notes anytime from the **Recordings History** tab via the rich **View Notes** dialog.
- **Automatic Post-Meeting Retention & HUD Reset:** Preserves notes and transcript in the HUD when a call finishes for post-meeting review, then automatically clears the workspace when your next recording begins (with manual reset anytime).

### 📁 Recordings History & Compact Actions (New in v1.2.0)
- **Compact Icon Buttons:** Sleek, space-efficient icon action buttons (`📝` Notes, `▶️` Play, `☁️` Re-Upload, `📁` Reveal in Explorer, `🗑️` Delete) with descriptive tooltips matching the macOS companion layout.
- **Native File Explorer Integration (`📁`):** Instantly reveals and highlights the recording audio and associated sidecar notes in Windows File Explorer.
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
  - **API Upload:** Post recordings, tags, and Copilot sidecar notes directly to the Speakr server via REST API.
  - **NAS Folder Copy:** Drop recordings and sidecar notes into a local directory mapped to your Syncthing NAS Share (`Z:\AudioRecordings\Inbox`).
- **Live Closed Captions Hint & Shortcut:** Integrated dashboard card with one-click access and shortcut guidance (<kbd>Win</kbd> + <kbd>Ctrl</kbd> + <kbd>L</kbd>) to toggle Windows 11's hardware-accelerated, real-time Live Captions for any active meeting or playback.
- **Modern App Icon & Tray Minimization:** Multi-resolution icon layers (16x16 up to 256x256) with configurable minimize-to-tray and close-to-tray settings.

---

## ⚙️ Configuration & Preferences

Under the **Preferences** tab, settings are organized into distinct categories:

1. **General:** Local recording storage directory, retention expiration policy (default: 30 days), post-stop cooldown delay, and window/system tray minimize behaviors.
2. **Speakr Server:** Configure Speakr endpoints, API keys, and upload preferences (Direct API Upload vs NAS Folder Copy).
3. **Audio & Hardware:** Select microphone and speaker loopback devices, audio encoding format (`MP4 (AAC Compressed)` or `WAV (Uncompressed PCM)`), and auto-record process rules (Zoom, Teams, Citrix).
4. **Live Copilot & AI:**
   - **ASR Provider:** Choose between Local CPU Whisper (`tiny.en`, `base.en`, `small.en`), LAN Mac MLX, or Cloud API.
   - **Reasoning LLM:** Configure LM Studio endpoint (`http://localhost:1234/v1`), optional API Token / Key, Authentication Bypass toggle, model name (auto-detected via `Fetch Models`), or enable Offline Extractive Engine.
   - **Meeting Mode & Personas:** Toggle between Virtual (dual-channel: mic + system loopback) and In-Person (mic only), and select meeting personas (e.g. CAB Meeting, Bridge Call Troubleshooting, Architecture Review, General).

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
git tag v1.1.0
git push origin v1.1.0
```

