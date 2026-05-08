"""
DNV Coordinator — Sentinel 001 Seed Script
Backs up existing data, then replaces all four CSV tables with
programme data derived from BT3345_9001_009 and BT3345_9001_010.
"""
import sys, os, csv, shutil, json
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR   = r"C:\Users\lchas\DNV _System\data"
CONFIG_PATH = r"C:\Users\lchas\DNV _System\config.json"
BACKUP_DIR = os.path.join(r"C:\Users\lchas\DNV _System\_backups",
                          f"backup_{datetime.now().strftime('%Y-%m-%d_%H%M')}_sentinel_seed")

# ─── Backup ───────────────────────────────────────────────────────────────────
os.makedirs(BACKUP_DIR, exist_ok=True)
for fname in ["submissions.csv","action_tracker.csv","tq_log.csv","audit_definitions.csv"]:
    src = os.path.join(DATA_DIR, fname)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(BACKUP_DIR, fname))
        print(f"Backed up: {fname}")
shutil.copy2(CONFIG_PATH, os.path.join(BACKUP_DIR, "config.json"))
print(f"Backup written to: {BACKUP_DIR}\n")

def write_csv(filename, fieldnames, rows):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Written: {filename}  ({len(rows)} rows)")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. SUBMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════
SUB_FIELDS = ["DocumentNumber","DocumentTitle","Revision","DocumentType",
              "SubmittingEngineer","SubmittedDate","Status","DNVDisciplineQueue","Notes"]

