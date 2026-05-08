@echo off
title DNV Coordinator - Diagnostics
color 0E

echo.
echo  ============================================================
echo   DNV BASTION COORDINATOR - Diagnostics
echo  ============================================================
echo.

:: Python
echo  [1] Python version:
python --version
if errorlevel 1 (echo  [FAIL] Python not found && goto :end)
echo.

:: pip
echo  [2] pip version:
pip --version
echo.

:: Packages
echo  [3] Installed packages:
pip show flask pandas numpy 2>&1
echo.

:: Port availability
echo  [4] Port availability:
python -c "
import socket
for port in [5000, 5001, 8080, 8888]:
    try:
        s = socket.socket()
        s.bind(('127.0.0.1', port))
        s.close()
        print(f'  port {port}: AVAILABLE')
    except OSError as e:
        print(f'  port {port}: BLOCKED ({e})')
"
echo.

:: Imports
echo  [5] Import test:
python -c "
try:
    import flask; print('  flask OK -', flask.__version__)
except Exception as e:
    print('  flask FAIL:', e)
try:
    import pandas; print('  pandas OK -', pandas.__version__)
except Exception as e:
    print('  pandas FAIL:', e)
try:
    import numpy; print('  numpy OK -', numpy.__version__)
except Exception as e:
    print('  numpy FAIL:', e)
"
echo.

:: Try starting Flask directly and capture output
echo  [6] Flask startup test (5 seconds):
python -c "
import subprocess, sys, time, threading, urllib.request

proc = subprocess.Popen(
    [sys.executable, 'app.py'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1
)

output = []
def reader():
    for line in proc.stdout:
        output.append(line.rstrip())
        print('  ' + line.rstrip())

t = threading.Thread(target=reader, daemon=True)
t.start()
time.sleep(5)

# Try to connect
for port in [5000, 5001, 8080, 8888]:
    try:
        urllib.request.urlopen(f'http://localhost:{port}/', timeout=1)
        print(f'  [OK] Server responded on port {port}')
        break
    except Exception:
        pass
else:
    print('  [FAIL] No response on any port')

proc.terminate()
"
echo.

:end
echo  ============================================================
echo   Copy everything above and share with support if needed.
echo  ============================================================
echo.
pause
