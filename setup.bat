@echo off
echo ============================================================
echo  Zoom Transcriber - Setup
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

echo [1/3] Upgrading pip...
python -m pip install --upgrade pip

echo.
echo [2/3] Installing dependencies...
pip install -r requirements.txt

echo.
echo [3/3] Installing ffmpeg (required by Whisper)...
pip install ffmpeg-python
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARN] ffmpeg binary not found in PATH.
    echo        Whisper needs ffmpeg.exe - easiest way to get it:
    echo        1. Install via winget:  winget install Gyan.FFmpeg
    echo        2. Or download from:   https://ffmpeg.org/download.html
    echo           and add it to your PATH.
    echo.
)

echo.
echo ============================================================
echo  Setup complete!  Run:  run.bat   or   python zoom_transcriber.py
echo ============================================================
pause
