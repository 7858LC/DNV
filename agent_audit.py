"""
Agent 3 - Audit Readiness
"""
from __future__ import annotations

import pandas as pd

from utils import load_config, get_run_date, to_date, business_days_between


class AgentAudit:
    name = "Agent 3 - Audit Readiness"

    def run(self, data: dict) -> dict:
        cfg = load_config()
        run_date = get_run_date()
        readiness_threshold = cfg.get("readiness_threshold", 85)
        alert_days = 10

        audits_df = data["audit_definitions"].copy()
        subs_df = data["submissions"].copy()

        audits_df["AuditDate"] = pd.to_datetime(audits_df["AuditDate"], errors="coerce").dt.date
        audits_df["Status"] = audits_df["Status"].fillna("").str.strip()

        # Build lookup: DocumentNumber -> Status
        subs_df["Status"] = subs_df["Status"].fillna("").str.strip()
        # For re-subs, take the highest revision per DocNumber
        subs_df["Revision"] = subs_df["Revision"].fillna("A").astype(str)
        subs_df = subs_df.sort_values("Revision")
        doc_status: dict[str, str] = (
            subs_df.drop_duplicates("DocumentNumber", keep="last")
            .set_index("DocumentNumber")["Status"]
            .to_dict()
        )

        def evidence_status(doc_num: str) -> str:
            status = doc_status.get(doc_num.strip(), None)
            if status is None:
                return "MISSING"
            if status == "Accepted":
                return "IN-HAND"
            if status in ("Under Review", "New"):
                return "IN-REVIEW"
            return "MISSING"

        def readiness_label(score: int) -> str:
            if score >= 85:
                return "Green"
            if score >= 60:
                return "Amber"
            return "Red"

        audit_outputs = []
        alert_count = 0

        for _, row in audits_df.iterrows():
            status = str(row.get("Status", "")).strip()
            audit_date = to_date(row.get("AuditDate"))
            audit_id = str(row.get("AuditID", ""))
            audit_name = str(row.get("AuditName", ""))

            if status in ("Complete", "Cancelled"):
                audit_outputs.append({
                    "AuditID": audit_id,
                    "AuditName": audit_name,
                    "AuditDate": str(audit_date) if audit_date else "",
                    "Status": status,
                    "ReadinessScore": int(row.get("ReadinessScore", 0) or 0),
                    "ReadinessStatus": str(row.get("ReadinessStatus", "")),
                    "evidence_breakdown": [],
                    "checklist": [],
                    "alert_flag": False,
                    "days_to_audit": None,
                })
                continue

            raw_docs = str(row.get("RequiredEvidenceDocNumbers", "") or "")
            required_docs = [d.strip() for d in raw_docs.split("|") if d.strip()]

            checklist = []
            in_hand = 0
            in_review = 0
            missing = 0
            for doc in required_docs:
                ev = evidence_status(doc)
                checklist.append({"doc": doc, "status": ev})
                if ev == "IN-HAND":
                    in_hand += 1
                elif ev == "IN-REVIEW":
                    in_review += 1
                else:
                    missing += 1

            total = len(required_docs)
            score = int(round((in_hand / total * 100) if total > 0 else 0))

            days_to_audit = None
            alert_flag = False
            if audit_date:
                days_to_audit = business_days_between(run_date, audit_date)
                if days_to_audit <= alert_days and score < readiness_threshold:
                    alert_flag = True
                    alert_count += 1

            audit_outputs.append({
                "AuditID": audit_id,
                "AuditName": audit_name,
                "AuditDate": str(audit_date) if audit_date else "",
                "Status": status,
                "ReadinessScore": score,
                "ReadinessStatus": readiness_label(score),
                "evidence_breakdown": {
                    "in_hand": in_hand,
                    "in_review": in_review,
                    "missing": missing,
                    "total": total,
                },
                "checklist": checklist,
                "alert_flag": alert_flag,
                "days_to_audit": days_to_audit,
            })

        return {
            "status": "OK",
            "audits": audit_outputs,
            "alert_count": alert_count,
        }
