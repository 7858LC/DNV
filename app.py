"""
DNV Bastion Coordinator - Flask Web Server
Serves the dashboard at http://localhost:<port>
Auto-selects a free port from [5000, 5001, 8080, 8888, 8000].
"""
from __future__ import annotations
import hmac
import hashlib
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import datetime as _dt
from flask import Flask, jsonify, render_template, request, send_file, abort, make_response
from werkzeug.utils import secure_filename
import io

from utils import load_config, resolve_path
from experience_routes import experience_bp
from comms_routes import comms_bp

# ── CSV write lock ────────────────────────────────────────────────────────────
# All read-modify-write operations on CSV files must hold this lock.
# Prevents last-writer-wins data loss when multiple users submit simultaneously.
# SQLite modules (packages, schedule, comms) handle their own concurrency via WAL.
_csv_lock = threading.Lock()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.register_blueprint(experience_bp)
app.register_blueprint(comms_bp)
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024   # 50 MB upload cap
app.secret_key = os.environ.get("FLASK_SECRET", "dnv-bastion-dev-key-change-in-prod")

CANDIDATE_PORTS = [5000, 5001, 8080, 8888, 8000]


def find_free_port() -> int:
    for port in CANDIDATE_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _load_state() -> dict:
    cfg = load_config()
    state_path = resolve_path(cfg["state_dir"]) / "computed_state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"error": "No computed state found. Run the pipeline first."}


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/state")
def api_state():
    return jsonify(_load_state())


@app.route("/api/run", methods=["POST"])
def api_run():
    mode = request.json.get("mode", "daily") if request.is_json else "daily"
    try:
        from orchestrator import run_pipeline
        state = run_pipeline(mode=mode)
        return jsonify({"status": "ok", "state": state})
    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}), 500


@app.route("/api/export/sla-pdf")
def export_sla_pdf():
    cfg = load_config()
    try:
        from report_sla import generate_sla_pdf
        import datetime as _dt
        pdf_bytes = generate_sla_pdf(cfg)
        filename  = f"Sentinel001_TQ_SLA_Forecast_{_dt.date.today()}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}), 500


@app.route("/api/export/audit-pdf")
def export_audit_pdf():
    cfg = load_config()
    try:
        from report_audit import generate_audit_pdf
        import datetime as _dt
        pdf_bytes = generate_audit_pdf(cfg)
        filename  = f"Sentinel001_Audit_Readiness_Forecast_{_dt.date.today()}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}), 500


@app.route("/api/export/docreq-pdf")
def export_docreq_pdf():
    cfg = load_config()
    try:
        from report_docreq import generate_docreq_pdf
        import datetime as _dt
        pdf_bytes = generate_docreq_pdf(cfg)
        filename  = f"Sentinel001_DNV_DocReq_Coverage_{_dt.date.today()}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}), 500


@app.route("/api/export/scorecard-pdf")
def export_scorecard_pdf():
    """Generate and return the Interface Health Scorecard as a PDF."""
    cfg = load_config()
    try:
        from report_scorecard import generate_scorecard_pdf
        import datetime as _dt
        pdf_bytes = generate_scorecard_pdf(cfg)
        filename  = f"Sentinel001_Interface_Health_Scorecard_{_dt.date.today()}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}), 500


@app.route("/api/export/md")
def export_md():
    cfg = load_config()
    from utils import get_run_date
    run_date = get_run_date()
    out_dir = resolve_path(cfg["outputs_dir"]) / str(run_date)
    md_path = out_dir / "weekly_report.md"
    if not md_path.exists():
        outputs_root = resolve_path(cfg["outputs_dir"])
        candidates = sorted(outputs_root.glob("*/weekly_report.md"), reverse=True)
        if not candidates:
            abort(404, "No weekly report found. Run in weekly mode first.")
        md_path = candidates[0]
    return send_file(str(md_path), as_attachment=True,
                     download_name="weekly_report.md", mimetype="text/markdown")


_CSV_TABLE_MAP = {
    "submissions":        "submissions",
    "actions":            "action_tracker",
    "tqs":                "tq_log",
    "audits":             "audit_definitions",
    "dnv_comments":       "dnv_comments",
    "document_register":  "document_register",
    "dnv_requirements":   "dnv_doc_requirements",
}


def _csv_path(table: str):
    cfg = load_config()
    data_dir = resolve_path(cfg["data_dir"])
    key = _CSV_TABLE_MAP.get(table)
    return (data_dir / cfg["csv_files"][key]) if key else None


@app.route("/coordinator")
def coordinator():
    return render_template("coordinator.html")


# ── DOC REQUIREMENTS MODULE ───────────────────────────────────────────────────
def _docreq_db_path():
    cfg = load_config()
    from utils import resolve_path
    return resolve_path(cfg["state_dir"]) / "docreq.db"


def _ensure_docreq_db():
    from docreq_db import init_db, migrate_from_csv
    from utils import resolve_path
    cfg = load_config()
    db_path  = _docreq_db_path()
    csv_path = resolve_path(cfg["data_dir"]) / cfg["csv_files"].get(
        "dnv_doc_requirements", "dnv_doc_requirements.csv"
    )
    init_db(db_path)
    migrate_from_csv(db_path, csv_path)
    return db_path


@app.route("/docreq")
def docreq_page():
    _ensure_docreq_db()
    return render_template("docreq.html")


@app.route("/api/docreq/requirements", methods=["GET"])
def api_docreq_requirements():
    from docreq_db import get_requirements
    db = _ensure_docreq_db()
    return jsonify(get_requirements(db))


@app.route("/api/docreq/requirements/<int:req_id>", methods=["GET"])
def api_docreq_requirement(req_id):
    from docreq_db import get_requirement
    db = _docreq_db_path()
    r = get_requirement(db, req_id)
    if not r:
        return jsonify({"error": "Not found"}), 404
    return jsonify(r)


@app.route("/api/docreq/requirements/<int:req_id>/documents", methods=["POST"])
def api_docreq_add_document(req_id):
    from docreq_db import link_document
    db   = _docreq_db_path()
    data = request.get_json(force=True) or {}
    doc_number = (data.get("doc_number") or "").strip()
    if not doc_number:
        return jsonify({"error": "doc_number required"}), 400
    doc_id = link_document(db, req_id, doc_number, created_by=_current_user())
    return jsonify({"status": "ok", "id": doc_id}), 201


