@echo off
title Meeting Minutes
color 0A
cd /d "%~dp0"

echo.
echo  ============================================
echo   MEETING MINUTES
echo  ============================================
echo.

:: ── Find Python ──────────────────────────────────────────────────────────────
set PYTHON=
for %%P in (python py) do (
    if not defined PYTHON (
        %%P --version >nul 2>&1 && set PYTHON=%%P
    )
)
if not defined PYTHON (
    echo  [ERROR] Python not found.
    echo  Download from https://www.python.org
    pause & exit /b 1
)

:: ── API Key ───────────────────────────────────────────────────────────────────
if not defined ANTHROPIC_API_KEY (
    echo  Enter your Anthropic API key (starts with sk-ant-):
    set /p ANTHROPIC_API_KEY=  Key:
    echo.
)

:: ── Dependencies ─────────────────────────────────────────────────────────────
echo  [..] Installing dependencies...
%PYTHON% -m pip install flask anthropic -q --disable-pip-version-check
echo  [OK] Ready

:: ── Start ─────────────────────────────────────────────────────────────────────
echo.
%PYTHON% app.py
pause
