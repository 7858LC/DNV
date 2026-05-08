"""
Agent 0 — Orchestrator

Usage:
  python orchestrator.py               # daily mode
  python orchestrator.py --mode weekly # weekly mode (also runs Agent 5)
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import traceback
from datetime import datetime, date
from pathlib import Path

import pandas as pd

from utils import load_config, get_run_date, resolve_path, ensure_dirs
from agent_intake import AgentIntake
from agent_tracker import AgentTracker
from agent_audit import AgentAudit
from agent_tq import AgentTQ
from agent_dashboard import AgentDashboard


def _load_csvs(cfg: dict) -> dict:
    data_dir = resolve_path(cfg["data_dir"])
    files = cfg["csv_files"]
    return {
        "submissions": pd.read_csv(data_dir / files["submissions"]),
        "action_tracker": pd.read_csv(data_dir / files["action_tracker"]),
        "tq_log": pd.read_csv(data_dir / files["tq_log"]),
        "audit_definitions": pd.read_csv(data_dir / files["audit_definitions"]),
    }


def _write_back_mutations(cfg: dict, agent_outputs: dict):
    """Write agent-computed fields back to source CSVs."""
    data_dir = resolve_path(cfg["data_dir"])
    files = cfg["csv_files"]

    intake_out = agent_outputs.get("agent_intake", {})
    tracker_out = agent_outputs.get("agent_tracker", {})
    tq_out = agent_outputs.get("agent_tq", {})

    # Submissions — routing & hold status
    if "_mutated_submissions" in intake_out:
        df: pd.DataFrame = intake_out["_mutated_submissions"]
        cols = ["DocumentNumber", "DocumentTitle", "Revision", "DocumentType",
                "SubmittingEngineer", "SubmittedDate", "Status", "DNVDisciplineQueue", "Notes"]
        df[cols].to_csv(data_dir / files["submissions"], index=False)

    # Action tracker — RAGStatus
    if "_mutated_tracker" in tracker_out:
        df = tracker_out["_mutated_tracker"]
        cols = ["ActionID", "Title", "Owner", "DueDate", "Status", "RAGStatus",
                "LastUpdated", "Category", "Notes"]
        df[cols].to_csv(data_dir / files["action_tracker"], index=False)

    # TQ log — EscalationTier
    if "_mutated_tq" in tq_out:
        df = tq_out["_mutated_tq"]
        cols = ["TQID", "Subject", "OriginatingReviewer", "SourceDocumentNumber",
                "DateOpened", "DateResponded", "Status", "ResponseOwner", "EscalationTier", "Notes"]
        df[cols].to_csv(data_dir / files["tq_log"], index=False)


def _clean_for_json(obj):
    """Recursively make obj JSON-serialisable (remove internal _keys, handle dates)."""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items() if not k.startswith("_mutated")}
    if isinstance(obj, list):
        return [_clean_for_json(i) for i in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, float):
        import math
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


def run_pipeline(mode: str = "daily") -> dict:
    start_ts = time.time()
    cfg = load_config()
    ensure_dirs()
    run_date = get_run_date()

    print(f"\n{'='*60}")
    print(f"  DNV BASTION COORDINATOR — Pipeline Run")
    print(f"  Date: {run_date}   Mode: {mode.upper()}")
    print(f"{'='*60}")

    # Load CSVs
    try:
        data = _load_csvs(cfg)
        print(f"  [OK] CSV data loaded — {sum(len(v) for v in data.values())} total rows")
    except Exception as e:
        print(f"  [ERROR] Failed to load CSVs: {e}")
        raise

    agent_outputs: dict = {}
    agents = [
        ("agent_intake", AgentIntake()),
        ("agent_tracker", AgentTracker()),
        ("agent_audit", AgentAudit()),
        ("agent_tq", AgentTQ()),
    ]

    for key, agent in agents:
        t0 = time.time()
        try:
            result = agent.run(data)
            agent_outputs[key] = result
            elapsed = time.time() - t0
            status = result.get("status", "OK")
            print(f"  [{'OK' if status == 'OK' else 'WARN'}] {agent.name} — {elapsed:.2f}s  status={status}")
        except Exception as e:
            elapsed = time.time() - t0
            tb = traceback.format_exc()
            agent_outputs[key] = {"status": "ERROR", "message": str(e), "traceback": tb}
            print(f"  [ERROR] {agent.name} — {elapsed:.2f}s\n    {e}")

    # Write CSV mutations
    try:
        _write_back_mutations(cfg, agent_outputs)
        print(f"  [OK] CSV write-back complete")
    except Exception as e:
        print(f"  [WARN] CSV write-back failed: {e}")

    # Agent 5 — weekly only
    if mode == "weekly":
        data["computed_state"] = agent_outputs
        t0 = time.time()
        try:
            dash = AgentDashboard()
            result = dash.run(data)
            agent_outputs["agent_dashboard"] = result
            elapsed = time.time() - t0
            print(f"  [OK] {dash.name} — {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - t0
            agent_outputs["agent_dashboard"] = {"status": "ERROR", "message": str(e)}
            print(f"  [ERROR] Agent 5 — {elapsed:.2f}s\n    {e}")

    # Compute overall program RAG for state
    tq_out = agent_outputs.get("agent_tq", {})
    tracker_out = agent_outputs.get("agent_tracker", {})
    audit_out = agent_outputs.get("agent_audit", {})
    dash_out = agent_outputs.get("agent_dashboard", {})

    if dash_out.get("program_rag"):
        program_rag = dash_out["program_rag"]
    else:
        # Compute inline for daily mode
        program_rag = "GREEN"
        if (tq_out.get("p1_count", 0) > 0 or
                audit_out.get("alert_count", 0) > 0 or
                tracker_out.get("red_count", 0) > 0):
            program_rag = "RED"
        elif (tq_out.get("p2_count", 0) > 0 or
              tracker_out.get("amber_count", 0) > 0):
            program_rag = "AMBER"

    computed_state = {
        "run_date": str(run_date),
        "run_timestamp": datetime.now().isoformat(),
        "mode": mode,
        "program_rag": program_rag,
        "week_number": run_date.isocalendar()[1],
        "data_counts": {k: len(v) for k, v in data.items() if isinstance(v, pd.DataFrame)},
        **{k: v for k, v in agent_outputs.items()},
    }

    # Write computed state
    state_dir = resolve_path(cfg["state_dir"])
    state_path = state_dir / "computed_state.json"
    clean_state = _clean_for_json(computed_state)
    state_path.write_text(json.dumps(clean_state, indent=2), encoding="utf-8")
    print(f"  [OK] State written -> {state_path}")

    # Append session log
    total_elapsed = time.time() - start_ts
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "run_date": str(run_date),
        "mode": mode,
        "program_rag": program_rag,
        "agents": {k: v.get("status", "?") for k, v in agent_outputs.items()},
        "elapsed_s": round(total_elapsed, 2),
    }
    log_path = resolve_path(cfg["logs_dir"]) / "session_log.json"
    existing = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
        except Exception:
            existing = []
    existing.append(log_entry)
    log_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    print(f"\n  Total: {total_elapsed:.2f}s   Program RAG: {program_rag}")
    print(f"{'='*60}\n")

    return clean_state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DNV Bastion Coordinator Pipeline")
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    args = parser.parse_args()
    run_pipeline(mode=args.mode)
