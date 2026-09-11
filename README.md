# Speakr Windows Companion App

[![Release](https://img.shields.io/github/v/release/sandersoncw55/speakr-companion?color=blue&label=Latest%20Release)](https://github.com/sandersoncw55/speakr-companion/releases/latest)
[![Windows 11](https://img.shields.io/badge/Platform-Windows%2011%20%2F%2010%20(x64)-0078D6?logo=windows)](https://github.com/sandersoncw55/speakr-companion/releases/latest)

A background desktop utility for Windows 11 designed to capture, manage, tag, and upload meeting recordings automatically to your **Speakr** instance.

### 📥 [Download Latest Release (v1.0.0)](https://github.com/sandersoncw55/speakr-companion/releases/latest)
- 🚀 **[SpeakrCompanion-Setup-v1.0.0.exe](https://github.com/sandersoncw55/speakr-companion/releases/download/v1.0.0/SpeakrCompanion-Setup-v1.0.0.exe)** — Standard Windows installer wizard with Start Menu shortcuts and optional auto-start on boot.
- 🗜️ **[SpeakrCompanion_Portable_v1.0.0.zip](https://github.com/sandersoncw55/speakr-companion/releases/download/v1.0.0/SpeakrCompanion_Portable_v1.0.0.zip)** — Zero-install portable zip archive.

---

## Features

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

## Installation & Running from Source

### Prerequisites
1. **Windows 11 OS**
2. **Python 3.12** (Make sure to check "Add Python to PATH" during installation)

### Steps
1. Open PowerShell and navigate to the project folder:
   ```powershell
   cd c:\Temp\Google_Antigravity\speakr_compainion
   ```
2. Create and activate a Python virtual environment:
   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
3. Install the required dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. Run the application:
   ```powershell
   python main.py
   ```

---

---

## Packaging & Distributing for Windows

We provide multiple packaging formats depending on how you plan to share and distribute the application:

### Option 1: One-Click Automated Release (`.zip` & `.exe`)

Run the automated release script:
```powershell
powershell -ExecutionPolicy Bypass -File .\package_release.ps1
```
This script automatically:
1. Runs and verifies the full 15-test unit suite.
2. Compiles `dist/SpeakrCompanion.exe` using PyInstaller.
3. Bundles the binary, icon, and README into `releases/SpeakrCompanion_Portable_v1.0.0.zip`.
4. Compiles `SpeakrCompanion-Setup-v1.0.0.exe` if Inno Setup is detected.

---

### Option 2: Standalone Portable Binary (`SpeakrCompanion.exe`)

Ideal for quick sharing via network shares (NAS), Slack, or USB drives:
1. Compile using PyInstaller:
   ```powershell
   .venv\Scripts\pyinstaller.exe --clean SpeakrCompanion.spec
   ```
2. Distribute `dist/SpeakrCompanion.exe`. Users can double-click and run it directly without installing Python or needing Administrator privileges.

---

### Option 3: Standard Windows Setup Installer Wizard (`.exe`)

For a professional Windows Setup Wizard with Start Menu shortcuts, Desktop icons, uninstaller, and "Start on Windows Boot":
1. Download and install [Inno Setup 6](https://jrsoftware.org/isinfo.php).
2. Compile the bundled script:
   ```powershell
   iscc installer.iss
   ```
3. The resulting setup executable will be generated at `releases/SpeakrCompanion-Setup-v1.0.0.exe`.

---

### Option 4: Enterprise & Microsoft Intune Deployment (`.intunewin`)

For silent deployment across domain-joined enterprise endpoints or VDI pools:
1. Use the Microsoft Win32 Content Prep Tool (`IntuneWinAppUtil.exe`):
   ```powershell
   .\IntuneWinAppUtil.exe -c .\releases\ -s SpeakrCompanion-Setup-v1.0.0.exe -o .\intune_output\
   ```
2. Deploy via Intune with the silent install command:
   ```text
   SpeakrCompanion-Setup-v1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="startupicon"
   ```
3. Detection Rule: File exists `%LOCALAPPDATA%\Programs\Speakr Companion\SpeakrCompanion.exe`.

## Configuration & Usage

1. **Server Setup:** Under the **Preferences** tab, click **Add** to configure your Speakr instance. Enter a friendly name, the API base URL (e.g. `http://192.168.0.88:8899/api/v1`), and your API Key.
2. **Upload Preference:**
   - Choose **Direct API Upload** if you want the app to handle file uploads over HTTP.
   - Choose **NAS Folder Copy** and browse to select your NAS Syncthing directory (e.g. `Z:\AudioRecordings\Inbox`) if you prefer local share synchronization.
3. **Devices Select:** Choose your default or specific Microphone and Speaker channels. The level meters on the **Dashboard** will immediately show sound waves indicating functionality.
4. **Auto-Record:** Toggle the checkbox to allow background process monitoring. The app will hide in the tray and start recording automatically whenever Zoom, Teams, or Citrix sessions begin!
