"""
Shared utilities for DNV Bastion Coordinator pipeline.
"""
from __future__ import annotations
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Union

import numpy as np


_config: dict | None = None
_holidays: list[np.datetime64] | None = None


def load_config() -> dict:
    global _config
    if _config is None:
        cfg_path = Path(__file__).parent / "config.json"
        with open(cfg_path, "r") as f:
            _config = json.load(f)
    return _config


def get_holidays() -> list[np.datetime64]:
    global _holidays
    if _holidays is None:
        cfg = load_config()
        _holidays = [np.datetime64(d, "D") for d in cfg.get("holidays", [])]
    return _holidays


def to_date(val) -> date | None:
    """Convert various inputs to a date object."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if hasattr(val, "date"):
        return val.date()
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", ""):
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def business_days_between(start: Union[date, str], end: Union[date, str]) -> int:
    """
    Return the number of business days from `start` (inclusive) to `end` (exclusive).
    Positive = end is after start. Negative = end is before start.
    Uses Mon-Fri week mask and the holiday list from config.
    """
    if start is None or end is None:
        return 0
    s = to_date(start)
    e = to_date(end)
    if s is None or e is None:
        return 0
    holidays = get_holidays()
    return int(np.busday_count(s, e, holidays=holidays))


def get_run_date() -> date:
    return date.today()


def resolve_path(rel: str) -> Path:
    """Resolve a path relative to the project root."""
    root = Path(__file__).parent
    return (root / rel).resolve()


def ensure_dirs():
    cfg = load_config()
    for key in ("state_dir", "logs_dir", "outputs_dir", "data_dir"):
        resolve_path(cfg[key]).mkdir(parents=True, exist_ok=True)
