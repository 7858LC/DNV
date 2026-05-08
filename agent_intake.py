"""
Agent 1 - Submission Intake & Routing
"""
from __future__ import annotations
from datetime import timedelta

import pandas as pd

from utils import load_config, get_run_date, to_date, business_days_between


class AgentIntake:
    name = "Agent 1 - Submission Intake & Routing"

    def run(self, data: dict) -> dict:
        cfg = load_config()
        run_date = get_run_date()
        df = data["submissions"].copy()

        # Normalise SubmittedDate
        df["SubmittedDate"] = pd.to_datetime(df["SubmittedDate"], errors="coerce").dt.date
        df["Revision"] = df["Revision"].fillna("A").astype(str).str.strip()
        df["Status"] = df["Status"].fillna("").str.strip()
        df["DNVDisciplineQueue"] = df["DNVDisciplineQueue"].fillna("").str.strip()

        routing = cfg.get("routing_table", {})
        required_fields = ["DocumentNumber", "DocumentTitle", "Revision",
                           "DocumentType", "SubmittingEngineer", "SubmittedDate"]

        mutations: list[dict] = []

        # --- Validate & auto-hold ---
        for idx, row in df.iterrows():
            missing = [f for f in required_fields if pd.isna(row.get(f)) or str(row.get(f, "")).strip() == ""]
            if missing and row["Status"] not in ("Accepted", "Rejected", "Closed"):
                df.at[idx, "Status"] = "Intake-Hold"
                df.at[idx, "Notes"] = (
                    str(row.get("Notes", "") or "") + f" [AUTO-HOLD: missing {', '.join(missing)}]"
                ).strip()

            # Apply routing where blank
            if not df.at[idx, "DNVDisciplineQueue"]:
                doc_type = str(row.get("DocumentType", "")).strip()
                df.at[idx, "DNVDisciplineQueue"] = routing.get(doc_type, "General")

        # --- Identify categories ---
        window_start = run_date - timedelta(days=7)

        # New submissions: submitted in last 7 days and not a re-sub (handled below)
        new_mask = (
            (df["SubmittedDate"] >= window_start) &
            (df["Status"].isin(["New", "Expected"]))
        )

        # Re-submissions: same DocumentNumber appearing more than once
        dup_docs = df[df.duplicated("DocumentNumber", keep=False)]["DocumentNumber"].unique()
        resub_rows = []
        for doc in dup_docs:
            group = df[df["DocumentNumber"] == doc].copy()
            # sort revisions lexicographically; latest is current
            group = group.sort_values("Revision")
            # all but the latest are prior revisions
            resub_rows.append(group.iloc[-1].to_dict())  # current (highest rev)

        resub_doc_numbers = {r["DocumentNumber"] for r in resub_rows}

        hold_mask = df["Status"] == "Intake-Hold"
        overdue_mask = (df["Status"] == "Expected") & (df["SubmittedDate"] < run_date)

        def rows_to_dicts(frame: pd.DataFrame) -> list[dict]:
            out = []
            for _, r in frame.iterrows():
                d = r.to_dict()
                d["SubmittedDate"] = str(d["SubmittedDate"]) if d["SubmittedDate"] else ""
                out.append(d)
            return out

        new_items = rows_to_dicts(df[new_mask & ~df["DocumentNumber"].isin(resub_doc_numbers)])
        hold_items = rows_to_dicts(df[hold_mask])
        overdue_items = rows_to_dicts(df[overdue_mask])

        return {
            "status": "OK",
            "new_count": int(new_mask.sum()),
            "resub_count": len(resub_rows),
            "hold_count": int(hold_mask.sum()),
            "overdue_expected_count": int(overdue_mask.sum()),
            "new_items": new_items,
            "resub_items": resub_rows,
            "hold_items": hold_items,
            "overdue_items": overdue_items,
            "total_submissions": len(df),
            # pass back mutated df for orchestrator CSV write-back
            "_mutated_submissions": df,
        }
