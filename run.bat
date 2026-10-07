@echo off
rem Webcam + reactions -> "OBS Virtual Camera" (Zoom, Meet, Teams, Discord...)
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python gesture_reactions.py %*
if errorlevel 1 pause