@app.route("/api/docreq/documents/<int:doc_id>", methods=["DELETE"])
def api_docreq_delete_document(doc_id):
    from docreq_db import unlink_document
    unlink_document(_docreq_db_path(), doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/docreq/documents/<int:doc_id>/comments", methods=["POST"])
def api_docreq_add_comment(doc_id):
    from docreq_db import add_comment
    db   = _docreq_db_path()
    data = request.get_json(force=True) or {}
    thread_id = add_comment(db, doc_id, data, created_by=_current_user())
    return jsonify({"status": "ok", "id": thread_id}), 201


@app.route("/api/docreq/comments/<int:thread_id>", methods=["PUT"])
def api_docreq_update_comment(thread_id):
    from docreq_db import update_comment
    db   = _docreq_db_path()
    data = request.get_json(force=True) or {}
    # Inject updated_by from session
    data["updated_by"] = _current_user()
    update_comment(db, thread_id, data)
    return jsonify({"status": "ok"})


@app.route("/api/docreq/comments/<int:thread_id>", methods=["DELETE"])
def api_docreq_delete_comment(thread_id):
    from docreq_db import delete_comment
    delete_comment(_docreq_db_path(), thread_id)
    return jsonify({"status": "ok"})


@app.route("/api/docreq/summary", methods=["GET"])
def api_docreq_summary():
    from docreq_db import get_summary
    db = _ensure_docreq_db()
    return jsonify(get_summary(db))


@app.route("/api/docreq/metrics", methods=["GET"])
def api_docreq_metrics():
    from docreq_db import get_metrics
    db = _ensure_docreq_db()
    return jsonify(get_metrics(db))


@app.route("/api/docreq/export", methods=["GET"])
def api_docreq_export():
    from docreq_db import export_requirements_csv
    import datetime as _dt
    db       = _docreq_db_path()
    dnv_code = request.args.get("dnv_code", "")
    coverage = request.args.get("coverage", "")
    csv_bytes = export_requirements_csv(db, dnv_code=dnv_code, coverage=coverage)
    filename = f"DNV_DocReq_{_dt.date.today()}.csv"
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


# ── IDENTITY ─────────────────────────────────────────────────────────────────
def _get_session() -> dict:
    """Read bastion_session cookie (JSON). Falls back to legacy bastion_user cookie."""
    raw = request.cookies.get("bastion_session", "")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    # Legacy fallback
    name = request.cookies.get("bastion_user", "")
    return {"name": name, "role": "", "tz": "UTC"}


def _current_user() -> str:
    """Return the signed-in user's name for audit trail."""
    return _get_session().get("name", "") or ""


@app.route("/api/identity", methods=["GET"])
def api_identity_get():
    return jsonify(_get_session())


@app.route("/api/identity", methods=["POST"])
def api_identity_set():
    data = request.get_json(force=True) or {}
    session_data = {
        "name": str(data.get("name", "")).strip(),
        "role": str(data.get("role", "")).strip(),
        "tz":   str(data.get("tz",   "UTC")).strip(),
    }
    resp = make_response(jsonify({"status": "ok", **session_data}))
    resp.set_cookie(
        "bastion_session", json.dumps(session_data),
        max_age=60 * 60 * 24 * 365, samesite="Lax",
    )
    # Clear legacy cookie
    resp.delete_cookie("bastion_user")
    return resp


@app.route("/logout", methods=["GET", "POST"])
def logout():
    resp = make_response(jsonify({"status": "ok"}))
    resp.delete_cookie("bastion_session")
    resp.delete_cookie("bastion_user")
    return resp


# ── RAG STATUS (computed from DueDate) ───────────────────────────────────────
def _compute_rag(due_date_str: str, status: str) -> str:
    """GREEN / AMBER / RED based on days to due date. Closed items return CLOSED."""
    if str(status).lower() in ("closed", "complete", "completed", "done"):
        return "CLOSED"
    if not due_date_str:
        return "GREEN"
    try:
        due   = _dt.date.fromisoformat(str(due_date_str)[:10])
        today = _dt.date.today()
        delta = (due - today).days
        if delta < 0:  return "RED"
        if delta <= 5: return "AMBER"
        return "GREEN"
    except Exception:
        return "GREEN"


# ── SLA DIGEST TRIGGER ────────────────────────────────────────────────────────
@app.route("/api/admin/sla-digest", methods=["POST"])
def api_sla_digest():
    try:
        from sla_digest import run as run_digest
        result = run_digest()
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}), 500


# ── EXECUTIVE DASHBOARD ───────────────────────────────────────────────────────
@app.route("/exec")
def exec_dashboard():
    return render_template("exec_dashboard.html")


@app.route("/datasheet")
def datasheet():
    return render_template("datasheet.html")


@app.route("/kanban")
def kanban():
    return render_template("kanban.html")


@app.route("/reports")
def reports():
    return render_template("reports.html")


@app.route("/workflow")
def workflow():
    return render_template("workflow.html")


