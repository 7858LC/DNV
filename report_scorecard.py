"""
report_scorecard.py
ReportLab PDF generator for the Interface Health Scorecard.
Replicates the renderScorecard() logic from reports.html exactly:
  - 6 KPIs with identical color thresholds
  - Business-day SLA calculation (Mon-Fri, same algorithm as JS)
  - Three bar sections: TQs by Reviewer, Submissions by Status, Actions by RAG
  - Programme snapshot summary row
"""
from __future__ import annotations

import csv
import io
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas as rl_canvas

# ── Palette (matches DNV Coordinator palette) ─────────────────────────────────
NAVY       = HexColor("#1F3864")
LIGHT_BLUE = HexColor("#D5E8F0")
TILE_BG    = HexColor("#F2F6FC")
GREEN_COL  = HexColor("#00B050")
AMBER_COL  = HexColor("#FF8C00")
RED_COL    = HexColor("#C00000")
BLUE_COL   = HexColor("#1F78B4")
MUTED_COL  = HexColor("#888888")
WHITE      = white
BLACK      = black

PAGE_W, PAGE_H = LETTER  # 612 × 792 pts


# ── Color map (mirrors JS color names) ───────────────────────────────────────
def _kpi_color(name: str):
    return {
        "green": GREEN_COL,
        "amber": AMBER_COL,
        "red":   RED_COL,
        "blue":  BLUE_COL,
        "muted": MUTED_COL,
    }.get(name, MUTED_COL)


# ── Date helpers (identical logic to JS) ─────────────────────────────────────
def _biz_days_between(from_str: str, to_str: str) -> int:
    """Business days from from_str to to_str (skip weekends, no holiday table here)."""
    if not from_str or not to_str:
        return 0
    try:
        start = datetime.strptime(from_str[:10], "%Y-%m-%d").date()
        end   = datetime.strptime(to_str[:10],   "%Y-%m-%d").date()
    except ValueError:
        return 0
    count = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:   # 0=Mon … 4=Fri
            count += 1
    return count


def _cal_days_to(date_str: str, today: date) -> int:
    """Calendar days from today to date_str. Negative = overdue."""
    if not date_str:
        return 0
    try:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (target - today).days


