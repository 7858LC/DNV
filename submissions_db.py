"""
submissions_db.py — Submission workflow state machine + transition audit log

Transition map defines which status moves are legal.
Role gate defines which roles can initiate each move.
Every transition is written to SQLite with who/when/note.

The authoritative status value lives in submissions.csv;
this DB is purely the audit trail.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# ── Workflow definition ───────────────────────────────────────────────────────

TRANSITION_MAP: dict[str, list[str]] = {
    "Draft":              ["Internal Review"],
    "Internal Review":    ["Submitted to DNV", "Draft"],
    "Submitted to DNV":   ["Under DNV Review"],
    "Under DNV Review":   ["Comments Issued", "Closed"],
    "Comments Issued":    ["Response Submitted"],
    "Response Submitted": ["Closed", "Comments Issued"],
    "Closed":             [],
}

# Roles allowed to initiate each (from, to) pair
TRANSITION_ROLES: dict[tuple[str, str], list[str]] = {
    ("Draft",              "Internal Review"):    ["Bastion Engineer", "Bastion Coordinator", "Admin"],
    ("Internal Review",    "Submitted to DNV"):   ["Bastion Coordinator", "Admin"],
    ("Internal Review",    "Draft"):              ["Bastion Engineer", "Bastion Coordinator", "Admin"],
    ("Submitted to DNV",   "Under DNV Review"):   ["Bastion Coordinator", "Admin"],
    ("Under DNV Review",   "Comments Issued"):    ["Bastion Coordinator", "Admin"],
    ("Under DNV Review",   "Closed"):             ["Bastion Coordinator", "Admin"],
    ("Comments Issued",    "Response Submitted"): ["Bastion Engineer", "Bastion Coordinator", "Admin"],
    ("Response Submitted", "Closed"):             ["Bastion Coordinator", "Admin"],
    ("Response Submitted", "Comments Issued"):    ["Bastion Coordinator", "Admin"],
}

STATUS_ORDER = list(TRANSITION_MAP.keys())

STATUS_COLORS: dict[str, str] = {
    "Draft":              "muted",
    "Internal Review":    "blue",
    "Submitted to DNV":   "amber",
    "Under DNV Review":   "amber",
    "Comments Issued":    "red",
    "Response Submitted": "blue",
    "Closed":             "green",
}

# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS submission_transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_number  TEXT    NOT NULL,
    from_status TEXT    NOT NULL,
    to_status   TEXT    NOT NULL,
    changed_by  TEXT    NOT NULL DEFAULT '',
    changed_at  TEXT    DEFAULT (datetime('now')),
    note        TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trans_doc ON submission_transitions(doc_number);
CREATE INDEX IF NOT EXISTS idx_trans_ts  ON submission_transitions(changed_at);
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


# ── Public API ────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        con.executescript(SCHEMA)


def allowed_transitions(from_status: str, role: str) -> list[str]:
    """Return list of valid target statuses for this role."""
    targets = TRANSITION_MAP.get(from_status, [])
    return [t for t in targets
            if role in TRANSITION_ROLES.get((from_status, t), [])]


def validate_transition(from_status: str, to_status: str, role: str) -> str | None:
    """Return error string if invalid, or None if OK."""
    valid_targets = TRANSITION_MAP.get(from_status)
    if valid_targets is None:
        return f"Unknown status '{from_status}'"
    if to_status not in valid_targets:
        return f"'{from_status}' -> '{to_status}' is not a legal transition"
    allowed_roles = TRANSITION_ROLES.get((from_status, to_status), [])
    if role not in allowed_roles:
        return f"Role '{role}' cannot move '{from_status}' -> '{to_status}'"
    return None


def log_transition(db_path: Path, doc_number: str,
                   from_status: str, to_status: str,
                   changed_by: str, note: str = "") -> int:
    with _conn(db_path) as con:
        cur = con.execute("""
            INSERT INTO submission_transitions
              (doc_number, from_status, to_status, changed_by, changed_at, note)
            VALUES (?,?,?,?,?,?)
        """, (doc_number, from_status, to_status, changed_by, _now(), note))
        return cur.lastrowid


def get_history(db_path: Path, doc_number: str) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT * FROM submission_transitions
            WHERE doc_number=? ORDER BY changed_at DESC
        """, (doc_number,)).fetchall()
        return [dict(r) for r in rows]


def get_recent_activity(db_path: Path, limit: int = 50) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT * FROM submission_transitions
            ORDER BY changed_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
