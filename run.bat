@echo off
echo ============================================================
echo  Zoom Transcriber
echo  Transcripts saved to: %USERPROFILE%\Documents\ZoomTranscripts
echo ============================================================
echo.

:: Options: change --model to tiny/base/small/medium/large
::          change --chunk to adjust seconds per transcription segment
python zoom_transcriber.py --model medium --chunk 30

pause