# ── CSV loading ───────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── KPI computation ───────────────────────────────────────────────────────────
def _compute_kpis(tqs, acts, subs, audits, today: date) -> list[dict]:
    # KPI 1 — SLA compliance (closed TQs within 10 business days)
    closed_tqs    = [t for t in tqs if t.get("Status", "") != "Open"
                     and t.get("DateOpened") and t.get("DateResponded")]
    sla_compliant = sum(1 for t in closed_tqs
                        if _biz_days_between(t["DateOpened"], t["DateResponded"]) <= 10)
    sla_pct       = round(sla_compliant / len(closed_tqs) * 100) if closed_tqs else None

    # KPI 2 — Open TQs / P1
    open_tqs = [t for t in tqs if t.get("Status") == "Open"]
    p1_open  = sum(1 for t in open_tqs
                   if (t.get("EscalationTier") or "").upper() == "P1")

    # KPI 3 — Actions overdue
    open_acts    = [a for a in acts if a.get("Status", "") not in ("Complete", "Closed")]
    acts_overdue = sum(1 for a in open_acts
                       if a.get("DueDate") and _cal_days_to(a["DueDate"], today) < 0)

    # KPI 4 — Submission accept rate
    decided  = [s for s in subs if s.get("Status", "") in ("Accepted", "Rejected")]
    accepted = sum(1 for s in subs if s.get("Status", "") == "Accepted")
    acc_rate = round(accepted / len(decided) * 100) if decided else None

    # KPI 5 — Unassigned TQs
    unassigned = sum(1 for t in open_tqs if not (t.get("ResponseOwner") or "").strip())

    # KPI 6 — Avg audit readiness
    active_audits = [a for a in audits if a.get("Status", "") in ("Active", "Upcoming")]
    scores        = [float(a.get("ReadinessScore") or 0) for a in active_audits]
    avg_readiness = round(sum(scores) / len(scores)) if scores else None

    def _sla_color():
        if sla_pct is None:    return "muted"
        if sla_pct >= 80:      return "green"
        if sla_pct >= 60:      return "amber"
        return "red"

    def _tq_color():
        if len(open_tqs) == 0: return "green"
        if p1_open > 0:        return "red"
        return "amber"

    def _act_color():
        if acts_overdue == 0:  return "green"
        if acts_overdue <= 3:  return "amber"
        return "red"

    def _acc_color():
        if acc_rate is None:   return "muted"
        if acc_rate >= 85:     return "green"
        if acc_rate >= 70:     return "amber"
        return "red"

    def _una_color():
        if unassigned == 0:    return "green"
        if unassigned <= 2:    return "amber"
        return "red"

    def _aud_color():
        if avg_readiness is None: return "muted"
        if avg_readiness >= 80:   return "green"
        if avg_readiness >= 50:   return "amber"
        return "red"

    return [
        {
            "label": "SLA Compliance",
            "value": f"{sla_pct}%" if sla_pct is not None else "N/A",
            "sub":   f"{sla_compliant}/{len(closed_tqs)} TQs within 10 bd",
            "color": _sla_color(),
        },
        {
            "label": "Open TQs",
            "value": str(len(open_tqs)),
            "sub":   f"{p1_open} critical path (P1)",
            "color": _tq_color(),
        },
        {
            "label": "Actions Overdue",
            "value": str(acts_overdue),
            "sub":   f"of {len(open_acts)} open actions",
            "color": _act_color(),
        },
        {
            "label": "Submission Accept Rate",
            "value": f"{acc_rate}%" if acc_rate is not None else "N/A",
            "sub":   f"{accepted} of {len(decided)} decided",
            "color": _acc_color(),
        },
        {
            "label": "Unassigned TQs",
            "value": str(unassigned),
            "sub":   "open TQs with no response owner",
            "color": _una_color(),
        },
        {
            "label": "Avg Audit Readiness",
            "value": f"{avg_readiness}%" if avg_readiness is not None else "N/A",
            "sub":   f"{len(active_audits)} active/upcoming audits",
            "color": _aud_color(),
        },
    ], open_tqs, open_acts, decided, active_audits


# ── Drawing helpers ───────────────────────────────────────────────────────────
def _draw_header(c, today_str: str) -> None:
    banner_h = 52
    # Navy banner
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - banner_h, PAGE_W, banner_h, fill=1, stroke=0)
    # Title
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(36, PAGE_H - 22, "INTERFACE HEALTH SCORECARD")
    # Subtitle
    c.setFont("Helvetica", 8)
    c.drawString(36, PAGE_H - 37, "Sentinel 001  ·  AiP Programme  ·  Bastion Technologies, Inc.")
    # Date / confidential (right-aligned)
    c.setFont("Helvetica", 8)
    c.drawRightString(PAGE_W - 36, PAGE_H - 22, today_str)
    c.drawRightString(PAGE_W - 36, PAGE_H - 37, "CONFIDENTIAL")


def _draw_footer(c, page_num: int, today_str: str) -> None:
    c.setStrokeColor(MUTED_COL)
    c.setLineWidth(0.4)
    c.line(36, 38, PAGE_W - 36, 38)
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, 26, f"Bastion Technologies, Inc.  ·  CONFIDENTIAL  ·  Generated {today_str}")
    c.drawRightString(PAGE_W - 36, 26, f"Page {page_num}")


