"""Team / project context tools (read-only) — Task 4.

Implements:
  - get_team_leave(start_date, end_date)
  - check_coverage(start_date, end_date)
  - get_project_events(start_date, end_date)
  - find_viable_date_ranges(leave_type, duration_days, preferred_start, search_days)

All logic is deterministic. Session user_id comes from backend.state, never
from the LLM. Chat team leave exposes names and absence dates only for the
session user's teams. Private leave types, reasons, employee ids and contact
details are omitted from the chat tool.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

from .. import storage
from ..state import get_session
from . import hr

# Requests in these statuses do not occupy a person (don't reduce coverage).
_INACTIVE_STATUSES = {"Cancelled", "Rejected"}


@lru_cache(maxsize=None)
def _load_csv(name: str) -> pd.DataFrame:
    return storage.dataframe(name)


def _load(name: str) -> pd.DataFrame:
    return storage.dataframe(name) if storage.using_sheets() else _load_csv(name)


_load.cache_clear = _load_csv.cache_clear


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
    """Named availability list per team the session user belongs to.

    Signature accepts (start_date, end_date); the middle positional is tolerated
    for callers that pass dates positionally.
    """
    end = end_date if end_date is not None else start_end
    start, end = _parse(start_date), _parse(end)
    uid = _current_user_id()
    teams = _user_team_ids(uid)
    absences = _absences_in_range(start, end)

    names = _employee_names()
    result: list[dict[str, Any]] = []
    for team_id in teams:
        members = set(_team_members(team_id))
        out_rows = absences[absences.user_id.isin(members)]
        entries = []
        for _, r in out_rows.iterrows():
            entries.append(
                {
                    "label": "Out of office",
                    "name": names.get(r["user_id"], "Team member"),
                    "is_self": r["user_id"] == uid,
                    "half_day": r["half_day"],
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

    # Search forward from the preferred start first (people rarely want
    # earlier-than-requested dates), then fall back to earlier days.
    offsets = list(range(0, search_days + 1)) + [-i for i in range(1, search_days + 1)]

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


# ---------------------------------------------------------------------------
# get_team_calendar — month view with named entries + per-day coverage
# ---------------------------------------------------------------------------

def _employee_names() -> dict[str, str]:
    ji = _load("02_Job_Information.csv")
    return dict(zip(ji.user_id, ji.full_name))


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return first, nxt - timedelta(days=1)


def get_team_calendar(year: int, month: int) -> dict[str, Any]:
    """Month calendar for the session user's teams.

    Returns, for each team the user belongs to:
      - team metadata (name, headcount, min_staff_on_duty)
      - named leave entries overlapping the month (who, type, dates, status)
      - per-day coverage status (OK / AT_MIN / SHORT) for colouring

    Like the chat availability tool, only the user's own teams are exposed.
    This first-party calendar additionally includes leave types and employee ids.
    """
    uid = _current_user_id()
    start, end = _month_bounds(year, month)
    names = _employee_names()
    teams_df = _load("03_Teams.csv")
    types_df = _load("05_Time_Type.csv")
    type_name = dict(zip(types_df.time_type_code, types_df.time_type_name))

    absences = _absences_in_range(start, end)

    # Working-day rules come from the viewer's work schedule + holiday calendar.
    profile = hr.get_employee_profile()
    work_hours = hr._work_hours_by_dow(profile.get("work_schedule_code", "SG_STD"))
    hol = _load("10_Holiday_Calendar.csv")
    hol = hol[hol.holiday_calendar_code == profile.get("holiday_calendar_code", "SG")]
    holiday_names = {_parse(r["date"]): r["holiday_name"] for _, r in hol.iterrows()}

    teams_out: list[dict[str, Any]] = []
    for team_id in _user_team_ids(uid):
        trow = teams_df[teams_df.team_id == team_id]
        if trow.empty:
            continue
        trow = trow.iloc[0]
        headcount = int(float(trow["headcount"]))
        min_required = int(float(trow["min_staff_on_duty"]))
        members = set(_team_members(team_id))

        # Named leave entries for this team's members, overlapping the month.
        team_abs = absences[absences.user_id.isin(members)]
        entries = []
        for _, r in team_abs.iterrows():
            entries.append(
                {
                    "user_id": r["user_id"],
                    "name": names.get(r["user_id"], r["user_id"]),
                    "leave_type": r["time_type_code"],
                    "leave_type_name": type_name.get(r["time_type_code"], r["time_type_code"]),
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                    "status": r["approval_status"],
                    "is_self": r["user_id"] == uid,
                }
            )

        # Per-day coverage across the month (for day colouring).
        # Rules (mirrors hr_data/15_Leave_Calendar.csv):
        #   * only WORKING days are assessed; weekends and public holidays are
        #     NON_WORKING (no coverage rule applies, nobody is "off")
        #   * on_duty = headcount - DISTINCT people with an active request that
        #     covers the day (two overlapping requests by one person count once)
        #   * OK if on_duty > min, AT_MIN if == min, SHORT if < min
        spans: list[tuple[str, date, date]] = []
        for _, r in team_abs.iterrows():
            try:
                spans.append((r["user_id"], _parse(r["start_date"]), _parse(r["end_date"])))
            except (ValueError, TypeError):
                continue

        day_status: dict[str, str] = {}
        day_on_duty: dict[str, int] = {}
        day_type: dict[str, str] = {}
        day_label: dict[str, str] = {}
        d = start
        while d <= end:
            key = d.isoformat()
            if d in holiday_names:
                day_type[key], day_label[key] = "HOLIDAY", holiday_names[d]
                day_status[key] = "NON_WORKING"
            elif work_hours[d.weekday()] <= 0:
                day_type[key], day_label[key] = "WEEKEND", "Weekend"
                day_status[key] = "NON_WORKING"
            else:
                absent = {uid_ for uid_, rs, re in spans if rs <= d <= re}
                on_duty = headcount - len(absent)
                if on_duty > min_required:
                    status = "OK"
                elif on_duty == min_required:
                    status = "AT_MIN"
                else:
                    status = "SHORT"
                day_type[key], day_status[key], day_on_duty[key] = "WORKING", status, on_duty
            d += timedelta(days=1)

        teams_out.append(
            {
                "team_id": team_id,
                "team_name": trow["team_name"],
                "headcount": headcount,
                "min_required": min_required,
                "entries": entries,
                "day_status": day_status,
                "day_on_duty": day_on_duty,
                "day_type": day_type,
                "day_label": day_label,
            }
        )

    return {
        "year": year,
        "month": month,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "teams": teams_out,
    }
