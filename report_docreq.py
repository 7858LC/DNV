"""
report_docreq.py
ReportLab PDF generator for the DNV Document Requirements Coverage report.
Reads live data from state/docreq.db via docreq_db.get_requirements().
Falls back to dnv_doc_requirements.csv if DB is absent.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas as rl_canvas

# ── Palette ───────────────────────────────────────────────────────────────────
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

PAGE_W, PAGE_H = LETTER   # 612 × 792 pts
MARGIN         = 36

COV_COLORS = {
    "MISSING":       RED_COL,
    "Gap":           AMBER_COL,
    "Open Comments": AMBER_COL,
    "Answered":      BLUE_COL,
    "Submitted":     BLUE_COL,
    "DNV Reviewed":  GREEN_COL,
    "Satisfied":     GREEN_COL,
}

# Columns pulling from live DB fields
COLUMNS = [
    ("#",          "item_number",    22, "center"),
    ("Code",       "dnv_code",       34, "left"),
    ("Requirement","requirement_text",152,"left"),
    ("Type",       "approval_type",  28, "center"),
    ("Subsystem",  "subsystem",      62, "left"),
    ("Docs",       "doc_count",      24, "center"),
    ("Open Thr",   "open_threads",   30, "center"),
    ("Coverage",   "coverage_status",84, "left"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _truncate(text: str, max_chars: int) -> str:
    s = str(text or "").strip()
    return (s[: max_chars - 1] + "…") if len(s) > max_chars else s


def _load_requirements(cfg: dict) -> list[dict]:
    """Load from SQLite DB; fall back to CSV if DB doesn't exist."""
    from utils import resolve_path
    state_dir = resolve_path(cfg.get("state_dir", "./state"))
    db_path   = state_dir / "docreq.db"

    if db_path.exists():
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from docreq_db import get_requirements
        return get_requirements(db_path)

    # Fallback — flat CSV
    import csv
    data_dir  = resolve_path(cfg.get("data_dir", "./data"))
    csv_files = cfg.get("csv_files", {})
    csv_path  = data_dir / csv_files.get("dnv_doc_requirements", "dnv_doc_requirements.csv")
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Normalise CSV field names to match DB field names
    for r in rows:
        if "object_description" in r and "requirement_text" not in r:
            r["requirement_text"] = r.pop("object_description")
        r.setdefault("doc_count", 0)
        r.setdefault("open_threads", 0)
    return rows


# ── Page structure ────────────────────────────────────────────────────────────
def _draw_header(c, today_str: str) -> None:
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 52, PAGE_W, 52, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, PAGE_H - 22, "DNV DOCUMENT REQUIREMENTS COVERAGE")
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, PAGE_H - 37,
                 "Sentinel 001  ·  DNV-RU-UWT Pt.5 Ch.10 Sec.1  ·  Vanguard 02")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 22, today_str)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 37, "CONFIDENTIAL")


def _draw_footer(c, page_num: int, today_str: str) -> None:
    c.setStrokeColor(MUTED_COL)
    c.setLineWidth(0.4)
    c.line(MARGIN, 38, PAGE_W - MARGIN, 38)
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, 26,
                 f"Bastion Technologies, Inc.  ·  CONFIDENTIAL  ·  Generated {today_str}")
    c.drawRightString(PAGE_W - MARGIN, 26, f"Page {page_num}")


def _draw_kpi_tiles(c, kpis: list[dict], y_top: float) -> float:
    n      = len(kpis)
    gap    = 10
    tile_w = (PAGE_W - 2 * MARGIN - gap * (n - 1)) / n
    tile_h = 56

    for i, k in enumerate(kpis):
        tx, ty = MARGIN + i * (tile_w + gap), y_top
        c.setFillColor(TILE_BG)
        c.setStrokeColor(LIGHT_BLUE)
        c.setLineWidth(0.6)
        c.roundRect(tx, ty - tile_h, tile_w, tile_h, 4, fill=1, stroke=1)
        accent = k["color"]
        c.setFillColor(accent)
        c.roundRect(tx, ty - 4, tile_w, 4, 2, fill=1, stroke=0)
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 6)
        c.drawString(tx + 6, ty - 14, k["label"].upper())
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(tx + 6, ty - 36, str(k["value"]))
        c.setFillColor(MUTED_COL)
        c.setFont("Helvetica", 6)
        c.drawString(tx + 6, ty - 48, _truncate(k["sub"], 30))

    return y_top - tile_h - 6


def _draw_table_header(c, y: float) -> float:
    row_h   = 13
    total_w = sum(col[2] for col in COLUMNS)
    c.setFillColor(NAVY)
    c.rect(MARGIN, y - row_h, total_w, row_h, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 6)
    cx = MARGIN
    for header, _, width, align in COLUMNS:
        if align == "center":
            c.drawCentredString(cx + width / 2, y - row_h + 4, header.upper())
        else:
            c.drawString(cx + 3, y - row_h + 4, header.upper())
        cx += width
    return y - row_h


