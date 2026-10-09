@echo off
rem One-time setup: creates .venv and installs everything.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python not found. Install Python 3.12+ from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
python -m venv .venv || (pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (pause & exit /b 1)
echo.
echo Setup done. Double-click run.bat (Zoom/Meet/Teams) or run-whatsapp.bat (WhatsApp).
echo WhatsApp also needs OBS, the DroidCam Client and the DroidCam OBS plugin:
echo see "DroidCam Client and OBS setup" in README.md.
pause
