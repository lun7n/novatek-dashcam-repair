@echo off
REM Build standalone DashcamRepair.exe (Windows, no Python needed for end users)
cd /d "%~dp0"

echo Installing PyInstaller if needed...
python -m pip install pyinstaller --quiet

echo Building DashcamRepair.exe ...
python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name DashcamRepair ^
  --clean ^
  repair_gui.py

if errorlevel 1 (
  echo BUILD FAILED
  pause
  exit /b 1
)

echo.
echo SUCCESS: dist\DashcamRepair.exe
echo Upload to GitHub Releases for users without Python.
pause
