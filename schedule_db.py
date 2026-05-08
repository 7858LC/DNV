"""
schedule_db.py — Schedule Impact module: tasks, document links, risk engine

Tasks are loaded from schedule_raw.json (MPP extraction) or a coordinator upload.
Risk engine computes business-day lead time and flags WATCH / RISK / BREACH.
Document links connect schedule tasks to submission records (many-to-many).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Risk thresholds (business days to task start) ─────────────────────────────
WATCH_BD  = 21   # approaching danger zone — start planning
RISK_BD   = 15   # within mandatory lead time — action required
BREACH_BD = 0    # at or past start date — overdue

# Keywords that make a task DNV-relevant
_DNV_KEYWORDS     = ["dnv", "surveyor", "certificate", "class approval"]
_WITNESS_KEYWORDS = ["witness", "hold point", "fat complete", "sat complete",
                     "fat procedure", "manned trial", "dnv acceptance",
                     "dnv reviewed", "dnv review"]

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS schedule_tasks (
    id            INTEGER PRIMARY KEY,
    wbs           TEXT    DEFAULT '',
    name          TEXT    DEFAULT '',
    start_dt      TEXT    DEFAULT '',
    finish_dt     TEXT    DEFAULT '',
    pct           REAL    DEFAULT 0,
    milestone     INTEGER DEFAULT 0,
    summary       INTEGER DEFAULT 0,
    dnv_witness   INTEGER DEFAULT 0,
    dnv_relevant  INTEGER DEFAULT 0,
    resources     TEXT    DEFAULT '',
    notes         TEXT    DEFAULT '',
    updated_at    TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sched_wbs ON schedule_tasks(wbs);

CREATE TABLE IF NOT EXISTS task_document_links (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL,
    doc_number TEXT    NOT NULL,
    linked_by  TEXT    DEFAULT '',
    linked_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(task_id, doc_number)
);
CREATE INDEX IF NOT EXISTS idx_link_task ON task_document_links(task_id);
CREATE INDEX IF NOT EXISTS idx_link_doc  ON task_document_links(doc_number);

CREATE TABLE IF NOT EXISTS schedule_imports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at TEXT    DEFAULT (datetime('now')),
    imported_by TEXT    DEFAULT '',
    task_count  INTEGER DEFAULT 0,
    source_file TEXT    DEFAULT ''
);
"""


