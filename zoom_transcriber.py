#!/usr/bin/env python3
"""
Zoom Meeting Transcriber
========================
Automatically detects when Zoom is running, records mic + system audio
via WASAPI loopback, transcribes in real-time using OpenAI Whisper,
and saves a timestamped transcript to ~/Documents/ZoomTranscripts/.

Usage:
    python zoom_transcriber.py [--model base] [--output DIR] [--chunk 30]
"""

import os
import sys
import time
import queue
import threading
import tempfile
import argparse
from datetime import datetime

# ── Ensure ffmpeg is on PATH ───────────────────────────────────────────────────
# First try the app's own directory (ffmpeg.exe copied here during setup),
# then fall back to the imageio-ffmpeg bundled binary.
_app_dir = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] = _app_dir + os.pathsep + os.environ.get("PATH", "")
try:
    import imageio_ffmpeg as _iio_ff
    _ff_dir = os.path.dirname(_iio_ff.get_ffmpeg_exe())
    os.environ["PATH"] = _ff_dir + os.pathsep + os.environ["PATH"]
    # imageio bundles ffmpeg with a version suffix; make it callable as 'ffmpeg'
    _ff_src = _iio_ff.get_ffmpeg_exe()
    _ff_dst = os.path.join(_app_dir, "ffmpeg.exe")
    if not os.path.exists(_ff_dst):
        import shutil
        shutil.copy2(_ff_src, _ff_dst)
except Exception:
    pass
from pathlib import Path

import numpy as np
import psutil
import sounddevice as sd
import scipy.io.wavfile as wavfile
import whisper

# ── Constants ─────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16_000          # Whisper expects 16 kHz
POLL_INTERVAL = 5             # seconds between meeting checks
BLOCKSIZE = 8_000             # ~0.5 s per callback block

# Zoom: CptHost.exe is spawned only during an active meeting (audio/video).
ZOOM_IN_MEETING_PROCESS = "CptHost.exe"

# Teams: no single process reliably signals "in meeting", so we check window
# titles via the Win32 API (no extra deps needed — ctypes is stdlib).
# When in a meeting the window title is "<Topic> | Microsoft Teams".
# Teams processes (either old or new Teams client).
TEAMS_PROCESSES = {"Teams.exe", "ms-teams.exe"}


