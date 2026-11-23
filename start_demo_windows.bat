@echo off
rem EHMS demo on Windows: double-click this file, then open http://localhost:8000
rem Needs Python 3.11+ (python.org, tick "Add python.exe to PATH"). Node is not needed: the interface is pre-built.
cd /d "%~dp0backend"
python -m pip install -r requirements.txt
if errorlevel 1 (echo Python or pip failed - install Python 3.11+ and try again & pause & exit /b 1)
for /f %%k in ('python -c "import secrets;print(secrets.token_urlsafe(48))"') do set EHMS_SECRET_KEY=%%k
set DATABASE_URL=sqlite:///./ehms.db
set EHMS_SEED_DEMO=1
echo.
echo EHMS is starting: open http://localhost:8000 and sign in as admin@demo.ehms / Demo@12345
echo Keep this window open while you use EHMS. Press Ctrl+C to stop.
python -m uvicorn ehms.app:app --port 8000
pause