submissions = [
    {
        "DocumentNumber":   "BT3345_9001_009",
        "DocumentTitle":    "Sentinel 001 DNV Compliance Map — DNV-RU-UWT Pt.5 Ch.10 (December 2024)",
        "Revision":         "00",
        "DocumentType":     "AIP",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-24",
        "Status":           "New",
        "DNVDisciplineQueue": "Structural",
        "Notes":            ("72 requirements mapped across 11 sections of Pt.5 Ch.10. "
                             "STATUS: 6 COMPLIANT | 5 GAP | 2 CONFLICT (BLOCKING) | "
                             "2 IN PROGRESS | 3 TBD | 1 N/A | 53 ASSUMED. "
                             "2 blocking conflicts (steel spec Row 3.3; battery capacity Row 6.3). "
                             "All 4 corrections applied. See BT3345_9001_010 for resolution actions."),
    },
    {
        "DocumentNumber":   "BT3345_9001_010",
        "DocumentTitle":    "Sentinel 001 SDD Correction List — Input to SDD-SENTINEL-001 Rev 1.1",
        "Revision":         "00 DRAFT",
        "DocumentType":     "OTHER",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-24",
        "Status":           "New",
        "DNVDisciplineQueue": "General",
        "Notes":            ("13 correction items across 3 priority tiers: 5 BLOCKING (4 conflict TBD + "
                             "1 life-safety OPEN) | 6 HIGH | 2 MEDIUM. "
                             "Internal document — not for DNV submittal until blocking conflicts resolved. "
                             "Authoritative input to SDD Rev 1.1 revision process."),
    },
    {
        "DocumentNumber":   "SDD-SENTINEL-001",
        "DocumentTitle":    "Sentinel 001 System Design Description",
        "Revision":         "1.0",
        "DocumentType":     "OTHER",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-24",
        "Status":           "Under Triage",
        "DNVDisciplineQueue": "Structural",
        "Notes":            ("Rev 1.0 Draft. 3 confirmed blocking conflicts vs RTM Rev E and PDP D000004318: "
                             "(1) Steel spec §3.2: SA-516 Gr.70 vs required A576 Gr.50; "
                             "(2) Battery capacity §4.8/§5.3: 40 kWh/80 hr vs required 60 kWh/120 hr; "
                             "(3) Operating pressure: 2.40 bar(a) vs programme baseline 2.38 bar(a). "
                             "Rev 1.1 required before DNV submittal. See BT3345_9001_010 for full correction list."),
    },
    {
        "DocumentNumber":   "RTM-SENT-001",
        "DocumentTitle":    "Sentinel 001 Requirements Traceability Matrix",
        "Revision":         "E",
        "DocumentType":     "OTHER",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-24",
        "Status":           "Under Triage",
        "DNVDisciplineQueue": "General",
        "Notes":            ("Rev E. 141 requirements across 17 columns. "
                             "DOCUMENT INTEGRITY ISSUE: cover page title cell reads "
                             "'Rev D | 13 February 2026' — revision detail row correctly states "
                             "Rev E dated 2026-03-20. Must be corrected before DNV submittal. "
                             "See BT3345_9001_010 Item 012. Action owner: Larry Chase."),
    },
    {
        "DocumentNumber":   "BTI-9001-020",
        "DocumentTitle":    "Crew Competency and Operational Safety Management Requirements for Mixed-Occupancy LIVHAB(SAT)",
        "Revision":         "-",
        "DocumentType":     "AIP",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-21",
        "Status":           "New",
        "DNVDisciplineQueue": "General",
        "Notes":            ("LIVHAB(SAT) classification under DNV-RU-UWT Pt.5 Ch.10. Mixed-occupancy model: "
                             "professional staff + scientific researchers + recreational diving customers. "
                             "4 questions raised for DNV adjudication: crew competency requirements, "
                             "AiP/construction approval conditions, HRA crediting of human-dependent FMECA mitigations, "
                             "and operational envelope scope of LIVHAB(SAT) notation. See TQ-SENT-006."),
    },
    {
        "DocumentNumber":   "FMECA-SENTINEL-001",
        "DocumentTitle":    "Sentinel 001 Failure Mode and Effects Criticality Analysis",
        "Revision":         "DRAFT",
        "DocumentType":     "FMECA",
        "SubmittingEngineer": "Ken Ngo",
        "SubmittedDate":    "2026-04-24",
        "Status":           "Expected",
        "DNVDisciplineQueue": "Safety",
        "Notes":            ("OI-07 OPEN. Structural tab coverage 3/10 — full revision required. "
                             "Dual analysis described as SHOULD not SHALL — must be corrected to SHALL. "
                             "FMECA is prerequisite for DNV plan approval. "
                             "See BT3345_9001_010 Item 008. Due before AiP submission. Action: Ken Ngo."),
    },
    {
        "DocumentNumber":   "PHA-SENTINEL-001",
        "DocumentTitle":    "Sentinel 001 Preliminary Hazard Analysis",
        "Revision":         "00",
        "DocumentType":     "HAZID",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-24",
        "Status":           "Expected",
        "DNVDisciplineQueue": "Safety",
        "Notes":            ("GAP — document not yet initiated. Referenced in SDD §1.2 but absent from "
                             "programme suite. DNV-RU-UWT Pt.5 Ch.10 Sec.1 [105] requires formal safety "
                             "assessment as design basis. Must cover all hazard categories before DNV submittal. "
                             "See BT3345_9001_009 Row 1.5, BT3345_9001_010 Item 006. Action: Larry Chase."),
    },
    {
        "DocumentNumber":   "PDP-D000004318",
        "DocumentTitle":    "Sentinel 001 Programme Design Philosophy",
        "Revision":         "CURRENT",
        "DocumentType":     "OTHER",
        "SubmittingEngineer": "Larry Chase",
        "SubmittedDate":    "2026-04-24",
        "Status":           "Under Review",
        "DNVDisciplineQueue": "Structural",
        "Notes":            ("Governing programme specification. §3.3.1 mandates A576 Gr.50 steel "
                             "(conflicts SDD §3.2 SA-516 Gr.70 — BT3345_9001_010 Item 001). "
                             "§5.2 mandates 60 kWh / 120 hr battery "
                             "(conflicts SDD §4.8/§5.3 40 kWh/80 hr — BT3345_9001_010 Item 002). "
                             "Programme baseline operating pressure 2.38 bar(a) "
                             "(conflicts SDD 2.40 bar(a) — BT3345_9001_010 Item 004)."),
    },
]

write_csv("submissions.csv", SUB_FIELDS, submissions)

# ═══════════════════════════════════════════════════════════════════════════════
# 2. ACTION TRACKER
# 13 items from BT3345_9001_010 + 2 programme milestone actions
# ═══════════════════════════════════════════════════════════════════════════════
ACT_FIELDS = ["ActionID","Title","Owner","DueDate","Status","RAGStatus",
              "LastUpdated","Category","Notes"]

