"""
Zoom & Teams Transcriber — System Tray Launcher
Runs the transcriber silently in the background with a tray icon.
Launch with:  pythonw.exe tray_app.py
"""

import os
import sys
import threading
import subprocess
from pathlib import Path
from PIL import Image

# ── Suppress console window flashes from ffmpeg/subprocess calls ───────────────
# Whisper calls ffmpeg internally; without this it briefly flashes a terminal
# every time a chunk is transcribed.
if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
    _orig_popen = subprocess.Popen.__init__
    def _silent_popen(self, *args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        _orig_popen(self, *args, **kwargs)
    subprocess.Popen.__init__ = _silent_popen

# ── Load config.env ───────────────────────────────────────────────────────────
_cfg = Path(__file__).parent / "config.env"
if _cfg.exists():
    for _line in _cfg.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Setup PATH for ffmpeg ──────────────────────────────────────────────────────
_app_dir = Path(__file__).parent.resolve()
os.environ["PATH"] = str(_app_dir) + os.pathsep + os.environ.get("PATH", "")

import pystray

# ── State shared between tray and transcriber thread ──────────────────────────
_status  = "Waiting for meeting..."
_running = True


def get_icon_image():
    """Load the .ico file as a PIL Image for pystray."""
    ico = _app_dir / "zoom_transcriber.ico"
    if ico.exists():
        return Image.open(ico).convert("RGBA").resize((64, 64))
    # Fallback: simple blue circle
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(30, 120, 200, 255))
    return img


def open_transcripts(_icon, _item):
    output_dir = Path.home() / "Documents" / "ZoomTranscripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(output_dir)])


def quit_app(icon, _item):
    global _running
    _running = False
    icon.stop()


def run_transcriber():
    """Run the transcriber in-process on a background thread."""
    global _status

    # Import here so PATH is already set
    sys.path.insert(0, str(_app_dir))
    from zoom_transcriber import ZoomTranscriber, POLL_INTERVAL
    import time

    model   = "--model"
    chunk   = "--chunk"
    m_val   = "medium"
    c_val   = "30"

    # Parse args if passed (e.g. pythonw tray_app.py --model small)
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--model" and i + 1 < len(args):
            m_val = args[i + 1]
        if a == "--chunk" and i + 1 < len(args):
            c_val = args[i + 1]

    zt = ZoomTranscriber(model_size=m_val, chunk_duration=int(c_val))
    zt._load_model()

    meeting_active = False
    collect_t = transcribe_t = None

    while _running:
        app = zt._detect_meeting()

        if app and not meeting_active:
            _status = f"Recording: {app}"
            _update_tray()
            meeting_active = True
            zt._zoom_active = True
            zt._open_transcript(app)
            zt.recorder.start()

            import threading as _t
            zt._stop_event.clear()
            collect_t    = _t.Thread(target=zt._collection_thread, daemon=True)
            transcribe_t = _t.Thread(target=zt._transcription_thread, daemon=True)
            collect_t.start()
            transcribe_t.start()

        elif not app and meeting_active:
            _status = "Saving transcript..."
            _update_tray()
            zt._zoom_active = False
            zt.recorder.stop()
            audio = zt.recorder.drain()
            if audio is not None:
                zt._audio_q.put((__import__('datetime').datetime.now(), audio))
            if collect_t:
                collect_t.join(timeout=5)
            zt._stop_event.set()
            if transcribe_t:
                transcribe_t.join(timeout=120)
            zt._close_transcript()
            zt._stop_event.clear()
            meeting_active = False
            _status = "Waiting for meeting..."
            _update_tray()

        time.sleep(POLL_INTERVAL)

    # Clean up if still in meeting when quit
    if meeting_active:
        zt._zoom_active = False
        zt.recorder.stop()
        zt._stop_event.set()
        zt._close_transcript()


# ── Tray icon setup ───────────────────────────────────────────────────────────
_tray_icon = None


def _update_tray():
    if _tray_icon:
        _tray_icon.title = f"Transcriber — {_status}"
        _tray_icon.update_menu()


def status_label(_item=None):
    return _status


def main():
    global _tray_icon

    # Start transcriber on a background daemon thread
    t = threading.Thread(target=run_transcriber, daemon=True)
    t.start()

    menu = pystray.Menu(
        pystray.MenuItem(status_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Transcripts Folder", open_transcripts),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )

    _tray_icon = pystray.Icon(
        name="ZoomTranscriber",
        icon=get_icon_image(),
        title="Transcriber — Waiting for meeting...",
        menu=menu,
    )
    _tray_icon.run()


if __name__ == "__main__":
    main()
