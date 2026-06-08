@echo off
REM Edit MOVIE_FOLDER to point at your dashcam videos folder.
SET MOVIE_FOLDER=%USERPROFILE%\Videos\dashcam

cd /d "%~dp0"
python repair_all.py "%MOVIE_FOLDER%"
if errorlevel 1 (
  echo.
  echo Repair failed. See message above.
  pause
  exit /b 1
)
echo.
echo Repaired files are in: %MOVIE_FOLDER%\_repaired
echo.
pause
