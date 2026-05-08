"""
packages_db.py — DNV Submission Package management

A "package" is a named collection of Bastion submissions sent together to DNV
via Veracity (e.g. "AIP DOCUMENT PACKAGE"). Mirrors Veracity's Packages tab.

Schema:
  packages            — named package with status + Veracity reference
  package_documents   — many-to-many: package ↔ submission (by DocumentNumber)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# ── Package statuses (mirrors Veracity workflow) ──────────────────────────────
PACKAGE_STATUSES = [
    "Draft",
    "Ready to Submit",
    "Submitted to DNV",
    "Under DNV Review",
    "Approved",
    "Approved with Comments",
    "Rejected",
    "On Hold",
]

PACKAGE_STATUS_COLORS = {
    "Draft":                 "muted",
    "Ready to Submit":       "blue",
    "Submitted to DNV":      "amber",
    "Under DNV Review":      "amber",
    "Approved":              "green",
    "Approved with Comments":"green",
    "Rejected":              "red",
    "On Hold":               "muted",
}

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS packages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    description      TEXT    DEFAULT '',
    status           TEXT    DEFAULT 'Draft',
    veracity_ref     TEXT    DEFAULT '',
    veracity_url     TEXT    DEFAULT '',
    created_by       TEXT    DEFAULT '',
    created_at       TEXT    DEFAULT (datetime('now')),
    submitted_at     TEXT    DEFAULT '',
    updated_by       TEXT    DEFAULT '',
    updated_at       TEXT    DEFAULT (datetime('now')),
    notes            TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pkg_status ON packages(status);

CREATE TABLE IF NOT EXISTS package_documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id     INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    doc_number     TEXT    NOT NULL,
    dnv_doc_number TEXT    DEFAULT '',
    est_reply_date TEXT    DEFAULT '',
    dnv_type       TEXT    DEFAULT '',
    dnv_not_applicable INTEGER DEFAULT 0,
    added_by       TEXT    DEFAULT '',
    added_at       TEXT    DEFAULT (datetime('now')),
    UNIQUE(package_id, doc_number)
);
CREATE INDEX IF NOT EXISTS idx_pkgdoc_pkg ON package_documents(package_id);
CREATE INDEX IF NOT EXISTS idx_pkgdoc_doc ON package_documents(doc_number);

CREATE TABLE IF NOT EXISTS package_activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id  INTEGER NOT NULL,
    event       TEXT    NOT NULL,
    detail      TEXT    DEFAULT '',
    by_user     TEXT    DEFAULT '',
    at_time     TEXT    DEFAULT (datetime('now'))
);
"""

# ── Connection ────────────────────────────────────────────────────────────────
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
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Init ──────────────────────────────────────────────────────────────────────
def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        con.executescript(SCHEMA)


# ── Packages CRUD ─────────────────────────────────────────────────────────────
def create_package(db_path: Path, name: str, description: str = "",
                   veracity_ref: str = "", created_by: str = "") -> int:
    now = _now()
    with _conn(db_path) as con:
        cur = con.execute("""
            INSERT INTO packages (name, description, veracity_ref, created_by, created_at, updated_at)
            VALUES (?,?,?,?,?,?)
        """, (name, description, veracity_ref, created_by, now, now))
        pkg_id = cur.lastrowid
        con.execute("""
            INSERT INTO package_activity (package_id, event, by_user, at_time)
            VALUES (?,?,?,?)
        """, (pkg_id, "Package created", created_by, now))
        return pkg_id


def get_packages(db_path: Path) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT p.*,
                   COUNT(pd.id) as doc_count
            FROM packages p
            LEFT JOIN package_documents pd ON pd.package_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_package(db_path: Path, pkg_id: int) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM packages WHERE id=?", (pkg_id,)).fetchone()
        return dict(row) if row else None


def update_package(db_path: Path, pkg_id: int, fields: dict,
                   updated_by: str = "") -> None:
    allowed = {"name", "description", "status", "veracity_ref",
               "veracity_url", "notes", "submitted_at"}
    now = _now()
    with _conn(db_path) as con:
        for k, v in fields.items():
            if k in allowed:
                con.execute(f"UPDATE packages SET {k}=?, updated_by=?, updated_at=? WHERE id=?",
                            (v, updated_by, now, pkg_id))
        # Log status change
        if "status" in fields:
            con.execute("""
                INSERT INTO package_activity (package_id, event, detail, by_user, at_time)
                VALUES (?,?,?,?,?)
            """, (pkg_id, "Status changed", fields["status"], updated_by, now))


def delete_package(db_path: Path, pkg_id: int) -> None:
    with _conn(db_path) as con:
        con.execute("DELETE FROM packages WHERE id=?", (pkg_id,))


