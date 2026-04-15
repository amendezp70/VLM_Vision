@echo off
REM Run VLM Vision natively on Windows (no Docker needed).
REM Usage:  scripts\run_windows.bat

cd /d "%~dp0\.."

REM ── Check Python ──────────────────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: Python not found. Install Python 3.11 from https://python.org
    exit /b 1
)

python --version

REM ── Virtual environment ───────────────────────────────────
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM ── Dependencies ──────────────────────────────────────────
echo Installing dependencies...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

REM ── Environment ───────────────────────────────────────────
if not exist ".env" (
    echo Warning: .env not found — copy .env.example to .env and edit it.
    echo   copy .env.example .env
    exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "%%a=%%b"
)

REM ── Create data dir ──────────────────────────────────────
if not exist "data" mkdir data
if not exist "models" mkdir models

REM ── Launch ────────────────────────────────────────────────
echo Starting VLM Vision on http://localhost:%WEBSOCKET_PORT%
python -m local_agent.main
