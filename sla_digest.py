"""
sla_digest.py  — DNV DocReq SLA breach digest → Microsoft Teams webhook

Usage:
    python sla_digest.py                   # uses config.json webhook URL
    python sla_digest.py --dry-run         # prints the card JSON, no POST
    python sla_digest.py --url <webhook>   # override URL from command line

Schedule via Windows Task Scheduler:
    Action:   python "C:\\Users\\lchas\\DNV _System\\sla_digest.py"
    Trigger:  Daily, 8:00 AM (or whatever suits the team)

Thresholds:
    WARNING  8+ open business days (approaching SLA)
    BREACH  10+ open business days (SLA exceeded)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent


def _load_config() -> dict:
    p = ROOT / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p


def build_digest(db_path: Path) -> dict:
    """Return {"warning": [...], "breach": [...], "clean": bool}."""
    sys.path.insert(0, str(ROOT))
    from docreq_db import get_requirements, sla_status

    reqs = get_requirements(db_path)

    warning, breach = [], []
    for req in reqs:
        for doc in req.get("documents", []):
            for t in doc.get("threads", []):
                if t.get("disposition") != "Open":
                    continue
                sla = t.get("sla") or sla_status(t)
                bd = sla.get("bd_open") or 0
                entry = {
                    "item_number":  req.get("item_number", ""),
                    "dnv_code":     req.get("dnv_code", ""),
                    "doc_number":   doc.get("doc_number", ""),
                    "round":        t.get("round", 1),
                    "category":     t.get("category", ""),
                    "assigned_to":  t.get("assigned_to") or "Unassigned",
                    "bd_open":      bd,
                    "dnv_comment_date": t.get("dnv_comment_date", ""),
                }
                if bd >= 10:
                    breach.append(entry)
                elif bd >= 8:
                    warning.append(entry)

    # Sort worst-first
    breach.sort(key=lambda x: -x["bd_open"])
    warning.sort(key=lambda x: -x["bd_open"])

    return {"warning": warning, "breach": breach, "clean": not warning and not breach}


def _facts(threads: list[dict]) -> list[dict]:
    return [
        {
            "name":  f"Req {t['item_number']} · {t['doc_number']} (Round {t['round']})",
            "value": (
                f"{t['bd_open']}bd open  |  "
                f"{t['category']}  |  "
                f"Assigned: {t['assigned_to']}  |  "
                f"Received: {t['dnv_comment_date'] or 'unknown'}"
            ),
        }
        for t in threads
    ]


def build_card(digest: dict) -> dict:
    today_str = date.today().strftime("%d %b %Y")
    breach  = digest["breach"]
    warning = digest["warning"]

    if digest["clean"]:
        return {
            "@type":     "MessageCard",
            "@context":  "http://schema.org/extensions",
            "themeColor": "00B050",
            "summary":   f"DNV SLA Digest {today_str} — All Clear",
            "title":     f"DNV Comment SLA Digest — {today_str}",
            "text":      (
                f"**All Clear.** No open threads approaching or exceeding the "
                f"10 business-day SLA as of {today_str}."
            ),
        }

    sections = []

    if breach:
        sections.append({
            "activityTitle":    f"🔴  {len(breach)} SLA BREACH{'ES' if len(breach)>1 else ''}",
            "activitySubtitle": "Open threads exceeding the 10 business-day response SLA",
            "facts":            _facts(breach),
            "markdown":         True,
        })

    if warning:
        sections.append({
            "activityTitle":    f"🟡  {len(warning)} SLA WARNING{'S' if len(warning)>1 else ''}",
            "activitySubtitle": "Open threads at 8–9 business days — response due within 2 days",
            "facts":            _facts(warning),
            "markdown":         True,
        })

    sections.append({
        "text": (
            f"[Open DNV Doc Requirements](http://localhost:5000/docreq)  ·  "
            f"Generated {today_str}"
        ),
        "markdown": True,
    })

    color = "C00000" if breach else "FF8C00"
    total = len(breach) + len(warning)
    summary = (
        f"{len(breach)} breach{'es' if len(breach)!=1 else ''}, "
        f"{len(warning)} warning{'s' if len(warning)!=1 else ''}"
    )

    return {
        "@type":     "MessageCard",
        "@context":  "http://schema.org/extensions",
        "themeColor": color,
        "summary":   f"DNV SLA Digest {today_str} — {summary}",
        "title":     f"DNV Comment SLA Digest — {today_str}",
        "sections":  sections,
    }


def post_to_teams(webhook_url: str, card: dict) -> bool:
    try:
        import urllib.request
        data = json.dumps(card).encode("utf-8")
        req  = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Teams POST failed: {e}", file=sys.stderr)
        return False


def run(webhook_url: str = "", dry_run: bool = False) -> dict:
    cfg      = _load_config()
    state    = _resolve(cfg.get("state_dir", "./state"))
    db_path  = state / "docreq.db"

    if not db_path.exists():
        print("[WARN] docreq.db not found — nothing to report.")
        return {"status": "no_db"}

    url = webhook_url or cfg.get("teams_webhook_url", "")

    digest = build_digest(db_path)
    card   = build_card(digest)

    if dry_run:
        print(json.dumps(card, indent=2))
        return {"status": "dry_run", "digest": digest}

    if not url:
        print("[WARN] No Teams webhook URL configured.")
        print("  Set 'teams_webhook_url' in config.json or pass --url.")
        print("\nDigest preview:")
        print(f"  Breaches : {len(digest['breach'])}")
        print(f"  Warnings : {len(digest['warning'])}")
        return {"status": "no_url", "digest": digest}

    ok = post_to_teams(url, card)
    status = "sent" if ok else "error"
    print(f"[{'OK' if ok else 'ERROR'}] Digest {status} — "
          f"{len(digest['breach'])} breaches, {len(digest['warning'])} warnings")
    return {"status": status, "digest": digest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DNV SLA digest → Teams")
    parser.add_argument("--url",     default="", help="Teams incoming webhook URL")
    parser.add_argument("--dry-run", action="store_true", help="Print card JSON, don't POST")
    args = parser.parse_args()
    result = run(webhook_url=args.url, dry_run=args.dry_run)
    sys.exit(0 if result.get("status") in ("sent", "dry_run", "no_url", "no_db") else 1)