@app.route("/process_document")
def process_document():
    cfg = load_config()
    doc_path = resolve_path(cfg["outputs_dir"]) / "Bastion_DNV_Process_Workflow.docx"
    if not doc_path.exists():
        abort(404, "Process document not found. Check outputs/ directory.")
    return send_file(
        str(doc_path),
        as_attachment=True,
        download_name="Bastion_DNV_Process_Workflow.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── PDM IMPORT (Option A: CSV upload from SolidWorks PDM export) ──────────────
# Expected PDM CSV columns (SolidWorks PDM standard export):
#   Number, Name, Revision, State, Category, Checked In By, Date Modified
# Maps into submissions table. New rows only — existing doc numbers are skipped.

PDM_COLUMN_MAP = {
    "Number":          "PDMDocumentNumber",
    "Name":            "DocumentTitle",
    "Revision":        "Revision",
    "State":           None,           # used to derive PDMApprovalDate only if State == Approved
    "Category":        "DocumentType",
    "Checked In By":   "PDMApprover",
    "Date Modified":   "PDMApprovalDate",
}

@app.route("/api/import/pdm", methods=["POST"])
def api_import_pdm():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a .csv export from SolidWorks PDM"}), 400
    try:
        pdm_df = pd.read_csv(io.StringIO(f.read().decode("utf-8", errors="replace")))
    except Exception as e:
        return jsonify({"error": f"Could not parse CSV: {e}"}), 400

    sub_path = _csv_path("submissions")
    if not sub_path or not sub_path.exists():
        return jsonify({"error": "submissions.csv not found"}), 500

    with _csv_lock:
        sub_df = pd.read_csv(sub_path).fillna("")
        existing = set(sub_df["PDMDocumentNumber"].astype(str).str.strip())

        added, skipped = [], []
        for _, row in pdm_df.iterrows():
            pdm_num = str(row.get("Number", "")).strip()
            if not pdm_num:
                continue
            if pdm_num in existing:
                skipped.append(pdm_num)
                continue
            new_row = {c: "" for c in sub_df.columns}
            new_row["PDMDocumentNumber"] = pdm_num
            new_row["DocumentTitle"]     = str(row.get("Name", "")).strip()
            new_row["Revision"]          = str(row.get("Revision", "")).strip()
            new_row["DocumentType"]      = str(row.get("Category", "")).strip()
            new_row["PDMApprover"]       = str(row.get("Checked In By", "")).strip()
            new_row["PDMApprovalDate"]   = str(row.get("Date Modified", "")).strip()
            new_row["Status"]            = "New"
            new_row["DocumentNumber"]    = pdm_num
            added.append(pdm_num)
            sub_df = pd.concat([sub_df, pd.DataFrame([new_row])], ignore_index=True)

        sub_df.to_csv(sub_path, index=False)
    return jsonify({"status": "ok", "added": added, "skipped": skipped,
                    "added_count": len(added), "skipped_count": len(skipped)})


def _submission_statuses() -> list:
    return load_config().get("submission_statuses", [])


def _maybe_add_audit_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure created_by / updated_by / updated_at columns exist on a DataFrame."""
    for col in ("created_by", "updated_by", "updated_at"):
        if col not in df.columns:
            df[col] = ""
    return df


@app.route("/api/csv/<table>", methods=["GET"])
def api_csv_get(table):
    path = _csv_path(table)
    if path is None:
        return jsonify({"error": "Unknown table"}), 400
    if not path.exists():
        return jsonify([])
    df = pd.read_csv(path).fillna("")
    records = df.to_dict(orient="records")
    for i, r in enumerate(records):
        r["_idx"] = i
        # Compute RAGStatus live for action tracker
        if table == "actions":
            r["RAGStatus"] = _compute_rag(r.get("DueDate", ""), r.get("Status", ""))
    return jsonify(records)


@app.route("/api/csv/<table>", methods=["POST"])
def api_csv_create(table):
    path = _csv_path(table)
    if path is None:
        return jsonify({"error": "Unknown table"}), 400
    body = request.get_json(force=True) or {}
    if not path.exists():
        return jsonify({"error": "CSV not found"}), 404
    user = _current_user()
    now  = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with _csv_lock:
        df = _maybe_add_audit_cols(pd.read_csv(path))
        new_row = {c: body.get(c, "") for c in df.columns}
        if "created_by" in df.columns: new_row["created_by"] = user
        if "updated_by" in df.columns: new_row["updated_by"] = user
        if "updated_at" in df.columns: new_row["updated_at"] = now
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(path, index=False)
    return jsonify({"status": "ok"})


@app.route("/api/csv/<table>/<int:idx>", methods=["PUT"])
def api_csv_update(table, idx):
    path = _csv_path(table)
    if path is None:
        return jsonify({"error": "Unknown table"}), 400
    body = request.get_json(force=True) or {}
    if not path.exists():
        return jsonify({"error": "CSV not found"}), 404
    user = _current_user()
    now  = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with _csv_lock:
        df = _maybe_add_audit_cols(pd.read_csv(path))
        if idx < 0 or idx >= len(df):
            return jsonify({"error": "Row index out of range"}), 404
        # Validate Status enum for submissions
        if table == "submissions" and "Status" in body:
            allowed = _submission_statuses()
            if allowed and body["Status"] not in allowed:
                return jsonify({
                    "error": f"Invalid status '{body['Status']}'.",
                    "allowed": allowed,
                }), 400
        for col, val in body.items():
            if col != "_idx" and col in df.columns:
                df.at[idx, col] = val
        if "updated_by" in df.columns: df.at[idx, "updated_by"] = user
        if "updated_at" in df.columns: df.at[idx, "updated_at"] = now
        df.to_csv(path, index=False)
    return jsonify({"status": "ok"})


def _log_deletion(table: str, row: dict) -> None:
    """Append one line to the deletion audit log whenever a CSV row is deleted."""
    try:
        cfg      = load_config()
        log_dir  = resolve_path(cfg.get("logs_dir", "./logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "deletions.log"

        user      = _current_user() or "unknown"
        timestamp = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Pick the most human-readable identifier from the row
        ident = (
            row.get("DocumentNumber")
            or row.get("CommentID")
            or row.get("ActionID")
            or row.get("TQID")
            or row.get("id")
            or f"row-data"
        )

        # Compact JSON of the full row so it can be restored from the log alone
        row_json = json.dumps(
            {k: v for k, v in row.items() if str(v).strip() not in ("", "nan")},
            ensure_ascii=False
        )

        line = f"{timestamp} | {table} | {ident} | deleted_by: {user} | {row_json}\n"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass   # logging must never break the main request


@app.route("/api/csv/<table>/<int:idx>", methods=["DELETE"])
def api_csv_delete(table, idx):
    path = _csv_path(table)
    if path is None:
        return jsonify({"error": "Unknown table"}), 400
    if not path.exists():
        return jsonify({"error": "CSV not found"}), 404
    with _csv_lock:
        df = pd.read_csv(path)
        if idx < 0 or idx >= len(df):
            return jsonify({"error": "Row index out of range"}), 404
        deleted_row = df.iloc[idx].to_dict()
        df = df.drop(index=idx).reset_index(drop=True)
        df.to_csv(path, index=False)
    _log_deletion(table, deleted_row)
    return jsonify({"status": "ok"})


# ── FILE ATTACHMENTS ────────────────────────────────────────────────────────
# Files are stored at:  uploads/<DocumentNumber>/<filename>
# Accepted types enforced client-side; any file is accepted server-side.

def _uploads_dir() -> Path:
    cfg = load_config()
    d = resolve_path(cfg.get("uploads_dir", "./uploads"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.route("/api/uploads/counts")
def uploads_counts():
    """Return {DocumentNumber: file_count} for all documents that have uploads."""
    base = _uploads_dir()
    result = {}
    if base.exists():
        for sub in base.iterdir():
            if sub.is_dir():
                result[sub.name] = sum(1 for f in sub.iterdir() if f.is_file())
    return jsonify(result)


@app.route("/api/uploads/<doc_number>", methods=["GET"])
def list_uploads(doc_number):
    """List files attached to a document."""
    d = _uploads_dir() / doc_number
    if not d.exists():
        return jsonify([])
    files = sorted(
        [{"name": f.name, "size": f.stat().st_size}
         for f in d.iterdir() if f.is_file()],
        key=lambda x: x["name"]
    )
    return jsonify(files)


@app.route("/api/uploads/<doc_number>", methods=["POST"])
def upload_file(doc_number):
    """Upload (or replace) a file attached to a document."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    filename = secure_filename(f.filename)
    if not filename:
        return jsonify({"error": "Invalid filename after sanitisation"}), 400
    d = _uploads_dir() / doc_number
    d.mkdir(parents=True, exist_ok=True)
    dest = d / filename
    f.save(str(dest))
    return jsonify({"status": "ok", "filename": filename, "size": dest.stat().st_size})


@app.route("/api/uploads/<doc_number>/<filename>", methods=["GET"])
def download_upload(doc_number, filename):
    """Download a specific attached file."""
    safe = secure_filename(filename)
    path = _uploads_dir() / doc_number / safe
    if not path.exists():
        abort(404, "File not found")
    return send_file(str(path), as_attachment=True, download_name=safe)


@app.route("/api/uploads/<doc_number>/<filename>", methods=["DELETE"])
def delete_upload(doc_number, filename):
    """Delete a specific attached file."""
    safe = secure_filename(filename)
    path = _uploads_dir() / doc_number / safe
    if path.exists():
        path.unlink()
    return jsonify({"status": "ok"})


@app.route("/logs/session_log.json")
def serve_session_log():
    cfg = load_config()
    log_path = resolve_path(cfg["logs_dir"]) / "session_log.json"
    if not log_path.exists():
        return jsonify([])
    return send_file(str(log_path), mimetype="application/json")


# ── CSRF ─────────────────────────────────────────────────────────────────────
# Token is stored in bastion_session cookie and validated on every write request.
# Routes exempt from CSRF: GET/HEAD/OPTIONS (all), identity POST (bootstrap),
# csrf-token GET, and logout.

_CSRF_EXEMPT_PATHS = {"/api/identity", "/api/csrf-token", "/logout"}


def _csrf_token_for_session() -> str:
    """Return the CSRF token stored in the current session cookie."""
    return _get_session().get("csrf_token", "")


def _issue_csrf_token() -> str:
    """Generate a new cryptographically random CSRF token."""
    return secrets.token_urlsafe(32)


@app.route("/api/csrf-token", methods=["GET"])
def api_csrf_token():
    """Return (and persist) a CSRF token for the current session."""
    session_data = _get_session()
    token = session_data.get("csrf_token", "")
    if not token:
        token = _issue_csrf_token()
        session_data["csrf_token"] = token
        resp = make_response(jsonify({"token": token}))
        resp.set_cookie(
            "bastion_session", json.dumps(session_data),
            max_age=60 * 60 * 24 * 365, samesite="Lax",
        )
        return resp
    return jsonify({"token": token})


@app.before_request
def _check_csrf():
    """Reject state-changing requests that lack a valid CSRF token."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.path in _CSRF_EXEMPT_PATHS:
        return
    if not request.path.startswith("/api/") and request.path != "/logout":
        return  # non-API routes (page renders) are GET-only
    client_token  = request.headers.get("X-CSRF-Token", "")
    session_token = _csrf_token_for_session()
    if not session_token or not client_token:
        return jsonify({"error": "CSRF token missing"}), 403
    # Constant-time compare to prevent timing attacks
    if not hmac.compare_digest(client_token, session_token):
        return jsonify({"error": "CSRF token invalid"}), 403


# ── SUBMISSIONS STATE MACHINE ─────────────────────────────────────────────────

def _sub_db_path() -> Path:
    cfg = load_config()
    return resolve_path(cfg["state_dir"]) / "submissions.db"


def _ensure_sub_db() -> Path:
    from submissions_db import init_db
    p = _sub_db_path()
    init_db(p)
    return p


@app.route("/submissions")
def submissions_page():
    _ensure_sub_db()
    return render_template("submissions.html")


@app.route("/api/submissions/workflow", methods=["GET"])
def api_submissions_workflow():
    """Return the full transition map and status colours for the UI."""
    from submissions_db import TRANSITION_MAP, TRANSITION_ROLES, STATUS_COLORS
    return jsonify({
        "map":    TRANSITION_MAP,
        "colors": STATUS_COLORS,
        "roles":  {f"{k[0]}→{k[1]}": v for k, v in TRANSITION_ROLES.items()},
    })


@app.route("/api/submissions/<doc_number>/transition", methods=["POST"])
def api_submissions_transition(doc_number):
    from submissions_db import validate_transition, log_transition
    db   = _ensure_sub_db()
    data = request.get_json(force=True) or {}
    to_status = (data.get("to_status") or "").strip()
    note      = (data.get("note") or "").strip()

    session   = _get_session()
    user      = session.get("name", "")
    role      = session.get("role", "")

    if not to_status:
        return jsonify({"error": "to_status required"}), 400

    sub_path = _csv_path("submissions")
    if not sub_path or not sub_path.exists():
        return jsonify({"error": "submissions.csv not found"}), 500

    # Validate transition before acquiring lock (read-only, safe outside lock)
    probe_df     = pd.read_csv(sub_path).fillna("")
    probe_mask   = probe_df["DocumentNumber"].astype(str).str.strip() == doc_number
    if not probe_mask.any():
        return jsonify({"error": f"Document '{doc_number}' not found"}), 404
    from_status  = str(probe_df.at[probe_df.index[probe_mask][0], "Status"]).strip()
    err = validate_transition(from_status, to_status, role)
    if err:
        return jsonify({"error": err}), 403

    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with _csv_lock:
        df   = _maybe_add_audit_cols(pd.read_csv(sub_path).fillna(""))
        mask = df["DocumentNumber"].astype(str).str.strip() == doc_number
        if not mask.any():
            return jsonify({"error": f"Document '{doc_number}' not found"}), 404
        idx  = df.index[mask][0]
        df.at[idx, "Status"]     = to_status
        df.at[idx, "updated_by"] = user
        df.at[idx, "updated_at"] = now
        df.to_csv(sub_path, index=False)

    # Log to SQLite (outside lock — SQLite handles its own concurrency)
    log_transition(db, doc_number, from_status, to_status, user, note)

    return jsonify({
        "status":      "ok",
        "doc_number":  doc_number,
        "from_status": from_status,
        "to_status":   to_status,
        "changed_by":  user,
        "changed_at":  now,
    })


@app.route("/api/submissions/<doc_number>/history", methods=["GET"])
def api_submissions_history(doc_number):
    from submissions_db import get_history
    db = _ensure_sub_db()
    return jsonify(get_history(db, doc_number))


@app.route("/api/submissions/activity", methods=["GET"])
def api_submissions_activity():
    from submissions_db import get_recent_activity
    db    = _ensure_sub_db()
    limit = int(request.args.get("limit", 50))
    return jsonify(get_recent_activity(db, limit))


# ── DNV COMMENT ENTRY ─────────────────────────────────────────────────────────

def _next_bc_comment_id() -> str:
    """Generate system comment ID: BC-YYYYMMDD-NNN, unique within existing CSV."""
    path = _csv_path("dnv_comments")
    prefix = _dt.date.today().strftime("BC-%Y%m%d-")
    existing: set[str] = set()
    if path and path.exists():
        try:
            df = pd.read_csv(path, usecols=["CommentID"]).fillna("")
            existing = set(df["CommentID"].astype(str))
        except Exception:
            pass
    n = 1
    while True:
        cid = f"{prefix}{n:03d}"
        if cid not in existing:
            return cid
        n += 1


@app.route("/api/dnv-comments/new", methods=["POST"])
def api_new_dnv_comment():
    """Create a new DNV comment row and append to dnv_comments.csv."""
    data = request.get_json(force=True) or {}
    path = _csv_path("dnv_comments")
    if not path or not path.exists():
        return jsonify({"error": "dnv_comments.csv not found"}), 500

    today      = _dt.date.today().isoformat()
    session    = _get_session()
    entered_by = session.get("name", "")

    with _csv_lock:
        df         = pd.read_csv(path).fillna("")
        comment_id = _next_bc_comment_id()   # reads inside lock → no duplicate IDs

        new_row = {col: "" for col in df.columns}
        new_row.update({
            "CommentID":        comment_id,
            "Status":           data.get("Status",     "Open"),
            "Type":             data.get("Type",        "Action Required"),
            "Title":            data.get("Title",        ""),
            "Description":      data.get("Description", ""),
            "Discipline":       data.get("Discipline",  ""),
            "RuleRef":          data.get("RuleRef",     ""),
            "IssueDate":        data.get("IssueDate",   today),
            "IssuedBy":         data.get("IssuedBy",    entered_by),
            "ActionNeededBy":   data.get("ActionNeededBy", ""),
            "ActionNeeded":     data.get("ActionNeeded", ""),
            "LinkedDocuments":  data.get("LinkedDocuments", ""),
            "LinkedDocTitles":  data.get("LinkedDocTitles", ""),
            "DEEPInternalNotes":  data.get("DEEPInternalNotes", ""),
            "ResponsibleParty":   data.get("ResponsibleParty",  ""),
            "ClosedDate":         "",
        })

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(path, index=False)

    return jsonify({"status": "ok", "comment_id": comment_id}), 201


# ── SCHEDULE IMPACT MODULE ───────────────────────────────────────────────────

def _sched_db_path() -> Path:
    cfg = load_config()
    return resolve_path(cfg["state_dir"]) / "schedule.db"


def _ensure_sched_db() -> Path:
    from schedule_db import init_db
    p = _sched_db_path()
    init_db(p)
    return p


def _sched_holidays() -> "set[_dt.date]":
    """Load holiday dates from config.json as a set of date objects."""
    holidays = set()
    for h in load_config().get("holidays", []):
        try:
            holidays.add(_dt.date.fromisoformat(h))
        except Exception:
            pass
    return holidays


def _sched_raw_json() -> Path:
    """Path to the coordinator-maintained schedule_raw.json."""
    cfg = load_config()
    return resolve_path(cfg["state_dir"]) / "schedule_raw.json"


@app.route("/schedule")
def schedule_page():
    _ensure_sched_db()
    return render_template("schedule.html")


@app.route("/api/schedule/status", methods=["GET"])
def api_schedule_status():
    """Return last import info + counts."""
    from schedule_db import get_last_import, get_tasks
    db = _ensure_sched_db()
    last = get_last_import(db)
    total   = len(get_tasks(db, dnv_only=False))
    dnv_cnt = len(get_tasks(db, dnv_only=True))
    return jsonify({
        "last_import": last,
        "task_count":  total,
        "dnv_count":   dnv_cnt,
        "raw_json_exists": _sched_raw_json().exists(),
    })


@app.route("/api/schedule/tasks", methods=["GET"])
def api_schedule_tasks():
    """Return tasks with risk flags.  ?dnv_only=1 (default) or 0 for all tasks."""
    from schedule_db import get_tasks_with_risk, get_link_counts
    db       = _ensure_sched_db()
    dnv_only = request.args.get("dnv_only", "1") != "0"
    holidays = _sched_holidays()
    tasks    = get_tasks_with_risk(db, holidays=holidays, dnv_only=dnv_only)
    counts   = get_link_counts(db)
    for t in tasks:
        t["link_count"] = counts.get(t["id"], 0)
    return jsonify(tasks)


# ── MPP → task-list conversion (jpype / mpxj) ─────────────────────────────────
_jvm_lock = threading.Lock()


def _mpp_bytes_to_tasks(file_bytes: bytes, filename: str) -> list[dict]:
    """
    Convert a binary .mpp file (MS Project) to the portal task-list format
    using the mpxj Java library via JPype.  Thread-safe JVM start.
    Raises RuntimeError with a human-readable message on failure.
    """
    import importlib.util, tempfile
    try:
        import jpype
        import jpype.imports
        from jpype import JClass
    except ImportError:
        raise RuntimeError(
            "JPype1 is not installed. Run: python -m pip install jpype1"
        )

    # Locate mpxj jars from the Python package
    spec = importlib.util.find_spec("mpxj")
    if not spec:
        raise RuntimeError(
            "mpxj is not installed. Run: python -m pip install mpxj"
        )
    lib_dir = Path(spec.origin).parent / "lib"
    jars = [str(j) for j in lib_dir.glob("*.jar")]
    if not jars:
        raise RuntimeError(f"No jars found in {lib_dir}")

    with _jvm_lock:
        if not jpype.isJVMStarted():
            jpype.startJVM(classpath=jars)

    # Write bytes to a temp file (mpxj needs a real path)
    suffix = Path(filename).suffix.lower() or ".mpp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        UniversalProjectReader = JClass("org.mpxj.reader.UniversalProjectReader")
        project = UniversalProjectReader().read(tmp_path)

        tasks = []
        for task in project.getTasks():
            if task is None:
                continue
            wbs   = str(task.getWBS()   or "")
            name  = str(task.getName()  or "")
            start = task.getStart()
            finish = task.getFinish()

            def _jdate(jd):
                if jd is None:
                    return ""
                try:
                    ldt = jd.toLocalDateTime() if hasattr(jd, "toLocalDateTime") else jd
                    return str(ldt)[:16]          # "2026-03-15T08:00"
                except Exception:
                    return str(jd)[:16]

            resources = []
            try:
                for ra in task.getResourceAssignments():
                    r = ra.getResource()
                    if r and r.getName():
                        resources.append(str(r.getName()))
            except Exception:
                pass

            tasks.append({
                "id":        int(task.getID() or 0),
                "wbs":       wbs,
                "name":      name,
                "start":     _jdate(start),
                "finish":    _jdate(finish),
                "pct":       float(str(task.getPercentageComplete() or 0).replace('%', '') or 0),
                "milestone": bool(task.getMilestone()),
                "summary":   bool(task.getSummary()),
                "resources": resources,
                "notes":     str(task.getNotes() or "").strip(),
            })
        return tasks
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


@app.route("/api/schedule/import", methods=["POST"])
def api_schedule_import():
    """
    Import schedule tasks.  Three modes:
      1. .mpp upload  — multipart POST with field 'file' containing MS Project binary
      2. .json upload — multipart POST with field 'file' containing task-list JSON
      3. Auto-load    — POST with no file; loads from state/schedule_raw.json
    Only Bastion Coordinator and Admin may import.
    """
    from schedule_db import import_tasks
    session = _get_session()
    role    = session.get("role", "")
    user    = session.get("name", "")

    if role not in ("Bastion Coordinator", "Admin"):
        return jsonify({"error": "Only Coordinators and Admins may import schedule data"}), 403

    db = _ensure_sched_db()

    # Mode 1 & 2: file upload
    if "file" in request.files:
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "Empty file"}), 400

        fname = f.filename.lower()
        file_bytes = f.read()

        # .mpp — convert via mpxj
        if fname.endswith(".mpp") or fname.endswith(".mpt"):
            try:
                raw = _mpp_bytes_to_tasks(file_bytes, f.filename)
            except RuntimeError as e:
                return jsonify({"error": str(e)}), 500
            except Exception as e:
                import traceback
                return jsonify({
                    "error": f"MPP conversion failed: {e}",
                    "detail": traceback.format_exc(),
                }), 500
            # Also save a fresh schedule_raw.json for the auto-load path
            try:
                _sched_raw_json().write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            except Exception:
                pass   # non-fatal
            result = import_tasks(db, raw, imported_by=user, source_file=f.filename)
            return jsonify({"status": "ok", **result})

        # .json — parse directly
        try:
            raw = json.loads(file_bytes.decode("utf-8"))
        except Exception as e:
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
        if not isinstance(raw, list):
            return jsonify({"error": "JSON must be a list of task objects"}), 400
        result = import_tasks(db, raw, imported_by=user, source_file=f.filename)
        return jsonify({"status": "ok", **result})

    # Mode 3: auto-load from state/schedule_raw.json
    raw_path = _sched_raw_json()
    if not raw_path.exists():
        return jsonify({"error": "state/schedule_raw.json not found. Upload a .mpp or .json file."}), 404
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"Could not read schedule_raw.json: {e}"}), 500

    result = import_tasks(db, raw, imported_by=user, source_file="schedule_raw.json")
    return jsonify({"status": "ok", **result})


@app.route("/api/schedule/tasks/<int:task_id>/links", methods=["GET"])
def api_sched_links_get(task_id):
    from schedule_db import get_links
    db   = _ensure_sched_db()
    return jsonify(get_links(db, task_id))


@app.route("/api/schedule/tasks/<int:task_id>/links", methods=["POST"])
def api_sched_links_add(task_id):
    from schedule_db import add_link, get_task
    db   = _ensure_sched_db()
    data = request.get_json(force=True) or {}
    doc  = str(data.get("doc_number", "")).strip()
    if not doc:
        return jsonify({"error": "doc_number required"}), 400
    if get_task(db, task_id) is None:
        return jsonify({"error": "Task not found"}), 404
    user    = _current_user()
    inserted = add_link(db, task_id, doc, linked_by=user)
    return jsonify({"status": "ok", "inserted": inserted})


@app.route("/api/schedule/tasks/<int:task_id>/links/<path:doc_number>", methods=["DELETE"])
def api_sched_links_delete(task_id, doc_number):
    from schedule_db import remove_link
    db = _ensure_sched_db()
    ok = remove_link(db, task_id, doc_number)
    return jsonify({"status": "ok", "removed": ok})


# ── PACKAGES / VERACITY MODULE ───────────────────────────────────────────────

def _pkg_db_path() -> Path:
    cfg = load_config()
    return resolve_path(cfg["state_dir"]) / "packages.db"


def _ensure_pkg_db() -> Path:
    from packages_db import init_db
    p = _pkg_db_path()
    init_db(p)
    return p


def _load_submissions_list() -> list[dict]:
    """Return all submissions rows as list of dicts."""
    path = _csv_path("submissions")
    if not path or not path.exists():
        return []
    try:
        return pd.read_csv(path).fillna("").to_dict(orient="records")
    except Exception:
        return []


@app.route("/packages")
def packages_page():
    _ensure_pkg_db()
    return render_template("packages.html")


@app.route("/api/packages", methods=["GET"])
def api_packages_list():
    from packages_db import get_packages
    db = _ensure_pkg_db()
    return jsonify(get_packages(db))


@app.route("/api/packages", methods=["POST"])
def api_packages_create():
    from packages_db import create_package
    db   = _ensure_pkg_db()
    data = request.get_json(force=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Package name required"}), 400
    user = _current_user()
    pkg_id = create_package(
        db,
        name=name,
        description=str(data.get("description", "")),
        veracity_ref=str(data.get("veracity_ref", "")),
        created_by=user,
    )
    return jsonify({"status": "ok", "id": pkg_id}), 201


@app.route("/api/packages/<int:pkg_id>", methods=["GET"])
def api_package_get(pkg_id):
    from packages_db import get_package, get_package_documents, get_activity
    db  = _ensure_pkg_db()
    pkg = get_package(db, pkg_id)
    if not pkg:
        return jsonify({"error": "Package not found"}), 404
    docs     = get_package_documents(db, pkg_id)
    activity = get_activity(db, pkg_id)
    return jsonify({"package": pkg, "documents": docs, "activity": activity})


@app.route("/api/packages/<int:pkg_id>", methods=["PUT"])
def api_package_update(pkg_id):
    from packages_db import update_package
    db   = _ensure_pkg_db()
    data = request.get_json(force=True) or {}
    update_package(db, pkg_id, data, updated_by=_current_user())
    return jsonify({"status": "ok"})


@app.route("/api/packages/<int:pkg_id>", methods=["DELETE"])
def api_package_delete(pkg_id):
    from packages_db import delete_package
    db = _ensure_pkg_db()
    delete_package(db, pkg_id)
    return jsonify({"status": "ok"})


@app.route("/api/packages/<int:pkg_id>/documents", methods=["POST"])
def api_package_add_doc(pkg_id):
    from packages_db import add_document
    db   = _ensure_pkg_db()
    data = request.get_json(force=True) or {}
    doc  = str(data.get("doc_number", "")).strip()
    if not doc:
        return jsonify({"error": "doc_number required"}), 400
    inserted = add_document(
        db, pkg_id, doc,
        dnv_doc_number=str(data.get("dnv_doc_number", "")),
        est_reply_date=str(data.get("est_reply_date", "")),
        dnv_type=str(data.get("dnv_type", "")),
        added_by=_current_user(),
    )
    return jsonify({"status": "ok", "inserted": inserted})


@app.route("/api/packages/<int:pkg_id>/documents/<path:doc_number>",
           methods=["PUT"])
def api_package_update_doc(pkg_id, doc_number):
    from packages_db import update_document
    db   = _ensure_pkg_db()
    data = request.get_json(force=True) or {}
    update_document(db, pkg_id, doc_number, data)
    return jsonify({"status": "ok"})


@app.route("/api/packages/<int:pkg_id>/documents/<path:doc_number>",
           methods=["DELETE"])
def api_package_remove_doc(pkg_id, doc_number):
    from packages_db import remove_document
    db = _ensure_pkg_db()
    ok = remove_document(db, pkg_id, doc_number, removed_by=_current_user())
    return jsonify({"status": "ok", "removed": ok})


@app.route("/api/packages/<int:pkg_id>/export", methods=["GET"])
def api_package_export(pkg_id):
    """Export package in Veracity-mirrored format — JSON or CSV."""
    from packages_db import export_package
    fmt = request.args.get("format", "json").lower()
    db  = _ensure_pkg_db()
    subs = _load_submissions_list()
    data = export_package(db, pkg_id, subs)
    if not data:
        return jsonify({"error": "Package not found"}), 404

    if fmt == "csv":
        import csv, io as _io
        buf = _io.StringIO()
        pkg = data["package"]
        writer = csv.writer(buf)
        writer.writerow([f"PACKAGE: {pkg['name']}",
                         f"Status: {pkg['status']}",
                         f"Veracity Ref: {pkg['veracity_ref']}",
                         f"Exported: {data['exported_at']}"])
        writer.writerow([])
        writer.writerow(["Bastion Doc #", "DNV Doc #", "Title", "Type",
                         "Revision", "Est. Reply Date", "Status",
                         "Discipline", "Not Applicable"])
        for d in data["documents"]:
            writer.writerow([
                d["doc_number"], d["dnv_doc_number"], d["title"],
                d["type"], d["revision"], d["est_reply_date"],
                d["status"], d["discipline"],
                "Yes" if d["dnv_not_applicable"] else "No",
            ])
        csv_bytes = buf.getvalue().encode("utf-8")
        pkg_name  = pkg["name"].replace(" ", "_")
        filename  = f"Package_{pkg_name}_{_dt.date.today()}.csv"
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename,
        )

    return jsonify(data)


@app.route("/api/packages/by-doc/<path:doc_number>", methods=["GET"])
def api_packages_by_doc(doc_number):
    """Return all packages containing a given document number."""
    from packages_db import get_document_packages
    db = _ensure_pkg_db()
    return jsonify(get_document_packages(db, doc_number))


@app.route("/api/packages/<int:pkg_id>/eligible-docs", methods=["GET"])
def api_package_eligible_docs(pkg_id):
    """
    Return submissions eligible to be added to this package.

    Eligible = Bastion-approved (status not in Draft/Internal Review)
               AND not already in this package.

    Returns list of {doc_number, title, status, revision, discipline}.
    """
    from packages_db import get_package_documents

    # Statuses that have NOT yet passed Bastion internal review
    NOT_READY = {"Draft", "Internal Review"}

    db        = _ensure_pkg_db()
    subs      = _load_submissions_list()
    in_pkg    = {r["doc_number"]
                 for r in get_package_documents(db, pkg_id)}

    eligible = []
    for s in subs:
        dn     = str(s.get("DocumentNumber", "")).strip()
        status = str(s.get("Status", "")).strip()
        if not dn:
            continue
        if status in NOT_READY:
            continue
        if dn in in_pkg:
            continue
        eligible.append({
            "doc_number":  dn,
            "title":       str(s.get("DocumentTitle", "")).strip(),
            "status":      status,
            "revision":    str(s.get("Revision", "")).strip(),
            "discipline":  str(s.get("DNVDisciplineQueue", "")).strip(),
        })

    return jsonify(eligible)


@app.route("/api/packages/<int:pkg_id>/import-veracity", methods=["POST"])
def api_package_import_veracity(pkg_id):
    """
    Bulk-import Veracity doc number mappings from a CSV upload.

    Expected CSV columns (case-insensitive, extras ignored):
      doc_number       — Bastion internal number (must already be in package)
      dnv_doc_number   — Veracity D000xxxxxx reference
      est_reply_date   — optional, ISO date YYYY-MM-DD

    Returns JSON: {updated, skipped, errors}
    """
    from packages_db import get_package_documents, update_document
    import io as _io

    db = _ensure_pkg_db()

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400

    try:
        raw = f.read().decode("utf-8-sig")   # strip BOM if Excel-exported
        df  = pd.read_csv(_io.StringIO(raw))
    except Exception as e:
        return jsonify({"error": f"Could not parse CSV: {e}"}), 400

    # Normalise column names: strip whitespace, lowercase
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    if "doc_number" not in df.columns or "dnv_doc_number" not in df.columns:
        return jsonify({
            "error": "CSV must have columns: doc_number, dnv_doc_number"
        }), 400

    # Index existing package documents for fast membership check
    existing = {r["doc_number"] for r in get_package_documents(db, pkg_id)}

    updated = 0
    skipped = []
    errors  = []

    for _, row in df.iterrows():
        doc_num = str(row.get("doc_number", "")).strip()
        dnv_num = str(row.get("dnv_doc_number", "")).strip()

        if not doc_num or not dnv_num:
            continue   # blank rows ignored silently

        if doc_num not in existing:
            skipped.append(doc_num)
            continue

        fields = {"dnv_doc_number": dnv_num}

        # Optional est_reply_date
        if "est_reply_date" in df.columns:
            erd = str(row.get("est_reply_date", "")).strip()
            if erd and erd.lower() not in ("nan", "none", ""):
                fields["est_reply_date"] = erd

        try:
            update_document(db, pkg_id, doc_num, fields)
            updated += 1
        except Exception as e:
            errors.append({"doc_number": doc_num, "error": str(e)})

    return jsonify({
        "updated": updated,
        "skipped": skipped,
        "errors":  errors,
        "message": f"{updated} document(s) updated"
    })


# ── Package file upload / download ───────────────────────────────────────────
def _pkg_uploads_dir(pkg_id: int, doc_number: str) -> Path:
    cfg = load_config()
    p   = resolve_path(cfg.get("uploads_dir", "./uploads")) / "packages" / str(pkg_id) / doc_number
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.route("/api/packages/<int:pkg_id>/documents/<path:doc_number>/files",
           methods=["GET"])
def api_pkg_files_list(pkg_id, doc_number):
    from packages_db import get_files
    db = _ensure_pkg_db()
    return jsonify(get_files(db, pkg_id, doc_number))


@app.route("/api/packages/<int:pkg_id>/documents/<path:doc_number>/files",
           methods=["POST"])
def api_pkg_file_upload(pkg_id, doc_number):
    from packages_db import add_file, get_latest_transmittal, create_transmittal
    import uuid, mimetypes

    db = _ensure_pkg_db()
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    f     = request.files["file"]
    fname = secure_filename(f.filename)
    if not fname:
        return jsonify({"error": "Invalid filename"}), 400

    ext         = Path(fname).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest        = _pkg_uploads_dir(pkg_id, doc_number) / stored_name
    f.save(str(dest))
    size      = dest.stat().st_size
    mime      = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    user      = _current_user()

    fid = add_file(db, pkg_id, doc_number, fname, stored_name,
                   file_size=size, mime_type=mime, uploaded_by=user)

    # If a transmittal exists and is Approved, bump to new revision (edit detected)
    tx = get_latest_transmittal(db, pkg_id)
    if tx and tx["status"] == "Approved":
        create_transmittal(db, pkg_id, generated_by=user)

    return jsonify({"id": fid, "filename": fname, "file_size": size})


@app.route("/api/packages/<int:pkg_id>/files/<int:file_id>/download",
           methods=["GET"])
def api_pkg_file_download(pkg_id, file_id):
    from packages_db import get_file
    db  = _ensure_pkg_db()
    rec = get_file(db, file_id)
    if not rec or rec["package_id"] != pkg_id:
        abort(404)
    fpath = (_pkg_uploads_dir(pkg_id, rec["doc_number"])
             / rec["stored_name"])
    if not fpath.exists():
        abort(404)
    return send_file(str(fpath), as_attachment=True,
                     download_name=rec["filename"],
                     mimetype=rec.get("mime_type") or "application/octet-stream")


@app.route("/api/packages/<int:pkg_id>/files/<int:file_id>",
           methods=["DELETE"])
def api_pkg_file_delete(pkg_id, file_id):
    from packages_db import delete_file, get_latest_transmittal, create_transmittal
    db  = _ensure_pkg_db()
    rec = delete_file(db, file_id, deleted_by=_current_user())
    if not rec:
        return jsonify({"error": "Not found"}), 404

    # Remove physical file
    fpath = (_pkg_uploads_dir(pkg_id, rec["doc_number"])
             / rec["stored_name"])
    try:
        fpath.unlink(missing_ok=True)
    except Exception:
        pass

    # Bump transmittal if Approved
    tx = get_latest_transmittal(db, pkg_id)
    if tx and tx["status"] == "Approved":
        create_transmittal(db, pkg_id, generated_by=_current_user())

    return jsonify({"status": "ok"})


# ── Transmittal routes ────────────────────────────────────────────────────────
def _build_transmittal_context(db_path, pkg_id: int,
                                submissions: list[dict]) -> dict:
    """Assemble all data needed to render transmittal.html."""
    from packages_db import (get_package, get_package_documents,
                              get_latest_transmittal, get_transmittals,
                              file_counts)
    cfg     = load_config()
    pkg     = get_package(db_path, pkg_id)
    tx      = get_latest_transmittal(db_path, pkg_id)
    all_tx  = get_transmittals(db_path, pkg_id)
    docs    = get_package_documents(db_path, pkg_id)
    counts  = file_counts(db_path, pkg_id)

    sub_idx = {str(s.get("DocumentNumber", "")).strip(): s for s in submissions}

    docs_out = []
    for d in docs:
        dn  = d["doc_number"]
        sub = sub_idx.get(dn, {})
        docs_out.append({
            "doc_number":       dn,
            "dnv_doc_number":   d.get("dnv_doc_number") or "",
            "title":            sub.get("DocumentTitle", ""),
            "type":             d.get("dnv_type") or sub.get("DocumentType", ""),
            "revision":         sub.get("Revision", ""),
            "est_reply_date":   d.get("est_reply_date") or "",
            "dnv_not_applicable": bool(d.get("dnv_not_applicable", 0)),
            "file_count":       counts.get(dn, 0),
        })

    return {
        "pkg":           pkg,
        "tx":            tx or {},
        "all_revisions": all_tx,
        "documents":     docs_out,
        "company_name":  cfg.get("company_name", "Bastion"),
        "project_name":  cfg.get("project_name", "Project"),
    }


@app.route("/api/packages/<int:pkg_id>/transmittal", methods=["GET"])
def api_transmittal_status(pkg_id):
    from packages_db import get_latest_transmittal, get_transmittals, file_counts
    db     = _ensure_pkg_db()
    tx     = get_latest_transmittal(db, pkg_id)
    counts = file_counts(db, pkg_id)
    return jsonify({
        "transmittal":  tx,
        "file_counts":  counts,
        "total_files":  sum(counts.values()),
    })


@app.route("/api/packages/<int:pkg_id>/transmittal/generate", methods=["POST"])
def api_transmittal_generate(pkg_id):
    from packages_db import create_transmittal
    db   = _ensure_pkg_db()
    user = _current_user()
    tx_id = create_transmittal(db, pkg_id, generated_by=user)
    return jsonify({"status": "ok", "transmittal_id": tx_id})


@app.route("/api/packages/<int:pkg_id>/transmittal/view", methods=["GET"])
def api_transmittal_view(pkg_id):
    db   = _ensure_pkg_db()
    subs = _load_submissions_list()
    ctx  = _build_transmittal_context(db, pkg_id, subs)
    if not ctx.get("tx"):
        return "No transmittal generated yet.", 404
    return render_template("transmittal.html", **ctx)


@app.route("/api/packages/<int:pkg_id>/transmittal/send-approval",
           methods=["POST"])
def api_transmittal_send_approval(pkg_id):
    from packages_db import (get_latest_transmittal,
                              send_transmittal_for_approval)
    import secrets as _secrets
    import smtplib, ssl
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import datetime as _dt2

    db  = _ensure_pkg_db()
    cfg = load_config()
    tx  = get_latest_transmittal(db, pkg_id)

    if not tx:
        return jsonify({"error": "No transmittal to send"}), 400
    if tx["status"] == "Approved":
        return jsonify({"error": "Already approved"}), 400

    pm_email = cfg.get("pm_email", "")
    if not pm_email:
        return jsonify({"error":
            "pm_email not configured in config.json"}), 400

    token   = _secrets.token_urlsafe(32)
    hours   = int(cfg.get("approval_token_hours", 72))
    expiry  = (_dt2.datetime.utcnow()
                + _dt2.timedelta(hours=hours)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")

    site    = cfg.get("site_url", "http://localhost:5000").rstrip("/")
    approve_url = f"{site}/api/transmittal/approve?token={token}&action=approve"
    reject_url  = f"{site}/api/transmittal/approve?token={token}&action=reject"

    subs    = _load_submissions_list()
    ctx     = _build_transmittal_context(db, pkg_id, subs)
    pkg     = ctx["pkg"]
    doc_rows = "".join(
        f"<tr><td>{d['doc_number']}</td><td>{d['title'] or '—'}</td>"
        f"<td>{d['revision'] or '—'}</td>"
        f"<td>{'✓ ' + str(d['file_count']) + ' file(s)' if d['file_count'] else '⚠ No file'}</td></tr>"
        for d in ctx["documents"]
    )

    html_body = f"""
<html><body style="font-family:Arial,sans-serif;font-size:11pt;color:#1a1a2e">
<h2 style="color:#1a3a5c">Transmittal Approval Required</h2>
<p>A document transmittal has been prepared and requires your approval.</p>
<table style="border-collapse:collapse;margin:16px 0;font-size:10pt">
  <tr><td style="padding:4px 12px 4px 0;color:#666">Package</td>
      <td><strong>{pkg['name']}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Transmittal No.</td>
      <td>TX-{pkg_id:04d}-R{tx['revision']:02d}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Prepared by</td>
      <td>{tx['generated_by']}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Documents</td>
      <td>{len(ctx['documents'])}</td></tr>
</table>
<table style="border-collapse:collapse;font-size:9pt;width:100%;margin-bottom:20px">
  <thead><tr style="background:#1a3a5c;color:#fff">
    <th style="padding:6px 8px;text-align:left">Doc Number</th>
    <th style="padding:6px 8px;text-align:left">Title</th>
    <th style="padding:6px 8px;text-align:left">Rev</th>
    <th style="padding:6px 8px;text-align:left">Files</th>
  </tr></thead>
  <tbody>{doc_rows}</tbody>
</table>
<p>Please review and take action:</p>
<p>
  <a href="{approve_url}" style="background:#15803d;color:#fff;padding:10px 24px;
     text-decoration:none;border-radius:4px;font-weight:bold;margin-right:12px">
    ✓ APPROVE</a>
  <a href="{reject_url}" style="background:#dc2626;color:#fff;padding:10px 24px;
     text-decoration:none;border-radius:4px;font-weight:bold">
    ✗ REJECT</a>
</p>
<p style="margin-top:16px;font-size:9pt;color:#666">
  This link expires in {hours} hours.<br>
  To view the full transmittal: <a href="{site}/api/packages/{pkg_id}/transmittal/view">
  View Transmittal</a>
</p>
</body></html>"""

    # Send email
    smtp_host = cfg.get("smtp_host", "")
    smtp_user = cfg.get("smtp_user", "")
    smtp_pass = cfg.get("smtp_pass", "")
    smtp_from = cfg.get("smtp_from", smtp_user)
    smtp_port = int(cfg.get("smtp_port", 587))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (f"[ACTION REQUIRED] Transmittal Approval: "
                      f"{pkg['name']} TX-{pkg_id:04d}-R{tx['revision']:02d}")
    msg["From"]    = smtp_from
    msg["To"]      = pm_email
    msg.attach(MIMEText(html_body, "html"))

    if not smtp_host or not smtp_user:
        # No SMTP configured — save token and return URL for manual sharing
        send_transmittal_for_approval(db, tx["id"], token, pm_email,
                                      expiry, sent_by=_current_user())
        return jsonify({
            "status": "no_smtp",
            "message": "SMTP not configured. Share this approval link manually.",
            "approve_url": approve_url,
            "reject_url":  reject_url,
        })

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, pm_email, msg.as_string())
    except Exception as e:
        return jsonify({"error": f"Email send failed: {e}"}), 500

    send_transmittal_for_approval(db, tx["id"], token, pm_email,
                                  expiry, sent_by=_current_user())
    return jsonify({"status": "sent", "sent_to": pm_email})


@app.route("/api/transmittal/approve", methods=["GET"])
def api_transmittal_approve():
    """Token-based approval endpoint — PM clicks link in email."""
    from packages_db import resolve_transmittal
    # Find db (scan all package dbs — only one db in this app)
    db     = _ensure_pkg_db()
    token  = request.args.get("token", "")
    action = request.args.get("action", "approve")
    name   = request.args.get("name", "")
    note   = request.args.get("note", "")

    if not token:
        return "Missing token.", 400

    if action not in ("approve", "reject"):
        return "Invalid action.", 400

    tx = resolve_transmittal(db, token, action,
                              by_name=name, reject_note=note)
    if tx is None:
        return render_template("approval_result.html",
                               success=False,
                               message="This link has expired or already been used.")

    verb = "approved" if action == "approve" else "rejected"
    return render_template("approval_result.html",
                           success=(action == "approve"),
                           message=f"Transmittal Rev {tx['revision']} has been {verb}. Thank you.")


@app.route("/api/packages/<int:pkg_id>/transmittal/download-zip",
           methods=["GET"])
def api_transmittal_zip(pkg_id):
    """ZIP of all attached files + transmittal HTML for Veracity upload."""
    import zipfile, io as _io
    from packages_db import (get_package, get_package_documents,
                              get_files, get_latest_transmittal)

    db  = _ensure_pkg_db()
    pkg = get_package(db, pkg_id)
    if not pkg:
        abort(404)

    tx = get_latest_transmittal(db, pkg_id)
    subs = _load_submissions_list()
    ctx  = _build_transmittal_context(db, pkg_id, subs)

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add transmittal HTML
        tx_html = render_template("transmittal.html", **ctx)
        zf.writestr(f"TX-{pkg_id:04d}-R{tx['revision']:02d}_Transmittal.html",
                    tx_html.encode("utf-8"))

        # Add each attached file
        all_files = get_files(db, pkg_id)
        for rec in all_files:
            fpath = (_pkg_uploads_dir(pkg_id, rec["doc_number"])
                     / rec["stored_name"])
            if fpath.exists():
                # Place in subfolder by doc number
                arc_name = f"{rec['doc_number']}/{rec['filename']}"
                zf.write(str(fpath), arc_name)

    buf.seek(0)
    pkg_slug = pkg["name"].replace(" ", "_")[:40]
    zip_name = f"{pkg_slug}_TX-{pkg_id:04d}-R{tx['revision']:02d}.zip"
    return send_file(buf, as_attachment=True,
                     download_name=zip_name,
                     mimetype="application/zip")


# ── Submission field migration (adds Veracity fields if missing) ──────────────
def _maybe_add_veracity_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Add EstReplyDate and DNVNotApplicable columns if not present."""
    for col in ("EstReplyDate", "DNVNotApplicable"):
        if col not in df.columns:
            df[col] = ""
    return df


# Patch api_csv_get to migrate veracity cols for submissions
_orig_api_csv_get = app.view_functions.get("api_csv_get")


# ── Risk thresholds used in impact route ──────────────────────────────────────
try:
    from schedule_db import WATCH_BD, RISK_BD
except ImportError:
    WATCH_BD = 21
    RISK_BD  = 15


@app.route("/api/schedule/impact", methods=["GET"])
def api_schedule_impact():
    """
    Risk summary: for each DNV-relevant task that has linked submissions,
    check whether the linked submissions are Closed before the task starts.
    Returns per-task risk assessment combining lead-time and document status.
    """
    from schedule_db import get_tasks_with_risk, get_link_counts, get_links

    db       = _ensure_sched_db()
    holidays = _sched_holidays()
    tasks    = get_tasks_with_risk(db, holidays=holidays, dnv_only=True)
    counts   = get_link_counts(db)

    # Load submissions for status lookup
    sub_path = _csv_path("submissions")
    sub_status: dict[str, str] = {}
    if sub_path and sub_path.exists():
        try:
            sdf = pd.read_csv(sub_path).fillna("")
            for _, row in sdf.iterrows():
                dn = str(row.get("DocumentNumber", "")).strip()
                st = str(row.get("Status", "")).strip()
                if dn:
                    sub_status[dn] = st
        except Exception:
            pass

    result = []
    for t in tasks:
        link_count = counts.get(t["id"], 0)
        links      = get_links(db, t["id"]) if link_count else []
        doc_risks  = []
        for lnk in links:
            dn  = lnk["doc_number"]
            st  = sub_status.get(dn, "UNKNOWN")
            closed = st.lower() in ("closed", "complete", "completed", "done")
            doc_risks.append({
                "doc_number": dn,
                "status":     st,
                "closed":     closed,
            })
        # Rule 2: any linked doc not closed + task within WATCH window = elevated risk
        open_docs = [d for d in doc_risks if not d["closed"]]
        task_risk = t.get("risk_level", "OK")
        if open_docs and t.get("lead_time_bd") is not None:
            if t["lead_time_bd"] <= WATCH_BD and task_risk == "OK":
                task_risk = "WATCH"
            elif t["lead_time_bd"] <= RISK_BD:
                task_risk = "RISK"

        result.append({
            "id":           t["id"],
            "wbs":          t["wbs"],
            "name":         t["name"],
            "start_dt":     t["start_dt"],
            "finish_dt":    t["finish_dt"],
            "pct":          t["pct"],
            "milestone":    t["milestone"],
            "dnv_witness":  t["dnv_witness"],
            "lead_time_bd": t.get("lead_time_bd"),
            "risk_level":   task_risk,
            "link_count":   link_count,
            "linked_docs":  doc_risks,
            "open_docs":    len(open_docs),
        })

    return jsonify(result)


# ── ERROR HANDLERS ────────────────────────────────────────────────────────────
@app.errorhandler(413)
def upload_too_large(e):
    return jsonify({
        "error": "File too large. Maximum upload size is 50 MB.",
        "limit_mb": 50,
    }), 413


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found", "path": request.path}), 404
    return jsonify({"error": str(e)}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500


if __name__ == "__main__":
    # Ensure we are running from the project root
    os.chdir(Path(__file__).parent)

    # Run initial pipeline if no state exists
    state_path = resolve_path(load_config()["state_dir"]) / "computed_state.json"
    if not state_path.exists():
        print("No existing state - running initial pipeline...")
        try:
            from orchestrator import run_pipeline
            run_pipeline(mode="daily")
        except Exception as e:
            print(f"[WARN] Initial pipeline run failed: {e}")

    port = find_free_port()
    lan_ip = get_lan_ip()
    local_url   = f"http://localhost:{port}"
    network_url = f"http://{lan_ip}:{port}"

    # Save chosen port so batch files can read it
    try:
        Path("state/.port").write_text(str(port))
    except Exception:
        pass

    # Try to open browser - wrapped so a corporate block won't crash the server
    def _open_browser():
        time.sleep(1.5)
        try:
            import webbrowser
            webbrowser.open(local_url)
        except Exception:
            pass  # Browser open blocked by policy - user navigates manually

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"\n  ============================================================")
    print(f"  DNV BASTION COORDINATOR")
    print(f"  Local     : {local_url}")
    print(f"  Network   : {network_url}   <-- share this with your team")
    print(f"  Open either address in your browser.")
    print(f"  Press CTRL+C to stop.")
    print(f"  ============================================================\n")

    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"\n  [ERROR] Flask failed to start: {e}")
        print(f"\n  Possible causes:")
        print(f"    - Port {port} blocked by firewall or security software")
        print(f"    - Missing package (run: python -m pip install flask pandas numpy)")
        print(f"    - Antivirus blocking network socket creation")
        print(f"\n  Run DIAGNOSE.py (double-click it) for full diagnostics.")
        input("\n  Press ENTER to exit...")
        sys.exit(1)
