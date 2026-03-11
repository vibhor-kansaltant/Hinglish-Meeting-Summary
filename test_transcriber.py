#!/usr/bin/env python3
"""
Test script for zoom_transcriber.py
Tests: audio devices, mic capture, RMS levels, and Whisper transcription.
Run: python test_transcriber.py
"""

import os
import sys
import time
import tempfile
import numpy as np

# Add app dir to PATH for ffmpeg
_app_dir = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] = _app_dir + os.pathsep + os.environ.get("PATH", "")

SAMPLE_RATE = 16_000
RECORD_SECONDS = 10  # seconds to record mic for transcription test


def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── TEST 1: Audio devices ─────────────────────────────────────
def test_audio_devices():
    print_header("TEST 1: Audio Devices")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()

        wasapi_idx = next(
            (i for i, api in enumerate(hostapis) if "WASAPI" in api["name"]), None
        )
        print(f"WASAPI host API index: {wasapi_idx}")

        print("\nAll INPUT devices:")
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                api_name = hostapis[dev["hostapi"]]["name"] if dev["hostapi"] < len(hostapis) else "?"
                marker = " *** WASAPI ***" if dev["hostapi"] == wasapi_idx else ""
                print(f"  [{i}] {dev['name']} | ch={dev['max_input_channels']} | "
                      f"{int(dev['default_samplerate'])}Hz | {api_name}{marker}")

        print("\nDefault input device:", sd.query_devices(kind="input")["name"])
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


# ── TEST 2: Mic detection (same logic as zoom_transcriber) ────
def test_mic_detection():
    print_header("TEST 2: Mic Detection (transcriber logic)")
    try:
        import sounddevice as sd
        SKIP_KEYWORDS = {"cable", "stereo mix", "virtual", "mapper", "primary"}
        MIC_KEYWORDS  = {"microphone", "mic", "input", "array"}

        wasapi_idx = next(
            (i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api["name"]), None
        )
        devices = list(enumerate(sd.query_devices()))

        chosen = None
        for i, dev in devices:
            name = dev["name"].lower()
            if dev["max_input_channels"] > 0 and dev["hostapi"] == wasapi_idx:
                if any(s in name for s in SKIP_KEYWORDS):
                    continue
                if any(m in name for m in MIC_KEYWORDS):
                    chosen = (i, dev["name"], int(dev["default_samplerate"]))
                    break

        if not chosen:
            for i, dev in devices:
                name = dev["name"].lower()
                if dev["max_input_channels"] > 0 and dev["hostapi"] == wasapi_idx:
                    if not any(s in name for s in SKIP_KEYWORDS):
                        chosen = (i, dev["name"], int(dev["default_samplerate"]))
                        break

        if chosen:
            print(f"[OK] Mic selected: [{chosen[0]}] {chosen[1]} @ {chosen[2]}Hz")
        else:
            print("[WARN] No mic found via transcriber logic — will use system default")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


