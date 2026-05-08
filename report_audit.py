"""
report_audit.py
ReportLab PDF generator for the Audit Readiness Forecast report.
Replicates renderAudit() from reports.html:
  - One card per upcoming / active audit (sorted by date ascending)
  - Readiness bar: docs accepted + no open TQ blockers / total required docs
  - Required evidence doc table with submission status
  - Blocker list: open TQs on required documents
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas as rl_canvas

NAVY       = HexColor("#1F3864")
LIGHT_BLUE = HexColor("#D5E8F0")
GREEN_COL  = HexColor("#00B050")
AMBER_COL  = HexColor("#FF8C00")
RED_COL    = HexColor("#C00000")
BLUE_COL   = HexColor("#1F78B4")
MUTED_COL  = HexColor("#888888")
TILE_BG    = HexColor("#F2F6FC")
WHITE      = white
BLACK      = black

PAGE_W, PAGE_H = LETTER
BOT_MARGIN     = 52
TOP_CONTENT    = PAGE_H - 64

DOC_ROW_H  = 13
BLOCKER_H  = 12


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _cal_days_to(date_str: str, today: date) -> int:
    if not date_str:
        return 0
    try:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (target - today).days


def _clip(s: str, n: int) -> str:
    s = str(s or "")
    return s[:n] + ("…" if len(s) > n else "")


# ── Page chrome ───────────────────────────────────────────────────────────────

def _draw_header(c, today_str: str) -> None:
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 52, PAGE_W, 52, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(36, PAGE_H - 22, "AUDIT READINESS FORECAST")
    c.setFont("Helvetica", 8)
    c.drawString(36, PAGE_H - 37,
                 "Sentinel 001  ·  AiP Programme  ·  Bastion Technologies, Inc."
                 "  ·  Upcoming & Active DNV Assessments")
    c.drawRightString(PAGE_W - 36, PAGE_H - 22, today_str)
    c.drawRightString(PAGE_W - 36, PAGE_H - 37, "CONFIDENTIAL")


def _draw_footer(c, page_num: int, today_str: str) -> None:
    c.setStrokeColor(MUTED_COL)
    c.setLineWidth(0.4)
    c.line(36, 38, PAGE_W - 36, 38)
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, 26,
                 f"Bastion Technologies, Inc.  ·  CONFIDENTIAL  ·  Generated {today_str}")
    c.drawRightString(PAGE_W - 36, 26, f"Page {page_num}")


# ── Audit card ────────────────────────────────────────────────────────────────

def _card_height(doc_rows: list, blockers: list) -> float:
    """Estimate the height of one audit card in points."""
    h = 14 + 12 + 10 + 12 + 14 + 16   # header block + bar + docs-title
    h += len(doc_rows) * DOC_ROW_H
    if blockers:
        h += 16 + len(blockers) * BLOCKER_H
    else:
        h += 14
    h += 10   # bottom padding
    return h


def _draw_audit_card(c, audit: dict, subs: list[dict], tqs: list[dict],
                     y: float, today: date, page_num: int,
                     today_str: str) -> tuple[float, int]:
    """Draw one audit card. Returns (new_y, page_num)."""

    USABLE_W = PAGE_W - 72
    L = 36   # left edge of card
    R = PAGE_W - 36

    doc_nums = [s.strip() for s in
                (audit.get("RequiredEvidenceDocNumbers") or "").split("|")
                if s.strip()]

    doc_rows = []
    for doc_num in doc_nums:
        sub        = next((s for s in subs if s.get("DocumentNumber") == doc_num), None)
        open_tqs_d = [t for t in tqs
                      if t.get("SourceDocumentNumber") == doc_num
                      and t.get("Status") == "Open"]
        sub_status = (sub.get("Status", "") if sub else "Not Submitted") or "Not Submitted"
        doc_rows.append({
            "docNum":  doc_num,
            "title":   (sub.get("DocumentTitle", doc_num) if sub else doc_num),
            "status":  sub_status,
            "openTQs": open_tqs_d,
        })

    blockers      = [t for d in doc_rows for t in d["openTQs"]]
    docs_ok       = sum(1 for d in doc_rows if d["status"] == "Accepted" and not d["openTQs"])
    readiness_pct = round(docs_ok / len(doc_nums) * 100) if doc_nums else 0
    bar_color     = GREEN_COL if readiness_pct >= 80 else AMBER_COL if readiness_pct >= 50 else RED_COL

    days_to    = _cal_days_to(audit.get("AuditDate", ""), today)
    days_color = RED_COL if days_to < 0 else AMBER_COL if days_to <= 7 else NAVY
    if days_to < 0:
        days_label = f"{abs(days_to)}d OVERDUE"
    elif days_to == 0:
        days_label = "TODAY"
    else:
        days_label = f"{days_to}d"

    card_h = _card_height(doc_rows, blockers)

    if y - card_h < BOT_MARGIN:
        c.showPage()
        page_num += 1
        _draw_header(c, today_str)
        _draw_footer(c, page_num, today_str)
        y = TOP_CONTENT

    # Card background + border
    c.setFillColor(TILE_BG)
    c.setStrokeColor(LIGHT_BLUE)
    c.setLineWidth(0.7)
    c.roundRect(L, y - card_h, USABLE_W, card_h, 5, fill=1, stroke=1)

    # Accent left bar (readiness colour)
    c.setFillColor(bar_color)
    c.roundRect(L, y - card_h, 5, card_h, 3, fill=1, stroke=0)

    cx = L + 10   # inner content x
    cy = y - 12

    # Audit ID + Name
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(cx, cy, _clip(f"{audit.get('AuditID','')} — {audit.get('AuditName','')}", 70))
    cy -= 12

    # Scope
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(cx, cy, _clip(audit.get("Scope") or "", 88))
    cy -= 10

    # Date + countdown (right-aligned)
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(cx, cy, f"Scheduled: {audit.get('AuditDate', '—')}")
    c.setFillColor(days_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(R - 4, cy + 2, days_label)
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 6)
    c.drawRightString(R - 4, cy - 7, "to audit")
    cy -= 10

    # Readiness bar
    cy -= 4
    bar_x = cx
    bar_w = USABLE_W - 16
    c.setFillColor(HexColor("#E8EEF7"))
    c.rect(bar_x, cy - 8, bar_w, 8, fill=1, stroke=0)
    c.setFillColor(bar_color)
    c.rect(bar_x, cy - 8, max(4, bar_w * readiness_pct / 100), 8, fill=1, stroke=0)
    c.setFillColor(bar_color)
    c.setFont("Helvetica-Bold", 7)
    c.drawRightString(R - 4, cy - 7,
                      f"{readiness_pct}% READY  ({docs_ok}/{len(doc_nums)} docs accepted)")
    cy -= 14

    # Required docs section header
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(cx, cy, f"REQUIRED EVIDENCE DOCUMENTS ({len(doc_nums)})")
    cy -= 3
    c.setStrokeColor(LIGHT_BLUE)
    c.setLineWidth(0.4)
    c.line(cx, cy, R - 4, cy)
    cy -= 11

    for d in doc_rows:
        st = d["status"]
        if st == "Accepted":
            st_col = GREEN_COL
        elif st == "Not Submitted":
            st_col = RED_COL
        elif st in ("Rejected",):
            st_col = RED_COL
        elif st in ("New", "Under Triage", "Submitted to DEEP",
                    "With DNV (Veracity)", "TQ Issued", "TQ Responded"):
            st_col = BLUE_COL
        else:
            st_col = AMBER_COL

        c.setFillColor(BLACK)
        c.setFont("Helvetica", 6.5)
        c.drawString(cx, cy, _clip(d["docNum"], 20))

        c.setFillColor(MUTED_COL)
        c.drawString(cx + 90, cy, _clip(d["title"], 38))

        c.setFillColor(st_col)
        c.setFont("Helvetica-Bold", 6)
        c.drawRightString(R - 4, cy, _clip(st, 24))

        if d["openTQs"]:
            c.setFillColor(AMBER_COL)
            c.setFont("Helvetica", 6)
            n_tq = len(d["openTQs"])
            c.drawString(cx + 340, cy, f"⚠ {n_tq} open TQ{'s' if n_tq > 1 else ''}")

        cy -= DOC_ROW_H

    # Blockers
    if blockers:
        cy -= 4
        c.setFillColor(RED_COL)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(cx, cy,
                     f"⛔ BLOCKERS — {len(blockers)} OPEN TQ(s) ON REQUIRED DOCUMENTS")
        cy -= 3
        c.setStrokeColor(RED_COL)
        c.setLineWidth(0.4)
        c.line(cx, cy, R - 4, cy)
        cy -= 10

        for t in blockers:
            tier     = (t.get("EscalationTier") or "—").upper()
            tier_col = RED_COL if tier == "P1" else AMBER_COL if tier == "P2" else MUTED_COL

            c.setFillColor(BLUE_COL)
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(cx, cy, _clip(t.get("TQID", ""), 10))

            c.setFillColor(BLACK)
            c.setFont("Helvetica", 6.5)
            c.drawString(cx + 56, cy, _clip(t.get("Subject", ""), 52))

            c.setFillColor(tier_col)
            c.setFont("Helvetica-Bold", 6)
            c.drawRightString(R - 4, cy, tier[:4])

            cy -= BLOCKER_H
    else:
        cy -= 4
        c.setFillColor(GREEN_COL)
        c.setFont("Helvetica", 7)
        c.drawString(cx, cy, "✓  No open TQ blockers on required documents")

    return y - card_h - 10, page_num


# ── Public entry point ────────────────────────────────────────────────────────

def generate_audit_pdf(cfg: dict) -> bytes:
    from utils import resolve_path

    data_dir  = resolve_path(cfg["data_dir"])
    csv_files = cfg.get("csv_files", {})

    tqs    = _read_csv(data_dir / csv_files.get("tq_log",            "tq_log.csv"))
    subs   = _read_csv(data_dir / csv_files.get("submissions",       "submissions.csv"))
    audits = _read_csv(data_dir / csv_files.get("audit_definitions", "audit_definitions.csv"))

    today     = date.today()
    today_str = today.strftime("%d %b %Y")

    upcoming = sorted(
        [a for a in audits if a.get("Status", "") != "Complete"],
        key=lambda a: a.get("AuditDate", ""),
    )

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle("Audit Readiness Forecast — Sentinel 001")
    c.setAuthor("Bastion Technologies, Inc.")
    c.setSubject("DNV AiP Programme — Audit Readiness Forecast")

    page_num = 1
    _draw_header(c, today_str)
    _draw_footer(c, page_num, today_str)

    y = TOP_CONTENT
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, y, f"UPCOMING & ACTIVE ASSESSMENTS — {len(upcoming)} AUDIT(S)")
    y -= 10

    if not upcoming:
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 9)
        c.drawString(36, y - 20, "No upcoming audits scheduled.")
        c.showPage()
        c.save()
        buf.seek(0)
        return buf.read()

    for audit in upcoming:
        y, page_num = _draw_audit_card(
            c, audit, subs, tqs, y, today, page_num, today_str
        )

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