def _draw_kpi_tiles(c, kpis: list[dict], y_top: float) -> float:
    """
    Draw 3-column × 2-row KPI tile grid.
    Returns y-coordinate immediately below the grid.
    """
    n_cols   = 3
    gap_x    = 10
    gap_y    = 10
    tile_w   = (PAGE_W - 72 - gap_x * (n_cols - 1)) / n_cols   # ≈ 170 pts
    tile_h   = 74
    left     = 36

    for i, k in enumerate(kpis):
        col = i % n_cols
        row = i // n_cols
        tx  = left + col * (tile_w + gap_x)
        ty  = y_top - row * (tile_h + gap_y)   # top of this tile

        accent = _kpi_color(k["color"])

        # Tile background
        c.setFillColor(TILE_BG)
        c.setStrokeColor(LIGHT_BLUE)
        c.setLineWidth(0.6)
        c.roundRect(tx, ty - tile_h, tile_w, tile_h, 5, fill=1, stroke=1)

        # Accent bar on top edge
        c.setFillColor(accent)
        c.setStrokeColor(accent)
        c.roundRect(tx, ty - 5, tile_w, 5, 2, fill=1, stroke=0)

        # Label (uppercase, muted)
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 7)
        c.drawString(tx + 8, ty - 18, k["label"].upper())

        # Value (large, accent colour)
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(tx + 8, ty - 45, k["value"])

        # Sub-text
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 7)
        sub = k["sub"]
        # Soft-wrap at 34 chars so it fits the tile
        if len(sub) > 34:
            # Try to break on a space near the midpoint
            mid = 34
            break_at = sub.rfind(" ", 0, mid) or mid
            c.drawString(tx + 8, ty - 58, sub[:break_at].strip())
            c.drawString(tx + 8, ty - 67, sub[break_at:].strip()[:34])
        else:
            c.drawString(tx + 8, ty - 58, sub)

    n_rows = math.ceil(len(kpis) / n_cols)
    return y_top - n_rows * (tile_h + gap_y) + gap_y   # gap_y already added once too many, correct by returning without double-gap


def _draw_bar_section(c, title: str, rows: list[tuple], y_top: float,
                      section_w: float, x_left: float) -> float:
    """
    Draw one labeled horizontal bar section.
    rows: list of (label, count, _, color)
    Returns y-coordinate immediately below the section.
    """
    ROW_H  = 17
    LABEL_W = 88
    BAR_X   = x_left + LABEL_W
    BAR_W   = section_w - LABEL_W - 22
    VAL_X   = BAR_X + BAR_W + 4

    # Section title
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x_left, y_top, title.upper())
    y = y_top - 3
    c.setStrokeColor(LIGHT_BLUE)
    c.setLineWidth(0.5)
    c.line(x_left, y, x_left + section_w, y)
    y -= ROW_H

    if not rows:
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 7)
        c.drawString(x_left, y, "No data")
        return y - 8

    max_v = max((r[1] for r in rows), default=1) or 1

    for label, value, _, color in rows:
        pct = value / max_v
        # Label
        c.setFillColor(BLACK)
        c.setFont("Helvetica", 7)
        lbl = (label[:15] + "…") if len(label) > 16 else label
        c.drawString(x_left, y - 4, lbl)
        # Bar track
        c.setFillColor(HexColor("#E8EEF7"))
        c.rect(BAR_X, y - 10, BAR_W, 10, fill=1, stroke=0)
        # Bar fill
        c.setFillColor(color)
        fill_w = max(2, BAR_W * pct)
        c.rect(BAR_X, y - 10, fill_w, 10, fill=1, stroke=0)
        # Value label
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(VAL_X, y - 8, str(value))
        y -= ROW_H

    return y - 4


def _draw_snapshot_row(c, tqs, open_tqs, open_acts, subs, active_audits, y: float) -> None:
    """Programme snapshot numbers across the bottom of page 1."""
    items = [
        ("Total TQs",           str(len(tqs))),
        ("Open TQs",            str(len(open_tqs))),
        ("Total Submissions",   str(len(subs))),
        ("Open Actions",        str(len(open_acts))),
        ("Active/Upcoming Audits", str(len(active_audits))),
    ]
    col_w = (PAGE_W - 72) / len(items)
    for i, (label, val) in enumerate(items):
        sx = 36 + i * col_w
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 6)
        c.drawString(sx, y, label.upper())
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(sx, y - 18, val)