# ── TEST 3: Record mic and check RMS ─────────────────────────
def test_mic_recording():
    print_header(f"TEST 3: Mic Recording + RMS ({RECORD_SECONDS}s)")
    try:
        import sounddevice as sd
        from scipy.signal import resample_poly
        from math import gcd

        # Find the mic explicitly (same logic as transcriber)
        SKIP_KEYWORDS = {"cable", "stereo mix", "virtual", "mapper", "primary"}
        MIC_KEYWORDS  = {"microphone", "mic", "input", "array"}
        wasapi_idx = next(
            (i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api["name"]), None
        )
        mic_dev = None
        mic_rate = SAMPLE_RATE
        for i, dev in enumerate(sd.query_devices()):
            name = dev["name"].lower()
            if dev["max_input_channels"] > 0 and dev["hostapi"] == wasapi_idx:
                if any(s in name for s in SKIP_KEYWORDS):
                    continue
                if any(m in name for m in MIC_KEYWORDS):
                    mic_dev = i
                    mic_rate = int(dev["default_samplerate"])
                    break

        if mic_dev is None:
            print("[WARN] Could not find WASAPI mic — using system default")
        else:
            print(f"[INFO] Recording from device [{mic_dev}] @ {mic_rate}Hz")

        print(f">> SPEAK NOW for {RECORD_SECONDS} seconds (Hindi, English, or Hinglish)...")

        recording = sd.rec(
            int(RECORD_SECONDS * mic_rate),
            samplerate=mic_rate,
            channels=1,
            dtype="float32",
            device=mic_dev,
        )
        for i in range(RECORD_SECONDS, 0, -1):
            print(f"  {i}s remaining...", end="\r")
            time.sleep(1)
        sd.wait()
        print("\n[OK] Recording complete.")

        # Resample to 16kHz if needed
        audio = recording.flatten()
        if mic_rate != SAMPLE_RATE:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(SAMPLE_RATE, mic_rate)
            audio = resample_poly(audio, SAMPLE_RATE // g, mic_rate // g).astype(np.float32)
            print(f"[INFO] Resampled {mic_rate}Hz -> {SAMPLE_RATE}Hz")

        audio = recording.flatten()
        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        print(f"  RMS  : {rms:.5f}  (threshold: 0.002 — {'PASS' if rms >= 0.002 else 'FAIL: too quiet, audio will be skipped!'})")
        print(f"  Peak : {peak:.5f}")

        if rms < 0.002:
            print("  [WARN] Audio is below RMS threshold — check mic volume/permissions")
            return audio, False
        return audio, True
    except Exception as e:
        print(f"[FAIL] {e}")
        return None, False


# ── TEST 4: Whisper transcription ────────────────────────────
def test_transcription(audio):
    print_header("TEST 4: Whisper Transcription")
    if audio is None:
        print("[SKIP] No audio to transcribe")
        return

    try:
        import whisper
        import scipy.io.wavfile as wavfile

        print("[INFO] Loading Whisper medium model (may take a moment)...")
        try:
            import truststore
            truststore.inject_into_ssl()
        except ImportError:
            pass
        model = whisper.load_model("medium")
        print("[OK] Model loaded.")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name

        audio_i16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        wavfile.write(tmp, SAMPLE_RATE, audio_i16)

        hinglish_prompt = (
            "Theek hai, chalte hain. Haan bilkul, sahi kaha. "
            "Toh isko finalize karte hain. Koi issue nahi hai. "
            "Aage badhte hain next point pe."
        )

        print("[INFO] Transcribing with language=None (auto-detect)...")
        result = model.transcribe(
            tmp,
            language=None,
            beam_size=5,
            fp16=False,
            condition_on_previous_text=False,
            initial_prompt=hinglish_prompt,
            no_speech_threshold=0.8,
            compression_ratio_threshold=2.4,
        )

        detected_lang = result.get("language", "unknown")
        text = result["text"].strip()

        print(f"\n  Detected language : {detected_lang}")
        print(f"  Transcribed text  : {text if text else '(empty)'}")

        if not text:
            print("\n  [WARN] Empty output — Whisper may have filtered the audio.")
            print("  Try speaking louder or closer to the mic.")
        else:
            print("\n  [OK] Transcription successful!")

        os.unlink(tmp)

    except Exception as e:
        print(f"[FAIL] {e}")
        import traceback
        traceback.print_exc()


# ── TEST 5: System audio (loopback) ──────────────────────────
def test_system_audio():
    print_header("TEST 5: System Audio / Loopback Device")
    try:
        import sounddevice as sd
        devices = list(enumerate(sd.query_devices()))

        for i, dev in devices:
            if dev["max_input_channels"] > 0 and "cable output" in dev["name"].lower():
                print(f"[OK] VB-Cable Output found: [{i}] {dev['name']}")
                return

        wasapi_idx = next(
            (i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api["name"]), None
        )
        for i, dev in devices:
            if (dev["hostapi"] == wasapi_idx and dev["max_input_channels"] > 0
                    and "stereo mix" in dev["name"].lower()):
                print(f"[OK] Stereo Mix found: [{i}] {dev['name']}")
                return

        print("[WARN] No VB-Cable or Stereo Mix found.")
        print("  System audio (other participants) will NOT be captured.")
        print("  Only your microphone will be transcribed.")
        print("  Install VB-Audio Virtual Cable for full capture.")
    except Exception as e:
        print(f"[FAIL] {e}")


# ── Run all tests ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\nZoom Transcriber - Diagnostic Test")
    print("===================================")

    test_audio_devices()
    test_mic_detection()
    test_system_audio()
    audio, rms_ok = test_mic_recording()
    test_transcription(audio)

    print_header("DONE")
    print("Share the output above to diagnose any issues.\n")
