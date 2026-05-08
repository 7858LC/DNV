"""
Experience Conflict System — Flask Blueprint
All routes prefixed /api/experience/ plus report route /experience/report/<token>
"""
from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request

from utils import load_config, resolve_path

experience_bp = Blueprint("experience", __name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    cfg = load_config()
    return resolve_path(cfg["data_dir"])

def _state_dir() -> Path:
    cfg = load_config()
    return resolve_path(cfg["state_dir"])

def _findings_path() -> Path:
    return _data_dir() / "experience_findings.json"

def _constraints_path() -> Path:
    return _data_dir() / "sentinel_constraints.json"

def _action_tracker_path() -> Path:
    return _data_dir() / "action_tracker.csv"

def _tq_log_path() -> Path:
    return _data_dir() / "tq_log.csv"

def _report_token_path() -> Path:
    return _state_dir() / "report_token.txt"


# ---------------------------------------------------------------------------
# JSON persistence helpers
# ---------------------------------------------------------------------------

def _load_findings() -> list:
    p = _findings_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_findings(findings: list) -> None:
    _findings_path().write_text(
        json.dumps(findings, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def _load_constraints() -> list:
    p = _constraints_path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))

def _signals_path() -> Path:
    return _data_dir() / "design_signals.json"

def _load_signals() -> list:
    p = _signals_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_signals(signals: list) -> None:
    _signals_path().write_text(
        json.dumps(signals, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Design Signal pattern analysis
# ---------------------------------------------------------------------------

_SIGNAL_THRESHOLD_CONSTRAINT = 2  # ≥N findings hitting same constraint
_SIGNAL_THRESHOLD_DIMENSION  = 3  # ≥N findings in same dimension

_BLOCKING = {"HARD_BLOCK", "SOFT_CONFLICT"}

def _build_constraint_clusters(findings: list) -> dict:
    """
    Returns clusters that cross detection thresholds.
    Key: 'constraint:<CON-XXX>' or 'dimension:<DimName>'
    """
    con_map: dict[str, dict] = {}
    dim_map: dict[str, set] = {}

    for f in findings:
        fid = f.get("finding_id", "")
        ca  = f.get("conflict_analysis", {})
        for c in ca.get("single_dimension_checks", []):
            if c.get("classification") in _BLOCKING:
                cid = c.get("constraint_id", "")
                if cid:
                    if cid not in con_map:
                        con_map[cid] = {"name": c.get("constraint_name", ""), "finding_ids": []}
                    if fid not in con_map[cid]["finding_ids"]:
                        con_map[cid]["finding_ids"].append(fid)
        for dim in f.get("dimensions_affected", []):
            dim_map.setdefault(dim, set()).add(fid)

    clusters: dict = {}
    for cid, info in con_map.items():
        if len(info["finding_ids"]) >= _SIGNAL_THRESHOLD_CONSTRAINT:
            clusters[f"constraint:{cid}"] = {
                "type": "constraint", "key": cid, "name": info["name"],
                "finding_ids": info["finding_ids"], "constraint_ids": [cid],
            }
    for dim, fids in dim_map.items():
        if len(fids) >= _SIGNAL_THRESHOLD_DIMENSION:
            clusters[f"dimension:{dim}"] = {
                "type": "dimension", "key": dim, "name": dim,
                "finding_ids": list(fids), "constraint_ids": [],
            }
    return clusters


def _covered_cluster_keys(signals: list) -> set:
    return {s.get("_cluster_key", "") for s in signals}


# ---------------------------------------------------------------------------
# Design Signal system prompt
# ---------------------------------------------------------------------------

_DS_SYSTEM_PROMPT = (
    "You are a systems engineer reviewing a cluster of failure modes for Sentinel 001, "
    "a nine-person ambient-pressure underwater habitat at 13.7 msw, Florida Keys, "
    "operating at 2.40 bar(a) under DNV LIVHAB(SAT) classification.\n\n"
    "Your task is to determine whether a pattern of experience conflicts — multiple "
    "findings all hitting the same constraint or design dimension — indicates a "
    "design weakness that cannot be resolved through operational procedures, "
    "scheduling changes, or customer management alone.\n\n"
    "You reason like an FMEA lead engineer. You identify what the cluster reveals "
    "about system margin, single points of failure, or latent design gaps. "
    "You speak directly to design engineers. You do not suggest procedural workarounds "
    "and you do not generate marketing language.\n\n"
    "Respond only in valid JSON matching the schema provided. "
    "Do not include markdown formatting or code fences in your response."
)


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------

def _next_ecf_id(findings: list) -> str:
    nums = []
    for f in findings:
        fid = f.get("finding_id", "")
        if fid.startswith("ECF-"):
            try:
                nums.append(int(fid[4:]))
            except ValueError:
                pass
    return f"ECF-{(max(nums) + 1 if nums else 1):03d}"

def _next_disp_id(dispositions: list) -> str:
    nums = []
    for d in dispositions:
        did = d.get("disposition_id", "")
        if did.startswith("DISP-"):
            try:
                nums.append(int(did[5:]))
            except ValueError:
                pass
    return f"DISP-{(max(nums) + 1 if nums else 1):03d}"

def _next_act_id() -> str:
    p = _action_tracker_path()
    if not p.exists():
        return "ACT-001"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        nums = []
        for row in reader:
            aid = row.get("ActionID", "")
            if aid.startswith("ACT-"):
                try:
                    nums.append(int(aid[4:]))
                except ValueError:
                    pass
    return f"ACT-{(max(nums) + 1 if nums else 1):03d}"

def _next_tq_id() -> str:
    p = _tq_log_path()
    if not p.exists():
        return "TQ-001"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        nums = []
        for row in reader:
            tid = row.get("TQID", "")
            if tid.startswith("TQ-"):
                try:
                    nums.append(int(tid[3:]))
                except ValueError:
                    pass
    return f"TQ-{(max(nums) + 1 if nums else 1):03d}"


# ---------------------------------------------------------------------------
# Report token
# ---------------------------------------------------------------------------

def _get_or_create_token() -> str:
    p = _report_token_path()
    if p.exists():
        tok = p.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = str(uuid.uuid4())
    p.write_text(tok, encoding="utf-8")
    return tok


# ---------------------------------------------------------------------------
# Claude API call helper
# ---------------------------------------------------------------------------

def _call_claude(system_prompt: str, user_message: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed — run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


_SYSTEM_PROMPT = (
    "You are a mission planning engineer and experience design analyst "
    "for Sentinel 001, a nine-person ambient-pressure underwater habitat "
    "at 13.7 msw, Florida Keys, operating at 2.40 bar(a) under DNV "
    "LIVHAB(SAT) classification.\n\n"
    "Your job is to identify conflicts between customer expectations and "
    "habitat constraints — physical, atmospheric, power, gas, "
    "decompression, egress, temporal, regulatory, and human factors.\n\n"
    "You reason like a failure modes analyst. You lead with what fails "
    "before what works. You never generate marketing language.\n\n"
    "The full constraint set is provided in the user message.\n"
    "Respond only in valid JSON matching the schema provided.\n"
    "Do not include markdown formatting or code fences in your response."
)


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def _compute_summary(findings: list) -> dict:
    today_str = str(date.today())
    total = len(findings)
    open_count = sum(1 for f in findings if f.get("status") == "Open")
    closed_count = sum(1 for f in findings if f.get("status") == "Closed")
    critical_count = sum(
        1 for f in findings
        if f.get("conflict_analysis", {}).get("criticality") == "CRITICAL"
    )

    by_dimension: dict[str, int] = {}
    by_status: dict[str, int] = {}
    overdue: list = []

    for f in findings:
        for dim in f.get("dimensions_affected", []):
            by_dimension[dim] = by_dimension.get(dim, 0) + 1
        st = f.get("status", "Unknown")
        by_status[st] = by_status.get(st, 0) + 1
        for d in f.get("dispositions", []):
            if d.get("status") != "Closed":
                pcd = d.get("planned_closure_date")
                if pcd and pcd < today_str:
                    overdue.append({
                        "finding_id": f.get("finding_id"),
                        "disposition_id": d.get("disposition_id"),
                        "planned_closure_date": pcd,
                        "assignee": d.get("assignee"),
                    })

    signals  = _load_signals()
    sig_open = sum(1 for s in signals if s.get("status") != "Closed")
    clusters = _build_constraint_clusters(findings)
    covered  = _covered_cluster_keys(signals)
    pending  = any(k not in covered for k in clusters)

    return {
        "total_findings": total,
        "open_count": open_count,
        "closed_count": closed_count,
        "critical_count": critical_count,
        "by_dimension": by_dimension,
        "by_status": by_status,
        "overdue_dispositions": overdue,
        "design_signal_count": len(signals),
        "signals_open_count": sig_open,
        "pending_signal_review": pending,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@experience_bp.route("/api/experience/analyze", methods=["POST"])
def analyze():
    body = request.get_json(force=True) or {}
    expectation = body.get("expectation", "").strip()
    context = body.get("context", "").strip()
    if not expectation:
        return jsonify({"error": "expectation is required"}), 400

    constraints = _load_constraints()
    response_schema = {
        "implied_assumptions": ["array of strings"],
        "dimensions_affected": ["array of dimension names"],
        "single_dimension_checks": [
            {
                "constraint_id": "string",
                "constraint_name": "string",
                "classification": "HARD_BLOCK|SOFT_CONFLICT|COMPATIBLE_WITH_MARGIN|COMPATIBLE_AT_LIMIT",
                "explanation": "string"
            }
        ],
        "stacking_risks": ["array of strings"],
        "criticality": "CRITICAL|OPERATIONAL|PLANNING|DESIGN",
        "disposition_options": [
            {
                "type": "Engineering|Procedural|Scheduling|CustomerManagement",
                "description": "string",
                "what_it_does_not_resolve": "string",
                "residual_risk": "string"
            }
        ],
        "summary": "2-3 sentence plain English summary"
    }

    user_msg = json.dumps({
        "constraints": constraints,
        "customer_expectation": expectation,
        "context": context,
        "response_schema": response_schema,
    }, ensure_ascii=False)

    try:
        raw = _call_claude(_SYSTEM_PROMPT, user_msg)
        result = json.loads(raw)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Claude returned non-JSON response", "raw": raw}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    result["customer_expectation"] = expectation
    result["context"] = context
    return jsonify(result)


@experience_bp.route("/api/experience/findings", methods=["POST"])
def create_finding():
    body = request.get_json(force=True) or {}
    findings = _load_findings()
    fid = _next_ecf_id(findings)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    finding = {
        "finding_id": fid,
        "created_date": str(date.today()),
        "created_by": body.get("created_by", "System"),
        "status": body.get("status", "Open"),
        "title": body.get("title", "Untitled Finding"),
        "customer_expectation": body.get("customer_expectation", ""),
        "implied_assumptions": body.get("implied_assumptions", []),
        "dimensions_affected": body.get("dimensions_affected", []),
        "conflict_analysis": body.get("conflict_analysis", {
            "single_dimension_checks": [],
            "stacking_risks": [],
            "criticality": "PLANNING",
            "ai_reasoning": "",
        }),
        "dispositions": [],
        "action_tracker_ref": None,
        "tq_ref": None,
        "dnv_submittal_required": body.get("dnv_submittal_required", False),
        "tags": body.get("tags", []),
        "last_updated": now,
    }
    findings.append(finding)
    _save_findings(findings)
    return jsonify(finding), 201


@experience_bp.route("/api/experience/findings", methods=["GET"])
def list_findings():
    findings = _load_findings()
    summary = _compute_summary(findings)
    return jsonify({"findings": findings, "summary": summary})


@experience_bp.route("/api/experience/findings/<finding_id>", methods=["GET"])
def get_finding(finding_id: str):
    findings = _load_findings()
    for f in findings:
        if f.get("finding_id") == finding_id:
            return jsonify(f)
    abort(404)


@experience_bp.route("/api/experience/findings/<finding_id>", methods=["PATCH"])
def update_finding(finding_id: str):
    body = request.get_json(force=True) or {}
    findings = _load_findings()
    for f in findings:
        if f.get("finding_id") == finding_id:
            protected = {"finding_id", "created_date", "dispositions",
                         "action_tracker_ref", "tq_ref"}
            for k, v in body.items():
                if k not in protected:
                    f[k] = v
            f["last_updated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_findings(findings)
            return jsonify(f)
    abort(404)


@experience_bp.route("/api/experience/findings/<finding_id>/dispositions", methods=["POST"])
def add_disposition(finding_id: str):
    body = request.get_json(force=True) or {}
    findings = _load_findings()
    for f in findings:
        if f.get("finding_id") == finding_id:
            all_disps = [d for fi in findings for d in fi.get("dispositions", [])]
            disp_id = _next_disp_id(all_disps)
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            disposition = {
                "disposition_id": disp_id,
                "type": body.get("type", "Procedural"),
                "description": body.get("description", ""),
                "what_it_does_not_resolve": body.get("what_it_does_not_resolve", ""),
                "residual_risk": body.get("residual_risk", ""),
                "new_conflicts_introduced": body.get("new_conflicts_introduced", None),
                "assignee": body.get("assignee", ""),
                "date_assigned": body.get("date_assigned", str(date.today())),
                "planned_closure_date": body.get("planned_closure_date", ""),
                "actual_closure_date": body.get("actual_closure_date", None),
                "status": body.get("status", "Open"),
                "completion_notes": body.get("completion_notes", None),
                "verified_by": body.get("verified_by", None),
                "verified_date": body.get("verified_date", None),
            }
            f.setdefault("dispositions", []).append(disposition)
            f["last_updated"] = now
            _save_findings(findings)
            return jsonify(f), 201
    abort(404)


@experience_bp.route(
    "/api/experience/findings/<finding_id>/dispositions/<disposition_id>",
    methods=["PATCH"]
)
def update_disposition(finding_id: str, disposition_id: str):
    body = request.get_json(force=True) or {}
    findings = _load_findings()
    for f in findings:
        if f.get("finding_id") == finding_id:
            for d in f.get("dispositions", []):
                if d.get("disposition_id") == disposition_id:
                    protected = {"disposition_id"}
                    for k, v in body.items():
                        if k not in protected:
                            d[k] = v
                    f["last_updated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    _save_findings(findings)
                    return jsonify(f)
            abort(404)
    abort(404)


@experience_bp.route("/api/experience/findings/<finding_id>/promote", methods=["POST"])
def promote_to_action_tracker(finding_id: str):
    body = request.get_json(force=True) or {}
    owner = body.get("owner", "")
    due_date = body.get("due_date", "")
    if not owner or not due_date:
        return jsonify({"error": "owner and due_date are required"}), 400

    findings = _load_findings()
    target = None
    for f in findings:
        if f.get("finding_id") == finding_id:
            target = f
            break
    if target is None:
        abort(404)

    action_id = _next_act_id()
    today = str(date.today())
    row = {
        "ActionID": action_id,
        "Title": target.get("title", "")[:200],
        "Owner": owner,
        "DueDate": due_date,
        "Status": "Open",
        "RAGStatus": "GREEN",
        "LastUpdated": today,
        "Category": "Experience-Conflict",
        "Notes": f"Promoted from {finding_id}",
    }

    p = _action_tracker_path()
    fieldnames = ["ActionID", "Title", "Owner", "DueDate", "Status",
                  "RAGStatus", "LastUpdated", "Category", "Notes"]
    file_exists = p.exists()
    with p.open("a", newline="", encoding="utf-8") as csvf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    target["action_tracker_ref"] = action_id
    target["last_updated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if target.get("status") == "Open":
        target["status"] = "Assigned"
    _save_findings(findings)

    return jsonify({"action_id": action_id, "finding": target})


@experience_bp.route("/api/experience/findings/<finding_id>/flag-tq", methods=["POST"])
def flag_tq(finding_id: str):
    body = request.get_json(force=True) or {}
    subject = body.get("subject", "")
    response_owner = body.get("response_owner", "")
    if not subject:
        return jsonify({"error": "subject is required"}), 400

    findings = _load_findings()
    target = None
    for f in findings:
        if f.get("finding_id") == finding_id:
            target = f
            break
    if target is None:
        abort(404)

    tq_id = _next_tq_id()
    today = str(date.today())
    row = {
        "TQID": tq_id,
        "Subject": subject,
        "OriginatingReviewer": "Experience-Conflict-Module",
        "SourceDocumentNumber": finding_id,
        "DateOpened": today,
        "DateResponded": "",
        "Status": "Open",
        "ResponseOwner": response_owner,
        "EscalationTier": "P3",
        "Notes": f"TQ raised from finding {finding_id}",
    }

    p = _tq_log_path()
    fieldnames = ["TQID", "Subject", "OriginatingReviewer", "SourceDocumentNumber",
                  "DateOpened", "DateResponded", "Status", "ResponseOwner",
                  "EscalationTier", "Notes"]
    file_exists = p.exists()
    with p.open("a", newline="", encoding="utf-8") as csvf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    target["tq_ref"] = tq_id
    target["last_updated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_findings(findings)

    return jsonify({"tq_id": tq_id, "finding": target})


@experience_bp.route("/api/experience/summary", methods=["GET"])
def summary():
    findings = _load_findings()
    return jsonify(_compute_summary(findings))


@experience_bp.route("/api/experience/generate-usecases", methods=["POST"])
def generate_usecases():
    body = request.get_json(force=True) or {}
    category = body.get("category", "").strip()
    if not category:
        return jsonify({"error": "category is required"}), 400

    constraints = _load_constraints()
    user_msg = json.dumps({
        "constraints": constraints,
        "task": "generate_use_cases",
        "category": category,
        "response_schema": {
            "use_cases": [
                {
                    "title": "string",
                    "description": "string",
                    "implied_constraints": ["list of constraint IDs"],
                    "risk_level": "HIGH|MEDIUM|LOW",
                    "notes": "string"
                }
            ]
        }
    }, ensure_ascii=False)

    try:
        raw = _call_claude(_SYSTEM_PROMPT, user_msg)
        result = json.loads(raw)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Claude returned non-JSON response", "raw": raw}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


@experience_bp.route("/api/experience/stress-test", methods=["POST"])
def stress_test():
    body = request.get_json(force=True) or {}
    scenario = body.get("scenario", "").strip()
    if not scenario:
        return jsonify({"error": "scenario is required"}), 400

    constraints = _load_constraints()
    user_msg = json.dumps({
        "constraints": constraints,
        "task": "stress_test",
        "scenario": scenario,
        "response_schema": {
            "conflict_register": [
                {
                    "constraint_id": "string",
                    "constraint_name": "string",
                    "classification": "HARD_BLOCK|SOFT_CONFLICT|COMPATIBLE_WITH_MARGIN|COMPATIBLE_AT_LIMIT",
                    "explanation": "string"
                }
            ],
            "stacking_map": [
                {
                    "primary_conflict": "string",
                    "stacked_with": ["list of constraint IDs"],
                    "combined_risk": "string"
                }
            ],
            "critical_path": ["ordered list of failure modes strings"],
            "mitigation_register": [
                {
                    "mitigation": "string",
                    "addresses": ["constraint IDs"],
                    "residual_risk": "string"
                }
            ],
            "overall_viability": "VIABLE|CONDITIONAL|NOT_VIABLE",
            "summary": "string"
        }
    }, ensure_ascii=False)

    try:
        raw = _call_claude(_SYSTEM_PROMPT, user_msg)
        result = json.loads(raw)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Claude returned non-JSON response", "raw": raw}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


@experience_bp.route("/api/experience/report-link", methods=["GET"])
def report_link():
    token = _get_or_create_token()
    host = request.host_url.rstrip("/")
    url = f"{host}/experience/report/{token}"
    return jsonify({"url": url, "token": token})


# ---------------------------------------------------------------------------
# Report page (read-only, token-gated)
# ---------------------------------------------------------------------------

@experience_bp.route("/experience/report/<token>")
def report_page(token: str):
    expected = _get_or_create_token()
    if token != expected:
        abort(403)
    findings = _load_findings()
    summary = _compute_summary(findings)
    return render_template(
        "experience_report.html",
        findings=findings,
        summary=summary,
        token=token,
        today=str(date.today()),
    )


# ---------------------------------------------------------------------------
# Design Signal routes
# ---------------------------------------------------------------------------

def _next_ds_id(signals: list) -> str:
    nums = [int(s["signal_id"][3:]) for s in signals
            if s.get("signal_id", "").startswith("DS-")
            and s["signal_id"][3:].isdigit()]
    return f"DS-{(max(nums) + 1 if nums else 1):03d}"


@experience_bp.route("/api/experience/design-signals", methods=["GET"])
def list_design_signals():
    signals  = _load_signals()
    findings = _load_findings()
    clusters = _build_constraint_clusters(findings)
    covered  = _covered_cluster_keys(signals)
    pending  = any(k not in covered for k in clusters)
    open_cnt = sum(1 for s in signals if s.get("status") != "Closed")
    return jsonify({
        "signals": signals,
        "total": len(signals),
        "open_count": open_cnt,
        "pending_signal_review": pending,
    })


@experience_bp.route("/api/experience/design-signals/compute", methods=["POST"])
def compute_design_signals():
    findings    = _load_findings()
    signals     = _load_signals()
    clusters    = _build_constraint_clusters(findings)
    covered     = _covered_cluster_keys(signals)
    new_signals: list = []
    errors:      list = []

    for cluster_key, cluster in clusters.items():
        if cluster_key in covered:
            continue

        contributing = [f for f in findings if f.get("finding_id") in cluster["finding_ids"]]

        if cluster["type"] == "dimension":
            con_ids: set = set()
            for f in contributing:
                for c in f.get("conflict_analysis", {}).get("single_dimension_checks", []):
                    if c.get("classification") in _BLOCKING and c.get("constraint_id"):
                        con_ids.add(c["constraint_id"])
            cluster["constraint_ids"] = list(con_ids)

        findings_summary = [
            {
                "finding_id":   f.get("finding_id"),
                "title":        f.get("title"),
                "dimensions_affected": f.get("dimensions_affected", []),
                "criticality":  (f.get("conflict_analysis") or {}).get("criticality"),
                "stacking_risks": (f.get("conflict_analysis") or {}).get("stacking_risks", []),
                "relevant_constraints": [
                    c for c in (f.get("conflict_analysis") or {}).get("single_dimension_checks", [])
                    if c.get("classification") in _BLOCKING
                ],
            }
            for f in contributing
        ]

        user_msg = json.dumps({
            "task": "synthesize_design_signal",
            "cluster_type":  cluster["type"],
            "cluster_key":   cluster["key"],
            "cluster_name":  cluster["name"],
            "affected_constraints": cluster["constraint_ids"],
            "contributing_findings": findings_summary,
            "response_schema": {
                "title": "short descriptive name for the design signal (max 80 chars)",
                "signal_type": "DesignGap|CapacityLimit|SinglePointOfFailure|LatentRisk",
                "description": "2-3 sentence description of what the pattern shows",
                "engineering_implication": (
                    "what a design engineer needs to know — what must be evaluated or changed"
                ),
                "recommended_action": "DesignReview|FEA|TestRequired|ConstraintRevision",
                "dnv_submittal_required": "boolean true or false",
            },
        }, ensure_ascii=False)

        try:
            raw       = _call_claude(_DS_SYSTEM_PROMPT, user_msg)
            synthesis = json.loads(raw)
        except Exception as e:
            errors.append({"cluster_key": cluster_key, "error": str(e)})
            continue

        now    = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        sig_id = _next_ds_id(signals + new_signals)
        signal = {
            "signal_id":             sig_id,
            "created_date":          str(date.today()),
            "status":                "Open",
            "_cluster_key":          cluster_key,
            "title":                 synthesis.get("title", f"Design Signal — {cluster['name']}"),
            "description":           synthesis.get("description", ""),
            "signal_type":           synthesis.get("signal_type", "DesignGap"),
            "affected_constraints":  cluster["constraint_ids"],
            "contributing_findings": cluster["finding_ids"],
            "trigger_threshold":     (
                f"{len(cluster['finding_ids'])} findings on "
                f"{'constraint ' + cluster['key'] if cluster['type'] == 'constraint' else 'dimension ' + cluster['key']}"
            ),
            "engineering_implication": synthesis.get("engineering_implication", ""),
            "recommended_action":    synthesis.get("recommended_action", "DesignReview"),
            "assigned_to":           "",
            "target_date":           "",
            "dnv_submittal_required": bool(synthesis.get("dnv_submittal_required", False)),
            "tq_ref":                None,
            "last_updated":          now,
        }
        new_signals.append(signal)

    signals.extend(new_signals)
    _save_signals(signals)
    return jsonify({"signals": signals, "new_count": len(new_signals), "errors": errors})


@experience_bp.route("/api/experience/design-signals/<signal_id>", methods=["PATCH"])
def update_signal(signal_id: str):
    body    = request.get_json(force=True) or {}
    signals = _load_signals()
    for s in signals:
        if s.get("signal_id") == signal_id:
            protected = {"signal_id", "created_date", "_cluster_key",
                         "contributing_findings", "affected_constraints"}
            for k, v in body.items():
                if k not in protected:
                    s[k] = v
            s["last_updated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_signals(signals)
            return jsonify(s)
    abort(404)


@experience_bp.route("/api/experience/design-signals/<signal_id>/flag-tq", methods=["POST"])
def flag_signal_tq(signal_id: str):
    body    = request.get_json(force=True) or {}
    subject = body.get("subject", "")
    if not subject:
        return jsonify({"error": "subject is required"}), 400

    signals = _load_signals()
    target  = next((s for s in signals if s.get("signal_id") == signal_id), None)
    if target is None:
        abort(404)

    tq_id = _next_tq_id()
    today = str(date.today())
    row   = {
        "TQID": tq_id,
        "Subject": subject,
        "OriginatingReviewer": "Design-Signal-Layer",
        "SourceDocumentNumber": signal_id,
        "DateOpened": today,
        "DateResponded": "",
        "Status": "Open",
        "ResponseOwner": body.get("response_owner", ""),
        "EscalationTier": "P2",
        "Notes": f"TQ raised from design signal {signal_id}",
    }
    p          = _tq_log_path()
    fieldnames = ["TQID", "Subject", "OriginatingReviewer", "SourceDocumentNumber",
                  "DateOpened", "DateResponded", "Status", "ResponseOwner",
                  "EscalationTier", "Notes"]
    file_exists = p.exists()
    with p.open("a", newline="", encoding="utf-8") as csvf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    target["tq_ref"]      = tq_id
    target["last_updated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_signals(signals)
    return jsonify({"tq_id": tq_id, "signal": target})


# ---------------------------------------------------------------------------
# Module UI page
# ---------------------------------------------------------------------------

@experience_bp.route("/experience")
def experience_page():
    return render_template("experience_module.html")
