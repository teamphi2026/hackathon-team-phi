"""Plain-English wording for the Agent Activity panel.

`describe(name, args, result)` turns a finished tool call into one short
sentence ("Checked your leave balances: Annual Leave has 9 days available")
plus a status used for the icon/colour: ok | fail | info | rec.

Returns None for tools that already log their own activity line (so the panel
doesn't show the same step twice). Pure formatting: no side effects.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .tools import hr

LEAVE_NAMES = {
    "AL": "Annual Leave", "CL": "Childcare Leave", "SL": "Sick Leave",
    "HL": "Hospitalisation Leave", "OIL": "Off-in-Lieu", "ECL": "Extended Childcare Leave",
}


def _leave(code: Any) -> str:
    return LEAVE_NAMES.get(str(code or "").upper(), str(code or "leave"))


def _days(n: Any) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    f = int(f) if f == int(f) else f
    return f"{f} day" + ("" if f == 1 else "s")


def _range(args: dict[str, Any]) -> str:
    """'Tuesday 13 – Thursday 15 October 2026' from start/end args (best effort)."""
    try:
        s = date.fromisoformat(str(args.get("start_date") or args.get("preferred_start")))
        e = date.fromisoformat(str(args.get("end_date") or s))
        return hr.format_date_range(s, e)
    except (TypeError, ValueError):
        return "those dates"


def describe(name: str, args: dict[str, Any], result: Any) -> tuple[str, str] | None:
    """Return (status, sentence) for a finished tool call, or None to skip."""
    r = result if isinstance(result, dict) else {}

    if name == "get_employee_profile":
        if "error" in r:
            return "fail", "Couldn't find your employee profile"
        bits = [b for b in (r.get("job_title"), r.get("employer")) if b]
        return "ok", "Looked up your profile" + (f" ({', '.join(bits)})" if bits else "")

    if name == "get_entitlements":
        accounts = r.get("accounts", [])
        al = next((a for a in accounts if a.get("leave_type") == "AL"), None)
        extra = f": Annual Leave has {_days(al['available'])} available" if al else ""
        return "ok", "Checked your leave balances" + extra

    if name == "check_childcare_eligibility":
        return "ok", ("Checked Childcare Leave eligibility: you're eligible"
                      if r.get("eligible") else
                      "Checked Childcare Leave eligibility: you're not eligible")

    if name == "get_dependents":
        return "ok", "Reviewed the dependents on your record"

    if name == "validate_policy":
        what = f"{_leave(args.get('leave_type'))} request for {_range(args)}"
        if r.get("valid"):
            left = r.get("remaining_after")
            tail = f", leaving {_days(left)}" if left is not None else ""
            return "ok", f"Checked your {what} against leave policy: valid, {_days(r.get('working_days'))} of leave{tail}"
        why = (r.get("violations") or ["it doesn't meet policy"])[0]
        return "fail", f"Checked your {what} against leave policy: {why}"

    if name == "check_coverage":
        teams = r.get("teams", [])
        if not teams:
            return "info", "Checked team coverage: you're not on a team with a staffing minimum"
        order = {"OK": 0, "AT_MIN": 1, "SHORT": 2}
        t = max(teams, key=lambda x: order.get(x["status"], 0))
        base = (f"Team {t['team_name']} would have {t['on_duty']} of {t['headcount']} people on duty "
                f"(minimum {t['min_required']})")
        if t["status"] == "SHORT":
            return "fail", f"{base}: not enough cover"
        if t["status"] == "AT_MIN":
            return "ok", f"{base}: covered, but right at the minimum"
        return "ok", f"{base}: well covered"

    if name == "get_project_events":
        events = r.get("events", [])
        if not events:
            return "ok", f"Checked project calendar for {_range(args)}: no freezes or milestones in the way"
        e = events[0]
        kind = str(e.get("event_type", "event")).replace("_", " ").lower()
        more = f" (+{len(events) - 1} more)" if len(events) > 1 else ""
        return "fail", f"Found a project {kind} overlapping those dates: {e.get('description', '')}{more}"

    if name == "get_team_leave":
        return "ok", "Checked who on your team is out of office"

    if name == "find_viable_date_ranges":
        n = len(r.get("candidates", []))
        return (("ok", f"Searched nearby dates for a window with enough cover: found {n} option" + ("" if n == 1 else "s"))
                if n else ("fail", "Searched nearby dates but found no window with enough cover"))

    if name == "search_policy":
        cites = r.get("citations", [])
        who = r.get("employer") or "your employer"
        if not cites:
            return "info", f"Searched the {who} leave policy: nothing relevant found"
        return "ok", f"Searched the {who} leave policy: matched the '{cites[0]['section']}' section"

    if name == "get_request_status":
        if not r.get("found"):
            ref = args.get("reference_id")
            return "info", f"Looked up request {str(ref).upper()}: not found on your record" if ref \
                else "Looked up your requests: none on record"
        first = r["requests"][0]
        if args.get("reference_id"):
            wait = f", waiting on {first['awaiting_approval_from']}" if first.get("awaiting_approval_from") else ""
            return "ok", f"Looked up request {first['reference_id']}: {first['status']}{wait}"
        return "ok", f"Looked up your {len(r['requests'])} most recent request" + ("" if len(r["requests"]) == 1 else "s")

    if name == "submit_leave_request":
        if r.get("success"):
            return None   # actions.submit_leave_request already logs this step
        return "fail", f"Couldn't submit the request: {r.get('error', 'unknown problem')}"

    return "info", "Ran " + name.replace("_", " ")
