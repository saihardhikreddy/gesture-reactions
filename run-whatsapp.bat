@echo off
rem Webcam + reactions -> "Gesture Reactions Output" window for OBS + DroidCam (WhatsApp)
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python gesture_reactions.py --whatsapp %*
if errorlevel 1 pause
