@echo off
title DNV Bastion Coordinator - Shared via ngrok
color 0A

REM ── Detect Python ──────────────────────────────────────────────────────────
set PYTHON=
for %%P in (python python3) do (
    if not defined PYTHON (
        %%P --version >nul 2>&1 && set PYTHON=%%P
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found on PATH.
    pause & exit /b 1
)

REM ── Check ngrok is present ─────────────────────────────────────────────────
if not exist "%~dp0ngrok.exe" (
    echo  [ERROR] ngrok.exe not found in this folder.
    pause & exit /b 1
)

REM ── Ensure folders exist ───────────────────────────────────────────────────
if not exist state     mkdir state
if not exist logs      mkdir logs
if not exist outputs   mkdir outputs
if not exist static    mkdir static
if not exist uploads   mkdir uploads

REM ── Install dependencies ──────────────────────────────────────────────────
echo  Checking dependencies...
%PYTHON% -m pip install --quiet flask pandas numpy openpyxl

REM ── Start Flask app ────────────────────────────────────────────────────────
cd /d "%~dp0"
echo  Starting DNV Coordinator...
start "DNV Coordinator Server" %PYTHON% app.py

REM ── Wait for Flask to be ready ────────────────────────────────────────────
timeout /t 3 /nobreak >nul

REM ── Read port Flask chose ─────────────────────────────────────────────────
set PORT=5000
if exist state\.port (
    set /p PORT=<state\.port
)

REM ── Start ngrok tunnel ────────────────────────────────────────────────────
start "ngrok tunnel" "%~dp0ngrok.exe" http %PORT%
timeout /t 4 /nobreak >nul
start http://localhost:%PORT%

REM ── Print instructions ────────────────────────────────────────────────────
echo.
echo  ============================================================
echo   STEPS TO SHARE WITH YOUR TEAM
echo  ============================================================
echo.
echo  STEP 1 — Look at the "ngrok tunnel" window.
echo           Find the line that starts with "Forwarding"
echo           It looks like:
echo             Forwarding  https://xxxx.ngrok-free.dev
echo.
echo  STEP 2 — Copy that https:// URL and send it to your team.
echo           URL CHANGES every time you restart — always use
echo           the one showing in the ngrok window right now.
echo.
echo  STEP 3 — Tell your team: when the page first loads they
echo           will see a yellow ngrok warning screen.
echo           They must click  "Visit Site"  to get through.
echo           This happens on first visit only.
echo.
echo  ============================================================
echo   TO STOP: close both "DNV Coordinator Server" windows
echo  ============================================================
echo.
pause >nul
