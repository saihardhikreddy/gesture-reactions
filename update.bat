@echo off
rem Gets the latest version and refreshes the Python packages.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Run setup.bat first. & pause & exit /b 1)
if exist .git (
  git pull --ff-only || (echo Could not update with git. Commit or undo your own changes first. & pause & exit /b 1)
) else (
  echo This folder came from a ZIP. Download the new ZIP from
  echo https://github.com/saihardhikreddy/gesture-reactions and extract it over this folder,
  echo then run update.bat again to refresh the packages.
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt || (pause & exit /b 1)
echo.
echo Up to date.
pause
