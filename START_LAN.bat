@echo off
title DNV Bastion Coordinator - LAN Mode
color 0A

echo.
echo  ============================================================
echo   DNV BASTION COORDINATOR — LAN MODE
echo  ============================================================
echo.
echo  NOTE: This requires the firewall port to already be open.
echo  If teammates cannot connect, ask IT to run OPEN_FIREWALL.bat
echo  as administrator once.
echo.
echo  ============================================================
echo.

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

REM ── Ensure folders exist ───────────────────────────────────────────────────
if not exist state     mkdir state
if not exist logs      mkdir logs
if not exist outputs   mkdir outputs
if not exist static    mkdir static
if not exist uploads   mkdir uploads

REM ── Start Flask ────────────────────────────────────────────────────────────
cd /d "%~dp0"
echo  Starting DNV Coordinator...
echo.
echo  Your team can connect at:
echo    http://192.168.11.37:5000
echo.
echo  (If port 5000 is taken the console will show the actual port)
echo.

start "DNV Coordinator Server" %PYTHON% app.py

timeout /t 3 /nobreak >nul
start http://localhost:5000

echo  Server is running. Close the "DNV Coordinator Server" window to stop.
pause >nul
