@echo off
REM Diana launcher for Windows
cd /d "%~dp0"
echo ============================================
echo   Diana is waking up...
echo   Open in browser: http://localhost:8000
echo ============================================
start "" http://localhost:8000
python server.py
pause
