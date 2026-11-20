@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run: python -m venv .venv
  pause
  exit /b 1
)

if not exist ".env" (
  echo Missing .env. Run: python scripts\init_env.py
  pause
  exit /b 1
)

start "AdBot API" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe -m alembic upgrade head && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "AdBot Worker" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe -m app.worker"
start "AdBot Scheduler" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe -m app.scheduler"
start "AdBot Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Started API, Worker, Scheduler and Frontend.
echo Dashboard: http://127.0.0.1:5173