actions = [
    # ── BLOCKING CONFLICTS (TBD) ──────────────────────────────────────────────
    {
        "ActionID":    "ACT-SENT-001",
        "Title":       "Resolve steel specification conflict — SA-516 Gr.70 vs A576 Gr.50",
        "Owner":       "Joseph Welker",
        "DueDate":     "2026-05-08",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("BLOCKING CONFLICT — TBD. BT3345_9001_010 Item 001. "
                        "SDD §3.2: SA-516 Gr.70. PDP D000004318 §3.3.1: A576 Gr.50. "
                        "Engineering alignment meeting required. "
                        "SDD Rev 1.1 or RTM Rev F must resolve before DNV submittal."),
    },
    {
        "ActionID":    "ACT-SENT-002",
        "Title":       "Resolve battery capacity conflict — 40 kWh/80 hr vs 60 kWh/120 hr",
        "Owner":       "Oguzhan Kilic",
        "DueDate":     "2026-05-08",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("BLOCKING CONFLICT — TBD. BT3345_9001_010 Item 002. "
                        "SDD §4.8/§5.3: 40 kWh / 80 hr endurance. PDP D000004318 §5.2: 60 kWh / 120 hr. "
                        "SDD provides 67% of required capacity. Life-safety implication. "
                        "Upgrade battery or revise programme spec with justification."),
    },
    {
        "ActionID":    "ACT-SENT-003",
        "Title":       "Add hinge fatigue RPN 175 to SDD OI register and commission FLS analysis",
        "Owner":       "Joseph Welker / Ken Ngo",
        "DueDate":     "2026-05-08",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("BLOCKING CONFLICT — TBD. BT3345_9001_010 Item 003. "
                        "Escape hatch hinge fatigue RPN 175 not in SDD OI register. "
                        "FLS analysis not delivered. DNV-RU-UWT Pt.5 Ch.10 Sec.3 [306] requires fatigue assessment. "
                        "Add as named OI and commission FLS analysis."),
    },
    {
        "ActionID":    "ACT-SENT-004",
        "Title":       "Confirm governing operating pressure — 2.38 vs 2.40 bar(a) — and initiate SDD sweep",
        "Owner":       "Joseph Welker",
        "DueDate":     "2026-05-08",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("BLOCKING CONFLICT — TBD. BT3345_9001_010 Item 004. "
                        "SDD states 2.40 bar(a). Programme baseline is 2.38 bar(a). "
                        "Discrepancy propagates to all pressure-dependent calculations including CO2 pCO2 limits. "
                        "Confirm governing value then sweep SDD — see ACT-SENT-013."),
    },
    # ── BLOCKING LIFE SAFETY (OPEN) ───────────────────────────────────────────
    {
        "ActionID":    "ACT-SENT-005",
        "Title":       "Correct CO2 alarm setpoints from % vol to pCO2 partial pressure values",
        "Owner":       "Jim Williamson",
        "DueDate":     "2026-05-01",
        "Status":      "In Progress",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Safety",
        "Notes":       ("BLOCKING — LIFE SAFETY — OPEN. BT3345_9001_010 Item 005. "
                        "SDD §4.4 % vol thresholds exceed DNV pCO2 limits at 2.38 bar(a): "
                        "caution 0.5% vol = 0.012 bar pCO2 (2.4x DNV limit 0.005 bar); "
                        "alarm 1.0% vol = 0.024 bar pCO2 (exceeds DNV emergency limit 0.020 bar). "
                        "Williamson has corrected setpoint value. Cross-document update required: "
                        "SDD §4.4, RTM LSS-003, and monitoring system config must all reflect corrected pCO2 values."),
    },
    # ── HIGH ─────────────────────────────────────────────────────────────────
    {
        "ActionID":    "ACT-SENT-006",
        "Title":       "Initiate PHA-SENTINEL-001 or remove reference from SDD §1.2",
        "Owner":       "Larry Chase",
        "DueDate":     "2026-05-22",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Safety",
        "Notes":       ("HIGH. BT3345_9001_010 Item 006. BT3345_9001_009 Row 1.5 GAP. "
                        "PHA-SENTINEL-001 referenced in SDD §1.2 but not in programme suite. "
                        "DNV-RU-UWT Pt.5 Ch.10 Sec.1 [105] requires formal safety assessment. "
                        "Initiate document or remove reference and add as named open item."),
    },
    {
        "ActionID":    "ACT-SENT-007",
        "Title":       "Document DNV special approval pathway for battery thermal runaway in SDD §6.4",
        "Owner":       "Oguzhan Kilic",
        "DueDate":     "2026-05-22",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Safety",
        "Notes":       ("HIGH. BT3345_9001_010 Item 007. RTM OI-06 OPEN. "
                        "Highest hazard in SDD. DNV Type Approval or special consideration pathway "
                        "not documented. Include: detection method, suppression/containment, "
                        "ventilation strategy, and DNV Type Approval cert reference. Close OI-06."),
    },
    {
        "ActionID":    "ACT-SENT-008",
        "Title":       "Complete FMECA to 10/10 tabs and correct SHOULD to SHALL in dual analysis",
        "Owner":       "Ken Ngo",
        "DueDate":     "2026-05-22",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("HIGH. BT3345_9001_010 Item 008. RTM OI-07 OPEN. "
                        "FMECA structural tab coverage 3/10. SHOULD must be revised to SHALL "
                        "throughout dual analysis description. FMECA prerequisite for DNV plan approval. "
                        "Close OI-07 upon delivery."),
    },
    {
        "ActionID":    "ACT-SENT-009",
        "Title":       "Specify rescue mating flange in SDD §9.6 per applicable standard",
        "Owner":       "TBD — pending Flag 4 resolution",
        "DueDate":     "2026-05-22",
        "Status":      "Open",
        "RAGStatus":   "RED",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("HIGH. BT3345_9001_010 Item 009. BT3345_9001_009 Row 9.6 GAP. RTM EMG-006. "
                        "Rescue mating flange absent from SDD Rev 1.0. "
                        "DNV-RU-UWT Pt.5 Ch.10 Sec.9 [906] requires standard flange for HEV connection. "
                        "Confirm HEV compatibility (see ACT-SENT-004/TQ-SENT-004). Action owner TBD pending Flag 4."),
    },
    {
        "ActionID":    "ACT-SENT-010",
        "Title":       "Document escape hatch O-ring OEA compatibility in SDD OI register §3.8",
        "Owner":       "TBD",
        "DueDate":     "2026-05-22",
        "Status":      "Open",
        "RAGStatus":   "AMBER",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("HIGH. BT3345_9001_010 Item 010. Construction hold — not in SDD OI register. "
                        "O-ring material compatibility in OEA (oxygen-enriched atmosphere) is safety-critical. "
                        "Add as named OI in SDD §3.8. Reference ASTM G63/G94. "
                        "Construction hold to remain until material selection confirmed."),
    },
    {
        "ActionID":    "ACT-SENT-011",
        "Title":       "Add compliance basis statements to SDD for 6 COMPLIANT rows in BT3345_9001_009",
        "Owner":       "Larry Chase",
        "DueDate":     "2026-05-22",
        "Status":      "Open",
        "RAGStatus":   "AMBER",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("HIGH. BT3345_9001_010 Item 011. "
                        "Rows 3.12 (buoyancy), 6.1 (main power), 6.2 (emergency changeover), "
                        "7.1 (EMS), 7.3 (comms), 10.3 (this document). "
                        "Each COMPLIANT row needs documented basis in relevant SDD section: "
                        "calc reference, test result, or design feature explicitly cited."),
    },
    # ── MEDIUM ───────────────────────────────────────────────────────────────
    {
        "ActionID":    "ACT-SENT-012",
        "Title":       "Correct RTM-SENT-001 cover page title cell from Rev D to Rev E",
        "Owner":       "Larry Chase",
        "DueDate":     "2026-05-08",
        "Status":      "Open",
        "RAGStatus":   "AMBER",
        "LastUpdated": "2026-04-24",
        "Category":    "Administrative",
        "Notes":       ("MEDIUM. BT3345_9001_010 Item 012. RTM action (not SDD). "
                        "Cover page title cell: 'Rev D | 13 February 2026'. "
                        "Revision detail row correctly states Rev E | 2026-03-20. "
                        "Correct and reissue RTM-SENT-001 Rev E. Document integrity issue — "
                        "must be resolved before DNV submittal."),
    },
    {
        "ActionID":    "ACT-SENT-013",
        "Title":       "Sweep SDD for all 2.40 bar(a) instances and correct to approved value",
        "Owner":       "Joseph Welker",
        "DueDate":     "2026-06-05",
        "Status":      "Open",
        "RAGStatus":   "AMBER",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("MEDIUM. BT3345_9001_010 Item 013. Depends on ACT-SENT-004 resolution. "
                        "Full-text sweep of SDD for '2.40 bar' instances — correct to 2.38 bar(a) "
                        "or approved value post-resolution. Re-check all pressure-dependent calculations. "
                        "Document sweep results in SDD Rev 1.1 change record."),
    },
    # ── PROGRAMME MILESTONES ──────────────────────────────────────────────────
    {
        "ActionID":    "ACT-SENT-014",
        "Title":       "Issue SDD-SENTINEL-001 Rev 1.1 with all 13 BT3345_9001_010 items closed",
        "Owner":       "Larry Chase",
        "DueDate":     "2026-06-12",
        "Status":      "Open",
        "RAGStatus":   "AMBER",
        "LastUpdated": "2026-04-24",
        "Category":    "Technical",
        "Notes":       ("Programme milestone. All 13 correction items in BT3345_9001_010 must be "
                        "closed before Rev 1.1 is issued. BLOCKING items 001-005 are hard prerequisites. "
                        "Rev 1.1 is prerequisite for DNV plan approval submission."),
    },
    {
        "ActionID":    "ACT-SENT-015",
        "Title":       "Submit full AiP package to DNV — target November 2026 AiP certificate",
        "Owner":       "Larry Chase",
        "DueDate":     "2026-09-30",
        "Status":      "Open",
        "RAGStatus":   "GREEN",
        "LastUpdated": "2026-04-24",
        "Category":    "Coordination",
        "Notes":       ("Programme milestone. AiP submission package: BT3345_9001_009, "
                        "SDD-SENTINEL-001 Rev 1.1, RTM-SENT-001 Rev F, FMECA-SENTINEL-001, "
                        "PHA-SENTINEL-001, BTI-9001-020. All BLOCKING and HIGH items must be closed. "
                        "DNV AiP certificate target: November 2026."),
    },
]

