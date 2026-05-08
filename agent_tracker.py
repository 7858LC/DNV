"""
Agent 2 - Action Tracker
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

from utils import load_config, get_run_date, to_date, business_days_between, resolve_path


class AgentTracker:
    name = "Agent 2 - Action Tracker"

    def run(self, data: dict) -> dict:
        cfg = load_config()
        run_date = get_run_date()
        amber_threshold = cfg.get("amber_threshold", 5)
        stale_threshold = cfg.get("stale_threshold", 7)

        df = data["action_tracker"].copy()
        df["DueDate"] = pd.to_datetime(df["DueDate"], errors="coerce").dt.date
        df["LastUpdated"] = pd.to_datetime(df["LastUpdated"], errors="coerce").dt.date
        df["Status"] = df["Status"].fillna("Open").str.strip()

        # --- Compute RAGStatus ---
        def compute_rag(row) -> str:
            status = str(row.get("Status", "")).strip()
            if status == "Closed":
                return "CLOSED"
            due = to_date(row.get("DueDate"))
            if due is None:
                return "GREEN"
            days_until = business_days_between(run_date, due)  # positive = future
            if due < run_date:
                return "RED"
            if days_until <= amber_threshold:
                return "AMBER"
            return "GREEN"

        def is_stale(row) -> bool:
            status = str(row.get("Status", "")).strip()
            if status == "Closed":
                return False
            last = to_date(row.get("LastUpdated"))
            if last is None:
                return True
            return business_days_between(last, run_date) > stale_threshold

        df["RAGStatus"] = df.apply(compute_rag, axis=1)
        df["_stale"] = df.apply(is_stale, axis=1)
        df["_days_until_due"] = df["DueDate"].apply(
            lambda d: business_days_between(run_date, d) if d else None
        )

        # --- Load previous snapshot for delta ---
        snapshot_path = resolve_path(cfg["state_dir"]) / "tracker_snapshot.json"
        prev_snapshot: dict[str, str] = {}
        if snapshot_path.exists():
            try:
                prev_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except Exception:
                prev_snapshot = {}

        # --- Compute delta ---
        delta = []
        for _, row in df.iterrows():
            aid = str(row["ActionID"])
            current_rag = row["RAGStatus"]
            previous_rag = prev_snapshot.get(aid)
            if previous_rag and previous_rag != current_rag:
                delta.append({
                    "ActionID": aid,
                    "Title": str(row.get("Title", "")),
                    "previous_rag": previous_rag,
                    "current_rag": current_rag,
                })

        # --- Save new snapshot ---
        new_snapshot = {str(r["ActionID"]): r["RAGStatus"] for _, r in df.iterrows()}
        snapshot_path.write_text(json.dumps(new_snapshot, indent=2), encoding="utf-8")

        def to_output_list(frame: pd.DataFrame) -> list[dict]:
            out = []
            for _, r in frame.iterrows():
                d = r.to_dict()
                d["DueDate"] = str(d["DueDate"]) if d.get("DueDate") else ""
                d["LastUpdated"] = str(d["LastUpdated"]) if d.get("LastUpdated") else ""
                d["_days_until_due"] = int(d["_days_until_due"]) if d.get("_days_until_due") is not None else None
                d.pop("_stale", None)
                out.append(d)
            return out

        red_df = df[df["RAGStatus"] == "RED"]
        amber_df = df[df["RAGStatus"] == "AMBER"]
        green_df = df[df["RAGStatus"] == "GREEN"]
        closed_df = df[df["RAGStatus"] == "CLOSED"]
        stale_df = df[df["_stale"]]

        return {
            "status": "OK",
            "red_count": len(red_df),
            "amber_count": len(amber_df),
            "green_count": len(green_df),
            "closed_count": len(closed_df),
            "stale_count": len(stale_df),
            "red_items": to_output_list(red_df),
            "amber_items": to_output_list(amber_df),
            "green_items": to_output_list(green_df),
            "stale_items": to_output_list(stale_df),
            "delta": delta,
            # mutated df for write-back
            "_mutated_tracker": df,
        }
