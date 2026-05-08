# DNV Bastion Portal

Internal web portal for the **DEEP Sentinel 001** subsea habitat programme — managing the interface between Bastion (engineering/submitting party) and DNV (classification/verification authority).

**Programme timeline:** January 2026 → March 2027  
**Certification target:** DNV Certificate of Compliance for a subsea habitat system  
**App root:** `C:\Users\lchas\DNV _System\`  
**Stack:** Python 3.14 · Flask 3.x · pandas · SQLite (WAL) · jpype1/mpxj (MPP parsing) · OpenJDK 21

---

## What this does

Every document submission, technical query, DNV comment, compliance action, and schedule risk flag flows through this portal. It is the single source of truth between Bastion and DNV — audit trail included.

- **Track submissions** through a 7-stage workflow from Draft → Closed
- **Log and respond to DNV comments** with auto-generated CommentIDs (BC-YYYYMMDD-NNN)
- **Monitor schedule impact** — 400 MS Project tasks parsed from .mpp; 14 DNV-tagged; risk-flagged by business-day lead time
- **TQ SLA tracking** — Technical Queries monitored against 10 business-day response target
- **Audit readiness** — compliance checklist coverage per upcoming DNV review gate
- **Export** — SLA Forecast, Audit Readiness, DocReq Coverage, Interface Health Scorecard PDFs

---

## Portal pages

| Route | Page | Purpose |
|---|---|---|
| `/` | Dashboard | KPI cards, pipeline table, RAG status, DAILY/WEEKLY mode |
| `/coordinator` | Coordinator | 7-tab hub: Action Tracker, TQ Log, DNV Comments, Submissions, Doc Register, DNV DocReq, Audit |
| `/submissions` | Submissions | 7-stage workflow state machine, role-gated transitions, audit trail |
| `/schedule` | Schedule Impact | DNV task lead-time risk, .mpp import, task↔submission links |
| `/docreq` | Doc Requirements | DNV-mandated deliverable coverage tracking |
| `/kanban` | Kanban | Visual board view of action tracker |
| `/reports` | Reports | PDF export hub |
| `/exec` | Exec Dashboard | Senior leadership metrics (direct URL, no nav link) |

---

## Roles

| Role | Key permissions |
|---|---|
| Bastion Engineer | Draft submissions, move Draft→Internal Review, update actions |
| Bastion Coordinator | Gate submissions to DNV, enter DNV comments, import schedule, export PDFs |
| DNV Reviewer | Read-only across all views |
| Admin | Full access, all workflow transitions |

Sign-in modal on first visit — sets name, role, timezone. Persists via `bastion_session` cookie. User chip visible on every page.

---

## Submission workflow

```
Draft → Internal Review → Submitted to DNV → Under DNV Review
     → Comments Issued → Response Submitted → Closed
```

State machine enforced server-side (`submissions_db.py`). Every transition logged to SQLite with user, timestamp, and optional note.

---

## Schedule Impact — risk thresholds

15 business days = mandatory DNV lead time for witness/inspection events.

| Level | BD to task start | Meaning |
|---|---|---|
| BREACH | ≤ 0 | Past start date — act immediately |
| RISK | 1–15 | Within mandatory lead time |
| WATCH | 16–21 | Pre-notify DNV now |
| OK | > 21 | No action needed |

**Current flag (as of May 2026):** WBS 1.7.7 — DNV Surveyor Witness, Structural Fabrication Hold Points = **BREACH**

Coordinator imports updated .mpp weekly via Schedule Impact → Import Schedule. Converted server-side automatically — no separate script.

---

## Key files

| File | Purpose |
|---|---|
| `app.py` | All Flask routes, CSRF, identity, RAGStatus, PDF exports |
| `static/auth.js` | Sign-in modal, user chip, TZ utils, CSRF fetch interceptor |
| `submissions_db.py` | Submission workflow state machine + SQLite audit log |
| `schedule_db.py` | Schedule tasks, risk engine (BD arithmetic), document links |
| `docreq_db.py` | Doc requirements SQLite, delta sync, audit columns |
| `config.json` | Submission statuses, roles, holidays, thresholds |
| `orchestrator.py` | Pipeline runner — calls agents 1–5 in sequence |
| `agent_*.py` | Intake, tracker, audit, TQ, dashboard agents |

### Data files (not in repo — populate locally)
```
data/submissions.csv          — document submission register
data/action_tracker.csv       — action items
data/tq_log.csv               — technical queries
data/dnv_comments.csv         — DNV formal review comments (218 rows, RuleRef normalised)
data/audit_definitions.csv    — compliance checklist
data/document_register.csv    — master document register
data/dnv_doc_requirements.csv — DNV-mandated deliverables
```

### State files (generated at runtime — not in repo)
```
state/submissions.db      — submission transition audit log
state/schedule.db         — schedule tasks, task↔submission links
state/schedule_raw.json   — last imported MPP as JSON (400 tasks)
state/computed_state.json — pipeline output
```

---

## Getting started (new machine)

```bash
# 1. Clone
git clone https://github.com/<your-org>/dnv-bastion-portal.git
cd dnv-bastion-portal

# 2. Install dependencies
pip install -r requirements.txt
pip install jpype1   # required for .mpp schedule import

# 3. Restore data files
# Copy data/*.csv from secure backup into data/

# 4. Run
python app.py
# Opens browser at http://localhost:5000
# Network URL shown in terminal for team access
```

**Java required** for .mpp import: [Eclipse Adoptium OpenJDK 21](https://adoptium.net)

---

## Monday morning workflow

1. Download latest .mpp from project server
2. Portal → Schedule Impact → Import Schedule → drop .mpp → Upload & Import
3. Dashboard → WEEKLY mode → RUN PIPELINE
4. Reports → export Scorecard PDF + SLA Forecast PDF for programme meeting
5. Check Schedule Impact for tasks entering WATCH window → send DNV pre-notification

---

## Blocked / pending (external dependencies)

- **Excel intake route** — awaiting Bastion Excel file for column mapping
- **DNV file output package** — awaiting DNV file structure spec
- **IT firewall rule** — port 5000 LAN access (ticket sent, awaiting IT)

---

## Security notes

- CSRF protection on all write routes — token in session cookie, validated via `hmac.compare_digest()`
- `bastion_session` cookie is JSON, not signed — do not store sensitive values in it
- `FLASK_SECRET` env var should be set in production (defaults to dev key)
- Data files excluded from repo — never commit CSVs or DBs

---

## Claude Code context

This project uses Claude Code CLI with `/dnvstart` as the session-start command.  
Memory files: `~/.claude/projects/C--Users-lchas-DNV--System/memory/`  
For claude.ai Projects: use this README + `memory/project_dnv_portal.md` as knowledge files.