write_csv("action_tracker.csv", ACT_FIELDS, actions)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. TQ LOG
# ═══════════════════════════════════════════════════════════════════════════════
TQ_FIELDS = ["TQID","Subject","OriginatingReviewer","SourceDocumentNumber",
             "DateOpened","DateResponded","Status","ResponseOwner","EscalationTier","Notes"]

tqs = [
    {
        "TQID":                 "TQ-SENT-001",
        "Subject":              "CO2 alarm threshold basis — pCO2 arithmetic error at 2.38 bar(a) operating pressure",
        "OriginatingReviewer":  "Jim Williamson (Unique Group)",
        "SourceDocumentNumber": "SDD-SENTINEL-001",
        "DateOpened":           "2026-04-20",
        "DateResponded":        "2026-04-23",
        "Status":               "Responded",
        "ResponseOwner":        "Jim Williamson",
        "EscalationTier":       "P1",
        "Notes":                ("Life-safety finding. SDD §4.4 states CO2 alarms at 0.5% vol (caution) "
                                 "and 1.0% vol (alarm). At 2.38 bar(a): 0.5% = 0.012 bar pCO2 "
                                 "(2.4x DNV limit 0.005 bar); 1.0% = 0.024 bar pCO2 "
                                 "(exceeds DNV emergency limit 0.020 bar). "
                                 "Williamson has corrected setpoint value. "
                                 "Cross-document update required: SDD §4.4 + RTM LSS-003 + monitoring config. "
                                 "See BT3345_9001_009 Row 5.3, BT3345_9001_010 Item 005, ACT-SENT-005."),
    },
    {
        "TQID":                 "TQ-SENT-002",
        "Subject":              "Bilge system applicability for open-bottom moon-pool habitat — DNV Pt.5 Ch.10 Sec.4 [402]",
        "OriginatingReviewer":  "DNV-Marine",
        "SourceDocumentNumber": "BT3345_9001_009",
        "DateOpened":           "2026-04-24",
        "DateResponded":        "",
        "Status":               "Open",
        "ResponseOwner":        "Larry Chase",
        "EscalationTier":       "P3",
        "Notes":                ("TBD. BT3345_9001_009 Row 4.2. SDD §4.2 does not address bilge "
                                 "for open-bottom moon-pool configuration. Seek DNV technical clarification: "
                                 "does Pt.5 Ch.10 Sec.4 [402] apply to open-bottom habitats? "
                                 "Include in AiP pre-submission meeting agenda. See AUD-SENT-001."),
    },
    {
        "TQID":                 "TQ-SENT-003",
        "Subject":              "Steel specification governing document — SA-516 Gr.70 vs A576 Gr.50",
        "OriginatingReviewer":  "Internal — Engineering",
        "SourceDocumentNumber": "SDD-SENTINEL-001",
        "DateOpened":           "2026-04-24",
        "DateResponded":        "",
        "Status":               "Open",
        "ResponseOwner":        "Joseph Welker",
        "EscalationTier":       "P1",
        "Notes":                ("BLOCKING CONFLICT. BT3345_9001_010 Item 001. "
                                 "SDD §3.2 specifies SA-516 Gr.70 (ASME P-No.1, Fy=38 ksi). "
                                 "PDP D000004318 §3.3.1 requires A576 Gr.50 (Fy=50 ksi min). "
                                 "Engineering alignment meeting required. "
                                 "Governing spec to be confirmed before SDD Rev 1.1. See ACT-SENT-001."),
    },
    {
        "TQID":                 "TQ-SENT-004",
        "Subject":              "Rescue mating flange standard and HEV compatibility — Pt.5 Ch.10 Sec.9 [906]",
        "OriginatingReviewer":  "DNV-Safety",
        "SourceDocumentNumber": "SDD-SENTINEL-001",
        "DateOpened":           "2026-04-24",
        "DateResponded":        "",
        "Status":               "Open",
        "ResponseOwner":        "Larry Chase",
        "EscalationTier":       "P2",
        "Notes":                ("HIGH. BT3345_9001_010 Item 009. BT3345_9001_009 Row 9.6 GAP. "
                                 "Rescue mating flange not specified in SDD §9.6. HEV compatibility unconfirmed. "
                                 "DNV-RU-UWT Pt.5 Ch.10 Sec.9 [906] requires standard flange for HEV connection. "
                                 "Pending Flag 4 resolution. See ACT-SENT-009."),
    },
    {
        "TQID":                 "TQ-SENT-005",
        "Subject":              "Battery thermal runaway — DNV special approval pathway for lithium installation",
        "OriginatingReviewer":  "DNV-Electrical",
        "SourceDocumentNumber": "SDD-SENTINEL-001",
        "DateOpened":           "2026-04-24",
        "DateResponded":        "",
        "Status":               "Open",
        "ResponseOwner":        "Oguzhan Kilic",
        "EscalationTier":       "P2",
        "Notes":                ("HIGH. BT3345_9001_010 Item 007. RTM OI-06 OPEN. "
                                 "Highest hazard classification in SDD. DNV Type Approval or special "
                                 "consideration pathway not documented for lithium battery installation. "
                                 "DNV-RU-UWT Pt.5 Ch.10 Sec.6 [605]. "
                                 "Required: detection method, suppression, ventilation, Type Approval ref. "
                                 "See ACT-SENT-007."),
    },
    {
        "TQID":                 "TQ-SENT-006",
        "Subject":              "Crew competency, HRA crediting, and operational envelope for mixed-occupancy LIVHAB(SAT)",
        "OriginatingReviewer":  "DNV-Safety",
        "SourceDocumentNumber": "BTI-9001-020",
        "DateOpened":           "2026-04-21",
        "DateResponded":        "",
        "Status":               "Open",
        "ResponseOwner":        "Larry Chase",
        "EscalationTier":       "P2",
        "Notes":                ("HIGH. BTI-9001-020 AiP submission. 4 questions for DNV adjudication: "
                                 "(1) Does Pt.5 Ch.10 impose specific crew competency requirements for LIVHAB(SAT)? "
                                 "(2) Will DNV impose competency conditions in AiP cert or construction approval? "
                                 "(3) What is DNV expectation for crediting human-dependent FMECA mitigations "
                                 "where occupant capability is non-uniform? Is Crew Capability Baseline statement "
                                 "sufficient or is formal HRA required? "
                                 "(4) Is mixed-occupancy model (paying recreational customers) within LIVHAB(SAT) "
                                 "envelope or does it require Special Feature notation?"),
    },
]

