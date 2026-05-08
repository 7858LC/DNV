"""
comms_db.py  — Sentinel Communications Log & Action Tracker (SQLite)

Two tables:
  communications  — logged external comms (email, Teams, call, text, meeting)
  comm_actions    — action items extracted from comms or created standalone

Every record carries a lane tag: executive | technical | contractual | cost
Actions carry RAG status derived from due_date at query time.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS communications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    comm_id         TEXT UNIQUE,
    source          TEXT NOT NULL DEFAULT 'email',
    lane            TEXT NOT NULL DEFAULT 'technical',
    comm_date       TEXT NOT NULL,
    participants    TEXT,
    subject         TEXT,
    summary         TEXT,
    decisions       TEXT,
    linked_ref      TEXT,
    linked_ref_type TEXT,
    logged_by       TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS comm_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id       TEXT UNIQUE,
    comm_id         INTEGER REFERENCES communications(id) ON DELETE SET NULL,
    description     TEXT NOT NULL,
    owner           TEXT,
    due_date        TEXT,
    lane            TEXT NOT NULL DEFAULT 'technical',
    status          TEXT NOT NULL DEFAULT 'open',
    escalated_to    TEXT,
    notes           TEXT,
    logged_by       TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_comms_lane    ON communications(lane);
CREATE INDEX IF NOT EXISTS idx_comms_source  ON communications(source);
CREATE INDEX IF NOT EXISTS idx_comms_date    ON communications(comm_date);
CREATE INDEX IF NOT EXISTS idx_actions_status ON comm_actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_lane  ON comm_actions(lane);
CREATE INDEX IF NOT EXISTS idx_actions_comm  ON comm_actions(comm_id);
"""

SOURCES = ["email", "teams", "call", "text", "meeting"]
LANES   = ["executive", "technical", "contractual", "cost"]
STATUSES = ["open", "in_progress", "closed", "escalated"]
LINKED_TYPES = ["submission", "tq", "ecf", "action", "requirement", ""]

SOURCE_LABELS = {
    "email":   "EMAIL",
    "teams":   "TEAMS",
    "call":    "CALL",
    "text":    "TEXT",
    "meeting": "MEETING",
}

LANE_LABELS = {
    "executive":   "EXECUTIVE",
    "technical":   "TECHNICAL",
    "contractual": "CONTRACTUAL",
    "cost":        "COST",
}


