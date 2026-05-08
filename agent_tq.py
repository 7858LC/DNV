"""
Agent 4 - TQ Log Manager
"""
from __future__ import annotations
from datetime import timedelta

import pandas as pd

from utils import load_config, get_run_date, to_date, business_days_between


class AgentTQ:
    name = "Agent 4 - TQ Log Manager"

    def run(self, data: dict) -> dict:
        cfg = load_config()
        run_date = get_run_date()
        tq_sla_days = cfg.get("tq_sla_days", 10)
        critical_path_docs = set(cfg.get("critical_path_docs", []))

        df = data["tq_log"].copy()
        df["DateOpened"] = pd.to_datetime(df["DateOpened"], errors="coerce").dt.date
        df["DateResponded"] = pd.to_datetime(df["DateResponded"], errors="coerce").dt.date
        df["Status"] = df["Status"].fillna("Open").str.strip()
        df["ResponseOwner"] = df["ResponseOwner"].fillna("").str.strip()
        df["SourceDocumentNumber"] = df["SourceDocumentNumber"].fillna("").str.strip()

        def assign_tier(row) -> str:
            status = str(row.get("Status", "")).strip()
            if status == "Closed":
                return ""
            date_opened = to_date(row.get("DateOpened"))
            sla_days = business_days_between(date_opened, run_date) if date_opened else 0
            sla_breached = sla_days > tq_sla_days
            unassigned = not row.get("ResponseOwner", "").strip()
            cp = row.get("SourceDocumentNumber", "").strip() in critical_path_docs
            if cp and sla_breached:
                return "P1"
            if sla_breached and not cp:
                return "P2"
            if unassigned and not sla_breached:
                return "P3"
            return "P4"

        df["EscalationTier"] = df.apply(assign_tier, axis=1)
        df["_sla_days"] = df.apply(
            lambda r: business_days_between(to_date(r.get("DateOpened")), run_date)
            if to_date(r.get("DateOpened")) else 0, axis=1
        )

        open_df = df[df["Status"] != "Closed"]
        avg_days_open = float(open_df["_sla_days"].mean()) if len(open_df) > 0 else 0.0

        window_start = run_date - timedelta(days=7)
        closed_this_week = int(
            ((df["DateResponded"] >= window_start) & (df["Status"].isin(["Closed", "Responded"]))).sum()
        )

        def to_list(frame: pd.DataFrame) -> list[dict]:
            out = []
            for _, r in frame.iterrows():
                d = r.to_dict()
                d["DateOpened"] = str(d["DateOpened"]) if d.get("DateOpened") else ""
                d["DateResponded"] = str(d["DateResponded"]) if d.get("DateResponded") else ""
                d["_sla_days"] = int(d.get("_sla_days", 0))
                out.append(d)
            return out

        p1 = df[df["EscalationTier"] == "P1"]
        p2 = df[df["EscalationTier"] == "P2"]
        p3 = df[df["EscalationTier"] == "P3"]
        p4 = df[df["EscalationTier"] == "P4"]

        return {
            "status": "OK",
            "p1_items": to_list(p1),
            "p2_items": to_list(p2),
            "p3_items": to_list(p3),
            "p4_items": to_list(p4),
            "p1_count": len(p1),
            "p2_count": len(p2),
            "p3_count": len(p3),
            "p4_count": len(p4),
            "avg_days_open": round(avg_days_open, 1),
            "closed_this_week_count": closed_this_week,
            "total_open": len(open_df),
            # mutated df for write-back
            "_mutated_tq": df,
        }
