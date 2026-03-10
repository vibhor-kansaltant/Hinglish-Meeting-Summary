# Zoom & Teams Meeting Transcriber

Automatically detects when you join a Zoom or Microsoft Teams meeting, records both your microphone and the remote participants' audio, transcribes everything using OpenAI Whisper, and saves a timestamped transcript to your Documents folder — all silently in the background.

---

## Features

- **Auto-detection** — Watches for Zoom and Teams meetings in the background. Recording starts the moment you join a call and stops when you leave. No manual action needed.
- **Both sides of the conversation** — Captures your microphone (your voice) and system audio via VB-Cable (remote participants' voices) simultaneously and mixes them together.
- **OpenAI Whisper transcription** — Uses the locally-installed Whisper `medium` model. Runs 100% on your machine — no internet required after first setup, no data sent anywhere.
- **English & Hindi support** — Optimised for English and Hindi (Hinglish code-switching). The language hint ensures Whisper handles mixed-language conversations accurately.
- **Timestamped transcripts** — Every 30 seconds of audio is transcribed and appended as a new line with the exact time, e.g. `[14:32:05] Let's get started with the agenda...`
- **Separate files per meeting** — Each meeting gets its own transcript file named `zoom_transcript_YYYYMMDD_HHMMSS.txt` or `teams_transcript_YYYYMMDD_HHMMSS.txt`.
- **Silent system tray app** — Runs as a tray icon with no visible terminal window. Right-click the tray icon to check status or open the transcripts folder.
- **Auto-start on login** — Installed to the Windows Startup folder so it's always running when you log in.
- **Smart Teams detection** — Only triggers on active Teams calls, not when browsing the Teams app (chat, calendar, new meeting form, etc.).

---

## Requirements

### 1. Python 3.10 or higher
Download from [python.org](https://python.org). During installation, tick **"Add Python to PATH"**.

### 2. VB-Audio Virtual Cable (free)
Required to capture remote participants' audio.
- Download from [vb-audio.com/Cable](https://vb-audio.com/Cable)
- Extract the zip, right-click `VBCABLE_Setup_x64.exe` → **Run as Administrator**
- Restart your PC after installation

### 3. Configure audio (one-time after VB-Cable install)

**Zoom:**
Go to Zoom → Settings → Audio → **Speaker** → set to `CABLE Input (VB-Audio Virtual Cable)`

**Microsoft Teams:**
Go to Teams → Settings → Devices → **Speaker** → set to `CABLE Input (VB-Audio Virtual Cable)`

**So you can still hear the meeting:**
- Press `Win + R`, type `mmsys.cpl`, press Enter
- Go to the **Recording** tab
- Right-click **CABLE Output (VB-Audio Virtual Cable)** → Properties
- Click the **Listen** tab → tick **"Listen to this device"**
- Set **Playback through** to `Default` (your speakers/headphones)
- Click OK

---

## Installation

1. Extract this zip to any folder (e.g. `C:\Tools\ZoomTeamsTranscriber`)
2. Double-click **`INSTALL.bat`**
3. The installer will:
   - Check Python is installed
   - Install all required Python packages
   - Set up ffmpeg automatically
   - Check for VB-Cable and warn if missing
   - Create a Desktop shortcut
4. A **"Zoom Transcriber"** icon will appear on your Desktop

> **First launch:** Whisper will download the `medium` model (~1.5 GB) on the first run. This is a one-time download and may take a few minutes depending on your connection.

---

## Usage

### Starting the app
Double-click the **Zoom Transcriber** icon on your Desktop or taskbar.
The app starts silently — no window will open.

### System tray icon
Look for the icon in the **system tray** (bottom-right corner of your taskbar, near the clock). Right-click it for options:

| Menu item | Description |
|---|---|
| `Waiting for meeting...` | App is idle, watching for a meeting to start |
| `Recording: Zoom` | Actively recording a Zoom meeting |
| `Recording: Teams` | Actively recording a Teams meeting |
| `Saving transcript...` | Meeting ended, processing final audio chunk |
| **Open Transcripts Folder** | Opens the folder containing all transcripts |
| **Quit** | Stops the app completely |

### During a meeting
- Join your Zoom or Teams call as normal
- The tray icon status will change to `Recording: Zoom` or `Recording: Teams`
- Every 30 seconds, audio is transcribed and appended to the transcript file
- Leave the meeting — the app automatically finalises the transcript

### Finding your transcripts
Transcripts are saved to:
```
C:\Users\<YourName>\Documents\ZoomTranscripts\
```
Files are named:
```
zoom_transcript_20260310_143000.txt
teams_transcript_20260310_160000.txt
```

Each transcript looks like:
```
Zoom Meeting Transcript
Started : 2026-03-10 14:30:00
Model   : whisper/medium
================================================================

[14:30:35] Good morning everyone, let's get started.
[14:31:05] I wanted to follow up on the proposal from last week.
[14:31:35] Haan, maine dekha tha, looks good to me.
[14:32:05] Great, so we're aligned on the timeline then.

================================================================
Ended   : 2026-03-10 15:00:00
```

---

## Troubleshooting

**Only my voice is being transcribed, not the other person's**
- Make sure VB-Cable is installed and your Zoom/Teams speaker is set to `CABLE Input`
- Make sure "Listen to this device" is enabled on CABLE Output (see Requirements above)

**App is not detecting my meeting**
- For Zoom: The app detects `CptHost.exe` which Zoom only spawns during an active call (not just when the app is open)
- For Teams: The app checks window titles. If your meeting isn't being detected, the window title may be unusual — contact the person who shared this tool

**Transcription quality is poor**
- Make sure you have a stable audio setup (not too much background noise)
- The `medium` model works best — do not change to `tiny` or `base`
- Transcription is processed every 30 seconds, so there is always a short delay

**The app is not auto-starting after reboot**
- Run `INSTALL.bat` again — it will recreate the startup shortcut

**Where are the model files stored?**
Whisper model files are cached at:
```
C:\Users\<YourName>\.cache\whisper\
```
You can delete this folder to free up ~1.5 GB of disk space, but the model will re-download on next launch.

---

## Privacy

- All processing happens **100% locally** on your machine
- No audio or transcript data is ever sent to any server
- Whisper runs entirely offline after the initial model download
- Transcripts are only stored in your local `Documents\ZoomTranscripts` folder

---

## Technical Details

| Component | Details |
|---|---|
| Transcription engine | OpenAI Whisper `medium` model |
| Mic capture | Windows WASAPI, Intel Smart Sound / Realtek |
| System audio capture | VB-Audio Virtual Cable (CABLE Output) |
| Audio sample rate | 16 kHz (Whisper standard) |
| Chunk duration | 30 seconds per transcription batch |
| Zoom detection | `CptHost.exe` process (active meeting only) |
| Teams detection | Window title pattern matching |
| Supported languages | English, Hindi (and most other languages) |

---

## Files in this package

| File | Description |
|---|---|
| `INSTALL.bat` | One-click installer — run this first |
| `tray_app.py` | System tray launcher (what the shortcut runs) |
| `zoom_transcriber.py` | Core transcription engine |
| `create_icon.py` | Creates the desktop shortcut and icon |
| `run.bat` | Alternative terminal launcher (for debugging) |
| `zoom_transcriber.ico` | App icon |
| `README.md` | This file |
