# Changelog

All notable changes to the Speakr Windows Companion application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-10-09

### Added
- **Dedicated "Copilot Prompts" Sub-Tab (`gui/main_window.py`):**
  - Added a dedicated 4th subtab under Preferences specifically for customizing Live Copilot Quick Action instructions (`what_to_ask`, `catch_me_up`, `clarify_ownership`, `spot_risks`, `explain_jargon`).
  - Added clean dark-styled multi-line prompt editors with generous height, helper text, `💾 Save Quick Action Prompts`, and `🔄 Reset Prompts to Defaults` buttons.
- **Configurable Quick Action Prompts System (`core/config.py`, `core/copilot/agent.py`, `core/copilot/prompts.py`):**
  - Added persistent dictionary storage and property helpers (`DEFAULT_QUICK_ACTION_PROMPTS`, `get_quick_action_instruction()`, `reset_quick_action_prompts()`) supporting string and structured dictionary formats.
  - Quick action execution now accepts custom runtime instructions dispatched directly to local or cloud LLMs.
- **Reasoning Engine Healthcheck & Status Indicators (`core/copilot/agent.py`, `gui/hud.py`, `gui/main_window.py`):**
  - Added real-time healthcheck engine (`check_health()`) supporting Offline Extractive, LM Studio, Ollama, OpenRouter, and Gemini providers.
  - Added dynamic Reasoning Engine badge, live status dot (🟢 Available, 🟡 Testing, 🔴 Unreachable), and one-click `⚡ Check Engine` button to the HUD header.
- **Topic-Based Rolling Meeting Summary (`core/copilot/memory.py`, `core/copilot/agent.py`, `core/copilot/prompts.py`, `gui/hud.py`):**
  - Replaced repetitive verbatim quotes with structured topic synthesis cards (`topics` list with title, category, and bullet points).
  - Enhanced system prompt with strict negative constraints against casual banter, hallway chatter, and filler remarks.
  - Extractive offline engine upgraded with technical keyword scoring, conversational noise filtering, and domain-based topic clustering.
- **One-Click Prompt Customization from HUD (`gui/hud.py`, `gui/main_window.py`):**
  - Added `⚙️ Prompts` shortcut button to the HUD Quick Actions toolbar with direct navigation to the Preferences customization subtab.

### Fixed & Improved
- **Preferences Tab Decluttering & Responsive Vertical Scrolling (`gui/main_window.py`):**
  - Wrapped both `Live Copilot & ASR` and `Copilot Prompts` tabs in `QScrollArea(widgetResizable=True)` containers, preventing squished or clipped inputs on lower screen resolutions.
  - Replaced bulky prompt textareas in `Live Copilot & ASR` with a compact `✏️ Configure Prompt Templates →` navigation card.
- **Copilot Scratchpad Scrollbars (`gui/hud.py`):**
  - Configured explicit vertical and horizontal scrollbars with custom dark/light styled scroll handles on both the Rolling Executive Summary browser and Custom Notes scratchpad list.
- **Audio Recorder Thread Termination Guard (`core/recorder.py`):**
  - Added safety checks before joining recorder threads to prevent `RuntimeError("cannot join thread before it is started")` when stopping before audio capture begins.

---

## [1.3.0] - 2026-10-05

### Added
- **Cyber Dark & Studio Clean Light Themes (`gui/theme.py`, `core/config.py`, `gui/widgets.py`, `gui/hud.py`, `gui/main_window.py`):**
  - High-contrast, modern Cyber-Studio Dark Mode palette (Obsidian `#0e1015`, Surface `#181b22`, Cyan `#22d3ee`, Lavender `#c084fc`, Coral `#fb7185`) and Studio Clean Light Mode (`#f8fafc`, `#ffffff`, Cerulean `#0284c7`, Royal Purple `#7c3aed`).
  - Dynamic runtime theme switching via top-bar `🌙 Dark` / `☀️ Light` button and Preferences dropdown with zero application restarts required.
  - Channel-differentiated Volume Level Meters: Microphone stream renders in glowing Cyan while System Speaker Loopback renders in Lavender/Royal Purple.
  - Persistent theme configuration stored in `%APPDATA%\SpeakrCompanion\settings.json`.
- **"Open Speakr" Web Instance Button (`gui/main_window.py`):**
  - Added `🌐 Open Speakr` button to the persistent top control bar.
  - Automatically resolves and sanitizes active server API endpoints (e.g. stripping `/api/v1`) to launch the root Speakr web portal in the default system browser.
  - Interactive tooltip dynamically updates when switching server profiles.
- **Embedded Copilot Dashboard & 3-Tier Resizable Layout (`gui/hud.py`, `gui/main_window.py`):**
  - Integrated 3-tier live copilot workspace directly inside the Dashboard tab with collapsible/resizable splitters.
  - Real-time rolling summary header featuring current meeting topic, executive summary, and key decisions.
  - Dedicated Copilot Enable switch and synchronized state management across embedded dashboard and floating HUD modes.

### Fixed & Improved
- **Tag Selector Layout & Checkbox Clipping (`gui/widgets.py`, `gui/main_window.py`):**
  - Resolved tag item truncation and checkbox clipping across different DPIs.
  - Made the tag selection container expand smoothly when resizing the main window.
- **Subtitles & Closed Captions Card Docking (`gui/main_window.py`):**
  - Anchored the live closed captions card statically to the bottom of the dashboard layout to eliminate scrolling overlap.
- **Default Application Window Dimensions (`gui/main_window.py`):**
  - Updated default launch geometry to 1055x995 for optimal layout visibility without manual resizing.
- **Automated CI/CD Release Notes Extraction (`.github/workflows/release.yml`):**
  - Automatic parsing of versioned CHANGELOG entries directly into GitHub Release descriptions on tag pushes.

