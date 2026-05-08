"""
report_sla.py
ReportLab PDF generator for the TQ SLA Forecast report.
Replicates renderSLA() from reports.html:
  - 5 summary cards: Breached, Critical, Warning, On Track, P1 Open
  - Table of all open TQs sorted by days remaining (ascending, breached first)
  - Business-day SLA calculation matches JS exactly (10 bd window)
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas as rl_canvas

NAVY       = HexColor("#1F3864")
LIGHT_BLUE = HexColor("#D5E8F0")
GREEN_COL  = HexColor("#00B050")
AMBER_COL  = HexColor("#FF8C00")
RED_COL    = HexColor("#C00000")
ORANGE_COL = HexColor("#F97316")
BLUE_COL   = HexColor("#1F78B4")
MUTED_COL  = HexColor("#888888")
TILE_BG    = HexColor("#F2F6FC")
WHITE      = white
BLACK      = black

PAGE_W, PAGE_H = LETTER   # 612 × 792 pts
BOT_MARGIN     = 52
TOP_CONTENT    = PAGE_H - 64


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _biz_days_elapsed(from_str: str, today: date) -> int:
    if not from_str:
        return 0
    try:
        start = datetime.strptime(from_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    count, d = 0, start
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def _add_biz_days(from_str: str, n: int) -> date | None:
    if not from_str:
        return None
    try:
        d = datetime.strptime(from_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def _clip(s: str, n: int) -> str:
    s = str(s or "")
    return s[:n] + ("…" if len(s) > n else "")


# ── Page chrome ───────────────────────────────────────────────────────────────

def _draw_header(c, today_str: str) -> None:
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 52, PAGE_W, 52, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(36, PAGE_H - 22, "TQ SLA FORECAST")
    c.setFont("Helvetica", 8)
    c.drawString(36, PAGE_H - 37,
                 "Sentinel 001  ·  AiP Programme  ·  Bastion Technologies, Inc."
                 "  ·  Open Technical Queries — 10 Business Day Window")
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


# ── Summary cards ─────────────────────────────────────────────────────────────

def _draw_summary_cards(c, breached, critical, warning, ontrack, p1_open, y_top: float) -> float:
    cards = [
        ("SLA Breached",   breached, RED_COL),
        ("Critical (≤2d)", critical, AMBER_COL),
        ("Warning (3–5d)", warning,  ORANGE_COL),
        ("On Track",       ontrack,  GREEN_COL),
        ("P1 Open",        p1_open,  BLUE_COL),
    ]
    n      = len(cards)
    gap    = 8
    tile_w = (PAGE_W - 72 - gap * (n - 1)) / n
    tile_h = 58

    for i, (label, val, color) in enumerate(cards):
        tx = 36 + i * (tile_w + gap)
        c.setFillColor(TILE_BG)
        c.setStrokeColor(LIGHT_BLUE)
        c.setLineWidth(0.6)
        c.roundRect(tx, y_top - tile_h, tile_w, tile_h, 4, fill=1, stroke=1)
        c.setFillColor(color)
        c.roundRect(tx, y_top - 4, tile_w, 4, 2, fill=1, stroke=0)
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 6.5)
        c.drawString(tx + 6, y_top - 17, label.upper())
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(tx + 6, y_top - 44, str(val))

    return y_top - tile_h - 10


# ── Table ─────────────────────────────────────────────────────────────────────

# (label, x, width)
COLS = [
    ("TQ ID",    36,  52),
    ("SUBJECT",  90, 138),
    ("TIER",    230,  28),
    ("REVIEWER",260,  78),
    ("OWNER",   340,  78),
    ("RAISED",  420,  50),
    ("DEADLINE",472,  50),
    ("STATUS",  524,  52),
]
ROW_H = 15


def _draw_col_header(c, y: float) -> float:
    c.setFillColor(NAVY)
    c.rect(36, y - 14, PAGE_W - 72, 14, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 6.5)
    for label, x, _ in COLS:
        c.drawString(x + 2, y - 10, label)
    return y - 14


def _draw_tq_row(c, row: dict, y: float, alt: bool) -> None:
    c.setFillColor(HexColor("#F7F9FC") if alt else WHITE)
    c.rect(36, y - ROW_H, PAGE_W - 72, ROW_H, fill=1, stroke=0)

    rem = row["remaining"]
    if rem < 0:
        st_color, st_label = RED_COL,    f"BREACHED +{abs(rem)}d"
    elif rem <= 2:
        st_color, st_label = AMBER_COL,  f"CRITICAL {rem}d"
    elif rem <= 5:
        st_color, st_label = ORANGE_COL, f"WARNING {rem}d"
    else:
        st_color, st_label = GREEN_COL,  f"OK {rem}d"

    tier      = (_clip(row.get("EscalationTier") or "—", 2)).upper()
    tier_col  = RED_COL if tier == "P1" else AMBER_COL if tier == "P2" else MUTED_COL
    dl_str    = row["deadline"].strftime("%d %b") if row["deadline"] else "—"
    raised    = (row.get("DateOpened") or "")[:10] or "—"

    c.setFont("Helvetica", 6.5)

    c.setFillColor(BLUE_COL)
    c.drawString(38, y - 10, _clip(row.get("TQID", ""), 9))

    c.setFillColor(BLACK)
    c.drawString(92, y - 10, _clip(row.get("Subject", ""), 22))

    c.setFillColor(tier_col)
    c.drawString(232, y - 10, tier[:2])

    c.setFillColor(MUTED_COL)
    c.drawString(262, y - 10, _clip(row.get("OriginatingReviewer") or "—", 12))
    c.drawString(342, y - 10, _clip(row.get("ResponseOwner") or "Unassigned", 12))
    c.drawString(422, y - 10, raised)
    c.drawString(474, y - 10, dl_str)

    c.setFillColor(st_color)
    c.setFont("Helvetica-Bold", 6)
    c.drawString(526, y - 10, st_label[:13])

    c.setStrokeColor(LIGHT_BLUE)
    c.setLineWidth(0.3)
    c.line(36, y - ROW_H, PAGE_W - 36, y - ROW_H)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_sla_pdf(cfg: dict) -> bytes:
    from utils import resolve_path

    data_dir  = resolve_path(cfg["data_dir"])
    csv_files = cfg.get("csv_files", {})
    tqs = _read_csv(data_dir / csv_files.get("tq_log", "tq_log.csv"))

    today     = date.today()
    today_str = today.strftime("%d %b %Y")

    open_tqs = [t for t in tqs if t.get("Status") == "Open"]
    rows = []
    for t in open_tqs:
        elapsed   = _biz_days_elapsed(t.get("DateOpened", ""), today)
        remaining = 10 - elapsed
        deadline  = _add_biz_days(t.get("DateOpened", ""), 10)
        rows.append({**t, "elapsed": elapsed, "remaining": remaining, "deadline": deadline})
    rows.sort(key=lambda r: r["remaining"])

    breached = sum(1 for r in rows if r["remaining"] < 0)
    critical = sum(1 for r in rows if 0 <= r["remaining"] <= 2)
    warning  = sum(1 for r in rows if 3 <= r["remaining"] <= 5)
    ontrack  = sum(1 for r in rows if r["remaining"] > 5)
    p1_open  = sum(1 for r in rows if (r.get("EscalationTier") or "").upper() == "P1")

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle("TQ SLA Forecast — Sentinel 001")
    c.setAuthor("Bastion Technologies, Inc.")
    c.setSubject("DNV AiP Programme — TQ SLA Forecast")

    page_num = 1
    _draw_header(c, today_str)
    _draw_footer(c, page_num, today_str)

    y = TOP_CONTENT
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, y, "SUMMARY")
    y -= 4

    y = _draw_summary_cards(c, breached, critical, warning, ontrack, p1_open, y)

    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(36, y, f"OPEN TQ DETAIL — {len(rows)} OPEN TECHNICAL QUERIES")
    y -= 4

    y = _draw_col_header(c, y)

    if not rows:
        c.setFillColor(GREEN_COL)
        c.setFont("Helvetica", 9)
        c.drawString(36, y - 22, "✓  No open TQs — all SLA targets met.")
        c.showPage()
        c.save()
        buf.seek(0)
        return buf.read()

    alt = False
    for row in rows:
        if y - ROW_H < BOT_MARGIN:
            c.showPage()
            page_num += 1
            _draw_header(c, today_str)
            _draw_footer(c, page_num, today_str)
            y = TOP_CONTENT
            y = _draw_col_header(c, y)
            alt = False

        _draw_tq_row(c, row, y, alt)
        alt = not alt
        y -= ROW_H

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
