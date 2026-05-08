@echo off
title DNV Bastion Coordinator - Network Mode
color 0A

REM ── Must run as Administrator to add firewall rule ─────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [!] This script needs Administrator rights to open the firewall port.
    echo      Right-click START_NETWORK.bat and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

REM ── Detect Python ──────────────────────────────────────────────────────────
set PYTHON=
for %%P in (python python3) do (
    if not defined PYTHON (
        %%P --version >nul 2>&1 && set PYTHON=%%P
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found on PATH.
    pause
    exit /b 1
)

REM ── Install / verify dependencies ─────────────────────────────────────────
echo  Checking dependencies...
%PYTHON% -m pip install --quiet flask pandas numpy openpyxl

REM ── Open Windows Firewall for port 5000 (and fallbacks) ───────────────────
echo  Adding firewall rule for DNV Coordinator (ports 5000, 5001, 8080, 8888, 8000)...

netsh advfirewall firewall delete rule name="DNV Coordinator" >nul 2>&1
netsh advfirewall firewall add rule ^
    name="DNV Coordinator" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=5000,5001,8080,8888,8000 ^
    description="DNV Bastion Coordinator web app - network access"

if %errorlevel% equ 0 (
    echo  [OK] Firewall rule added.
) else (
    echo  [WARN] Firewall rule may not have been applied - check manually if others cannot connect.
)

REM ── Ensure required folders exist ─────────────────────────────────────────
if not exist state     mkdir state
if not exist logs      mkdir logs
if not exist outputs   mkdir outputs
if not exist static    mkdir static
if not exist uploads   mkdir uploads

REM ── Start the server ──────────────────────────────────────────────────────
echo.
echo  Starting DNV Coordinator in network mode...
echo  Your team can connect at  http://192.168.11.37:5000
echo  (if port 5000 is taken, check the console window for the actual port)
echo.

cd /d "%~dp0"
start "DNV Coordinator Server" %PYTHON% app.py

REM ── Wait for server then open browser locally ─────────────────────────────
timeout /t 3 /nobreak >nul
start http://localhost:5000

echo.
echo  Server is running. Close the "DNV Coordinator Server" window to stop.
echo  Press any key to close this launcher.
pause >nul
