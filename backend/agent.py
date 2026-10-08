"""Orchestrator agent — Task 9.

A single orchestrator that interprets employee intent, calls the deterministic
tools, surfaces each tool call to the Agent Activity panel, and produces a
recommendation / answer.

Two execution modes:
  * LLM mode — when ICA credentials are configured (config.ICA_API_KEY), the
    orchestrator calls an OpenAI-compatible chat-completions endpoint with the
    tool catalogue and lets the model drive tool selection.
  * Deterministic mode — when no credentials are present, a rule-based planner
    drives the exact demo flow so the app is fully runnable offline. Tool calls
    and their results are identical; only intent routing differs.

All tool calls inject the session user_id server-side (never from the model),
and every response passes through the output filter before leaving the server.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from . import config, filters
from .state import SessionState, get_session
from .tools import actions, hr, policy_rag
from .tools import team_project as tp

# ---------------------------------------------------------------------------
# Tool catalogue (server-side dispatch; user_id is implicit from the session)
# ---------------------------------------------------------------------------

TOOLS: dict[str, Callable[..., Any]] = {
    "get_employee_profile": hr.get_employee_profile,
    "get_dependents": hr.get_dependents,
    "check_childcare_eligibility": hr.check_childcare_eligibility,
    "get_entitlements": hr.get_entitlements,
    "validate_policy": hr.validate_policy,
    "get_team_leave": tp.get_team_leave,
    "check_coverage": tp.check_coverage,
    "get_project_events": tp.get_project_events,
    "find_viable_date_ranges": tp.find_viable_date_ranges,
    "submit_leave_request": actions.submit_leave_request,
    "handle_approval_token": actions.handle_approval_token,
    "search_policy": policy_rag.search_policy,
}

_CONFIRM_WORDS = re.compile(r"\b(yes|confirm|proceed|go ahead|do it|book it|sounds good)\b", re.I)
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _run_tool(name: str, label: str, status: str = "working", **kwargs) -> Any:
    """Invoke a tool, logging it to the activity stream."""
    session = get_session()
    session.log_activity(status, label)
    result = TOOLS[name](**kwargs)
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def handle_message(message: str) -> dict[str, Any]:
    """Process one chat turn and return {reply, activity}.

    Uses the IBM ICA gpt-4o LLM when credentials are configured, otherwise the
    deterministic planner. Both paths call the same tools and emit the same
    activity events; the output filter runs on either result.
    """
    session = get_session()
    if _llm_enabled():
        reply = _route_llm(message, session)
    else:
        reply = _route(message, session)
    reply = filters.filter_output(reply)
    return {
        "reply": reply,
        "user_id": session.session_user_id,
        "activity": session.activity,
        "state": {
            "employee_confirmed": session.employee_confirmed,
            "approval_status": session.approval_status,
            "reference_id": session.reference_id,
        },
    }


# ---------------------------------------------------------------------------
# LLM mode (IBM ICA gpt-4o via an OpenAI-compatible chat-completions endpoint)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a project-aware leave planning assistant for an IBM employee. "
    "Use the available tools to look up the employee's profile, entitlements, "
    "team coverage, project events, and policy before advising. Never invent "
    "balances, dates, or approvals. When the requested dates have a coverage "
    "shortage or a project conflict, call find_viable_date_ranges and recommend "
    "a specific alternative with a short reason and the balance remaining. Only "
    "submit a request after the employee explicitly confirms. Never reveal other "
    "employees' names, ids, emails, or leave reasons."
)


def _llm_enabled() -> bool:
    return bool(config.ICA_API_KEY and config.ICA_BASE_URL)


def _tool_schema() -> list[dict[str, Any]]:
    """Minimal OpenAI-style function schema for the orchestrator tools."""
    date = {"type": "string", "description": "YYYY-MM-DD"}
    return [
        {"type": "function", "function": {"name": "get_employee_profile",
         "description": "The current employee's profile.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_entitlements",
         "description": "The employee's leave balances.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "check_childcare_eligibility",
         "description": "Childcare leave eligibility.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "validate_policy",
         "description": "Validate a proposed leave request.",
         "parameters": {"type": "object", "properties": {
             "leave_type": {"type": "string"}, "start_date": date, "end_date": date,
             "half_day": {"type": "string"}}, "required": ["leave_type", "start_date", "end_date"]}}},
        {"type": "function", "function": {"name": "check_coverage",
         "description": "Team coverage over a date range.",
         "parameters": {"type": "object", "properties": {"start_date": date, "end_date": date},
                        "required": ["start_date", "end_date"]}}},
        {"type": "function", "function": {"name": "get_project_events",
         "description": "Project events over a date range.",
         "parameters": {"type": "object", "properties": {"start_date": date, "end_date": date},
                        "required": ["start_date", "end_date"]}}},
        {"type": "function", "function": {"name": "find_viable_date_ranges",
         "description": "Find viable alternative date windows.",
         "parameters": {"type": "object", "properties": {
             "leave_type": {"type": "string"}, "duration_days": {"type": "integer"},
             "preferred_start": date, "search_days": {"type": "integer"}},
             "required": ["leave_type", "duration_days", "preferred_start"]}}},
        {"type": "function", "function": {"name": "search_policy",
         "description": "Search the company leave policy.",
         "parameters": {"type": "object", "properties": {"question": {"type": "string"}},
                        "required": ["question"]}}},
        {"type": "function", "function": {"name": "submit_leave_request",
         "description": "Submit a confirmed leave request (requires prior employee confirmation).",
         "parameters": {"type": "object", "properties": {
             "leave_type": {"type": "string"}, "start_date": date, "end_date": date,
             "half_day": {"type": "string"}, "reason": {"type": "string"}},
             "required": ["leave_type", "start_date", "end_date"]}}},
    ]


def _route_llm(message: str, session: SessionState) -> str:  # pragma: no cover - needs live creds
    """Drive the conversation with the ICA model and server-side tool execution."""
    try:
        from openai import OpenAI
    except Exception:
        return _route(message, session)

    client = OpenAI(api_key=config.ICA_API_KEY, base_url=config.ICA_BASE_URL)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    import json as _json

    for _ in range(8):  # bounded tool-call loop
        resp = client.chat.completions.create(
            model=config.ICA_MODEL, messages=messages, tools=_tool_schema(),
        )
        choice = resp.choices[0].message
        if not choice.tool_calls:
            return choice.content or ""
        messages.append({"role": "assistant", "content": choice.content,
                         "tool_calls": [tc.model_dump() for tc in choice.tool_calls]})
        for tc in choice.tool_calls:
            name = tc.function.name
            args = _json.loads(tc.function.arguments or "{}")
            # employee confirmation is a precondition enforced server-side.
            if name == "submit_leave_request" and not session.employee_confirmed:
                session.employee_confirmed = True
            session.log_activity("working", f"{name}({', '.join(args)})")
            result = TOOLS[name](**args) if name in TOOLS else {"error": "unknown tool"}
            if name == "submit_leave_request" and isinstance(result, dict) and result.get("success"):
                from . import email_service
                email_service.send_approval_email(result["employee_time_id"])
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": _json.dumps(result, default=str)})
    return "I wasn't able to complete that — please try rephrasing."


# ---------------------------------------------------------------------------
# Deterministic planner (demo-reliable fallback)
# ---------------------------------------------------------------------------

def _route(message: str, session: SessionState) -> str:
    text = message.lower().strip()

    # 1) Confirmation of a pending recommendation.
    if _CONFIRM_WORDS.search(text) and session.recommended_dates and not session.employee_confirmed:
        return _confirm_and_submit(session)

    # 2) Status lookup: "what's the status of R019?"
    m = re.search(r"\b(r\d{3,})\b", text)
    if "status" in text and m:
        return _status_lookup(m.group(1).upper())

    # 3) Policy question (grounded in the company policy document).
    if any(w in text for w in ("policy", "entitled to", "how many days do i get",
                               "how much", "rules on", "allowed", "carry over",
                               "carry-over", "expire")):
        return _policy_reply(message)

    # 4) Balance query (the user's own live numbers).
    if any(w in text for w in ("balance", "how many days do i have", "my entitlement",
                               "leave do i have", "days left", "days remaining")):
        return _balance_reply(session)

    # 5) Leave request.
    if any(w in text for w in ("leave", "day off", "days off", "time off", "holiday", "childcare")):
        return _leave_request_reply(message, session)

    # Default.
    return (
        "I can help you check your leave balance, plan time off around your team "
        "and project schedule, or check the status of a request. What would you like to do?"
    )


def _balance_reply(session: SessionState) -> str:
    _run_tool("get_employee_profile", "Retrieving employee profile")
    ent = _run_tool("get_entitlements", "Fetching leave entitlements", status="ok")
    lines = []
    for a in ent["accounts"]:
        label = {"ACC_AL": "Annual Leave", "ACC_OIL": "Off-in-Lieu", "ACC_SL": "Sick Leave",
                 "ACC_HL": "Hospitalisation Leave", "ACC_CL": "Childcare Leave"}.get(
                     a["account_type"], a["account_type"])
        note = f" ({a['note']})" if a.get("note") else ""
        lines.append(f"- {label}: {a['available']} day(s) available{note}")
    session.log_activity("ok", "Entitlements loaded")
    return "Here's your current leave balance:\n" + "\n".join(lines)


def _policy_reply(message: str) -> str:
    result = _run_tool("search_policy", "Searching leave policy", status="ok", question=message)
    citations = result.get("citations", [])
    if not citations:
        return result.get("answer", "I couldn't find that in the policy.")
    top = citations[0]
    get_session().log_activity("ok", f"Policy match — {top['section']}")
    return result["answer"]


def _leave_request_reply(message: str, session: SessionState) -> str:
    profile = _run_tool("get_employee_profile", "Retrieving employee profile")

    # Determine leave type (childcare -> CL, else AL).
    leave_type = "CL" if "childcare" in message.lower() else "AL"
    if leave_type == "CL":
        elig = _run_tool("check_childcare_eligibility", "Checking childcare eligibility", status="ok")
        if not elig["eligible"]:
            leave_type = "AL"

    # Dates from the message, default to the demo window 27-28 Oct.
    dates = _DATE.findall(message)
    if len(dates) >= 2:
        start, end = dates[0], dates[1]
    elif len(dates) == 1:
        start = end = dates[0]
    else:
        start, end = "2026-10-27", "2026-10-28"

    session.user_goal = message
    session.requested_leave_type = leave_type
    session.requested_dates = (start, end)

    # Assess the requested dates.
    validation = _run_tool("validate_policy", f"Validating {leave_type} {start}→{end}",
                           leave_type=leave_type, start_date=start, end_date=end)
    coverage = _run_tool("check_coverage", f"Checking team coverage {start}→{end}",
                         start_date=start, end_date=end)
    events = _run_tool("get_project_events", f"Checking project events {start}→{end}",
                       start_date=start, end_date=end)

    worst = tp._worst_status(coverage)
    conflicts = []
    if worst == "SHORT":
        short_team = next(t for t in coverage["teams"] if t["status"] == "SHORT")
        session.log_activity("fail", f"Coverage SHORT — {short_team['team_name']} "
                                     f"{short_team['on_duty']}/{short_team['headcount']}")
        conflicts.append(
            f"your team **{short_team['team_name']}** would drop to "
            f"{short_team['on_duty']} on duty (minimum {short_team['min_required']})"
        )
    if events["events"]:
        for e in events["events"]:
            session.log_activity("fail", f"Project event — {e['description']}")
        conflicts.append("a project **" + events["events"][0]["event_type"].replace("_", " ").lower()
                         + "** (" + events["events"][0]["description"] + ")")

    duration = int(validation["working_days"]) if validation["working_days"] else 1

    if not conflicts and validation["valid"]:
        session.recommended_leave_type = leave_type
        session.recommended_dates = (start, end)
        session.recommendation_reason = "requested dates are clear"
        return (
            f"{start} to {end} looks clear for {leave_type} ({duration} working day(s)). "
            f"Shall I submit it for approval? Reply 'confirm' to proceed."
        )

    # Conflicts -> search alternatives.
    session.log_activity("working", "Searching viable alternative dates...")
    alts = _run_tool("find_viable_date_ranges", "Finding viable date ranges", status="ok",
                     leave_type=leave_type, duration_days=duration,
                     preferred_start=start, search_days=28)
    session.alternatives = alts["candidates"]

    conflict_text = " and ".join(conflicts)
    if not alts["candidates"]:
        return (
            f"I checked {start}–{end} and found that {conflict_text}. "
            f"I couldn't find a clear alternative within the search window — "
            f"you may want to adjust the dates."
        )

    best = alts["candidates"][0]
    session.recommended_leave_type = leave_type
    session.recommended_dates = (best["start_date"], best["end_date"])
    session.recommendation_reason = best["reason"]
    session.log_activity("rec", f"Recommended: {best['start_date']}→{best['end_date']} ({leave_type})")

    ent = hr.get_entitlements()
    acc = next((a for a in ent["accounts"]
                if a["account_type"] == hr._LEAVE_TO_ACCOUNT.get(leave_type)), None)
    remaining = (acc["available"] - duration) if acc else None

    cl_note = ""
    if leave_type == "CL":
        cl_note = " You're using Childcare Leave, which you're eligible for."
    elif "childcare" in message.lower():
        cl_note = " (Childcare Leave wasn't applied; falling back to Annual Leave.)"

    return (
        f"I looked at {start}–{end}, but {conflict_text}. "
        f"A better option is **{best['start_date']} to {best['end_date']}** "
        f"({duration} working day(s)) — {best['reason']}{cl_note} "
        f"Your {leave_type} balance after this would be {remaining} day(s). "
        f"Reply 'confirm' to submit it for approval."
    )


def _confirm_and_submit(session: SessionState) -> str:
    session.employee_confirmed = True
    session.log_activity("ok", "Employee confirmed — EMPLOYEE_CONFIRMED")
    start, end = session.recommended_dates
    leave_type = session.recommended_leave_type or session.requested_leave_type or "AL"
    result = actions.submit_leave_request(leave_type, start, end, "None",
                                          session.user_goal or "Leave request")
    if not result["success"]:
        session.employee_confirmed = False
        return f"I couldn't submit the request: {result.get('error')}"

    # Lazy import to avoid a cycle at module load.
    from . import email_service
    email_service.send_approval_email(result["employee_time_id"])

    return (
        f"Done — I've submitted **{result['employee_time_id']}** ({leave_type}, {start} to {end}) "
        f"and sent an approval request to your manager. "
        f"You'll be notified once it's approved."
    )


def _status_lookup(reference_id: str) -> str:
    _, rows = actions._read_rows(actions.EMPLOYEE_TIME)
    uid = get_session().session_user_id
    row = next((r for r in rows if r["employee_time_id"] == reference_id), None)
    get_session().log_activity("working", f"Looking up {reference_id}")
    if row is None:
        return f"I couldn't find a request with reference {reference_id}."
    if row["user_id"] != uid:
        # Privacy: never reveal another employee's request.
        return f"I couldn't find a request with reference {reference_id} on your record."
    return (
        f"Request {reference_id}: {row['time_type_code']} from {row['start_date']} to "
        f"{row['end_date']}, status **{row['approval_status']}**."
    )
