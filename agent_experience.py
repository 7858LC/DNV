"""
Agent Experience — Experience Conflict Module summary agent.
Follows the same pattern as AgentTracker and AgentAudit.
Called optionally by orchestrator for computed_state integration.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from utils import load_config, resolve_path


class AgentExperience:
    name = "Agent Experience - Conflict Module"

    def run(self, data: dict) -> dict:  # noqa: ARG002
        cfg = load_config()
        findings_path = resolve_path(cfg["data_dir"]) / "experience_findings.json"

        if not findings_path.exists():
            return {
                "status": "NO_DATA",
                "total_findings": 0,
                "open_count": 0,
                "critical_count": 0,
                "overdue_dispositions_count": 0,
            }

        try:
            findings: list = json.loads(findings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)}

        today_str = str(date.today())
        total = len(findings)
        open_count = sum(1 for f in findings if f.get("status") == "Open")
        critical_count = sum(
            1 for f in findings
            if f.get("conflict_analysis", {}).get("criticality") == "CRITICAL"
        )
        overdue_count = 0
        for f in findings:
            for d in f.get("dispositions", []):
                if d.get("status") != "Closed":
                    pcd = d.get("planned_closure_date", "")
                    if pcd and pcd < today_str:
                        overdue_count += 1

        return {
            "status": "OK",
            "total_findings": total,
            "open_count": open_count,
            "critical_count": critical_count,
            "overdue_dispositions_count": overdue_count,
        }
