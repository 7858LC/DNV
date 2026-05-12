@echo off
:: ── Meeting Minutes — auto-start ─────────────────────────────────────────────
:: Runs at login via Windows Startup folder shortcut.
:: Logs to autostart.log in the same folder so you can verify it ran.

cd /d "%~dp0"

echo %DATE% %TIME% - Starting Meeting Minutes >> "%~dp0autostart.log"

:: ── Load API key from .apikey file ────────────────────────────────────────────
if not defined ANTHROPIC_API_KEY (
    if exist "%~dp0.apikey" (
        for /f "usebackq delims=" %%K in ("%~dp0.apikey") do set ANTHROPIC_API_KEY=%%K
    ) else (
        echo %DATE% %TIME% - ERROR: .apikey file not found >> "%~dp0autostart.log"
        exit /b 1
    )
)

:: ── Start app minimized ───────────────────────────────────────────────────────
start /min "Meeting Minutes" python "%~dp0app.py"

echo %DATE% %TIME% - App launched on port 5200 >> "%~dp0autostart.log"
