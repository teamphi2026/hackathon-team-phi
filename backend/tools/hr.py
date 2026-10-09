"""HR context tools (read-only) — Task 3.

Implements:
  - get_employee_profile()
  - get_dependents()
  - check_childcare_eligibility()
  - get_entitlements()
  - validate_policy(leave_type, start_date, end_date, half_day)

Session user_id is injected server-side via backend.state — these functions
never accept user_id as a parameter from the LLM. All business arithmetic
(working-day counts, balances, overlaps, eligibility) is deterministic here;
the LLM does none of it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

from ..config import data_file
from ..state import get_session

# ---------------------------------------------------------------------------
# Data access (cached CSV reads)
# ---------------------------------------------------------------------------

# Day-of-week index (Mon=0) -> work_schedule hours column.
_DOW_COLS = [
    "mon_hours",
    "tue_hours",
    "wed_hours",
    "thu_hours",
    "fri_hours",
    "sat_hours",
    "sun_hours",
]


@lru_cache(maxsize=None)
def _load(name: str) -> pd.DataFrame:
    return pd.read_csv(data_file(name), dtype=str).fillna("")


def _current_user_id() -> str:
    """Resolve the session user id. Never taken from the LLM."""
    return get_session().session_user_id


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# get_employee_profile
# ---------------------------------------------------------------------------

def get_employee_profile() -> dict[str, Any]:
    """Return the session user's job profile from Job_Information."""
    uid = _current_user_id()
    ji = _load("02_Job_Information.csv")
    row = ji[ji.user_id == uid]
    if row.empty:
        return {"error": f"No profile found for {uid}"}
    r = row.iloc[0]
    teams = [t.strip() for t in str(r.get("all_teams", "")).split(",") if t.strip()]
    return {
        "user_id": r["user_id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "home_team_id": r["home_team_id"],
        "job_title": r["job_title"],
        "employer": (r.get("employer", "") or "").strip() or None,   # legal employing entity
        "manager_id": r["manager_id"],
        "years_of_service": _to_num(r.get("years_of_service")),
        "teams": teams,
        "team_count": int(_to_num(r.get("team_count")) or 0),
        "time_profile_code": r["time_profile_code"],
        "work_schedule_code": r["work_schedule_code"],
        "holiday_calendar_code": r["holiday_calendar_code"],
        "project_id": r.get("project_id", "") or None,
    }


def _to_num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# get_dependents
# ---------------------------------------------------------------------------

def _age_on(dob: date, on: date) -> int:
    """Full years old on the given reference date."""
    years = on.year - dob.year
    if (on.month, on.day) < (dob.month, dob.day):
        years -= 1
    return years


def get_dependents(reference_year: int | None = None) -> list[dict[str, Any]]:
    """Return the session user's dependents with age computed from DOB.

    `age_at_jan1` is the age at 1 Jan of the leave year, which the Singapore
    Childcare Leave rules are keyed on.
    """
    uid = _current_user_id()
    year = reference_year or date.today().year
    jan1 = date(year, 1, 1)
    dep = _load("17_Dependents.csv")
    rows = dep[dep.user_id == uid]
    out: list[dict[str, Any]] = []
    for _, r in rows.iterrows():
        dob = _parse_date(r["date_of_birth"])
        out.append(
            {
                "dependent_id": r["dependent_id"],
                "name": r["name"],
                "date_of_birth": r["date_of_birth"],
                "relationship": r["relationship"],
                "age_today": _age_on(dob, date.today()),
                "age_at_jan1": _age_on(dob, jan1),
            }
        )
    return out


# ---------------------------------------------------------------------------
# check_childcare_eligibility
# ---------------------------------------------------------------------------

def _eval_rule(child_age_at_jan1: int, operator: str, value: float) -> bool:
    if operator == "<=":
        return child_age_at_jan1 <= value
    if operator == "<":
        return child_age_at_jan1 < value
    if operator == ">=":
        return child_age_at_jan1 >= value
    if operator == ">":
        return child_age_at_jan1 > value
    if operator in ("=", "=="):
        return child_age_at_jan1 == value
    return False


def check_childcare_eligibility(reference_year: int | None = None) -> dict[str, Any]:
    """Deterministic Childcare Leave eligibility from Dependents + Entitlement_Rules.

    Returns {eligible, quota_days, reason}. When the user has multiple
    children, the best-qualifying (highest quota) rule applies.
    """
    children = [d for d in get_dependents(reference_year) if d["relationship"].lower() == "child"]
    if not children:
        return {"eligible": False, "quota_days": 0, "reason": "No dependent children on record."}

    rules = _load("18_Entitlement_Rules.csv")
    cl_rules = rules[rules.time_type_code == "CL"]

    best_quota = 0
    best_reason = ""
    for child in children:
        age = child["age_at_jan1"]
        for _, rule in cl_rules.iterrows():
            if rule["condition_field"] != "child_age_at_jan1":
                continue
            if _eval_rule(age, rule["condition_operator"], float(rule["condition_value"])):
                quota = int(float(rule["annual_quota_days"]))
                if quota > best_quota:
                    best_quota = quota
                    best_reason = (
                        f"{child['name']} is {age} at 1 Jan "
                        f"({rule['condition_field']} {rule['condition_operator']} "
                        f"{rule['condition_value']}): {quota} days ({rule['notes']})."
                    )
                break  # rules ordered best-first per child

    if best_quota == 0:
        return {
            "eligible": False,
            "quota_days": 0,
            "reason": "Children on record do not meet any Childcare Leave age rule.",
        }
    return {"eligible": True, "quota_days": best_quota, "reason": best_reason}


# ---------------------------------------------------------------------------
# get_entitlements
# ---------------------------------------------------------------------------

def get_entitlements() -> dict[str, Any]:
    """Return live balances using account credits and authoritative request rows.

    For CL the available figure is gated on childcare eligibility.
    For OIL any credit expiring within 30 days is flagged.
    """
    from . import leave_queries
    requests = leave_queries.get_employee_leave_requests()
    pending = [r for r in requests["requests"] if r["status"] == leave_queries.PENDING]
    uid = _current_user_id()
    ta = _load("11_Time_Account.csv")
    # Read postings fresh, just like request statuses (CSV summaries are exports,
    # not formulas that recalculate when the application writes a request).
    detail = pd.read_csv(data_file("12_Time_Account_Detail.csv"), dtype=str).fillna("")
    tat = _load("06_Time_Account_Type.csv")
    type_name = dict(zip(tat.time_account_type_code, tat.time_account_type_name))

    # Account type -> bookable leave_type code (the value submit_leave_request wants).
    acc_to_leave = {v: k for k, v in _LEAVE_TO_ACCOUNT.items()}

    accounts: list[dict[str, Any]] = []
    rows = ta[(ta.user_id == uid) & (ta.account_closed != "Y")]
    for _, r in rows.iterrows():
        acc_type = r["time_account_type_code"]
        leave_type = acc_to_leave.get(acc_type, acc_type)
        relevant = [q for q in requests["requests"] if q["leave_type"] == leave_type
                    and r["account_valid_from"] <= q["start_date"] <= r["account_valid_until"]]
        reserved = sum(float(q["working_days"]) for q in relevant if q["status"] == leave_queries.PENDING)
        approved = [q for q in relevant if q["status"] == leave_queries.APPROVED]
        today = date.today().isoformat()
        credits = detail[(detail.time_account_id == r["time_account_id"])
                         & (detail.posting_type != "Employee Time")]
        # Some imported accounts (e.g. Childcare Leave) only have an opening
        # balance and no entitlement postings. Retain that opening credit.
        credited = (sum(_to_num(c["booking_amount"]) or 0.0 for _, c in credits.iterrows()
                        if c["booking_date"] <= today)
                    if not credits.empty else (_to_num(r["balance_today"]) or 0.0))
        # Count each Approved request exactly once. Legacy data contains duplicate
        # debit postings and even a debit for a Pending request; these must not
        # double-charge leave or override the authoritative request status.
        balance = credited - sum(float(q["working_days"]) for q in approved if q["start_date"] <= today)
        planned = -sum(float(q["working_days"]) for q in approved if q["start_date"] > today)
        available = round(balance + planned - reserved, 2)
        # Retain the imported future-accrual forecast while applying live usage.
        forecast_credit = (_to_num(r["projected_year_end"]) or 0.0) - (_to_num(r["available"]) or 0.0)
        entry: dict[str, Any] = {
            "time_account_id": r["time_account_id"],
            "account_type": acc_type,
            # Bookable leave-type code (e.g. "AL") so the agent maps names to codes.
            "leave_type": acc_to_leave.get(acc_type, acc_type),
            "account_name": type_name.get(acc_type, acc_type),
            "balance_today": round(balance, 2),
            "planned_bookings": planned,
            "pending_requests": reserved,  # days reserved, not a request count
            "pending_request_count": sum(q["status"] == leave_queries.PENDING for q in relevant),
            "available": available,
            "projected_year_end": round(available + forecast_credit, 2),
        }
        if acc_type == "ACC_CL":
            elig = check_childcare_eligibility()
            if not elig["eligible"]:
                entry["available"] = 0.0
                entry["note"] = f"Not eligible: {elig['reason']}"
            else:
                entry["note"] = elig["reason"]
        if acc_type == "ACC_OIL":
            entry["expiry_warning"] = _oil_expiry_warning(uid)
        accounts.append(entry)

    return {"user_id": uid, "accounts": accounts,
            "pending_request_count": len(pending), "pending_requests": pending,
            "balance_policy": "Pending leave is reserved from availability; only Approved leave is deducted."}


def _oil_expiry_warning(uid: str) -> str | None:
    """Flag OIL credits whose expiry_date is within 30 days (from Time_Account_Detail).

    Time_Account_Detail keys on time_account_id (not user_id), so the user's
    OIL account id is resolved from Time_Account first.
    """
    try:
        detail = _load("12_Time_Account_Detail.csv")
    except FileNotFoundError:
        return None
    if "expiry_date" not in detail.columns:
        return None

    ta = _load("11_Time_Account.csv")
    oil_account_ids = set(
        ta[(ta.user_id == uid) & (ta.time_account_type_code == "ACC_OIL")].time_account_id
    )
    if not oil_account_ids:
        return None

    today = date.today()
    soon = today + timedelta(days=30)
    rows = detail[detail.time_account_id.isin(oil_account_ids)]
    expiring = []
    for _, r in rows.iterrows():
        exp = str(r.get("expiry_date", "")).strip()
        if not exp:
            continue
        try:
            d = _parse_date(exp)
        except ValueError:
            continue
        if today <= d <= soon:
            expiring.append(exp)
    if expiring:
        return f"OIL credit expiring within 30 days on: {', '.join(sorted(set(expiring)))}"
    return None


# ---------------------------------------------------------------------------
# Working-day calculation
# ---------------------------------------------------------------------------

def _holidays(calendar_code: str) -> set[date]:
    hc = _load("10_Holiday_Calendar.csv")
    rows = hc[hc.holiday_calendar_code == calendar_code]
    return {_parse_date(d) for d in rows["date"]}


def _work_hours_by_dow(work_schedule_code: str) -> list[float]:
    ws = _load("09_Work_Schedule.csv")
    row = ws[ws.work_schedule_code == work_schedule_code]
    if row.empty:
        # Default to Mon-Fri if schedule unknown.
        return [8, 8, 8, 8, 8, 0, 0]
    r = row.iloc[0]
    return [_to_num(r[c]) or 0.0 for c in _DOW_COLS]


def count_working_days(
    start: date,
    end: date,
    work_schedule_code: str,
    calendar_code: str,
) -> int:
    """Count working days in [start, end] inclusive.

    A day counts if the work schedule assigns it hours AND it is not a public
    holiday for the user's calendar. In-lieu holidays are rows in the calendar
    and are therefore excluded like any other holiday.
    """
    hours = _work_hours_by_dow(work_schedule_code)
    holidays = _holidays(calendar_code)
    count = 0
    d = start
    while d <= end:
        if hours[d.weekday()] > 0 and d not in holidays:
            count += 1
        d += timedelta(days=1)
    return count


# ---------------------------------------------------------------------------
# validate_policy
# ---------------------------------------------------------------------------

_LEAVE_TO_ACCOUNT = {
    "AL": "ACC_AL",
    "OIL": "ACC_OIL",
    "SL": "ACC_SL",
    "HL": "ACC_HL",
    "CL": "ACC_CL",
}


def validate_policy(
    leave_type: str,
    start_date: str | date,
    end_date: str | date,
    half_day: str | bool | None = None,
) -> dict[str, Any]:
    """Deterministic validation of a proposed leave request.

    Checks: date range sanity, not in the past, leave type permitted by the
    user's Time_Profile, working-day count, sufficient balance, and no overlap
    with the user's existing non-cancelled requests.

    Returns {valid, working_days, remaining_after, violations}.
    """
    uid = _current_user_id()
    violations: list[str] = []

    try:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
    except (ValueError, TypeError):
        return {
            "valid": False,
            "working_days": 0,
            "remaining_after": None,
            "violations": ["Invalid date format; expected YYYY-MM-DD."],
        }

    if end < start:
        violations.append("End date is before start date.")
    if start < date.today():
        violations.append("Start date is in the past.")

    profile = get_employee_profile()
    if "error" in profile:
        return {
            "valid": False,
            "working_days": 0,
            "remaining_after": None,
            "violations": [profile["error"]],
        }

    # Leave type permitted by the user's time profile?
    tp = _load("08_Time_Profile.csv")
    allowed = set(
        tp[(tp.time_profile_code == profile["time_profile_code"]) & (tp.available_to_employee == "Y")]
        .time_type_code
    )
    if leave_type not in allowed:
        violations.append(
            f"{leave_type} is not available under time profile {profile['time_profile_code']}."
        )

    # Working-day count (half day = 0.5 of a single working day).
    is_half = str(half_day).strip().lower() in ("am", "pm", "true", "yes", "half")
    working_days: float = count_working_days(
        start, end, profile["work_schedule_code"], profile["holiday_calendar_code"]
    )
    if is_half:
        if start != end:
            violations.append("Half-day leave must be a single day.")
        working_days = 0.5 if working_days >= 1 else 0.0
    if working_days == 0 and not violations:
        violations.append("Requested range contains no working days.")

    # Balance check.
    remaining_after: float | None = None
    acc_type = _LEAVE_TO_ACCOUNT.get(leave_type)
    if acc_type:
        account = next((a for a in get_entitlements()["accounts"]
                        if a["account_type"] == acc_type), None)
        available = account["available"] if account else 0.0
        remaining_after = round(available - working_days, 2)
        if working_days > available:
            violations.append(
                f"Insufficient {leave_type} balance: {available} available, {working_days} requested."
            )

    # Overlap with existing non-cancelled/non-rejected requests.
    et = _load("13_Employee_Time.csv")
    active = et[
        (et.user_id == uid)
        & (~et.approval_status.isin(["Cancelled", "Rejected"]))
    ]
    for _, r in active.iterrows():
        try:
            r_start = _parse_date(r["start_date"])
            r_end = _parse_date(r["end_date"])
        except (ValueError, TypeError):
            continue
        if r_start <= end and start <= r_end:
            violations.append(
                f"Overlaps existing request {r['employee_time_id']} "
                f"({r['start_date']} to {r['end_date']}, {r['approval_status']})."
            )

    return {
        "valid": len(violations) == 0,
        "working_days": working_days,
        "remaining_after": remaining_after,
        "violations": violations,
        # Authoritative weekday-labelled range. The model must quote this
        # instead of working out weekdays itself (it gets them wrong).
        "date_label": format_date_range(start, end),
    }


def format_date_range(start: date, end: date) -> str:
    """Human label with weekdays, e.g. 'Tuesday 13 – Thursday 15 October 2026'."""
    def part(d: date, with_month: bool) -> str:
        base = f"{d.strftime('%A')} {d.day}"
        return f"{base} {d.strftime('%B %Y')}" if with_month else base

    if start == end:
        return part(start, True)
    if (start.year, start.month) == (end.year, end.month):
        return f"{part(start, False)} – {part(end, True)}"
    return f"{part(start, True)} – {part(end, True)}"
