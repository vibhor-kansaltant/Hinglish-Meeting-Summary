@echo off
setlocal enabledelayedexpansion
title Zoom ^& Teams Transcriber - Installer

echo ============================================================
echo   Zoom ^& Teams Meeting Transcriber - One-Click Installer
echo ============================================================
echo.

:: ── Step 1: Check Python ──────────────────────────────────────────────────────
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python is not installed.
    echo  Please install Python 3.10+ from https://python.org
    echo  Make sure to tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
python --version
echo  OK

:: ── Step 2: Install Python packages ──────────────────────────────────────────
echo.
echo [2/5] Installing Python packages (this may take a few minutes)...
pip install openai-whisper sounddevice numpy psutil scipy pystray pillow imageio-ffmpeg --user --quiet
if errorlevel 1 (
    echo  ERROR: Package installation failed. Check your internet connection.
    pause
    exit /b 1
)
echo  OK

:: ── Step 3: Setup ffmpeg ──────────────────────────────────────────────────────
echo.
echo [3/5] Setting up ffmpeg...
python -c "import imageio_ffmpeg, shutil, os; src=imageio_ffmpeg.get_ffmpeg_exe(); dst=os.path.join(os.path.dirname(os.path.abspath('%~f0')), 'ffmpeg.exe'); shutil.copy2(src,dst) if not os.path.exists(dst) else None; print('OK')"
echo  OK

:: ── Step 4: VB-Cable check ────────────────────────────────────────────────────
echo.
echo [4/5] Checking VB-Audio Virtual Cable...
python -c "import sounddevice as sd; found=any('cable' in d['name'].lower() for d in sd.query_devices()); print('FOUND' if found else 'MISSING')" > %TEMP%\vbcheck.txt 2>&1
set /p VBSTATUS=<%TEMP%\vbcheck.txt

if "!VBSTATUS!"=="FOUND" (
    echo  VB-Cable detected - OK
) else (
    echo.
    echo  VB-Cable NOT found.
    echo  ----------------------------------------------------------------
    echo  VB-Cable is required to capture remote audio (other participants).
    echo  Please:
    echo    1. Download VB-Cable from: vb-audio.com/Cable
    echo    2. Extract the zip
    echo    3. Right-click VBCABLE_Setup_x64.exe and Run as Administrator
    echo    4. Restart your PC
    echo    5. In Zoom/Teams settings, set Speaker to "CABLE Input"
    echo    6. In Windows Sound settings, Recording tab:
    echo       Right-click "CABLE Output" - Properties - Listen tab
    echo       Tick "Listen to this device" - Playback: Default
    echo  ----------------------------------------------------------------
    echo.
    echo  You can still use the app without VB-Cable (mic only - your voice only).
    echo.
)

:: ── Step 5: Create desktop shortcut ──────────────────────────────────────────
echo.
echo [5/5] Creating desktop shortcut...
python "%~dp0create_icon.py"
echo  OK

echo.
echo ============================================================
echo   Installation complete!
echo.
echo   The app will appear on your Desktop.
echo   Double-click to launch - it runs silently in the system tray.
echo   Right-click the tray icon to see status or open transcripts.
echo.
echo   Transcripts saved to: %USERPROFILE%\Documents\ZoomTranscripts
echo ============================================================
echo.
pause