# ── Audio Recorder ────────────────────────────────────────────────────────────
class AudioRecorder:
    """Captures microphone and system audio simultaneously."""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._mic_buf: list = []
        self._sys_buf: list = []
        self._lock = threading.Lock()
        self._mic_stream = None
        self._sys_stream = None
        self._sys_native_rate = 48000   # captured at device's native rate, resampled on drain
        self._mic_native_rate = 16000   # same, for mic
        self.has_system_audio = False

    # ── Callbacks ──────────────────────────────────────────────────────────────
    def _mic_cb(self, indata, frames, t, status):
        with self._lock:
            self._mic_buf.append(indata.copy())

    def _sys_cb(self, indata, frames, t, status):
        with self._lock:
            self._sys_buf.append(indata.copy())

    # ── Device detection ───────────────────────────────────────────────────────
    @staticmethod
    def _find_mic_device():
        """
        Find the real microphone device index under WASAPI, explicitly
        skipping VB-Cable and Stereo Mix which are not real mics.
        Returns (device_index, native_samplerate) or (None, 16000).
        """
        SKIP_KEYWORDS = {"cable", "stereo mix", "virtual", "mapper", "primary"}
        MIC_KEYWORDS  = {"microphone", "mic", "input", "array"}
        try:
            wasapi_idx = next(
                (i for i, api in enumerate(sd.query_hostapis())
                 if "WASAPI" in api["name"]),
                None,
            )
            devices = list(enumerate(sd.query_devices()))

            # Prefer a real mic under WASAPI
            for i, dev in devices:
                name = dev["name"].lower()
                if dev["max_input_channels"] > 0 and dev["hostapi"] == wasapi_idx:
                    if any(s in name for s in SKIP_KEYWORDS):
                        continue
                    if any(m in name for m in MIC_KEYWORDS):
                        return i, int(dev["default_samplerate"])

            # Fallback: any WASAPI input that isn't VB-Cable/Stereo Mix
            for i, dev in devices:
                name = dev["name"].lower()
                if dev["max_input_channels"] > 0 and dev["hostapi"] == wasapi_idx:
                    if not any(s in name for s in SKIP_KEYWORDS):
                        return i, int(dev["default_samplerate"])
        except Exception as exc:
            print(f"[WARN] Mic detection failed: {exc}")
        return None, 16000

    def _wasapi_loopback_device(self):
        """
        Return (device_index, num_channels, native_samplerate).
        Prefers 'Stereo Mix', falls back to any WASAPI input.
        """
        try:
            wasapi_idx = next(
                (i for i, api in enumerate(sd.query_hostapis())
                 if "WASAPI" in api["name"]),
                None,
            )
            if wasapi_idx is None:
                return None, 0, 48000

            devices = list(enumerate(sd.query_devices()))

            # 1. VB-Cable Output — most reliable, captures exactly what apps play
            for i, dev in devices:
                if (dev["max_input_channels"] > 0
                        and "cable output" in dev["name"].lower()):
                    return i, dev["max_input_channels"], int(dev["default_samplerate"])

            # 2. Stereo Mix — standard Windows loopback (WASAPI)
            for i, dev in devices:
                if (dev["hostapi"] == wasapi_idx
                        and dev["max_input_channels"] > 0
                        and "stereo mix" in dev["name"].lower()):
                    return i, dev["max_input_channels"], int(dev["default_samplerate"])

            # 3. Any device with "loopback" in the name
            for i, dev in devices:
                if (dev["hostapi"] == wasapi_idx
                        and dev["max_input_channels"] > 0
                        and "loopback" in dev["name"].lower()):
                    return i, dev["max_input_channels"], int(dev["default_samplerate"])

        except Exception as exc:
            print(f"[WARN] Loopback device search failed: {exc}")
        return None, 0, 48000

    # ── Start / Stop ───────────────────────────────────────────────────────────
    def start(self):
        with self._lock:
            self._mic_buf.clear()
            self._sys_buf.clear()

        # Microphone — explicitly find a real mic, skip VB-Cable/Stereo Mix
        mic_dev, mic_native_rate = self._find_mic_device()
        try:
            mic_info = sd.query_devices(mic_dev) if mic_dev is not None else {}
            self._mic_stream = sd.InputStream(
                device=mic_dev,
                samplerate=mic_native_rate,
                channels=1,
                dtype="float32",
                callback=self._mic_cb,
                blocksize=int(mic_native_rate * BLOCKSIZE / self.sample_rate),
            )
            self._mic_native_rate = mic_native_rate
            self._mic_stream.start()
            print(f"[INFO] Microphone capture started ({mic_info.get('name', 'default')}).")
        except Exception as exc:
            print(f"[WARN] Could not open microphone: {exc}")

        # System audio via Stereo Mix / WASAPI loopback device
        loopback_dev, loopback_ch, native_rate = self._wasapi_loopback_device()
        if loopback_dev is not None:
            try:
                dev_info = sd.query_devices(loopback_dev)
                ch = min(loopback_ch, 2)
                # Capture at device's native rate; resample to 16 kHz during drain
                self._sys_native_rate = native_rate
                sys_blocksize = int(native_rate * BLOCKSIZE / self.sample_rate)
                self._sys_stream = sd.InputStream(
                    device=loopback_dev,
                    samplerate=native_rate,
                    channels=ch,
                    dtype="float32",
                    callback=self._sys_cb,
                    blocksize=sys_blocksize,
                )
                self._sys_stream.start()
                self.has_system_audio = True
                print(f"[INFO] System audio capture started ({dev_info['name']}, "
                      f"{native_rate} Hz).")
            except Exception as exc:
                print(f"[WARN] System audio unavailable: {exc}")
                print("[WARN] Recording microphone only.")
        else:
            print("[WARN] No Stereo Mix / loopback device found — mic only.")

    def stop(self):
        for stream in (self._mic_stream, self._sys_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self._mic_stream = None
        self._sys_stream = None
        self.has_system_audio = False

    # ── Drain buffers ──────────────────────────────────────────────────────────
    def drain(self):
        """
        Extract all buffered audio, mix mic + system audio, return a
        mono float32 numpy array at self.sample_rate.  Returns None if empty.
        """
        with self._lock:
            mic_chunks = self._mic_buf[:]
            sys_chunks = self._sys_buf[:]
            self._mic_buf.clear()
            self._sys_buf.clear()

        if not mic_chunks and not sys_chunks:
            return None

        def concat_mono(chunks, stereo=False):
            if not chunks:
                return None
            arr = np.concatenate(chunks)
            if stereo and arr.ndim > 1:
                arr = arr.mean(axis=1)
            return arr.flatten()

        mic_audio = concat_mono(mic_chunks, stereo=False)
        sys_audio = concat_mono(sys_chunks, stereo=True)

        # Resample both streams to target rate (16 kHz) if captured at different rates
        from scipy.signal import resample_poly
        from math import gcd

        def resample(audio, native_rate):
            if audio is None or native_rate == self.sample_rate:
                return audio
            g = gcd(self.sample_rate, native_rate)
            return resample_poly(audio, self.sample_rate // g, native_rate // g).astype(np.float32)

        mic_audio = resample(mic_audio, self._mic_native_rate)
        sys_audio = resample(sys_audio, self._sys_native_rate)

        if mic_audio is None:
            return sys_audio
        if sys_audio is None:
            return mic_audio

        # Pad shorter array then mix
        max_len = max(len(mic_audio), len(sys_audio))
        mic_p = np.pad(mic_audio, (0, max_len - len(mic_audio)))
        sys_p = np.pad(sys_audio, (0, max_len - len(sys_audio)))
        return np.clip(mic_p * 0.55 + sys_p * 0.55, -1.0, 1.0)


# ── Main Application ──────────────────────────────────────────────────────────
class ZoomTranscriber:
    def __init__(self, model_size="base", output_dir=None, chunk_duration=30):
        self.model_size = model_size
        self.chunk_duration = chunk_duration
        self.output_dir = (
            Path(output_dir) if output_dir
            else Path.home() / "Documents" / "ZoomTranscripts"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.recorder = AudioRecorder()
        self.model = None

        self._transcript_file = None
        self._zoom_active = False
        self._stop_event = threading.Event()
        self._audio_q = queue.Queue()

    # ── Whisper ────────────────────────────────────────────────────────────────
    def _load_model(self):
        print(f"[INFO] Loading Whisper '{self.model_size}' model…")
        try:
            import truststore
            truststore.inject_into_ssl()
        except ImportError:
            pass
        self.model = whisper.load_model(self.model_size)
        print(f"[INFO] Whisper ready.\n")

    def _transcribe(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) < SAMPLE_RATE:
            return ""
        # Skip near-silent chunks — prevents Whisper from hallucinating prompt text
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.002:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        try:
            audio_i16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            wavfile.write(tmp, SAMPLE_RATE, audio_i16)

            # Short Hinglish prompt — guides Whisper toward Roman-script output.
            # Keep it minimal to reduce hallucination risk on silent/noisy chunks.
            hinglish_prompt = "Theek hai. Haan."

            result = self.model.transcribe(
                tmp,
                language=None,          # auto-detect: captures Hindi, English, Hinglish
                beam_size=5,
                fp16=False,
                condition_on_previous_text=False,
                initial_prompt=hinglish_prompt,
                no_speech_threshold=0.8,        # suppress hallucinations on silence (higher = less filtering)
                compression_ratio_threshold=2.4, # detect & reject repetitive outputs
            )
            text = result["text"].strip()

            # Guard against hallucinations:
            # 1. Reject if a sentence repeats 2+ times (Whisper looping)
            sentences = [s.strip() for s in text.replace(".", "|").replace("?", "|").replace("!", "|").split("|") if s.strip()]
            if len(sentences) >= 3:
                if len(set(sentences)) == 1:
                    return ""  # all sentences identical
                # Check if any sentence appears 3+ times
                from collections import Counter
                counts = Counter(sentences)
                if counts.most_common(1)[0][1] >= 3:
                    return ""

            # 2. Reject known Whisper hallucinations (common on silence/background noise)
            HALLUCINATIONS = {
                "theek hai", "haan", "theek hai haan",
                "thank you for watching", "thank you", "thanks for watching",
                "please subscribe", "subscribe", "like and subscribe",
                "transcript of a business meeting in hinglish",
                "hindi words in roman script", "hinglish",
                "[music]", "[applause]", "[silence]",
            }
            if text.lower().strip(".").strip("!").strip("?").strip() in HALLUCINATIONS:
                return ""

            return text

        except Exception as exc:
            print(f"[WARN] Transcription error: {exc}")
            return ""
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Transcript file ────────────────────────────────────────────────────────
    def _open_transcript(self, app: str = "Meeting"):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = app.lower()   # "zoom" or "teams"
        self._transcript_file = self.output_dir / f"{prefix}_transcript_{ts}.txt"
        with open(self._transcript_file, "w", encoding="utf-8") as f:
            f.write(f"{app} Meeting Transcript\n")
            f.write(f"Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Model   : whisper/{self.model_size}\n")
            f.write("=" * 64 + "\n\n")
        print(f"[INFO] Transcript → {self._transcript_file}")

    def _close_transcript(self):
        if not self._transcript_file:
            return
        with open(self._transcript_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 64}\n")
            f.write(f"Ended   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        print(f"[INFO] Transcript saved: {self._transcript_file}")
        self._generate_summary()

    def _generate_summary(self):
        """Generate a Fireflies-style summary and append it to the transcript."""
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            print("[INFO] No ANTHROPIC_API_KEY set — skipping summary.")
            return

        # Read the transcript lines (skip the header)
        try:
            raw = self._transcript_file.read_text(encoding="utf-8")
        except Exception:
            return

        # Extract only the timestamped lines
        lines = [l for l in raw.splitlines() if l.startswith("[")]
        if not lines:
            print("[INFO] Transcript too short to summarise.")
            return

        transcript_text = "\n".join(lines)
        print("[INFO] Generating meeting summary with Claude...")

        prompt = f"""You are an expert meeting assistant. Analyze the meeting transcript below and produce a structured summary in the style of Fireflies.ai / Otter.ai.

TRANSCRIPT:
{transcript_text}

Produce the summary in exactly this format (use the exact section headers):

## Meeting Summary
[3-5 sentence overview of what the meeting was about and the main outcomes]

## Key Topics Discussed
- [topic 1]
- [topic 2]
- [topic 3]
(list all main topics covered)

## Action Items
- [action item] — Owner: [person if mentioned, else "TBD"] | Due: [deadline if mentioned, else "TBD"]
(list every concrete task or follow-up mentioned; write "None identified" if there are none)

## Decisions Made
- [decision 1]
- [decision 2]
(list key decisions or conclusions reached; write "None identified" if there are none)

## Questions Raised
- [question 1]
- [question 2]
(list unresolved questions or topics that need follow-up; write "None identified" if there are none)

## Key Takeaways
- [takeaway 1]
- [takeaway 2]
- [takeaway 3]
(3-5 most important points anyone who missed the meeting should know)

Keep the language clear and professional. If the transcript is in Hinglish, write the summary in English."""

        try:
            import anthropic
            try:
                import truststore
                truststore.inject_into_ssl()
            except ImportError:
                pass
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = message.content[0].text.strip()

            with open(self._transcript_file, "a", encoding="utf-8") as f:
                f.write(f"\n\n{'=' * 64}\n")
                f.write("AI MEETING SUMMARY\n")
                f.write(f"{'=' * 64}\n\n")
                f.write(summary)
                f.write("\n")

            print("[INFO] Meeting summary added to transcript.")

        except Exception as exc:
            print(f"[WARN] Summary generation failed: {exc}")

    def _append(self, ts: datetime, text: str):
        if not text:
            return
        line = f"[{ts.strftime('%H:%M:%S')}] {text}\n"
        print(line, end="", flush=True)
        if self._transcript_file:
            with open(self._transcript_file, "a", encoding="utf-8") as f:
                f.write(line)

    # ── Background threads ─────────────────────────────────────────────────────
    def _collection_thread(self):
        """Drains audio every chunk_duration seconds and enqueues for transcription."""
        while self._zoom_active and not self._stop_event.is_set():
            time.sleep(self.chunk_duration)
            audio = self.recorder.drain()
            if audio is not None:
                self._audio_q.put((datetime.now(), audio))

    def _transcription_thread(self):
        """Pops audio chunks, transcribes, and writes timestamped lines."""
        while not self._stop_event.is_set() or not self._audio_q.empty():
            try:
                ts, audio = self._audio_q.get(timeout=2)
            except queue.Empty:
                continue
            text = self._transcribe(audio)
            self._append(ts, text)
            self._audio_q.task_done()

    # ── Meeting detection ───────────────────────────────────────────────────────
    @staticmethod
    def _zoom_in_meeting() -> bool:
        """True when CptHost.exe is running (Zoom spawns it only during meetings)."""
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] == ZOOM_IN_MEETING_PROCESS:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    @staticmethod
    def _teams_in_meeting() -> bool:
        """
        True when a Teams meeting/call is active.
        Teams has no dedicated meeting process, so we check window titles:
        an active meeting produces a window like '<Topic> | Microsoft Teams'
        (the title is never just 'Microsoft Teams' alone during a call).
        """
        import ctypes
        import ctypes.wintypes

        # Quick check: is Teams even running?
        teams_running = False
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] in TEAMS_PROCESSES:
                    teams_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if not teams_running:
            return False

        # Enumerate all visible window titles
        titles: list[str] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _enum_cb(hwnd, _):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    titles.append(buf.value)
            return True

        ctypes.windll.user32.EnumWindows(_enum_cb, 0)

        # These are normal Teams navigation pages — NOT meetings
        NON_MEETING_PAGES = {
            "activity", "chat", "teams", "calendar", "files",
            "apps", "calls", "help", "settings", "notifications",
            "dashboard", "new chat", "microsoft teams",
            "meet app",       # Teams meeting scheduling tab
            "new meeting",    # Teams meeting creation form
            "people",         # Teams contacts tab
            "assignments",    # Teams edu tab
        }

        for title in titles:
            tl = title.lower()

            # Explicit call/meeting keywords — always a meeting
            if "call with" in tl or "meeting now" in tl:
                return True

            # "<Topic> | Microsoft Teams" — only if topic is not a nav page
            if "| microsoft teams" in tl:
                # Extract the part before the first " | Microsoft Teams"
                page = tl.split("| microsoft teams")[0].strip().rstrip("|").strip()
                # A nav page title starts with a known nav keyword
                is_nav = any(page == nav or page.startswith(nav + " |") or page.startswith(nav + ",")
                             for nav in NON_MEETING_PAGES)
                if page and not is_nav:
                    return True

        # Fallback: "Meet App | ..." title appears both in scheduling AND active meetings.
        # Use audio session state to distinguish — Teams has an active audio session
        # only when a real call is in progress.
        return ZoomTranscriber._teams_has_active_audio()

    @staticmethod
    def _teams_has_active_audio() -> bool:
        """True if any ms-teams.exe process has an active (state=1) audio session."""
        try:
            from pycaw.pycaw import AudioUtilities
            teams_pids = set()
            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    if proc.info["name"] in TEAMS_PROCESSES:
                        teams_pids.add(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            for session in AudioUtilities.GetAllSessions():
                if (session.Process
                        and session.Process.pid in teams_pids
                        and session.State == 1):   # AudioSessionStateActive
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _detect_meeting() -> str | None:
        """
        Returns 'Zoom', 'Teams', or None depending on which (if any)
        meeting is currently active.
        """
        if ZoomTranscriber._zoom_in_meeting():
            return "Zoom"
        if ZoomTranscriber._teams_in_meeting():
            return "Teams"
        return None

    # ── Main loop ──────────────────────────────────────────────────────────────
    def run(self):
        self._load_model()
        print(f"[INFO] Waiting for a Zoom or Teams meeting (checks every {POLL_INTERVAL}s)…")
        print(f"[INFO] Output dir: {self.output_dir}")
        print("[INFO] Press Ctrl+C to quit.\n")

        meeting_active = False   # True while recording
        collect_t = None
        transcribe_t = None

        try:
            while not self._stop_event.is_set():
                app = self._detect_meeting()   # "Zoom", "Teams", or None

                # Meeting just started ─────────────────────────────────────────
                if app and not meeting_active:
                    print(f"\n[INFO] {app} meeting detected — recording started.")
                    self._zoom_active = True
                    self._open_transcript(app)
                    self.recorder.start()

                    self._stop_event.clear()
                    collect_t = threading.Thread(
                        target=self._collection_thread, daemon=True
                    )
                    transcribe_t = threading.Thread(
                        target=self._transcription_thread, daemon=True
                    )
                    collect_t.start()
                    transcribe_t.start()
                    meeting_active = True

                # Meeting just ended ───────────────────────────────────────────
                elif not app and meeting_active:
                    print("\n[INFO] Meeting ended — finishing transcription…")
                    self._zoom_active = False
                    self.recorder.stop()

                    # Flush any remaining audio
                    final_audio = self.recorder.drain()
                    if final_audio is not None:
                        self._audio_q.put((datetime.now(), final_audio))

                    if collect_t:
                        collect_t.join(timeout=5)
                    self._stop_event.set()
                    if transcribe_t:
                        transcribe_t.join(timeout=120)

                    self._close_transcript()
                    self._stop_event.clear()
                    meeting_active = False
                    print("\n[INFO] Watching for next meeting…\n")

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n[INFO] Interrupted by user.")
            self._zoom_active = False
            self.recorder.stop()
            final_audio = self.recorder.drain()
            if final_audio is not None:
                self._audio_q.put((datetime.now(), final_audio))
            self._stop_event.set()
            if transcribe_t:
                transcribe_t.join(timeout=120)
            if meeting_active:
                self._close_transcript()
            print("[INFO] Done.")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Auto-transcribe Zoom and Teams meetings with OpenAI Whisper."
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="DIR",
        help="Directory to save transcripts (default: ~/Documents/ZoomTranscripts)",
    )
    parser.add_argument(
        "--chunk",
        type=int,
        default=30,
        metavar="SECS",
        help="Seconds of audio per transcription chunk (default: 30)",
    )
    args = parser.parse_args()

    ZoomTranscriber(
        model_size=args.model,
        output_dir=args.output,
        chunk_duration=args.chunk,
    ).run()


if __name__ == "__main__":
    main()