@contextmanager
def _conn(db_path: Path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return date.today().isoformat()


def _rag(due_date: str | None, status: str) -> str:
    if status in ("closed", "escalated"):
        return "closed"
    if not due_date:
        return "green"
    try:
        d = date.fromisoformat(due_date[:10])
    except (ValueError, TypeError):
        return "green"
    today = date.today()
    if d < today:
        return "red"
    if (d - today).days <= 5:
        return "amber"
    return "green"


def _next_comm_id(con) -> str:
    year = date.today().year
    row = con.execute(
        "SELECT COUNT(*) FROM communications WHERE comm_id LIKE ?",
        (f"COMM-{year}-%",)
    ).fetchone()
    seq = (row[0] or 0) + 1
    return f"COMM-{year}-{seq:03d}"


def _next_action_id(con) -> str:
    year = date.today().year
    row = con.execute(
        "SELECT COUNT(*) FROM comm_actions WHERE action_id LIKE ?",
        (f"CACT-{year}-%",)
    ).fetchone()
    seq = (row[0] or 0) + 1
    return f"CACT-{year}-{seq:03d}"


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        con.executescript(SCHEMA)


# ── Communications CRUD ───────────────────────────────────────────────────────

def get_communications(db_path: Path, lane: str = "", source: str = "",
                       search: str = "") -> list[dict]:
    clauses, params = [], []
    if lane:
        clauses.append("lane=?"); params.append(lane)
    if source:
        clauses.append("source=?"); params.append(source)
    if search:
        like = f"%{search}%"
        clauses.append("(subject LIKE ? OR summary LIKE ? OR participants LIKE ?)")
        params.extend([like, like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn(db_path) as con:
        rows = con.execute(
            f"SELECT * FROM communications {where} ORDER BY comm_date DESC, id DESC",
            params
        ).fetchall()
        out = []
        for r in rows:
            c = dict(r)
            c["action_count"] = con.execute(
                "SELECT COUNT(*) FROM comm_actions WHERE comm_id=?", (c["id"],)
            ).fetchone()[0]
            c["open_action_count"] = con.execute(
                "SELECT COUNT(*) FROM comm_actions WHERE comm_id=? AND status NOT IN ('closed')",
                (c["id"],)
            ).fetchone()[0]
            out.append(c)
        return out


def get_communication(db_path: Path, comm_id: int) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM communications WHERE id=?", (comm_id,)).fetchone()
        if not row:
            return None
        c = dict(row)
        actions_raw = con.execute(
            "SELECT * FROM comm_actions WHERE comm_id=? ORDER BY due_date, id",
            (comm_id,)
        ).fetchall()
        c["actions"] = [_enrich_action(dict(a)) for a in actions_raw]
        return c


def create_communication(db_path: Path, data: dict) -> dict:
    with _conn(db_path) as con:
        comm_id = _next_comm_id(con)
        cur = con.execute("""
            INSERT INTO communications
              (comm_id, source, lane, comm_date, participants, subject,
               summary, decisions, linked_ref, linked_ref_type, logged_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            comm_id,
            data.get("source", "email"),
            data.get("lane", "technical"),
            data.get("comm_date", _today()),
            data.get("participants", ""),
            data.get("subject", ""),
            data.get("summary", ""),
            data.get("decisions", ""),
            data.get("linked_ref", ""),
            data.get("linked_ref_type", ""),
            data.get("logged_by", ""),
        ))
        new_id = cur.lastrowid

        # Inline actions
        for a in data.get("actions", []):
            if not a.get("description", "").strip():
                continue
            action_id = _next_action_id(con)
            con.execute("""
                INSERT INTO comm_actions
                  (action_id, comm_id, description, owner, due_date, lane,
                   status, notes, logged_by)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                action_id, new_id,
                a.get("description", ""),
                a.get("owner", ""),
                a.get("due_date", ""),
                a.get("lane", data.get("lane", "technical")),
                "open",
                a.get("notes", ""),
                data.get("logged_by", ""),
            ))

        return {"id": new_id, "comm_id": comm_id}


def update_communication(db_path: Path, comm_id: int, data: dict) -> bool:
    fields = ["source", "lane", "comm_date", "participants", "subject",
              "summary", "decisions", "linked_ref", "linked_ref_type"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return False
    updates["updated_at"] = _now()
    clause = ", ".join(f"{k}=?" for k in updates)
    with _conn(db_path) as con:
        con.execute(f"UPDATE communications SET {clause} WHERE id=?",
                    (*updates.values(), comm_id))
    return True


def delete_communication(db_path: Path, comm_id: int) -> None:
    with _conn(db_path) as con:
        con.execute("DELETE FROM comm_actions WHERE comm_id=?", (comm_id,))
        con.execute("DELETE FROM communications WHERE id=?", (comm_id,))


# ── Actions CRUD ──────────────────────────────────────────────────────────────

def _enrich_action(a: dict) -> dict:
    a["rag"] = _rag(a.get("due_date"), a.get("status", "open"))
    return a


def get_actions(db_path: Path, lane: str = "", status: str = "",
                overdue_only: bool = False) -> list[dict]:
    clauses, params = [], []
    if lane:
        clauses.append("lane=?"); params.append(lane)
    if status:
        clauses.append("status=?"); params.append(status)
    if overdue_only:
        clauses.append("due_date < ? AND status NOT IN ('closed')")
        params.append(_today())

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn(db_path) as con:
        rows = con.execute(
            f"""SELECT a.*, c.comm_id as source_comm_id, c.subject as source_subject
                FROM comm_actions a
                LEFT JOIN communications c ON c.id = a.comm_id
                {where}
                ORDER BY
                  CASE WHEN a.due_date IS NULL OR a.due_date='' THEN 1 ELSE 0 END,
                  a.due_date,
                  a.id""",
            params
        ).fetchall()
        return [_enrich_action(dict(r)) for r in rows]


def create_action(db_path: Path, data: dict) -> dict:
    with _conn(db_path) as con:
        action_id = _next_action_id(con)
        cur = con.execute("""
            INSERT INTO comm_actions
              (action_id, comm_id, description, owner, due_date, lane,
               status, notes, logged_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            action_id,
            data.get("comm_id"),
            data.get("description", ""),
            data.get("owner", ""),
            data.get("due_date", ""),
            data.get("lane", "technical"),
            data.get("status", "open"),
            data.get("notes", ""),
            data.get("logged_by", ""),
        ))
        return {"id": cur.lastrowid, "action_id": action_id}


def update_action(db_path: Path, action_id: int, data: dict) -> bool:
    fields = ["description", "owner", "due_date", "lane", "status",
              "escalated_to", "notes"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return False
    updates["updated_at"] = _now()
    clause = ", ".join(f"{k}=?" for k in updates)
    with _conn(db_path) as con:
        con.execute(f"UPDATE comm_actions SET {clause} WHERE id=?",
                    (*updates.values(), action_id))
    return True


def delete_action(db_path: Path, action_id: int) -> None:
    with _conn(db_path) as con:
        con.execute("DELETE FROM comm_actions WHERE id=?", (action_id,))


# ── Summary / KPIs ────────────────────────────────────────────────────────────

def get_summary(db_path: Path) -> dict:
    today = _today()
    with _conn(db_path) as con:
        total_comms = con.execute("SELECT COUNT(*) FROM communications").fetchone()[0]
        open_actions = con.execute(
            "SELECT COUNT(*) FROM comm_actions WHERE status NOT IN ('closed')"
        ).fetchone()[0]
        overdue = con.execute(
            "SELECT COUNT(*) FROM comm_actions WHERE status NOT IN ('closed') AND due_date < ? AND due_date != ''",
            (today,)
        ).fetchone()[0]

        lanes_raw = con.execute(
            "SELECT lane, COUNT(*) as cnt FROM communications GROUP BY lane"
        ).fetchall()
        lanes = {r["lane"]: r["cnt"] for r in lanes_raw}

        action_lanes_raw = con.execute(
            "SELECT lane, COUNT(*) as cnt FROM comm_actions WHERE status NOT IN ('closed') GROUP BY lane"
        ).fetchall()
        action_lanes = {r["lane"]: r["cnt"] for r in action_lanes_raw}

    return {
        "total_comms":   total_comms,
        "open_actions":  open_actions,
        "overdue":       overdue,
        "lanes":         lanes,
        "action_lanes":  action_lanes,
    }
