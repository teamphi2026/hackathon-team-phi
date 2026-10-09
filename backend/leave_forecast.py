"""Leave forecast sheet sync.

After a manager approves a request, record it in the team's leave forecast
sheet: one row per person (matched by full name), one column per month
("Jan-26", "Feb-26", ... "Sept-26"), and cells holding text such as
``9-11 (AL), 24 (SL)``.

Backends (same interface, picked from config):
  * GoogleSheetBackend  - the real Google Sheet, via a service account.
  * CsvBackend          - a CSV with the same layout (local dev, opt-in).

The sync is best-effort: it never raises into the approval flow. Re-running it
for the same request is a no-op (entries are de-duplicated).
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from . import config
from .state import get_session
from .tool_logger import log_forecast
from .tools import actions

_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_ENTRY = re.compile(r"^\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*\(([^)]*)\)\s*$")
_HEADER = re.compile(r"^\s*([A-Za-z]{3,9})\s*-\s*(\d{2}|\d{4})\s*$")


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------

def month_header_key(header: str) -> tuple[int, int] | None:
    """'Sept-26' -> (2026, 9). Returns None if the header isn't a month column."""
    m = _HEADER.match(header or "")
    if not m:
        return None
    abbr = m.group(1).lower()[:3]
    if abbr not in _MONTH_ABBR:
        return None
    yr = int(m.group(2))
    return (2000 + yr if yr < 100 else yr, _MONTH_ABBR.index(abbr) + 1)


def split_by_month(start: date, end: date) -> list[tuple[int, int, int, int]]:
    """Split [start, end] at month boundaries -> [(year, month, first_day, last_day)]."""
    out: list[tuple[int, int, int, int]] = []
    d = start
    while d <= end:
        nxt_month = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
        last = min(end, nxt_month - timedelta(days=1))
        out.append((d.year, d.month, d.day, last.day))
        d = last + timedelta(days=1)
    return out


def entry_text(first: int, last: int, leave_type: str, half_day: str = "") -> str:
    """'13-15 (AL)', '24 (SL)', or '3 (AL-AM)' for a half day."""
    label = leave_type + (f"-{half_day.upper()}" if half_day and half_day.lower() not in ("none", "") else "")
    days = f"{first}" if first == last else f"{first}-{last}"
    return f"{days} ({label})"


def merge_cell(existing: str, new_entry: str) -> str:
    """Add `new_entry` to a month cell: de-duplicated and ordered by day.

    Anything in the cell we can't parse is kept verbatim (after the parsed items).
    """
    parsed: list[tuple[int, int, str, str]] = []
    unknown: list[str] = []
    for tok in [t.strip() for t in (existing or "").split(",") if t.strip()]:
        m = _ENTRY.match(tok)
        if m:
            a = int(m.group(1))
            b = int(m.group(2) or m.group(1))
            parsed.append((a, b, m.group(3).strip().upper(), entry_text(a, b, m.group(3).strip().upper())))
        else:
            unknown.append(tok)
    m = _ENTRY.match(new_entry)
    assert m, f"bad entry {new_entry!r}"
    a, b, label = int(m.group(1)), int(m.group(2) or m.group(1)), m.group(3).strip().upper()
    if not any((p[0], p[1], p[2]) == (a, b, label) for p in parsed):
        parsed.append((a, b, label, entry_text(a, b, label)))
    parsed.sort(key=lambda p: (p[0], p[1]))
    return ", ".join([p[3] for p in parsed] + unknown)


def _norm_name(name: str) -> str:
    return " ".join((name or "").lower().split())


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class SheetBackend(Protocol):
    label: str

    def read_all(self) -> list[list[str]]: ...
    def write_cell(self, row: int, col: int, value: str) -> None: ...   # 0-based row/col