---

## [1.2.0] - 2026-10-05

### Added
- **Compact Icon Action Buttons in Recordings History (`gui/main_window.py`):**
  - Replaced wide text buttons with streamlined Unicode icon action buttons (`📝` Notes, `▶️` Play, `☁️` Re-Upload, `📁` Reveal in Explorer, `🗑️` Delete) with descriptive tooltips matching the macOS companion interface.
  - Distinct theme-matched visual styling for each action button with high-contrast text and hover states.
- **Native "Reveal in Explorer" (`📁`):**
  - Instantly reveals and highlights the recording audio file and its associated `<MeetingName>_Notes.md` sidecar in Windows File Explorer using `explorer.exe /select,"<file_path>"`.
- **LM Studio Model Auto-Discovery (`core/copilot/agent.py` & `gui/main_window.py`):**
  - Added `fetch_lm_studio_models()` utility to query `GET /v1/models` from local or LAN LM Studio endpoints.
  - Added `[🔄 Fetch Models]` button alongside an editable model selection `QComboBox` in the Live Copilot Preferences.
  - Background daemon worker thread execution ensuring zero UI blocking during network lookups.
  - Automatic endpoint canonicalization (supporting `http://localhost:1234`, `http://localhost:1234/v1`, or full path URLs).
- **LM Studio API Token & Authentication Bypass (`core/config.py`, `core/copilot/agent.py`, `gui/main_window.py`):**
  - Added dedicated configuration and UI controls for LM Studio API Token (`lm_studio_api_key`) and Authentication Bypass toggle (`lm_studio_bypass_auth`).
  - Seamlessly handles LM Studio instances that require Bearer token authorization headers or run in unauthenticated local bypass mode.
- **Unit & Integration Test Suite Enhancements (`tests/`):**
  - Added `test_fetch_lm_studio_models_function` testing API parsing and error response handling.
  - Added `test_history_icon_buttons_and_model_fetch_ui` testing all 5 icon buttons, LM Studio auth bypass toggling, and the model discovery UI workflow.

---

## [1.1.0] - 2026-10-02

### Added
- **Live Meeting Copilot (`gui/hud.py`):** 3-pane always-on-top floating HUD with collapsible panes for Live Transcript Stream, Suggested Questions Checklist, and Scratchpad Notes.
- **Multi-Provider Real-Time ASR (`core/asr/`):**
  - Offline local CPU speech recognition via `faster-whisper` (quantized INT8 `tiny.en`, `base.en`, `small.en`).
  - Network streaming transcription to Apple Silicon Macs via `Whisper-MLX`.
  - Cloud provider support (Groq `whisper-large-v3`, OpenAI, Deepgram, Speakr).
  - Voice Activity Detection (Silero VAD) with Virtual (stereo separation) and In-Person (mic-only) meeting modes.
- **Local & Remote Reasoning (`core/copilot/agent.py`):**
  - LM Studio integration (`http://localhost:1234/v1` or LAN IP) with model auto-discovery and zero-cloud privacy.
  - Persona prompt engineering (CAB Meetings, Incident Troubleshooting Bridge, Architecture Reviews, General).
  - Offline Extractive Engine for rule-based analysis without external LLMs.
- **Interactive Suggested Questions Checklist:**
  - One-click actions to mark questions as asked, copy to clipboard, or discard.
  - Automatic retention and deduplication across reasoning cycles.
- **Sidecar Markdown Notes & History Viewer:**
  - Automatic generation of `<MeetingName>_Notes.md` sidecar files containing timestamps, tags, transcript snippets, and checked action items.
  - Rich `NotesViewerDialog` directly in the Recordings History tab with one-click clipboard copying.
  - Seamless notes transmission with Speakr REST API uploads and Syncthing NAS Folder sync.
- **HUD Lifecycle Management:**
  - Preserves transcript and notes post-meeting for review.
  - Automatically wipes HUD and memory buffers upon starting a fresh recording session.
  - Manual "Reset / Clear" button on HUD header.
  - "Open / Hide Copilot HUD" toggle button on main dashboard.

### Fixed
- **History Table Layout Alignment:** Fixed container alignment issues in the Recordings History action layout.
- **Qt High DPI Attributes:** Removed deprecated `AA_EnableHighDpiScaling` and `AA_UseHighDpiPixmaps` attributes for clean PySide6 / Qt 6 execution.
- **Transcript Bleeding:** Resolved transcript bleed across consecutive meetings by resetting buffers on new recording start.
- **Audio Gating:** Hardened Citrix audio-gating debounce (2.0s) and 5-minute silence stop thresholds.

---

## [1.0.1] - 2026-09-10

### Added
- **Modern High-Resolution App Icon:** Multi-resolution master icon layers (16x16 up to 256x256) for Windows taskbar, shortcuts, and tray.
- **Configurable System Tray Minimization:** User preferences to minimize or close the window cleanly to the notification area.
- **Dynamic Tray Status Badges:** Color-coded status dots (🟢 Ready, 🔴 Recording, 🟡 Paused, 🟠 Cooldown).

---

## [1.0.0] - 2026-09-03

### Added
- **Dual-Stream WASAPI Audio Capture:** Microphone and system speaker loopback capture.
- **Process Auto-Record Monitoring:** Zoom (`CptHost.exe`), Teams (`Teams.exe`), and Citrix audio-gated monitoring (`wfica32.exe`, `MsTeamsVdi.exe`).
- **Post-Stop Cooldown Delay (60s):** Protection against accidental double-clicks and auto-retrigger loops.
- **Local Storage & Retention:** 30-day automatic retention pruning and Recordings History library.
- **Speakr Server & NAS Ingestion:** Direct REST API uploads and Syncthing NAS Share synchronization.