write_csv("tq_log.csv", TQ_FIELDS, tqs)

# ═══════════════════════════════════════════════════════════════════════════════
# 4. AUDIT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
AUD_FIELDS = ["AuditID","AuditName","AuditDate","Scope","Status",
              "ReadinessScore","ReadinessStatus","RequiredEvidenceDocNumbers"]

audits = [
    {
        "AuditID":                  "AUD-SENT-001",
        "AuditName":                "Blocking Conflict Resolution Gate",
        "AuditDate":                "2026-05-15",
        "Scope":                    ("Internal gate: BT3345_9001_010 Items 001-004 (CONFLICT) resolved, "
                                     "Item 005 (CO2) closed. Governing values confirmed. "
                                     "SDD Rev 1.1 draft initiated."),
        "Status":                   "Upcoming",
        "ReadinessScore":           0,
        "ReadinessStatus":          "Not Computed",
        "RequiredEvidenceDocNumbers": "BT3345_9001_010|SDD-SENTINEL-001|PDP-D000004318|RTM-SENT-001",
    },
    {
        "AuditID":                  "AUD-SENT-002",
        "AuditName":                "DNV AiP Pre-Submission Technical Meeting",
        "AuditDate":                "2026-06-30",
        "Scope":                    ("AiP document package readiness. All BLOCKING items resolved. "
                                     "Key TQs (bilge applicability, HEV flange, crew competency) "
                                     "raised with DNV for pre-submission clarification."),
        "Status":                   "Upcoming",
        "ReadinessScore":           0,
        "ReadinessStatus":          "Not Computed",
        "RequiredEvidenceDocNumbers": "BT3345_9001_009|BT3345_9001_010|SDD-SENTINEL-001|RTM-SENT-001|BTI-9001-020",
    },
    {
        "AuditID":                  "AUD-SENT-003",
        "AuditName":                "SDD Rev 1.1 Internal Issue Gate",
        "AuditDate":                "2026-06-12",
        "Scope":                    ("SDD-SENTINEL-001 Rev 1.1 issued with all 13 BT3345_9001_010 "
                                     "correction items closed. Document ready for DNV review."),
        "Status":                   "Upcoming",
        "ReadinessScore":           0,
        "ReadinessStatus":          "Not Computed",
        "RequiredEvidenceDocNumbers": "SDD-SENTINEL-001|BT3345_9001_010|FMECA-SENTINEL-001|PHA-SENTINEL-001",
    },
    {
        "AuditID":                  "AUD-SENT-004",
        "AuditName":                "DNV AiP Package Submission Gate",
        "AuditDate":                "2026-09-30",
        "Scope":                    ("Full AiP package submitted to DNV. All BLOCKING and HIGH items "
                                     "in BT3345_9001_010 closed. All required documents at approved revision. "
                                     "Compliance map BT3345_9001_009 at current revision."),
        "Status":                   "Upcoming",
        "ReadinessScore":           0,
        "ReadinessStatus":          "Not Computed",
        "RequiredEvidenceDocNumbers": ("BT3345_9001_009|SDD-SENTINEL-001|RTM-SENT-001|"
                                       "FMECA-SENTINEL-001|PHA-SENTINEL-001|BTI-9001-020|PDP-D000004318"),
    },
    {
        "AuditID":                  "AUD-SENT-005",
        "AuditName":                "DNV AiP Certificate — Target Milestone",
        "AuditDate":                "2026-11-30",
        "Scope":                    ("DNV Approval in Principle certificate issuance target for "
                                     "Sentinel 001 LIVHAB(SAT) classification under "
                                     "DNV-RU-UWT Pt.5 Ch.10 (December 2024)."),
        "Status":                   "Upcoming",
        "ReadinessScore":           0,
        "ReadinessStatus":          "Not Computed",
        "RequiredEvidenceDocNumbers": "BT3345_9001_009|SDD-SENTINEL-001|RTM-SENT-001|FMECA-SENTINEL-001",
    },
]

write_csv("audit_definitions.csv", AUD_FIELDS, audits)

# ─── Update config.json critical_path_docs ───────────────────────────────────
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

cfg["critical_path_docs"] = ["BT3345_9001_009", "SDD-SENTINEL-001", "FMECA-SENTINEL-001"]

with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
print("\nUpdated config.json critical_path_docs → Sentinel 001 documents")

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("SEED COMPLETE — Sentinel 001 Programme Data")
print("="*60)
print(f"  submissions.csv      : {len(submissions)} documents")
print(f"  action_tracker.csv   : {len(actions)} actions "
      f"(13 from BT3345_9001_010 + 2 programme milestones)")
print(f"  tq_log.csv           : {len(tqs)} technical queries")
print(f"  audit_definitions.csv: {len(audits)} audit/milestone gates")
print(f"\n  Backup location: {BACKUP_DIR}")