# ── Connection ────────────────────────────────────────────────────────────────
@contextmanager
def _conn(db_path: Path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Init ──────────────────────────────────────────────────────────────────────
def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        con.executescript(SCHEMA)


# ── Task tagging ──────────────────────────────────────────────────────────────
def _tag_task(name: str, resources: list) -> tuple[int, int]:
    """Return (dnv_witness, dnv_relevant) integers for a task."""
    text = (name + " " + " ".join(resources)).lower()
    dnv_rel = int(any(k in text for k in _DNV_KEYWORDS))
    witness = int(any(k in text for k in _WITNESS_KEYWORDS))
    # Witness implies DNV-relevant
    if witness:
        dnv_rel = 1
    return witness, dnv_rel


# ── Import tasks from JSON list ───────────────────────────────────────────────
def import_tasks(db_path: Path, tasks: list[dict],
                 imported_by: str = "", source_file: str = "") -> dict:
    """
    Full-refresh of schedule_tasks table from a list of task dicts.
    Preserves existing task_document_links (links use task id as FK).
    Returns {"task_count": n, "dnv_count": m, "witness_count": w}.
    """
    now = _now()
    rows = []
    for t in tasks:
        dw, dr = _tag_task(t.get("name", ""), t.get("resources", []))
        start  = str(t.get("start",  "") or "")[:10]
        finish = str(t.get("finish", "") or "")[:10]
        rows.append((
            int(t["id"]),
            str(t.get("wbs",  "") or ""),
            str(t.get("name", "") or ""),
            start, finish,
            float(t.get("pct", 0) or 0),
            int(bool(t.get("milestone", False))),
            int(bool(t.get("summary",   False))),
            dw, dr,
            ", ".join(t.get("resources", []) or []),
            str(t.get("notes", "") or ""),
            now,
        ))

    with _conn(db_path) as con:
        con.execute("DELETE FROM schedule_tasks")
        con.executemany("""
            INSERT INTO schedule_tasks
              (id, wbs, name, start_dt, finish_dt, pct, milestone, summary,
               dnv_witness, dnv_relevant, resources, notes, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        dnv_count = con.execute(
            "SELECT COUNT(*) FROM schedule_tasks WHERE dnv_relevant=1"
        ).fetchone()[0]
        wit_count = con.execute(
            "SELECT COUNT(*) FROM schedule_tasks WHERE dnv_witness=1"
        ).fetchone()[0]
        con.execute("""
            INSERT INTO schedule_imports
              (imported_at, imported_by, task_count, source_file)
            VALUES (?,?,?,?)
        """, (now, imported_by, len(rows), source_file))

    return {"task_count": len(rows), "dnv_count": dnv_count,
            "witness_count": wit_count}


# ── Business-day arithmetic ───────────────────────────────────────────────────
def business_days(from_date: date, to_date: date,
                  holidays: set[date] | None = None) -> int:
    """
    Count business days from from_date to to_date (exclusive of from_date).
    Returns negative values when to_date < from_date.
    Mon–Fri, excluding provided holiday dates.
    """
    if holidays is None:
        holidays = set()
    if to_date == from_date:
        return 0
    sign = 1 if to_date > from_date else -1
    d, count = from_date, 0
    while d != to_date:
        d += timedelta(days=sign)
        if d.weekday() < 5 and d not in holidays:
            count += sign
    return count


def risk_level(bd: int | None) -> str:
    """Translate lead-time business days to risk label."""
    if bd is None:
        return "UNKNOWN"
    if bd <= BREACH_BD:
        return "BREACH"
    if bd <= RISK_BD:
        return "RISK"
    if bd <= WATCH_BD:
        return "WATCH"
    return "OK"


# ── Task queries ──────────────────────────────────────────────────────────────
def get_tasks(db_path: Path, dnv_only: bool = False) -> list[dict]:
    where = "WHERE dnv_relevant=1" if dnv_only else ""
    with _conn(db_path) as con:
        rows = con.execute(
            f"SELECT * FROM schedule_tasks {where} ORDER BY wbs"
        ).fetchall()
        return [dict(r) for r in rows]


def get_task(db_path: Path, task_id: int) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM schedule_tasks WHERE id=?", (task_id,)
        ).fetchone()
        return dict(row) if row else None


def get_tasks_with_risk(db_path: Path,
                        holidays: set[date] | None = None,
                        dnv_only: bool = True) -> list[dict]:
    """Return tasks enriched with lead_time_bd and risk_level."""
    if holidays is None:
        holidays = set()
    tasks = get_tasks(db_path, dnv_only=dnv_only)
    today = date.today()
    for t in tasks:
        start_str = t.get("start_dt", "")
        if start_str:
            try:
                task_start = date.fromisoformat(start_str[:10])
                bd = business_days(today, task_start, holidays)
                rl = risk_level(bd)
            except Exception:
                bd, rl = None, "UNKNOWN"
        else:
            bd, rl = None, "UNKNOWN"
        t["lead_time_bd"] = bd
        t["risk_level"]   = rl
    return tasks


# ── Document links ────────────────────────────────────────────────────────────
def get_links(db_path: Path, task_id: int) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM task_document_links WHERE task_id=? ORDER BY linked_at",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_link(db_path: Path, task_id: int,
             doc_number: str, linked_by: str = "") -> bool:
    """Return True if inserted, False if already exists."""
    try:
        with _conn(db_path) as con:
            con.execute("""
                INSERT INTO task_document_links (task_id, doc_number, linked_by, linked_at)
                VALUES (?,?,?,?)
            """, (task_id, doc_number, linked_by, _now()))
        return True
    except sqlite3.IntegrityError:
        return False


def remove_link(db_path: Path, task_id: int, doc_number: str) -> bool:
    with _conn(db_path) as con:
        cur = con.execute(
            "DELETE FROM task_document_links WHERE task_id=? AND doc_number=?",
            (task_id, doc_number)
        )
        return cur.rowcount > 0


def get_links_for_doc(db_path: Path, doc_number: str) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM task_document_links WHERE doc_number=? ORDER BY linked_at",
            (doc_number,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_link_counts(db_path: Path) -> dict[int, int]:
    """Return {task_id: link_count} for all tasks with at least one link."""
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT task_id, COUNT(*) as cnt FROM task_document_links GROUP BY task_id"
        ).fetchall()
        return {r["task_id"]: r["cnt"] for r in rows}


# ── Import history ────────────────────────────────────────────────────────────
def get_last_import(db_path: Path) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM schedule_imports ORDER BY imported_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_import_history(db_path: Path, limit: int = 10) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM schedule_imports ORDER BY imported_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
