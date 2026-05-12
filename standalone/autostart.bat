@echo off
:: ── Meeting Minutes — background auto-start ──────────────────────────────────
:: Place a shortcut to this file in your Windows Startup folder so it runs at login.
:: To open the Startup folder: press Win+R, type shell:startup, press Enter.
::
:: The app runs minimized in the background. To stop it, close the
:: "Meeting Minutes Server" window from the taskbar.

cd /d "%~dp0"

if not defined ANTHROPIC_API_KEY (
    for /f "usebackq delims=" %%K in ("%~dp0.apikey") do set ANTHROPIC_API_KEY=%%K
)

start /min "Meeting Minutes Server" python app.py
