@echo off
title DNV Bastion Coordinator
color 0A
cd /d "%~dp0"

echo(
echo  ============================================================
echo   DNV BASTION COORDINATOR
echo  ============================================================
echo(

:: ── Find Python ──────────────────────────────────────────────────
set PYTHON=
for %%P in (python py) do (
    if not defined PYTHON (
        %%P --version >nul 2>&1 && set PYTHON=%%P
    )
)
if not defined PYTHON (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python311\python.exe"
        "C:\Python312\python.exe"
    ) do (
        if not defined PYTHON (
            if exist %%P set PYTHON=%%P
        )
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found.
    echo  Install Python from https://www.python.org and try again.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('%PYTHON% --version 2^>^&1') do echo  [OK] %%v

:: ── Dependencies ─────────────────────────────────────────────────
echo  [..] Checking dependencies...
%PYTHON% -m pip install flask pandas numpy openpyxl -q --disable-pip-version-check
echo  [OK] Dependencies ready

:: ── Required folders ─────────────────────────────────────────────
if not exist "state"   mkdir state
if not exist "logs"    mkdir logs
if not exist "outputs" mkdir outputs
if not exist "static"  mkdir static

:: ── Start server ──────────────────────────────────────────────────
echo(
echo  [..] Starting server...
echo(
start "" "%PYTHON%" app.py

:: Wait for Flask to bind and write state\.port
timeout /t 3 /nobreak >nul

:: Read the chosen port
set PORT=5000
if exist "state\.port" set /p PORT=<"state\.port"

:: Get LAN IP via PowerShell (skip loopback)
set LAN_IP=
for /f %%i in ('powershell -NoProfile -Command ^
  "([Net.Dns]::GetHostAddresses([Net.Dns]::GetHostName()) | Where-Object {$_.AddressFamily -eq 2 -and $_.ToString() -notlike '127.*'})[0].ToString() 2>$null"') do set LAN_IP=%%i

if not defined LAN_IP set LAN_IP=^<check-ipconfig^>

:: Open browser on local address
start "" "http://localhost:%PORT%"

echo(
echo  ============================================================
echo   DNV BASTION COORDINATOR  --  SERVER RUNNING
echo  ============================================================
echo(
echo   LOCAL    http://localhost:%PORT%
echo   NETWORK  http://%LAN_IP%:%PORT%   ^<-- share with team
echo(
echo   Teammates: open the NETWORK address in any browser.
echo   Press CTRL+C in the Python window to stop the server.
echo  ============================================================
echo(
pause >nul