def _draw_table_row(c, row: dict, y: float, shade: bool) -> float:
    row_h   = 12
    total_w = sum(col[2] for col in COLUMNS)
    if shade:
        c.setFillColor(HexColor("#EEF3FA"))
        c.rect(MARGIN, y - row_h, total_w, row_h, fill=1, stroke=0)

    cx = MARGIN
    for _, field, width, align in COLUMNS:
        val = str(row.get(field, "") or "").strip()

        if field == "coverage_status":
            txt_color = COV_COLORS.get(val, MUTED_COL)
            c.setFont("Helvetica-Bold", 6)
        elif field == "item_number":
            txt_color = MUTED_COL
            c.setFont("Helvetica-Bold", 6)
        elif field == "open_threads" and val not in ("", "0"):
            txt_color = AMBER_COL
            c.setFont("Helvetica-Bold", 6)
        elif field == "doc_count":
            txt_color = BLUE_COL
            c.setFont("Helvetica", 6)
        else:
            txt_color = BLACK
            c.setFont("Helvetica", 6)

        c.setFillColor(txt_color)
        max_chars = max(4, int(width / 4.2))
        label = _truncate(val, max_chars)
        if align == "center":
            c.drawCentredString(cx + width / 2, y - row_h + 4, label)
        else:
            c.drawString(cx + 3, y - row_h + 4, label)

        c.setStrokeColor(LIGHT_BLUE)
        c.setLineWidth(0.3)
        c.line(cx + width, y, cx + width, y - row_h)
        cx += width

    c.setStrokeColor(LIGHT_BLUE)
    c.setLineWidth(0.3)
    c.line(MARGIN, y - row_h, MARGIN + total_w, y - row_h)
    return y - row_h


# ── Main public function ──────────────────────────────────────────────────────
def generate_docreq_pdf(cfg: dict) -> bytes:
    reqs      = _load_requirements(cfg)
    today     = date.today()
    today_str = today.strftime("%d %b %Y")

    # KPI computation from live DB fields
    numbered   = [r for r in reqs if str(r.get("item_number", "")).strip() not in ("", "nan")]
    reviewed   = sum(1 for r in reqs if r.get("coverage_status") in ("DNV Reviewed", "Satisfied"))
    submitted  = sum(1 for r in reqs if r.get("coverage_status") == "Submitted")
    open_c     = sum(1 for r in reqs if r.get("coverage_status") == "Open Comments")
    open_thr   = sum(int(r.get("open_threads") or 0) for r in reqs)
    missing    = sum(1 for r in reqs if r.get("coverage_status") == "MISSING")
    gap        = sum(1 for r in reqs if r.get("coverage_status") == "Gap")

    kpis = [
        {"label": "Total Requirements", "value": len(numbered),
         "sub":   "numbered DNV items",        "color": BLUE_COL},
        {"label": "DNV Reviewed",        "value": reviewed,
         "sub":   "accepted / satisfied",       "color": GREEN_COL},
        {"label": "Submitted",           "value": submitted,
         "sub":   "awaiting DNV verdict",       "color": BLUE_COL},
        {"label": "Open Comments",       "value": open_c,
         "sub":   f"{open_thr} open threads",   "color": AMBER_COL},
        {"label": "Gap / No Document",   "value": gap,
         "sub":   "no doc linked yet",          "color": AMBER_COL},
        {"label": "MISSING",             "value": missing,
         "sub":   "not yet produced",           "color": RED_COL},
    ]

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle("DNV Document Requirements Coverage — Sentinel 001")
    c.setAuthor("Bastion Technologies, Inc.")
    c.setSubject("DNV-RU-UWT Pt.5 Ch.10 Sec.1 — Document Coverage Report")

    page_num = 1
    _draw_header(c, today_str)
    _draw_footer(c, page_num, today_str)

    y = PAGE_H - 64
    c.setFillColor(MUTED_COL)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, y, "COVERAGE SUMMARY")
    y -= 4
    y  = _draw_kpi_tiles(c, kpis, y)
    y -= 14

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(MARGIN, y, "REQUIREMENTS DETAIL")
    y -= 3
    c.setStrokeColor(LIGHT_BLUE)
    c.setLineWidth(0.5)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 6

    y = _draw_table_header(c, y)
    BOTTOM_MARGIN = 55

    for i, row in enumerate(reqs):
        if y - 12 < BOTTOM_MARGIN:
            c.showPage()
            page_num += 1
            _draw_header(c, today_str)
            _draw_footer(c, page_num, today_str)
            y = PAGE_H - 64
            y = _draw_table_header(c, y)
        y = _draw_table_row(c, row, y, shade=(i % 2 == 0))

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