class CsvBackend:
    """A CSV with the sheet's layout (header row first). For local development."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.label = f"csv:{self.path.name}"

    def read_all(self) -> list[list[str]]:
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            return [list(r) for r in csv.reader(fh)]

    def write_cell(self, row: int, col: int, value: str) -> None:
        rows = self.read_all()
        width = max(len(r) for r in rows)
        for r in rows:
            r.extend([""] * (width - len(r)))
        rows[row][col] = value
        with open(self.path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)


class GoogleSheetBackend:
    """The real Google Sheet, accessed with a service account (gspread)."""

    def __init__(self, sheet_id: str, tab: str = ""):
        import gspread
        from .google_sheets import load_credentials

        creds = load_credentials()
        book = gspread.authorize(creds).open_by_key(sheet_id)
        self.ws = book.worksheet(tab) if tab else book.sheet1
        self.label = f"google:{book.title}/{self.ws.title}"

    def read_all(self) -> list[list[str]]:
        return self.ws.get_all_values()

    def write_cell(self, row: int, col: int, value: str) -> None:
        # RAW: store exactly the text we send; Sheets must not reinterpret "9-11 (AL)" as a date/formula.
        self.ws.update(values=[[value]], range_name=gspread_cell(row, col), raw=True)


def gspread_cell(row: int, col: int) -> str:
    """0-based (row, col) -> A1 notation, e.g. (1, 3) -> 'D2'."""
    letters, n = "", col + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


def get_backend() -> SheetBackend | None:
    """The configured backend, or None when the feature is switched off."""
    if config.LEAVE_FORECAST_CSV:
        return CsvBackend(config.LEAVE_FORECAST_CSV)
    if config.GOOGLE_SHEET_ID:
        return GoogleSheetBackend(config.GOOGLE_SHEET_ID, config.GOOGLE_SHEET_TAB)
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _request_and_person(employee_time_id: str) -> tuple[dict[str, str] | None, str]:
    _, rows = actions._read_rows(actions.EMPLOYEE_TIME)
    req = next((r for r in rows if r["employee_time_id"] == employee_time_id), None)
    if req is None:
        return None, ""
    _, people = actions._read_rows("02_Job_Information.csv")
    person = next((p for p in people if p["user_id"] == req["user_id"]), {})
    return req, person.get("full_name", "")


def apply_to_grid(grid: list[list[str]], name: str, start: date, end: date,
                  leave_type: str, half_day: str = "") -> dict[str, Any]:
    """Compute the cell updates for one approved request against sheet contents.

    Returns {"updates": [(row, col, new_value, old_value)], "missing_columns": [...],
    "error": str|None}. Does not write anything.
    """
    if not grid:
        return {"updates": [], "missing_columns": [], "error": "The sheet is empty."}
    header = grid[0]
    name_col = next((i for i, h in enumerate(header) if _norm_name(h) in ("named resource", "name")), 0)
    month_cols = {k: i for i, h in enumerate(header) if (k := month_header_key(h))}
    row = next((i for i, r in enumerate(grid) if i > 0 and len(r) > name_col
                and _norm_name(r[name_col]) == _norm_name(name)), None)
    if row is None:
        return {"updates": [], "missing_columns": [], "error": f"No row for '{name}' in the sheet."}

    updates: list[tuple[int, int, str, str]] = []
    missing: list[str] = []
    for year, month, first, last in split_by_month(start, end):
        col = month_cols.get((year, month))
        if col is None:
            missing.append(f"{_MONTH_ABBR[month - 1].title()}-{str(year)[2:]}")
            continue
        old = grid[row][col] if col < len(grid[row]) else ""
        new = merge_cell(old, entry_text(first, last, leave_type, half_day))
        if new != old:
            updates.append((row, col, new, old))
    return {"updates": updates, "missing_columns": missing, "error": None}


def record_approved_leave(employee_time_id: str) -> dict[str, Any]:
    """Write an approved request into the forecast sheet. Never raises.

    Returns {"status": "updated"|"unchanged"|"skipped"|"failed", "message": str}.
    """
    session = get_session()
    base: dict[str, Any] = {"employee_time_id": employee_time_id}
    try:
        backend = get_backend()
        if backend is None:
            log_forecast("skipped", {**base, "reason": "no sheet configured (GOOGLE_SHEET_ID unset)"})
            return {"status": "skipped", "message": "Forecast sheet isn't configured."}

        req, name = _request_and_person(employee_time_id)
        if req is None:
            raise ValueError(f"request {employee_time_id} not found")
        start, end = date.fromisoformat(req["start_date"]), date.fromisoformat(req["end_date"])
        half = req.get("half_day", "")
        base.update({"employee": name, "dates": f"{start}..{end}", "leave_type": req["time_type_code"],
                     "sheet": backend.label})

        plan = apply_to_grid(backend.read_all(), name, start, end, req["time_type_code"], half)
        if plan["error"]:
            log_forecast("failed", {**base, "error": plan["error"]}, level=logging.ERROR)
            session.log_activity("conflict", f"Couldn't update the leave forecast: {plan['error']}")
            return {"status": "failed", "message": plan["error"]}

        for row, col, new, _old in plan["updates"]:
            backend.write_cell(row, col, new)

        extra = ({"no_column_for": plan["missing_columns"]} if plan["missing_columns"] else {})
        if plan["updates"]:
            cells = [f"{gspread_cell(r, c)}='{v}'" for r, c, v, _ in plan["updates"]]
            log_forecast("updated", {**base, "cells": cells, **extra})
            session.log_activity("ok", f"Updated the leave forecast for {name}: "
                                       + ", ".join(v for _, _, v, _ in plan["updates"]))
            return {"status": "updated", "message": "Forecast sheet updated."}
        if plan["missing_columns"]:
            msg = f"The sheet has no column for {', '.join(plan['missing_columns'])}"
            log_forecast("failed", {**base, "error": msg}, level=logging.ERROR)
            session.log_activity("conflict", f"Couldn't update the leave forecast: {msg}")
            return {"status": "failed", "message": msg}
        log_forecast("unchanged", base)
        return {"status": "unchanged", "message": "Forecast sheet already had this leave."}
    except Exception as exc:   # sheet problems must never break an approval
        log_forecast("failed", {**base, "error_type": type(exc).__name__, "error": str(exc)[:300]}, level=logging.ERROR)
        session.log_activity("conflict", f"Couldn't update the leave forecast sheet: {str(exc)[:140]}")
        return {"status": "failed", "message": str(exc)[:300]}
