====================================================================
 DNV BASTION COORDINATOR  —  Field Deployment Package
 Built for Windows 11 / Python 3.11+   No internet required after setup.
====================================================================

QUICK START
-----------
1.  Copy this folder to your machine (anywhere — no spaces in path recommended)
2.  Double-click  start.bat
3.  Browser opens automatically at  http://localhost:5000

That's it. The batch file installs dependencies, runs the pipeline,
and launches the dashboard.

--------------------------------------------------------------------
MONDAY MORNING WORKFLOW
--------------------------------------------------------------------
1.  Update the four CSV files in  data\  with the week's data:
      data\submissions.csv
      data\action_tracker.csv
      data\tq_log.csv
      data\audit_definitions.csv

2.  Double-click  run_weekly.bat   (runs all 5 agents, writes report)

3.  Double-click  start.bat        (launches dashboard)

4.  Click  EXPORT WEEKLY REPORT   in the sidebar to download
    the Markdown report for distribution.

--------------------------------------------------------------------
MANUAL COMMANDS (command prompt)
--------------------------------------------------------------------
  Daily run (Agents 1-4):
    python orchestrator.py

  Weekly run (Agents 1-5, generates report):
    python orchestrator.py --mode weekly

  Start dashboard only (no pipeline):
    python app.py

  Run pipeline + keep dashboard running in one step:
    start.bat

--------------------------------------------------------------------
FILE STRUCTURE
--------------------------------------------------------------------
  app.py                  Flask web server  (localhost:5000)
  orchestrator.py         Pipeline runner   (Agent 0)
  agent_intake.py         Agent 1 - Submission Intake & Routing
  agent_tracker.py        Agent 2 - Action Tracker
  agent_audit.py          Agent 3 - Audit Readiness
  agent_tq.py             Agent 4 - TQ Log Manager
  agent_dashboard.py      Agent 5 - Weekly Dashboard Generator
  utils.py                Shared utilities (date math, config)
  config.json             All thresholds, routing rules, holidays

  data\                   << EDIT THESE WEEKLY >>
    submissions.csv
    action_tracker.csv
    tq_log.csv
    audit_definitions.csv

  *.xlsx                  Excel seed files (reference copies of data\)
  state\                  Auto-generated pipeline state (do not edit)
  logs\                   Session log (JSON, append-only)
  outputs\YYYY-MM-DD\     Weekly reports (JSON + Markdown)
  templates\              Dashboard HTML (do not edit unless customising)

--------------------------------------------------------------------
CONFIG  (config.json)
--------------------------------------------------------------------
  amber_threshold       Business days until due = AMBER   (default 5)
  stale_threshold       Days since last update = stale    (default 7)
  tq_sla_days           TQ SLA breach threshold           (default 10)
  readiness_threshold   Audit readiness alert floor %     (default 85)
  critical_path_docs    Doc numbers triggering P1 TQs
  routing_table         DocType -> DNV discipline mapping
  holidays              2026 US + Norwegian public holidays

--------------------------------------------------------------------
REQUIREMENTS
--------------------------------------------------------------------
  Python 3.11 or later
  flask >= 3.0
  pandas >= 2.1
  numpy >= 1.26
  openpyxl >= 3.1   (for Excel seed files only)

  All installed automatically by start.bat via pip.
  No internet required after first install.

--------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------
  Port 5000 in use:
    Edit app.py last line: change port=5000 to port=5001
    Then open http://localhost:5001

  Unicode errors in console:
    Run:  chcp 65001   (sets console to UTF-8)
    Or just ignore — cosmetic only, does not affect output files.

  Pipeline errors appear in:
    logs\session_log.json     (all runs, append-only)
    state\computed_state.json (latest run, agent error messages)

====================================================================