# ── Package documents ─────────────────────────────────────────────────────────
def get_package_documents(db_path: Path, pkg_id: int) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT * FROM package_documents WHERE package_id=? ORDER BY added_at
        """, (pkg_id,)).fetchall()
        return [dict(r) for r in rows]


def add_document(db_path: Path, pkg_id: int, doc_number: str,
                 dnv_doc_number: str = "", est_reply_date: str = "",
                 dnv_type: str = "", added_by: str = "") -> bool:
    """Return True if inserted, False if already in package."""
    try:
        now = _now()
        with _conn(db_path) as con:
            con.execute("""
                INSERT INTO package_documents
                  (package_id, doc_number, dnv_doc_number, est_reply_date,
                   dnv_type, added_by, added_at)
                VALUES (?,?,?,?,?,?,?)
            """, (pkg_id, doc_number, dnv_doc_number, est_reply_date,
                  dnv_type, added_by, now))
            con.execute("""
                INSERT INTO package_activity (package_id, event, detail, by_user, at_time)
                VALUES (?,?,?,?,?)
            """, (pkg_id, "Document added", doc_number, added_by, now))
        return True
    except sqlite3.IntegrityError:
        return False


def update_document(db_path: Path, pkg_id: int, doc_number: str,
                    fields: dict) -> None:
    allowed = {"dnv_doc_number", "est_reply_date", "dnv_type", "dnv_not_applicable"}
    with _conn(db_path) as con:
        for k, v in fields.items():
            if k in allowed:
                con.execute(
                    f"UPDATE package_documents SET {k}=? WHERE package_id=? AND doc_number=?",
                    (v, pkg_id, doc_number)
                )


def remove_document(db_path: Path, pkg_id: int, doc_number: str,
                    removed_by: str = "") -> bool:
    now = _now()
    with _conn(db_path) as con:
        cur = con.execute(
            "DELETE FROM package_documents WHERE package_id=? AND doc_number=?",
            (pkg_id, doc_number)
        )
        if cur.rowcount:
            con.execute("""
                INSERT INTO package_activity (package_id, event, detail, by_user, at_time)
                VALUES (?,?,?,?,?)
            """, (pkg_id, "Document removed", doc_number, removed_by, now))
        return cur.rowcount > 0


def get_document_packages(db_path: Path, doc_number: str) -> list[dict]:
    """Return all packages that contain a given document number."""
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT p.id, p.name, p.status, pd.dnv_doc_number, pd.est_reply_date
            FROM package_documents pd
            JOIN packages p ON p.id = pd.package_id
            WHERE pd.doc_number=?
        """, (doc_number,)).fetchall()
        return [dict(r) for r in rows]


# ── Activity log ──────────────────────────────────────────────────────────────
def get_activity(db_path: Path, pkg_id: int) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("""
            SELECT * FROM package_activity WHERE package_id=?
            ORDER BY at_time DESC
        """, (pkg_id,)).fetchall()
        return [dict(r) for r in rows]


# ── Export (Veracity-format row list) ────────────────────────────────────────
def export_package(db_path: Path, pkg_id: int,
                   submissions: list[dict]) -> dict:
    """
    Build a Veracity-mirrored export dict for a package.
    submissions = list of dicts from submissions.csv (full table, all rows).
    Returns {"package": {...}, "documents": [...]} ready to JSON/CSV export.
    """
    pkg  = get_package(db_path, pkg_id)
    if not pkg:
        return {}
    pkg_docs = get_package_documents(db_path, pkg_id)

    # Index submissions by DocumentNumber for fast lookup
    sub_idx = {str(s.get("DocumentNumber", "")).strip(): s
               for s in submissions}

    docs_out = []
    for pd in pkg_docs:
        dn  = pd["doc_number"]
        sub = sub_idx.get(dn, {})
        docs_out.append({
            "doc_number":       dn,
            "dnv_doc_number":   pd.get("dnv_doc_number") or sub.get("VeracityRef", ""),
            "title":            sub.get("DocumentTitle", ""),
            "type":             pd.get("dnv_type")      or sub.get("DocumentType", ""),
            "revision":         sub.get("Revision", ""),
            "est_reply_date":   pd.get("est_reply_date") or sub.get("EstReplyDate", ""),
            "status":           sub.get("Status", ""),
            "dnv_not_applicable": bool(pd.get("dnv_not_applicable", 0)),
            "submitting_engineer": sub.get("SubmittingEngineer", ""),
            "submitted_date":   sub.get("SubmittedDate", ""),
            "discipline":       sub.get("DNVDisciplineQueue", ""),
        })

    return {
        "package": {
            "id":           pkg["id"],
            "name":         pkg["name"],
            "description":  pkg["description"],
            "status":       pkg["status"],
            "veracity_ref": pkg["veracity_ref"],
            "created_by":   pkg["created_by"],
            "created_at":   pkg["created_at"],
            "submitted_at": pkg["submitted_at"],
        },
        "documents": docs_out,
        "exported_at": _now(),
    }
