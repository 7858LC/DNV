"""
DNV Bastion Coordinator - Diagnostics
Double-click this file OR run:  python DIAGNOSE.py
Prints a full report of what is working and what is not.
"""
import sys
import os
import socket
import platform
import traceback
from pathlib import Path

# Always run from the script's own directory
os.chdir(Path(__file__).parent)

SEP = "=" * 62

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def ok(msg):   print(f"  [OK]   {msg}")
def fail(msg): print(f"  [FAIL] {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def info(msg): print(f"         {msg}")

print(f"\n{SEP}")
print("  DNV BASTION COORDINATOR - Diagnostics Report")
print(SEP)

# ── 1. System ────────────────────────────────────────────────────
section("1. System")
ok(f"Python  {sys.version}")
ok(f"OS      {platform.system()} {platform.release()} {platform.machine()}")
ok(f"Folder  {Path.cwd()}")

# ── 2. Required files ────────────────────────────────────────────
section("2. Required Files")
required = [
    "app.py", "orchestrator.py", "utils.py", "config.json",
    "agent_intake.py", "agent_tracker.py", "agent_audit.py",
    "agent_tq.py", "agent_dashboard.py",
    "templates/dashboard.html",
    "data/submissions.csv", "data/action_tracker.csv",
    "data/tq_log.csv", "data/audit_definitions.csv",
]
all_present = True
for f in required:
    p = Path(f)
    if p.exists():
        ok(f"{f}")
    else:
        fail(f"{f}  <-- MISSING")
        all_present = False

if all_present:
    ok("All required files present")

# ── 3. Package imports ───────────────────────────────────────────
section("3. Python Packages")
packages = {
    "flask":   "Flask",
    "pandas":  "pandas",
    "numpy":   "numpy",
    "openpyxl":"openpyxl",
}
imports_ok = True
for mod, name in packages.items():
    try:
        m = __import__(mod)
        ok(f"{name:12}  {m.__version__}")
    except ImportError as e:
        fail(f"{name:12}  NOT INSTALLED  ->  {e}")
        imports_ok = False
    except Exception as e:
        fail(f"{name:12}  ERROR: {e}")
        imports_ok = False

if not imports_ok:
    print()
    warn("Missing packages. Fix with:")
    info("python -m pip install --no-index --find-links=wheels -r requirements.txt")
    info("   (uses bundled wheels, no internet needed)")
    info("OR:  python -m pip install flask pandas numpy openpyxl")

# ── 4. Port availability ─────────────────────────────────────────
section("4. Port Availability")
free_port = None
for port in [5000, 5001, 8080, 8888, 8000]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            ok(f"Port {port}  AVAILABLE  <-- will use this one")
            if free_port is None:
                free_port = port
        except OSError:
            warn(f"Port {port}  IN USE OR BLOCKED")

if free_port is None:
    fail("No usable ports found - corporate firewall may be blocking all localhost ports")
    info("Ask IT to allow localhost (127.0.0.1) TCP ports 5000-9000")

# ── 5. Socket creation test ──────────────────────────────────────
section("5. Network Socket Permission")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.close()
    ok("Can create TCP socket")
except Exception as e:
    fail(f"Cannot create TCP socket: {e}")
    info("Security policy may be blocking Python network access")
    info("Ask IT to whitelist python.exe for localhost connections")

# ── 6. Config & state ────────────────────────────────────────────
section("6. Config & State")
try:
    import json
    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    ok(f"config.json loaded  (amber_threshold={cfg.get('amber_threshold')}, "
       f"tq_sla_days={cfg.get('tq_sla_days')})")
except Exception as e:
    fail(f"config.json: {e}")

state_path = Path("state/computed_state.json")
if state_path.exists():
    try:
        st = json.loads(state_path.read_text(encoding="utf-8"))
        ok(f"computed_state.json  (run_date={st.get('run_date')}, "
           f"rag={st.get('program_rag')})")
    except Exception as e:
        fail(f"computed_state.json corrupt: {e}")
else:
    warn("No computed_state.json - pipeline has not been run yet")
    info("Will run automatically on first start")

# ── 7. Live Flask test ───────────────────────────────────────────
section("7. Live Server Test")
if free_port and imports_ok:
    import threading, time, urllib.request, subprocess
    print(f"  Starting Flask on port {free_port} for 6 seconds...")

    env = os.environ.copy()
    env["DNV_TEST_PORT"] = str(free_port)
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"import os; os.chdir(r'{Path.cwd()}'); "
         f"from app import app; app.run(host='127.0.0.1', port={free_port}, "
         f"debug=False, use_reloader=False)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    time.sleep(3)
    try:
        resp = urllib.request.urlopen(f"http://localhost:{free_port}/api/state",
                                      timeout=3)
        data = json.loads(resp.read())
        if "error" not in data or "program_rag" in data:
            ok(f"Server responded on http://localhost:{free_port}")
            ok(f"API returned valid JSON (rag={data.get('program_rag','?')})")
        else:
            warn(f"Server responded but: {data.get('error','?')}")
    except Exception as e:
        fail(f"Could not reach http://localhost:{free_port}  ->  {e}")
        stdout, stderr = proc.communicate(timeout=2)
        if stderr:
            info("Flask stderr:")
            for line in stderr.strip().splitlines():
                info(f"  {line}")
    finally:
        proc.terminate()
else:
    warn("Skipping live test - fix packages/ports above first")

# ── Summary ──────────────────────────────────────────────────────
section("Summary & Next Steps")
if imports_ok and free_port:
    ok(f"Ready to run!  Open start.bat  OR  python app.py")
    ok(f"Dashboard will be at: http://localhost:{free_port}")
else:
    if not imports_ok:
        fail("Packages missing - run: python -m pip install --no-index --find-links=wheels -r requirements.txt")
    if not free_port:
        fail("All ports blocked - contact IT to allow Python on localhost")

print(f"\n{SEP}\n")
input("  Press ENTER to close...")