# ── Main public function ──────────────────────────────────────────────────────
def generate_scorecard_pdf(cfg: dict) -> bytes:
    """
    Read CSV tables via cfg, compute all KPIs, render PDF, return bytes.
    Called from the /api/export/scorecard-pdf Flask route.
    """
    from utils import resolve_path

    data_dir  = resolve_path(cfg["data_dir"])
    csv_files = cfg.get("csv_files", {})

    tqs    = _read_csv(data_dir / csv_files.get("tq_log",            "tq_log.csv"))
    acts   = _read_csv(data_dir / csv_files.get("action_tracker",    "action_tracker.csv"))
    subs   = _read_csv(data_dir / csv_files.get("submissions",       "submissions.csv"))
    audits = _read_csv(data_dir / csv_files.get("audit_definitions", "audit_definitions.csv"))

    today     = date.today()
    today_str = today.strftime("%d %b %Y")

    kpis, open_tqs, open_acts, decided, active_audits = _compute_kpis(
        tqs, acts, subs, audits, today
    )

    # ── Build bar data ────────────────────────────────────────────────────────
    # Discipline bars — TQ open count per OriginatingReviewer
    seen, disciplines = set(), []
    for t in tqs:
        rev = (t.get("OriginatingReviewer") or "").strip()
        if rev and rev not in seen:
            seen.add(rev)
            disciplines.append(rev)

    disc_rows = [
        (d,
         sum(1 for t in tqs if t.get("Status") == "Open" and (t.get("OriginatingReviewer") or "").strip() == d),
         0,
         BLUE_COL)
        for d in disciplines
    ]
    # Sort by open count desc
    disc_rows.sort(key=lambda r: r[1], reverse=True)

    # Submission status bars
    sub_status_cfg = [
        ("New",          BLUE_COL),
        ("Under Review", AMBER_COL),
        ("Accepted",     GREEN_COL),
        ("Rejected",     RED_COL),
    ]
    sub_rows = [
        (s, sum(1 for x in subs if x.get("Status", "") == s), 0, col)
        for s, col in sub_status_cfg
    ]

    # Action RAG bars
    rag_cfg = [("RED", RED_COL), ("AMBER", AMBER_COL), ("GREEN", GREEN_COL)]
    rag_rows = [
        (r, sum(1 for a in acts if a.get("RAGStatus", "") == r), 0, col)
        for r, col in rag_cfg
    ]

    # ── Render PDF ────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle("Interface Health Scorecard — Sentinel 001")
    c.setAuthor("Bastion Technologies, Inc.")
    c.setSubject("DNV AiP Programme — Interface Health Scorecard")

    # Page 1
    _draw_header(c, today_str)
    _draw_footer(c, 1, today_str)

    # Section label: KPIs
    y = PAGE_H - 64
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, y, "KEY PERFORMANCE INDICATORS")
    y -= 4

    y = _draw_kpi_tiles(c, kpis, y)
    y -= 18   # breathing room before bar sections

    # Section label: detail bars
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, y, "DETAIL BREAKDOWN")
    y -= 8

    # Three bar sections side by side
    n_sections = 3
    gap_s   = 14
    sec_w   = (PAGE_W - 72 - gap_s * (n_sections - 1)) / n_sections   # ≈ 164 pts

    x1 = 36
    x2 = x1 + sec_w + gap_s
    x3 = x2 + sec_w + gap_s

    y1 = _draw_bar_section(c, "Open TQs by Reviewer", disc_rows,  y, sec_w, x1)
    y2 = _draw_bar_section(c, "Submissions by Status", sub_rows,   y, sec_w, x2)
    y3 = _draw_bar_section(c, "Actions by RAG Status", rag_rows,   y, sec_w, x3)

    y_after = min(y1, y2, y3) - 20

    # Snapshot row (if room)
    if y_after > 90:
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(36, y_after, "PROGRAMME SNAPSHOT")
        y_after -= 4
        c.setStrokeColor(LIGHT_BLUE)
        c.setLineWidth(0.5)
        c.line(36, y_after, PAGE_W - 36, y_after)
        y_after -= 8
        _draw_snapshot_row(c, tqs, open_tqs, open_acts, subs, active_audits, y_after)

    c.showPage()
    c.save()

    buf.seek(0)
    return buf.read()
