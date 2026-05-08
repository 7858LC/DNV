"""
docreq_db.py  — DNV Document Requirements compliance backend (SQLite)

Three tables:
  dnv_requirements   — one row per DNV rule statement (parent)
  bastion_documents  — thin reference: doc_number linked to a requirement (child)
  comment_threads    — multi-round DNV<->Bastion exchange per document (grandchild)

Submission metadata (owner, version, dates, DNV status) lives in submissions.csv
and is fetched live via /api/csv/submissions.  This DB owns only the requirement
structure, the doc-number linkage, and the structured comment exchange.

Coverage rolls up: thread.disposition -> document.comment_status -> requirement.coverage_status
"""
from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

DB_VERSION = 2

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS dnv_requirements (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    item_number           TEXT,
    rule_ref              TEXT DEFAULT 'Pt.5 Ch.10 Sec.1',
    dnv_code              TEXT,
    requirement_text      TEXT,
    additional_description TEXT,
    approval_type         TEXT,
    subsystem             TEXT,
    paragraph_ref         TEXT,
    ref_source            TEXT,
    created_at            TEXT DEFAULT (datetime('now')),
    updated_at            TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bastion_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id  INTEGER NOT NULL REFERENCES dnv_requirements(id) ON DELETE CASCADE,
    doc_number      TEXT NOT NULL,
    created_by      TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS comment_threads (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id           INTEGER NOT NULL REFERENCES bastion_documents(id) ON DELETE CASCADE,
    round                 INTEGER DEFAULT 1,
    category              TEXT NOT NULL DEFAULT 'Technical',
    dnv_comment           TEXT,
    dnv_comment_date      TEXT,
    assigned_to           TEXT,
    assigned_date         TEXT,
    bastion_response      TEXT,
    bastion_response_date TEXT,
    dnv_closed_date       TEXT,
    dnv_approver          TEXT,
    disposition           TEXT DEFAULT 'Open',
    created_by            TEXT DEFAULT '',
    updated_by            TEXT DEFAULT '',
    created_at            TEXT DEFAULT (datetime('now')),
    updated_at            TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_docs_req    ON bastion_documents(requirement_id);
CREATE INDEX IF NOT EXISTS idx_docs_num    ON bastion_documents(doc_number);
CREATE INDEX IF NOT EXISTS idx_threads_doc ON comment_threads(document_id);
"""

CATEGORIES = ["Technical", "Administrative", "Missing Info", "Clarification", "Compliance"]
DISPOSITIONS = ["Open", "Answered", "Accepted", "Rejected"]


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
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return date.today().isoformat()


# ── SLA: business days between two date strings ───────────────────────────────
def business_days(from_str: str, to_str: str | None = None) -> int:
    if not from_str:
        return 0
    try:
        start = date.fromisoformat(from_str[:10])
        end   = date.fromisoformat(to_str[:10]) if to_str else date.today()
    except (ValueError, TypeError):
        return 0
    if end <= start:
        return 0
    count, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def sla_status(thread: dict) -> dict:
    """Return SLA metadata for a thread."""
    received  = thread.get("dnv_comment_date") or ""
    responded = thread.get("bastion_response_date") or ""
    closed    = thread.get("dnv_closed_date") or ""
    disp      = thread.get("disposition", "Open")

    bd_to_response = business_days(received, responded if responded else None)
    bd_open        = business_days(received) if disp == "Open" else 0
    breached       = (bd_to_response > 10) if responded else (bd_open > 10)

    return {
        "bd_to_response": bd_to_response if responded else None,
        "bd_open":        bd_open if disp == "Open" else None,
        "breached":       breached,
        "sla_target":     10,
    }


# ── Init ──────────────────────────────────────────────────────────────────────
def _add_column_if_missing(con, table: str, col: str, coldef: str) -> None:
    """ALTER TABLE to add a column only if it does not already exist."""
    existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if col not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        con.executescript(SCHEMA)
        row = con.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            con.execute("INSERT INTO schema_version VALUES (?)", (DB_VERSION,))
        # Migrate existing DBs: add audit columns if absent
        _add_column_if_missing(con, "bastion_documents",  "created_by", "TEXT DEFAULT ''")
        _add_column_if_missing(con, "comment_threads",    "created_by", "TEXT DEFAULT ''")
        _add_column_if_missing(con, "comment_threads",    "updated_by", "TEXT DEFAULT ''")


# ── Coverage rollup ───────────────────────────────────────────────────────────
def _doc_comment_status(threads: list[dict]) -> str:
    if not threads:
        return "Clean"
    disps = [t["disposition"] for t in threads]
    if any(d == "Open"     for d in disps): return "Open"
    if any(d == "Answered" for d in disps): return "Answered"
    if any(d == "Rejected" for d in disps): return "Open"
    return "Satisfied"


def _req_coverage(docs: list[dict]) -> str:
    if not docs:
        return "MISSING"
    statuses = [d.get("comment_status", "Clean") for d in docs]
    if any(s == "Open"      for s in statuses): return "Open Comments"
    if any(s == "Answered"  for s in statuses): return "Answered"
    return "Submitted" if any(s in ("Clean","Satisfied") for s in statuses) else "Gap"


# ── Internal fetch helpers ────────────────────────────────────────────────────
def _fetch_threads(con, doc_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM comment_threads WHERE document_id=? ORDER BY round, created_at",
        (doc_id,)
    ).fetchall()
    threads = []
    for r in rows:
        t = dict(r)
        t["sla"] = sla_status(t)
        threads.append(t)
    return threads


def _fetch_docs(con, req_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM bastion_documents WHERE requirement_id=? ORDER BY id",
        (req_id,)
    ).fetchall()
    docs = []
    for row in rows:
        d = dict(row)
        d["threads"]        = _fetch_threads(con, d["id"])
        d["comment_status"] = _doc_comment_status(d["threads"])
        d["open_threads"]   = sum(1 for t in d["threads"] if t["disposition"] == "Open")
        docs.append(d)
    return docs


# ── Public read ───────────────────────────────────────────────────────────────
def get_requirements(db_path: Path) -> list[dict]:
    with _conn(db_path) as con:
        reqs = con.execute(
            "SELECT * FROM dnv_requirements ORDER BY CAST(item_number AS INTEGER), id"
        ).fetchall()
        out = []
        for req in reqs:
            r = dict(req)
            docs = _fetch_docs(con, r["id"])
            r["doc_count"]       = len(docs)
            r["open_threads"]    = sum(d["open_threads"] for d in docs)
            r["coverage_status"] = _req_coverage(docs)
            out.append(r)
        return out


def get_requirement(db_path: Path, req_id: int) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM dnv_requirements WHERE id=?", (req_id,)).fetchone()
        if not row:
            return None
        r = dict(row)
        r["documents"]       = _fetch_docs(con, req_id)
        r["coverage_status"] = _req_coverage(r["documents"])
        return r


def get_threads_for_doc_number(db_path: Path, doc_number: str) -> list[dict]:
    """Fetch all comment threads for a doc_number (used from Submissions page)."""
    with _conn(db_path) as con:
        docs = con.execute(
            "SELECT id FROM bastion_documents WHERE doc_number=?", (doc_number,)
        ).fetchall()
        threads = []
        for doc in docs:
            threads.extend(_fetch_threads(con, doc["id"]))
        return threads


# ── Public write ──────────────────────────────────────────────────────────────
def link_document(db_path: Path, req_id: int, doc_number: str,
                  created_by: str = "") -> int:
    with _conn(db_path) as con:
        cur = con.execute(
            "INSERT INTO bastion_documents (requirement_id, doc_number, created_by) VALUES (?,?,?)",
            (req_id, doc_number.strip(), created_by)
        )
        return cur.lastrowid


def unlink_document(db_path: Path, doc_id: int) -> None:
    with _conn(db_path) as con:
        con.execute("DELETE FROM bastion_documents WHERE id=?", (doc_id,))


def add_comment(db_path: Path, doc_id: int, data: dict,
                created_by: str = "") -> int:
    with _conn(db_path) as con:
        last = con.execute(
            "SELECT MAX(round) FROM comment_threads WHERE document_id=?", (doc_id,)
        ).fetchone()[0]
        rnd = (last or 0) + 1
        cur = con.execute("""
            INSERT INTO comment_threads
              (document_id, round, category, dnv_comment, dnv_comment_date,
               assigned_to, assigned_date, bastion_response, bastion_response_date,
               dnv_closed_date, dnv_approver, disposition, created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            doc_id, rnd,
            data.get("category", "Technical"),
            data.get("dnv_comment", ""),
            data.get("dnv_comment_date", _today()),
            data.get("assigned_to", ""),
            data.get("assigned_date", ""),
            data.get("bastion_response", ""),
            data.get("bastion_response_date", ""),
            data.get("dnv_closed_date", ""),
            data.get("dnv_approver", ""),
            data.get("disposition", "Open"),
            created_by,
        ))
        return cur.lastrowid


def update_comment(db_path: Path, thread_id: int, data: dict) -> bool:
    fields = [
        "category", "dnv_comment", "dnv_comment_date",
        "assigned_to", "assigned_date",
        "bastion_response", "bastion_response_date",
        "dnv_closed_date", "dnv_approver", "disposition",
    ]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return False
    # Auto-set dates when key events happen
    if "bastion_response" in updates and updates["bastion_response"]:
        if "bastion_response_date" not in updates:
            updates["bastion_response_date"] = _today()
        if "disposition" not in updates:
            updates["disposition"] = "Answered"
    if updates.get("disposition") in ("Accepted", "Rejected"):
        if "dnv_closed_date" not in updates and updates.get("disposition") == "Accepted":
            updates["dnv_closed_date"] = _today()
    updates["updated_at"] = _now()
    clause = ", ".join(f"{k}=?" for k in updates)
    with _conn(db_path) as con:
        con.execute(f"UPDATE comment_threads SET {clause} WHERE id=?",
                    (*updates.values(), thread_id))
    return True


def update_comment_by(db_path: Path, thread_id: int, data: dict,
                      updated_by: str = "") -> bool:
    """update_comment with updated_by audit field."""
    data = dict(data)
    data["updated_by"] = updated_by
    return update_comment(db_path, thread_id, data)


def delete_comment(db_path: Path, thread_id: int) -> None:
    with _conn(db_path) as con:
        con.execute("DELETE FROM comment_threads WHERE id=?", (thread_id,))


def update_requirement(db_path: Path, req_id: int, data: dict) -> bool:
    fields = ["approval_type", "subsystem", "requirement_text",
              "additional_description", "rule_ref"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return False
    updates["updated_at"] = _now()
    clause = ", ".join(f"{k}=?" for k in updates)
    with _conn(db_path) as con:
        con.execute(f"UPDATE dnv_requirements SET {clause} WHERE id=?",
                    (*updates.values(), req_id))
    return True


# ── Metrics ───────────────────────────────────────────────────────────────────
def get_metrics(db_path: Path) -> dict:
    with _conn(db_path) as con:
        # All threads with sla data
        threads_raw = con.execute("""
            SELECT t.*, d.doc_number
            FROM comment_threads t
            JOIN bastion_documents d ON d.id = t.document_id
        """).fetchall()
        threads = [dict(r) for r in threads_raw]
        for t in threads:
            t["sla"] = sla_status(t)

        # Requirements with coverage
        reqs = con.execute("SELECT * FROM dnv_requirements ORDER BY CAST(item_number AS INTEGER)").fetchall()
        req_list = []
        for req in reqs:
            r = dict(req)
            docs = _fetch_docs(con, r["id"])
            r["coverage_status"] = _req_coverage(docs)
            r["doc_count"]       = len(docs)
            r["open_threads"]    = sum(d["open_threads"] for d in docs)
            req_list.append(r)

    # Coverage breakdown
    coverage_counts: dict[str, int] = {}
    for r in req_list:
        c = r["coverage_status"]
        coverage_counts[c] = coverage_counts.get(c, 0) + 1

    # DNV code distribution
    code_counts: dict[str, int] = {}
    for r in req_list:
        c = r["dnv_code"] or "—"
        code_counts[c] = code_counts.get(c, 0) + 1

    # SLA performance
    closed  = [t for t in threads if t["disposition"] in ("Accepted",)]
    open_t  = [t for t in threads if t["disposition"] == "Open"]
    all_resp = [t for t in threads if t.get("bastion_response")]

    sla_within = sum(1 for t in all_resp if (t["sla"]["bd_to_response"] or 99) <= 10)
    sla_breach  = sum(1 for t in all_resp if (t["sla"]["bd_to_response"] or 0)  > 10)
    sla_pct     = round(sla_within / len(all_resp) * 100) if all_resp else None

    avg_response = (
        round(sum(t["sla"]["bd_to_response"] for t in all_resp
                  if t["sla"]["bd_to_response"] is not None) / len(all_resp))
        if all_resp else None
    )

    # Open thread aging buckets (business days)
    aging = {"0-5 bd": 0, "6-10 bd": 0, "11-20 bd": 0, "20+ bd": 0}
    for t in open_t:
        bd = t["sla"].get("bd_open") or 0
        if bd <= 5:
            aging["0-5 bd"] += 1
        elif bd <= 10:
            aging["6-10 bd"] += 1
        elif bd <= 20:
            aging["11-20 bd"] += 1
        else:
            aging["20+ bd"] += 1

    # Category breakdown
    cat_counts: dict[str, int] = {}
    for t in threads:
        c = t.get("category") or "Unknown"
        cat_counts[c] = cat_counts.get(c, 0) + 1

    # Disposition breakdown
    disp_counts: dict[str, int] = {}
    for t in threads:
        d = t.get("disposition") or "Unknown"
        disp_counts[d] = disp_counts.get(d, 0) + 1

    return {
        "total_requirements": len(req_list),
        "coverage":           coverage_counts,
        "dnv_codes":          dict(sorted(code_counts.items())),
        "total_threads":      len(threads),
        "open_threads":       len(open_t),
        "sla_within_10bd":    sla_within,
        "sla_breach":         sla_breach,
        "sla_pct":            sla_pct,
        "avg_response_bd":    avg_response,
        "aging":              aging,
        "categories":         cat_counts,
        "dispositions":       disp_counts,
    }


# ── Summary (dashboard card) ──────────────────────────────────────────────────
def get_summary(db_path: Path) -> dict:
    with _conn(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM dnv_requirements").fetchone()[0]
        docs  = con.execute("SELECT COUNT(*) FROM bastion_documents").fetchone()[0]
        open_ = con.execute(
            "SELECT COUNT(*) FROM comment_threads WHERE disposition='Open'"
        ).fetchone()[0]
        missing = con.execute("""
            SELECT COUNT(*) FROM dnv_requirements r
            WHERE NOT EXISTS (SELECT 1 FROM bastion_documents WHERE requirement_id=r.id)
        """).fetchone()[0]
    return {
        "total_requirements": total,
        "linked_documents":   docs,
        "open_threads":       open_,
        "missing_requirements": missing,
    }


# ── Export (filtered CSV bytes) ───────────────────────────────────────────────
def export_requirements_csv(db_path: Path, dnv_code: str = "",
                            coverage: str = "") -> bytes:
    import io
    reqs = get_requirements(db_path)
    if dnv_code:
        reqs = [r for r in reqs if r.get("dnv_code") == dnv_code]
    if coverage:
        reqs = [r for r in reqs if r.get("coverage_status") == coverage]

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Item #", "DNV Code", "Requirement", "Approval Type",
                "Subsystem", "Coverage Status", "Docs Linked", "Open Threads"])
    for r in reqs:
        w.writerow([
            r.get("item_number", ""),
            r.get("dnv_code", ""),
            r.get("requirement_text", ""),
            r.get("approval_type", ""),
            r.get("subsystem", ""),
            r.get("coverage_status", ""),
            r.get("doc_count", 0),
            r.get("open_threads", 0),
        ])
    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel


# ── Migration from CSV (delta-sync) ──────────────────────────────────────────
def migrate_from_csv(db_path: Path, csv_path: Path) -> dict:
    """
    Import rows from CSV into dnv_requirements.
    Safe to call on a populated DB — only inserts rows whose
    (item_number, dnv_code) pair does not already exist.
    Existing rows are never overwritten so manual edits are preserved.
    """
    if not csv_path.exists():
        return {"error": "CSV not found"}

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    added = skipped = 0

    with _conn(db_path) as con:
        # Build lookup of already-imported (item_number, dnv_code) pairs
        existing: set[tuple[str, str]] = set()
        for row in con.execute("SELECT item_number, dnv_code FROM dnv_requirements"):
            existing.add((str(row[0] or ""), str(row[1] or "")))

        for row in rows:
            item = str(row.get("item_number", "")).strip()
            code = str(row.get("dnv_code", "")).strip()
            text = str(row.get("requirement_text", "")).strip()
            desc = str(row.get("additional_description", "")).strip()
            rule  = str(row.get("rule_ref", "")).strip() or "Pt.5 Ch.10 Sec.1"
            appr  = str(row.get("approval_type", "")).strip()
            sub   = str(row.get("subsystem", "")).strip()
            para  = str(row.get("paragraph_ref", "")).strip()
            refsrc= str(row.get("ref_source", "")).strip()

            # Skip blanks and formula artefacts
            if not item and not code and not text:
                continue
            if code.startswith("=") or code == "Code*":
                continue

            # Normalise float item numbers (e.g. "12.0" → "12")
            if item:
                try:
                    item = str(int(float(item)))
                except (ValueError, OverflowError):
                    pass

            key = (item, code)
            if key in existing:
                skipped += 1
                continue  # already in DB — do not overwrite

            con.execute("""
                INSERT INTO dnv_requirements
                  (item_number, rule_ref, dnv_code, requirement_text,
                   additional_description, approval_type, subsystem,
                   paragraph_ref, ref_source)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (item, rule, code, text, desc, appr, sub, para, refsrc))
            existing.add(key)  # prevent dupe within same CSV
            added += 1

    return {"added": added, "skipped": skipped}
