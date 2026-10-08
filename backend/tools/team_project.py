"""Team / project context tools (read-only) — Task 4.

Implements:
  - get_team_leave(start_date, end_date)
  - check_coverage(start_date, end_date)
  - get_project_events(start_date, end_date)
  - find_viable_date_ranges(leave_type, duration_days, preferred_start, search_days)

All logic is deterministic. Session user_id comes from backend.state, never
from the LLM. Other employees' identities are anonymised to "Out of office"
in the tool output itself (not only in the UI).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

from ..config import data_file
from ..state import get_session
from . import hr

# Requests in these statuses do not occupy a person (don't reduce coverage).
_INACTIVE_STATUSES = {"Cancelled", "Rejected"}


@lru_cache(maxsize=None)
def _load(name: str) -> pd.DataFrame:
    return pd.read_csv(data_file(name), dtype=str).fillna("")


def _current_user_id() -> str:
    return get_session().session_user_id


def _parse(d: str | date) -> date:
    return hr._parse_date(d)


def _user_team_ids(uid: str) -> list[str]:
    tm = _load("04_Team_Members.csv")
    return list(tm[tm.user_id == uid].team_id.unique())


def _team_members(team_id: str) -> list[str]:
    tm = _load("04_Team_Members.csv")
    return list(tm[tm.team_id == team_id].user_id.unique())


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def _absences_in_range(start: date, end: date) -> pd.DataFrame:
    """Employee_Time rows (active statuses) overlapping [start, end]."""
    et = _load("13_Employee_Time.csv")
    active = et[~et.approval_status.isin(_INACTIVE_STATUSES)].copy()
    keep = []
    for _, r in active.iterrows():
        try:
            rs, re = _parse(r["start_date"]), _parse(r["end_date"])
        except (ValueError, TypeError):
            continue
        keep.append(_overlaps(start, end, rs, re))
    return active[pd.Series(keep, index=active.index)] if keep else active.iloc[0:0]


# ---------------------------------------------------------------------------
# get_team_leave
# ---------------------------------------------------------------------------

def get_team_leave(start_date: str | date, start_end: str | date | None = None,
                   end_date: str | date | None = None) -> dict[str, Any]:
    """Anonymised 'Out of office' list per team the session user belongs to.

    Signature accepts (start_date, end_date); the middle positional is tolerated
    for callers that pass dates positionally.
    """
    end = end_date if end_date is not None else start_end
    start, end = _parse(start_date), _parse(end)
    uid = _current_user_id()
    teams = _user_team_ids(uid)
    absences = _absences_in_range(start, end)

    result: list[dict[str, Any]] = []
    for team_id in teams:
        members = set(_team_members(team_id))
        out_rows = absences[absences.user_id.isin(members)]
        entries = []
        for _, r in out_rows.iterrows():
            entries.append(
                {
                    "label": "Out of office",  # anonymised in the tool output
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                    "status": r["approval_status"],
                }
            )
        result.append({"team_id": team_id, "out_of_office": entries})
    return {"start_date": str(start), "end_date": str(end), "teams": result}


# ---------------------------------------------------------------------------
# check_coverage
# ---------------------------------------------------------------------------

def check_coverage(start_date: str | date, end_date: str | date,
                   include_self: bool = True) -> dict[str, Any]:
    """Coverage status per team for the session user's teams over [start, end].

    absent = team members with an active request overlapping the range,
             plus the session user (counted as taking this proposed leave).
    status = OK if on_duty > min, AT_MIN if on_duty == min, SHORT if below.
    """
    start, end = _parse(start_date), _parse(end_date)
    uid = _current_user_id()
    teams = _load("03_Teams.csv")
    absences = _absences_in_range(start, end)
    absent_users = set(absences.user_id.unique())

    out: list[dict[str, Any]] = []
    for team_id in _user_team_ids(uid):
        trow = teams[teams.team_id == team_id]
        if trow.empty:
            continue
        trow = trow.iloc[0]
        headcount = int(float(trow["headcount"]))
        min_required = int(float(trow["min_staff_on_duty"]))
        members = set(_team_members(team_id))

        absent = {u for u in absent_users if u in members}
        if include_self:
            absent.add(uid)  # the session user is proposing to be away
        on_duty = headcount - len(absent)

        if on_duty > min_required:
            status = "OK"
        elif on_duty == min_required:
            status = "AT_MIN"
        else:
            status = "SHORT"

        out.append(
            {
                "team_id": team_id,
                "team_name": trow["team_name"],
                "headcount": headcount,
                "on_duty": on_duty,
                "min_required": min_required,
                "status": status,
            }
        )
    return {"start_date": str(start), "end_date": str(end), "teams": out}


def _worst_status(coverage: dict[str, Any]) -> str:
    order = {"OK": 0, "AT_MIN": 1, "SHORT": 2}
    worst = "OK"
    for t in coverage["teams"]:
        if order[t["status"]] > order[worst]:
            worst = t["status"]
    return worst


# ---------------------------------------------------------------------------
# get_project_events
# ---------------------------------------------------------------------------

def get_project_events(start_date: str | date, end_date: str | date) -> dict[str, Any]:
    """Project events overlapping [start, end] for the session user's project."""
    start, end = _parse(start_date), _parse(end_date)
    profile = hr.get_employee_profile()
    project_id = profile.get("project_id")
    if not project_id:
        return {"project_id": None, "events": []}

    pe = _load("19_Project_Events.csv")
    rows = pe[pe.project_id == project_id]
    events = []
    for _, r in rows.iterrows():
        try:
            es, ee = _parse(r["start_date"]), _parse(r["end_date"])
        except (ValueError, TypeError):
            continue
        if _overlaps(start, end, es, ee):
            events.append(
                {
                    "event_id": r["event_id"],
                    "event_type": r["event_type"],
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                    "description": r["description"],
                }
            )
    return {"project_id": project_id, "events": events}


