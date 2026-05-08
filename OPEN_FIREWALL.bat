@echo off
title DNV Bastion — Open Firewall Port 5000
color 0A

echo(
echo  ============================================================
echo   DNV BASTION COORDINATOR — FIREWALL SETUP
echo  ============================================================
echo(
echo  This adds a Windows Firewall rule so teammates can reach
echo  the app on your network at http://[your-ip]:5000
echo(
echo  Requires administrator privileges (you may see a UAC prompt).
echo  ============================================================
echo(

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo  [!] Not running as administrator.
    echo      Right-click this file and choose "Run as administrator".
    echo(
    pause
    exit /b 1
)

:: Remove old rule if it exists (clean slate)
netsh advfirewall firewall delete rule name="DNV Bastion Coordinator (Port 5000)" >nul 2>&1

:: Add new rule — ALL profiles (Domain, Private, Public)
netsh advfirewall firewall add rule ^
  name="DNV Bastion Coordinator (Port 5000)" ^
  protocol=TCP ^
  dir=in ^
  localport=5000 ^
  action=allow ^
  profile=any ^
  description="Allow inbound TCP 5000 for DNV Bastion Coordinator Flask app"

if %errorLevel% EQU 0 (
    echo(
    echo  [OK] Firewall rule added successfully.
    echo(

    :: Show the machine's LAN IP
    echo  Your network addresses:
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
        set _raw=%%a
        setlocal enabledelayedexpansion
        set _ip=!_raw: =!
        echo    http://!_ip!:5000
        endlocal
    )
    echo(
    echo  Share any of the above addresses with your teammates.
    echo  They can open it in any browser on the same network.
) else (
    echo(
    echo  [ERROR] Could not add firewall rule. Contact your IT admin
    echo          and ask them to allow inbound TCP port 5000.
)

echo(
pause
