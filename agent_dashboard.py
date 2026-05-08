"""
Agent 5 - Weekly Dashboard Generator (--mode weekly only)
"""
from __future__ import annotations
import json
from datetime import date
from pathlib import Path

from utils import load_config, get_run_date, resolve_path


class AgentDashboard:
    name = "Agent 5 - Weekly Dashboard Generator"

    def run(self, data: dict) -> dict:
        cfg = load_config()
        run_date = get_run_date()
        state = data.get("computed_state", {})

        intake = state.get("agent_intake", {})
        tracker = state.get("agent_tracker", {})
        audit = state.get("agent_audit", {})
        tq = state.get("agent_tq", {})

        # --- Overall program RAG ---
        rag = "GREEN"
        rag_reasons: list[str] = []

        if tq.get("p1_count", 0) > 0:
            rag = "RED"
            rag_reasons.append(f"{tq['p1_count']} P1 TQ escalation(s)")
        if audit.get("alert_count", 0) > 0:
            rag = "RED"
            rag_reasons.append(f"{audit['alert_count']} audit readiness alert(s)")
        if tracker.get("red_count", 0) > 0:
            rag = "RED"
            rag_reasons.append(f"{tracker['red_count']} overdue action(s)")

        if rag != "RED":
            if tq.get("p2_count", 0) > 0:
                rag = "AMBER"
                rag_reasons.append(f"{tq['p2_count']} P2 TQ escalation(s)")
            if tracker.get("amber_count", 0) > 0:
                rag = "AMBER"
                rag_reasons.append(f"{tracker['amber_count']} upcoming-deadline action(s)")
            any_low_readiness = any(
                a.get("ReadinessScore", 100) < 85
                for a in audit.get("audits", [])
                if a.get("Status") in ("Active", "Upcoming")
            )
            if any_low_readiness:
                rag = "AMBER"
                rag_reasons.append("audit(s) below 85% readiness")

        # --- Build top flags list ---
        top_flags: list[str] = []
        for r in rag_reasons:
            top_flags.append(r)
        if tracker.get("stale_count", 0) > 0:
            top_flags.append(f"{tracker['stale_count']} stale action item(s) with no recent update")
        if intake.get("hold_count", 0) > 0:
            top_flags.append(f"{intake['hold_count']} submission(s) on Intake-Hold")
        if intake.get("overdue_expected_count", 0) > 0:
            top_flags.append(f"{intake['overdue_expected_count']} expected submission(s) overdue")

        # --- Risk notes for coordinator ---
        risk_notes = _build_risk_notes(top_flags, intake, tracker, audit, tq, run_date)

        summary = {
            "run_date": str(run_date),
            "week_number": run_date.isocalendar()[1],
            "program_rag": rag,
            "rag_reasons": rag_reasons,
            "top_flags": top_flags,
            "risk_notes": risk_notes,
            "intake_summary": {
                "total": intake.get("total_submissions", 0),
                "new": intake.get("new_count", 0),
                "resubs": intake.get("resub_count", 0),
                "holds": intake.get("hold_count", 0),
                "overdue_expected": intake.get("overdue_expected_count", 0),
            },
            "tracker_summary": {
                "red": tracker.get("red_count", 0),
                "amber": tracker.get("amber_count", 0),
                "green": tracker.get("green_count", 0),
                "stale": tracker.get("stale_count", 0),
            },
            "tq_summary": {
                "p1": tq.get("p1_count", 0),
                "p2": tq.get("p2_count", 0),
                "p3": tq.get("p3_count", 0),
                "p4": tq.get("p4_count", 0),
                "avg_days_open": tq.get("avg_days_open", 0),
                "closed_this_week": tq.get("closed_this_week_count", 0),
            },
        }

        # --- Write outputs ---
        out_dir = resolve_path(cfg["outputs_dir"]) / str(run_date)
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / "weekly_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (out_dir / "weekly_report.md").write_text(_build_markdown_report(summary, audit, tracker, tq), encoding="utf-8")

        return {
            "status": "OK",
            "program_rag": rag,
            "rag_reasons": rag_reasons,
            "top_flags": top_flags,
            "risk_notes": risk_notes,
            "output_dir": str(out_dir),
        }


def _build_risk_notes(flags, intake, tracker, audit, tq, run_date) -> str:
    lines = [f"## Risk Summary - Week {run_date.isocalendar()[1]} ({run_date})", ""]
    if not flags:
        lines.append("No critical flags. Program tracking GREEN.")
    else:
        lines.append("### Top Flags")
        for f in flags:
            lines.append(f"- {f}")
    lines += ["", "### Action Required"]
    red_items = tracker.get("red_items", [])
    if red_items:
        lines.append("**Overdue Actions:**")
        for item in red_items:
            lines.append(f"  - {item.get('ActionID')}: {item.get('Title')} (Owner: {item.get('Owner')})")
    p1_items = tq.get("p1_items", [])
    if p1_items:
        lines.append("**P1 TQ Escalations (critical path + SLA breached):**")
        for item in p1_items:
            lines.append(f"  - {item.get('TQID')}: {item.get('Subject')} ({item.get('_sla_days')} days open)")
    return "\n".join(lines)


def _build_markdown_report(summary, audit_data, tracker_data, tq_data) -> str:
    run_date = summary["run_date"]
    wk = summary["week_number"]
    rag = summary["program_rag"]
    lines = [
        f"# DNV Bastion Coordinator - Weekly Report",
        f"**Run Date:** {run_date}  **Week:** {wk}  **Program Health:** {rag}",
        "",
        "---",
        "",
        "## 1. Submission Intake",
        f"- Total submissions in register: {summary['intake_summary']['total']}",
        f"- New (last 7 days): {summary['intake_summary']['new']}",
        f"- Re-submissions: {summary['intake_summary']['resubs']}",
        f"- On Intake-Hold: {summary['intake_summary']['holds']}",
        f"- Overdue Expected: {summary['intake_summary']['overdue_expected']}",
        "",
        "## 2. Action Tracker",
        f"- RED (overdue): {summary['tracker_summary']['red']}",
        f"- AMBER (due soon): {summary['tracker_summary']['amber']}",
        f"- GREEN (healthy): {summary['tracker_summary']['green']}",
        f"- Stale items: {summary['tracker_summary']['stale']}",
        "",
        "## 3. Audit Readiness",
    ]
    for a in audit_data.get("audits", []):
        if a["Status"] in ("Active", "Upcoming"):
            alert = " ⚠ ALERT" if a.get("alert_flag") else ""
            lines.append(
                f"- **{a['AuditName']}** ({a['AuditDate']}): "
                f"{a['ReadinessScore']}% ready [{a['ReadinessStatus']}]{alert}"
            )
    lines += [
        "",
        "## 4. TQ Escalations",
        f"- P1 (critical + breached): {summary['tq_summary']['p1']}",
        f"- P2 (breached): {summary['tq_summary']['p2']}",
        f"- P3 (unassigned): {summary['tq_summary']['p3']}",
        f"- P4 (open, within SLA): {summary['tq_summary']['p4']}",
        f"- Avg days open: {summary['tq_summary']['avg_days_open']}",
        f"- Closed this week: {summary['tq_summary']['closed_this_week']}",
        "",
        "## 5. Risk Notes",
        "",
        summary.get("risk_notes", ""),
        "",
        "---",
        f"*Generated automatically by DNV Bastion Coordinator - {run_date}*",
    ]
    return "\n".join(lines)