# ---------------------------------------------------------------------------
# find_viable_date_ranges
# ---------------------------------------------------------------------------

def find_viable_date_ranges(
    leave_type: str,
    duration_days: int,
    preferred_start: str | date,
    search_days: int = 21,
) -> dict[str, Any]:
    """Search candidate windows outward from preferred_start.

    A candidate passes the pre-filter when:
      1. working_days == duration_days (so the window delivers the ask)
      2. sufficient balance for leave_type
      3. every team is OK or AT_MIN (never SHORT)
      4. no overlap with the user's existing requests
      5. within the current leave year

    Returns up to 3 candidates with coverage, project events, and a reason string.
    The agent chooses among these; it does not re-filter.
    """
    preferred = _parse(preferred_start)
    profile = hr.get_employee_profile()
    ws = profile["work_schedule_code"]
    cal = profile["holiday_calendar_code"]
    year_end = date(preferred.year, 12, 31)

    # Build an outward-ordered list of candidate start dates: preferred, +1, -1, +2 ...
    offsets = [0]
    for i in range(1, search_days + 1):
        offsets.extend([i, -i])

    candidates: list[dict[str, Any]] = []
    seen: set[date] = set()
    for off in offsets:
        cstart = preferred + timedelta(days=off)
        if cstart in seen or cstart < date.today() or cstart > year_end:
            continue
        seen.add(cstart)

        # Grow the window until it contains `duration_days` working days.
        cend = cstart
        wd = hr.count_working_days(cstart, cend, ws, cal)
        guard = 0
        while wd < duration_days and guard < 30:
            cend += timedelta(days=1)
            wd = hr.count_working_days(cstart, cend, ws, cal)
            guard += 1
        if wd != duration_days or cend > year_end:
            continue
        # Candidate must start on a working day (no leading weekend/holiday).
        if hr.count_working_days(cstart, cstart, ws, cal) == 0:
            continue

        validation = hr.validate_policy(leave_type, cstart, cend)
        if not validation["valid"]:
            continue

        coverage = check_coverage(cstart, cend)
        if _worst_status(coverage) == "SHORT":
            continue

        events = get_project_events(cstart, cend)
        reason = _reason_string(cstart, cend, duration_days, coverage, events)
        candidates.append(
            {
                "start_date": str(cstart),
                "end_date": str(cend),
                "working_days": duration_days,
                "coverage": coverage["teams"],
                "project_events": events["events"],
                "reason": reason,
            }
        )
        if len(candidates) >= 3:
            break

    return {
        "leave_type": leave_type,
        "duration_days": duration_days,
        "preferred_start": str(preferred),
        "candidates": candidates,
    }


def _reason_string(start, end, days, coverage, events) -> str:
    worst = _worst_status(coverage)
    cover_txt = "all teams covered" if worst == "OK" else "teams at minimum staffing but covered"
    ev_txt = ""
    if events["events"]:
        ev_txt = " Note: " + "; ".join(e["description"] for e in events["events"]) + "."
    return (
        f"{start} to {end} ({days} working day(s)): {cover_txt}, no conflicts "
        f"with your existing leave.{ev_txt}"
    )
