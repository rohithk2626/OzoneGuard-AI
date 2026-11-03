@echo off
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe
echo Installing Playwright (one time)...
%PY% -m pip install --quiet playwright
echo Starting the OzoneGuard server on port 8765...
start "OzoneGuard server" /min %PY% -m uvicorn backend.main:app --port 8765
echo Taking screenshots (about 2-4 minutes)...
%PY% tools\capture_analytics.py
echo Stopping server...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1
echo.
echo Done. Screenshots are in docs\report-screenshots
timeout /t 15
