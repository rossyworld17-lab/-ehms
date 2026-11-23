@echo off
rem EHMS demo on Windows: double-click this file, then open http://localhost:8000
rem Needs Python 3.11+ (python.org, tick "Add python.exe to PATH"). Node is not needed: the interface is pre-built.
title EHMS 1.1.2
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  echo.
  echo Port 8000 is already in use - most likely an OLDER copy of EHMS is still running.
  echo While it runs, your browser keeps showing the old screens.
  echo Close every other EHMS / Command Prompt window, or restart the PC, then double-click this file again.
  echo.
  pause
  exit /b 1
)
cd /d "%~dp0backend"
python -m pip install -r requirements.txt
if errorlevel 1 (echo Python or pip failed - install Python 3.11+ and try again & pause & exit /b 1)
for /f %%k in ('python -c "import secrets;print(secrets.token_urlsafe(48))"') do set EHMS_SECRET_KEY=%%k
set DATABASE_URL=sqlite:///./ehms.db
set EHMS_SEED_DEMO=1
echo.
echo EHMS 1.1.2 is starting: open http://localhost:8000 and sign in as admin@demo.ehms / Demo@12345
echo The sign-in page and the menu show "v1.1.2". Keep this window open; press Ctrl+C to stop.
python -m uvicorn ehms.app:app --port 8000
pause
