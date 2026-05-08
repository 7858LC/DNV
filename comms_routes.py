"""
comms_routes.py  — Sentinel Communications Log blueprint

Routes:
  GET  /comms                        → page
  GET  /api/comms                    → list communications (filters: lane, source, search)
  POST /api/comms                    → create communication (+ inline actions)
  GET  /api/comms/<id>               → get single communication with actions
  PUT  /api/comms/<id>               → update communication
  DELETE /api/comms/<id>             → delete communication + its actions

  GET  /api/comms/actions            → list actions (filters: lane, status, overdue)
  POST /api/comms/actions            → create standalone action
  PUT  /api/comms/actions/<id>       → update action
  DELETE /api/comms/actions/<id>     → delete action

  GET  /api/comms/summary            → KPI summary card
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from utils import load_config, resolve_path

comms_bp = Blueprint("comms", __name__)


def _db_path() -> Path:
    cfg = load_config()
    return resolve_path(cfg["state_dir"]) / "comms.db"


def _ensure_db() -> Path:
    from comms_db import init_db
    p = _db_path()
    init_db(p)
    return p


# ── Page ──────────────────────────────────────────────────────────────────────

@comms_bp.route("/comms")
def comms_page():
    _ensure_db()
    return render_template("comms.html")


# ── Communications ────────────────────────────────────────────────────────────

@comms_bp.route("/api/comms", methods=["GET"])
def api_comms_list():
    from comms_db import get_communications
    db   = _ensure_db()
    lane = request.args.get("lane", "")
    src  = request.args.get("source", "")
    srch = request.args.get("search", "")
    return jsonify(get_communications(db, lane=lane, source=src, search=srch))


@comms_bp.route("/api/comms", methods=["POST"])
def api_comms_create():
    from comms_db import create_communication
    db   = _ensure_db()
    data = request.get_json(force=True) or {}
    if not data.get("summary", "").strip() and not data.get("subject", "").strip():
        return jsonify({"error": "subject or summary required"}), 400
    result = create_communication(db, data)
    return jsonify({"status": "ok", **result}), 201


@comms_bp.route("/api/comms/<int:comm_id>", methods=["GET"])
def api_comms_get(comm_id):
    from comms_db import get_communication
    db = _db_path()
    c  = get_communication(db, comm_id)
    if not c:
        return jsonify({"error": "Not found"}), 404
    return jsonify(c)


@comms_bp.route("/api/comms/<int:comm_id>", methods=["PUT"])
def api_comms_update(comm_id):
    from comms_db import update_communication
    db   = _db_path()
    data = request.get_json(force=True) or {}
    update_communication(db, comm_id, data)
    return jsonify({"status": "ok"})


@comms_bp.route("/api/comms/<int:comm_id>", methods=["DELETE"])
def api_comms_delete(comm_id):
    from comms_db import delete_communication
    delete_communication(_db_path(), comm_id)
    return jsonify({"status": "ok"})


# ── Actions ───────────────────────────────────────────────────────────────────

@comms_bp.route("/api/comms/actions", methods=["GET"])
def api_actions_list():
    from comms_db import get_actions
    db           = _ensure_db()
    lane         = request.args.get("lane", "")
    status       = request.args.get("status", "")
    overdue_only = request.args.get("overdue", "").lower() in ("1", "true", "yes")
    return jsonify(get_actions(db, lane=lane, status=status, overdue_only=overdue_only))


@comms_bp.route("/api/comms/actions", methods=["POST"])
def api_actions_create():
    from comms_db import create_action
    db   = _ensure_db()
    data = request.get_json(force=True) or {}
    if not data.get("description", "").strip():
        return jsonify({"error": "description required"}), 400
    result = create_action(db, data)
    return jsonify({"status": "ok", **result}), 201


@comms_bp.route("/api/comms/actions/<int:action_id>", methods=["PUT"])
def api_actions_update(action_id):
    from comms_db import update_action
    db   = _db_path()
    data = request.get_json(force=True) or {}
    update_action(db, action_id, data)
    return jsonify({"status": "ok"})


@comms_bp.route("/api/comms/actions/<int:action_id>", methods=["DELETE"])
def api_actions_delete(action_id):
    from comms_db import delete_action
    delete_action(_db_path(), action_id)
    return jsonify({"status": "ok"})


# ── Summary ───────────────────────────────────────────────────────────────────

@comms_bp.route("/api/comms/summary", methods=["GET"])
def api_comms_summary():
    from comms_db import get_summary
    db = _ensure_db()
    return jsonify(get_summary(db))
