#!/usr/bin/env python3
"""
deploy-script.py — Automates messy local project → clean GitHub repo → Railway deployment.

Usage:
    python deploy-script.py /path/to/project
    python deploy-script.py  (interactive mode)
"""

import argparse
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Force UTF-8 on Windows so emoji in log/print output doesn't crash cp1252 terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# ──────────────────────────────────────────────
# Logging: console + file
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("deploy.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

@dataclass
class ProjectAudit:
    source_root: Path
    project_name: str = ""
    frontend_paths: list[Path] = field(default_factory=list)
    backend_paths: list[Path] = field(default_factory=list)
    db_paths: list[Path] = field(default_factory=list)
    secret_paths: list[Path] = field(default_factory=list)
    has_frontend: bool = False
    has_backend: bool = False
    has_db: bool = False
    backend_entrypoint: str = "main.py"


# ──────────────────────────────────────────────
# Phase 1: Audit & Discovery
# ──────────────────────────────────────────────

FRONTEND_MARKERS = {"package.json", "next.config.js", "next.config.ts", "vite.config.js"}
FRONTEND_DIRS = {"components", "app", "pages", "src", "public"}
BACKEND_MARKERS = {"requirements.txt", "main.py", "app.py", "pyproject.toml", "setup.py"}
BACKEND_EXTENSIONS = {".py"}
DB_EXTENSIONS = {".sql"}
DB_DIRS = {"migrations", "db", "database", "schema"}
SECRET_NAMES = {".env", ".env.local", ".env.development", ".env.production", ".env.test"}
SECRET_EXTENSIONS = {".key", ".pem", ".p12", ".pfx"}


def audit_project(source: Path) -> ProjectAudit:
    """Walk source folder and classify every file by layer."""
    log.info(f"Auditing: {source}")
    audit = ProjectAudit(source_root=source, project_name=source.name)

    all_files = list(source.rglob("*"))
    all_names = {f.name for f in all_files if f.is_file()}
    all_dirs = {f.name.lower() for f in all_files if f.is_dir()}

    # Frontend detection
    if FRONTEND_MARKERS & all_names or FRONTEND_DIRS & all_dirs:
        audit.has_frontend = True
        for f in all_files:
            if f.is_file() and (
                f.name in FRONTEND_MARKERS
                or any(part in FRONTEND_DIRS for part in f.parts)
                or f.suffix in {".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html"}
            ):
                audit.frontend_paths.append(f)

    # Backend detection
    if BACKEND_MARKERS & all_names or any(f.suffix == ".py" for f in all_files if f.is_file()):
        audit.has_backend = True
        for f in all_files:
            if f.is_file() and (
                f.name in BACKEND_MARKERS or f.suffix in BACKEND_EXTENSIONS
            ):
                audit.backend_paths.append(f)
        # Prefer main.py, fall back to app.py
        if (source / "main.py").exists() or any(f.name == "main.py" for f in all_files):
            audit.backend_entrypoint = "main.py"
        elif any(f.name == "app.py" for f in all_files):
            audit.backend_entrypoint = "app.py"

    # Database detection
    for f in all_files:
        if f.is_file() and (
            f.suffix in DB_EXTENSIONS
            or f.name.lower() == "schema.sql"
            or any(part.lower() in DB_DIRS for part in f.parts)
        ):
            audit.db_paths.append(f)
            audit.has_db = True

    # Secret detection — flag, never copy
    for f in all_files:
        if f.is_file() and (
            f.name in SECRET_NAMES
            or f.suffix in SECRET_EXTENSIONS
            or re.search(r"secret|credential|api[-_]?key|token", f.name, re.I)
        ):
            audit.secret_paths.append(f)

    return audit


def print_audit(audit: ProjectAudit) -> None:
    """Print human-readable audit summary."""
    print("\n" + "═" * 60)
    print(f"  AUDIT SUMMARY: {audit.project_name}")
    print("═" * 60)
    print(f"  📁 Source:    {audit.source_root}")
    print(f"  ⚛️  Frontend:  {'✅ Detected' if audit.has_frontend else '❌ Not found'}")
    if audit.has_frontend:
        print(f"             ({len(audit.frontend_paths)} files)")
    print(f"  🐍 Backend:   {'✅ Detected' if audit.has_backend else '❌ Not found'}")
    if audit.has_backend:
        print(f"             ({len(audit.backend_paths)} files, entrypoint: {audit.backend_entrypoint})")
    print(f"  🗄️  Database:  {'✅ Detected' if audit.has_db else '❌ Not found'}")
    if audit.has_db:
        print(f"             ({len(audit.db_paths)} files)")
    if audit.secret_paths:
        print(f"\n  ⚠️  SECRETS DETECTED ({len(audit.secret_paths)} files) — will NOT be copied:")
        for s in audit.secret_paths:
            print(f"       🔒 {s.relative_to(audit.source_root)}")
    print("═" * 60 + "\n")


def confirm_audit(audit: ProjectAudit) -> ProjectAudit:
    """Let user override detection results interactively."""
    print("Does this look correct? (y to continue, n to adjust)")
    choice = input("  → ").strip().lower()
    if choice == "n":
        name = input(f"  Project name [{audit.project_name}]: ").strip()
        if name:
            audit.project_name = name

        if not audit.has_frontend:
            audit.has_frontend = input("  Include frontend layer? (y/n): ").strip().lower() == "y"
        if not audit.has_backend:
            audit.has_backend = input("  Include backend layer? (y/n): ").strip().lower() == "y"
        if not audit.has_db:
            audit.has_db = input("  Include db layer? (y/n): ").strip().lower() == "y"
        if audit.has_backend:
            ep = input(f"  Backend entrypoint [{audit.backend_entrypoint}]: ").strip()
            if ep:
                audit.backend_entrypoint = ep
    return audit


# ──────────────────────────────────────────────
# Phase 2: Reorganize into standard structure
# ──────────────────────────────────────────────

def create_output_dir(audit: ProjectAudit, output_parent: Optional[Path] = None) -> Path:
    """Resolve and create the clean output directory (never overwrites source)."""
    base = output_parent or audit.source_root.parent
    out = base / f"{audit.project_name}-ready"

    if out.exists():
        print(f"\n⚠️  Output folder already exists: {out}")
        choice = input("  Overwrite it? (y/n): ").strip().lower()
        if choice != "y":
            log.info("User declined overwrite — exiting.")
            sys.exit(0)
        shutil.rmtree(out)
        log.info(f"Removed existing output: {out}")

    out.mkdir(parents=True)
    log.info(f"Created output dir: {out}")
    return out


def _safe_copy(src: Path, dst: Path) -> None:
    """Copy file, creating parent dirs as needed, skip secrets."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    log.info(f"  copied {src.name} → {dst}")


def organize_frontend(audit: ProjectAudit, out: Path) -> None:
    """Copy frontend files into out/frontend/, preserving relative structure."""
    if not audit.has_frontend:
        return
    fe_dir = out / "frontend"
    fe_dir.mkdir(parents=True, exist_ok=True)
    log.info("Organizing frontend...")

    # Try to find the frontend root (where package.json lives)
    fe_root: Optional[Path] = None
    for f in audit.frontend_paths:
        if f.name == "package.json":
            fe_root = f.parent
            break
    fe_root = fe_root or audit.source_root

    for f in audit.frontend_paths:
        if f in audit.secret_paths:
            continue
        try:
            rel = f.relative_to(fe_root)
        except ValueError:
            rel = Path(f.name)
        _safe_copy(f, fe_dir / rel)


def organize_backend(audit: ProjectAudit, out: Path) -> None:
    """Copy backend files into out/backend/, preserving relative structure."""
    if not audit.has_backend:
        return
    be_dir = out / "backend"
    be_dir.mkdir(parents=True, exist_ok=True)
    log.info("Organizing backend...")

    # Find backend root (where entrypoint lives)
    be_root: Optional[Path] = None
    for f in audit.backend_paths:
        if f.name == audit.backend_entrypoint:
            be_root = f.parent
            break
    be_root = be_root or audit.source_root

    for f in audit.backend_paths:
        if f in audit.secret_paths:
            continue
        try:
            rel = f.relative_to(be_root)
        except ValueError:
            rel = Path(f.name)
        _safe_copy(f, be_dir / rel)


def organize_db(audit: ProjectAudit, out: Path) -> None:
    """Copy DB/migration files into out/db/."""
    if not audit.has_db:
        return
    db_dir = out / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "migrations").mkdir(exist_ok=True)
    log.info("Organizing db...")

    for f in audit.db_paths:
        if f in audit.secret_paths:
            continue
        # Put migration files in migrations/, schema at root
        if "migrat" in str(f).lower():
            _safe_copy(f, db_dir / "migrations" / f.name)
        else:
            _safe_copy(f, db_dir / f.name)


# ──────────────────────────────────────────────
# Phase 3 & 4: Generate config & GitHub files
# ──────────────────────────────────────────────

ROOT_GITIGNORE = """\
# OS
.DS_Store
*.swp
*.swo
*~
Thumbs.db

# Secrets — never commit these
.env
.env.local
.env.*.local
*.key
*.pem

# Node
node_modules/
npm-debug.log
yarn-error.log
.next/
dist/
build/

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
venv/
env/
.venv/

# IDEs
.vscode/
.idea/
*.sublime-project
*.sublime-workspace
"""

FRONTEND_GITIGNORE = """\
node_modules/
.next/
out/
dist/
.env
.env.local
.env.*.local
"""

BACKEND_GITIGNORE = """\
__pycache__/
*.pyc
*.pyo
venv/
env/
.venv/
.env
.env.local
*.egg-info/
"""

FRONTEND_RAILWAY_JSON = {
    "build": {"builder": "nixpacks"},
    "deploy": {"startCommand": "npm start"},
}

BACKEND_RAILWAY_JSON = {
    "build": {"builder": "nixpacks"},
    "deploy": {"startCommand": "python main.py"},
}

BACKEND_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

DOCKER_COMPOSE = """\
version: "3.9"
services:
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    depends_on:
      - backend

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=mysql://root:password@db:3306/app
    depends_on:
      - db

  db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: password
      MYSQL_DATABASE: app
    ports:
      - "3306:3306"
    volumes:
      - ./db/schema.sql:/docker-entrypoint-initdb.d/schema.sql
"""

DB_README = """\
# Database

**Engine:** MySQL 8.0

## Initialize (Railway)

1. Add a MySQL plugin to your Railway backend service.
2. Railway provides `DATABASE_URL` automatically as an env var.
3. In the Railway service shell, run:
   ```bash
   mysql -h $MYSQLHOST -u $MYSQLUSER -p$MYSQLPASSWORD $MYSQLDATABASE < schema.sql
   ```

## Run Migrations

Place migration scripts in `migrations/` numbered sequentially (e.g. `001_init.sql`).
Run them in order:
```bash
for f in migrations/*.sql; do mysql ... < "$f"; done
```

## Connection String Pattern (Backend `.env`)
```
DATABASE_URL=mysql://USER:PASSWORD@HOST:3306/DB_NAME
```
Railway injects this automatically when a MySQL plugin is attached.
"""

BACKEND_README = """\
# Backend

**Runtime:** Python 3.11 | FastAPI

## Local Setup
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env       # fill in your values
python main.py
```

## Environment Variables
| Variable | Description |
|---|---|
| `DATABASE_URL` | MySQL connection string |
| `SECRET_KEY` | App secret key |
| `FRONTEND_URL` | CORS allow-origin |

## API Endpoints
Document your routes here.

## Deployment (Railway)
Root directory: `backend/`
Start command: `python main.py`
"""

FRONTEND_README = """\
# Frontend

**Runtime:** Node.js 18+ | Next.js

## Local Setup
```bash
npm install
cp .env.example .env.local   # fill in your values
npm run dev
```

## Environment Variables
| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend API base URL |

## Deployment (Railway)
Root directory: `frontend/`
Start command: `npm start`
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log.info(f"  generated {path}")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    log.info(f"  generated {path}")


def generate_root_readme(project_name: str) -> str:
    return f"""\
# {project_name}

**Tech Stack:** Next.js (frontend) | Python FastAPI (backend) | MySQL (database)

## Local Development

### Prerequisites
- Node.js 18+
- Python 3.11+
- MySQL 8.0+ (or Docker)

### Setup

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
python main.py
```

**With Docker (all services):**
```bash
docker-compose up --build
```

**Database:** See `db/README.md` for initialization steps.

## Deployment to Railway

### Step 1: Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/{project_name}
git push -u origin main
```

### Step 2: Deploy Frontend
1. railway.app → New Project → GitHub Repo
2. Root directory: `frontend/`
3. Set `NODE_ENV=production`

### Step 3: Deploy Backend
1. New Service → GitHub Repo
2. Root directory: `backend/`
3. Add MySQL plugin → copy `DATABASE_URL`
4. Set required env vars

### Step 4: Connect Services
- Frontend: set `NEXT_PUBLIC_API_URL=https://[backend-railway-url]`
- Redeploy frontend

## Full Docs
- [Frontend](frontend/README.md)
- [Backend](backend/README.md)
- [Database](db/README.md)
"""


def generate_configs(audit: ProjectAudit, out: Path) -> None:
    """Write all generated config, gitignore, Dockerfile, railway.json, README files."""
    log.info("Generating config files...")

    # Root
    write_text(out / ".gitignore", ROOT_GITIGNORE)
    write_text(out / "README.md", generate_root_readme(audit.project_name))
    write_text(out / "docker-compose.yml", DOCKER_COMPOSE)

    # Frontend
    if audit.has_frontend:
        fe = out / "frontend"
        fe.mkdir(exist_ok=True)
        if not (fe / ".gitignore").exists():
            write_text(fe / ".gitignore", FRONTEND_GITIGNORE)
        if not (fe / "README.md").exists():
            write_text(fe / "README.md", FRONTEND_README)
        write_json(fe / "railway.json", FRONTEND_RAILWAY_JSON)
        # .env.example placeholder (never copy real .env)
        if not (fe / ".env.example").exists():
            write_text(fe / ".env.example", "NEXT_PUBLIC_API_URL=http://localhost:8000\n")

    # Backend
    if audit.has_backend:
        be = out / "backend"
        be.mkdir(exist_ok=True)
        if not (be / ".gitignore").exists():
            write_text(be / ".gitignore", BACKEND_GITIGNORE)
        if not (be / "README.md").exists():
            write_text(be / "README.md", BACKEND_README)
        write_json(be / "railway.json", BACKEND_RAILWAY_JSON)
        if not (be / "Dockerfile").exists():
            write_text(be / "Dockerfile", BACKEND_DOCKERFILE)
        if not (be / ".env.example").exists():
            write_text(be / ".env.example", "DATABASE_URL=mysql://user:pass@host:3306/db\nSECRET_KEY=changeme\nFRONTEND_URL=http://localhost:3000\n")
        # Stub requirements.txt if missing
        if not (be / "requirements.txt").exists():
            write_text(be / "requirements.txt", "fastapi\nuvicorn[standard]\nmysqlclient\npython-dotenv\n")

    # DB
    if audit.has_db:
        db = out / "db"
        db.mkdir(exist_ok=True)
        (db / "migrations").mkdir(exist_ok=True)
        if not (db / "README.md").exists():
            write_text(db / "README.md", DB_README)
        # Stub schema.sql if none was found
        if not list(db.glob("*.sql")):
            write_text(db / "schema.sql", "-- Add your CREATE TABLE statements here\n")
    else:
        # Always create db/ with at least a README
        db = out / "db"
        db.mkdir(exist_ok=True)
        (db / "migrations").mkdir(exist_ok=True)
        write_text(db / "README.md", DB_README)
        write_text(db / "schema.sql", "-- Add your CREATE TABLE statements here\n")


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────

def validate_structure(out: Path, audit: ProjectAudit) -> bool:
    """Check that the required files exist in the output directory."""
    required: list[Path] = [
        out / ".gitignore",
        out / "README.md",
        out / "docker-compose.yml",
        out / "db" / "README.md",
    ]
    if audit.has_frontend:
        required += [out / "frontend" / "railway.json"]
    if audit.has_backend:
        required += [
            out / "backend" / "railway.json",
            out / "backend" / "Dockerfile",
        ]

    missing = [p for p in required if not p.exists()]
    if missing:
        log.warning("Validation: missing expected files:")
        for m in missing:
            log.warning(f"  {m}")
        return False

    log.info("Validation passed ✅")
    return True


# ──────────────────────────────────────────────
# Phase 5: Git & GitHub push
# ──────────────────────────────────────────────

def run_cmd(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    log.info(f"  $ {' '.join(args)}")
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"    stderr: {result.stderr.strip()}")
    return result


def git_init_and_commit(out: Path) -> bool:
    """Initialize git repo and create first commit."""
    log.info("Initializing git...")

    r = run_cmd(["git", "init"], out)
    if r.returncode != 0:
        print("❌ git init failed. Is git installed?")
        return False

    run_cmd(["git", "add", "."], out)
    r = run_cmd(["git", "commit", "-m", "Initial project structure"], out)
    if r.returncode != 0:
        print("❌ git commit failed.")
        print(r.stderr)
        return False

    log.info("First commit created.")
    return True


def push_to_github(out: Path) -> Optional[str]:
    """Prompt for GitHub URL and push. Returns the URL on success."""
    print("\nEnter your GitHub repo URL (leave blank to skip push):")
    print("  Example: https://github.com/yourusername/project-name")
    repo_url = input("  → ").strip()

    if not repo_url:
        log.info("GitHub push skipped by user.")
        return None

    r = run_cmd(["git", "remote", "add", "origin", repo_url], out)
    if r.returncode != 0 and "already exists" not in r.stderr:
        print("❌ Failed to add remote.")
        return None

    # Try main, fall back to master
    r = run_cmd(["git", "push", "-u", "origin", "main"], out)
    if r.returncode != 0:
        log.warning("Push to 'main' failed, trying 'master'...")
        r = run_cmd(["git", "push", "-u", "origin", "master"], out)

    if r.returncode != 0:
        print("❌ Push failed. Check your credentials and that the repo exists.")
        print(f"   {r.stderr.strip()}")
        return None

    log.info(f"Pushed to {repo_url}")
    return repo_url


# ──────────────────────────────────────────────
# Phase 6: Deployment instructions
# ──────────────────────────────────────────────

def deployment_instructions(project_name: str, github_url: Optional[str]) -> str:
    repo = github_url or f"https://github.com/YOUR_USERNAME/{project_name}"
    return f"""\
{"=" * 60}
✅  Project structure created and pushed to GitHub!

📦  GitHub: {repo}

🚀  Next Steps:

1. Frontend Deployment:
   - Go to railway.app
   - New Project → GitHub Repo → {repo}
   - Root directory: frontend/
   - Environment: NODE_ENV=production
   - Deploy

2. Backend Deployment:
   - New Service → GitHub Repo → {repo}
   - Root directory: backend/
   - Add MySQL plugin (Railway auto-injects DATABASE_URL)
   - Set env vars: SECRET_KEY, FRONTEND_URL
   - Deploy

3. Connect Frontend to Backend:
   - Add to frontend env in Railway:
       NEXT_PUBLIC_API_URL=https://[backend-railway-url]
   - Redeploy frontend

4. Database Initialization:
   - In Railway backend service → shell tab:
       mysql -h $MYSQLHOST -u $MYSQLUSER -p$MYSQLPASSWORD $MYSQLDATABASE < db/schema.sql
   - Or use Railway's built-in SQL runner

📖  Full docs: See README.md in repo root
{"=" * 60}
"""


# ──────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize a messy project folder into a Railway-ready GitHub repo."
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="Path to the source project folder",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Parent directory for the clean output folder (default: same as source parent)",
    )
    parser.add_argument(
        "--name",
        "-n",
        help="Override the project name",
    )
    args = parser.parse_args()

    # ── Resolve source path ──────────────────
    source_str = args.source
    if not source_str:
        print("\nNo source folder provided.")
        source_str = input("  Enter path to project folder: ").strip().strip('"').strip("'")

    source = Path(source_str).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        print(f"❌ Folder not found: {source}")
        sys.exit(1)

    output_parent = Path(args.output).resolve() if args.output else None

    # ── Phase 1: Audit ───────────────────────
    print(f"\n🔍 Auditing: {source}")
    audit = audit_project(source)
    if args.name:
        audit.project_name = args.name

    print_audit(audit)
    audit = confirm_audit(audit)

    if not audit.has_frontend and not audit.has_backend:
        print("❌ No frontend or backend detected. Nothing to do.")
        sys.exit(1)

    # ── Phase 2: Create output dir & copy ────
    out = create_output_dir(audit, output_parent)
    print(f"\n📁 Creating clean structure in: {out}")

    organize_frontend(audit, out)
    organize_backend(audit, out)
    organize_db(audit, out)

    # ── Phase 3 & 4: Generate configs ────────
    generate_configs(audit, out)

    # ── Validate ─────────────────────────────
    if not validate_structure(out, audit):
        print("⚠️  Some expected files are missing — check deploy.log for details.")

    print(f"\n✅ Clean structure written to: {out}")

    # ── Phase 5: Git + GitHub ─────────────────
    print("\nInitialize git and create first commit? (y/n)")
    if input("  → ").strip().lower() == "y":
        if git_init_and_commit(out):
            print("✅ Git initialized, first commit created.")

            print("\nPush to GitHub now? (y/n)")
            if input("  → ").strip().lower() == "y":
                github_url = push_to_github(out)
            else:
                github_url = None
        else:
            github_url = None
    else:
        github_url = None

    # ── Phase 6: Deployment instructions ─────
    instructions = deployment_instructions(audit.project_name, github_url)
    print(instructions)

    steps_file = out / "DEPLOYMENT_STEPS.txt"
    write_text(steps_file, instructions)
    print(f"📄 Deployment steps saved to: {steps_file}")


if __name__ == "__main__":
    main()
