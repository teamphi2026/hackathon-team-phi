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
from datetime import date, datetime
from typing import Any, Callable

from . import config, filters
from .state import SessionState, get_session
from .tool_logger import call_tool, log_intent, log_llm_call
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

# Default leave year used when the user omits the year (demo data is 2026).
_DEFAULT_YEAR = 2026

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# ISO:               2026-10-12
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
# Day Month [Year]:  10 Oct 2026 | 10 October | 10th Oct
_DMY = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})(?:\s+(\d{4}))?\b", re.I
)
# Month Day [Year]:  Oct 10 2026 | October 10, 2026
_MDY = re.compile(
    r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.I
)
# Numeric slash:     12/10/2026 | 12-10-2026  (day/month/year, SG convention)
_SLASH = re.compile(r"\b(\d{1,2})[/](\d{1,2})[/](\d{2,4})\b")
# Shared-month range: '20 to 27 Oct 2026' | '20-27 October' (first day borrows
# the month/year from the second).
_RANGE_SHARED_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:-|–|to|until|till|through|thru)\s*"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})(?:\s+(\d{4}))?\b",
    re.I,
)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_dates(message: str) -> list[str]:
    """Extract dates from free text, returned as ISO strings in reading order.

    Handles ISO (2026-10-12), '10 Oct 2026', 'October 10', '12/10/2026', and
    bare day-month without a year (assumes the demo leave year). Deduplicates
    while preserving order.
    """
    found: list[tuple[int, str]] = []  # (position, iso)
    consumed: list[tuple[int, int]] = []  # char spans already matched as a range

    def _overlaps_consumed(start: int, end: int) -> bool:
        return any(start < ce and cs < end for cs, ce in consumed)

    # Shared-month ranges first (so '20 to 27 Oct' isn't read as just '27 Oct').
    for m in _RANGE_SHARED_MONTH.finditer(message):
        mon = _MONTHS.get(m.group(3).lower())
        if not mon:
            continue
        year = int(m.group(4)) if m.group(4) else _DEFAULT_YEAR
        d1 = _safe_date(year, mon, int(m.group(1)))
        d2 = _safe_date(year, mon, int(m.group(2)))
        if d1 and d2:
            found.append((m.start(), d1.isoformat()))
            found.append((m.start() + 1, d2.isoformat()))
            consumed.append((m.start(), m.end()))

    for m in _ISO.finditer(message):
        if _overlaps_consumed(m.start(), m.end()):
            continue
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append((m.start(), d.isoformat()))

    for m in _DMY.finditer(message):
        if _overlaps_consumed(m.start(), m.end()):
            continue
        mon = _MONTHS.get(m.group(2).lower())
        if not mon:
            continue
        year = int(m.group(3)) if m.group(3) else _DEFAULT_YEAR
        d = _safe_date(year, mon, int(m.group(1)))
        if d:
            found.append((m.start(), d.isoformat()))

    for m in _MDY.finditer(message):
        if _overlaps_consumed(m.start(), m.end()):
            continue
        mon = _MONTHS.get(m.group(1).lower())
        if not mon:
            continue
        year = int(m.group(3)) if m.group(3) else _DEFAULT_YEAR
        d = _safe_date(year, mon, int(m.group(2)))
        if d:
            found.append((m.start(), d.isoformat()))

    for m in _SLASH.finditer(message):
        if _overlaps_consumed(m.start(), m.end()):
            continue
        day, mon, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        d = _safe_date(yr, mon, day)
        if d:
            found.append((m.start(), d.isoformat()))

    # Order by position in the sentence, dedupe preserving first occurrence.
    found.sort(key=lambda t: t[0])
    seen: set[str] = set()
    out: list[str] = []
    for _, iso in found:
        if iso not in seen:
            seen.add(iso)
            out.append(iso)
    return out


def _run_tool(name: str, label: str, status: str = "working", **kwargs) -> Any:
    """Invoke a tool, logging it to the activity stream and the debug log."""
    session = get_session()
    session.log_activity(status, label)
    return call_tool(name, TOOLS[name], **kwargs)


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
    mode = "llm" if _llm_enabled() else "deterministic"
    log_intent("user_message", {"mode": mode, "message": message})
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

# The leave data (balances, holidays, requests) is for calendar year 2026.
LEAVE_YEAR = _DEFAULT_YEAR  # 2026


def _system_prompt() -> str:
    """Build the system prompt with the current date so the model never guesses
    the year (it otherwise assumes its training-era year)."""
    today = date.today().isoformat()
    return (
        "You are a project-aware leave planning assistant for an IBM employee. "
        "You help the signed-in employee check balances, plan leave around team "
        "coverage and project events, and submit requests for manager approval.\n\n"
        f"TODAY'S DATE is {today}. The leave system operates in calendar year "
        f"{LEAVE_YEAR}; all balances, holidays, and existing requests are for "
        f"{LEAVE_YEAR}. When the user gives a date without a year, assume "
        f"{LEAVE_YEAR}. Resolve relative dates ('next month', 'mid-November', "
        "'the week of the 10th') to concrete YYYY-MM-DD dates before calling "
        "tools. Never treat any year other than the current leave year unless the "
        "user states one explicitly.\n\n"
        "LEAVE TYPES: AL=Annual Leave, CL=Childcare Leave, SL=Sick Leave, "
        "HL=Hospitalisation Leave, OIL=Off-in-Lieu. get_entitlements returns each "
        "account with its bookable 'leave_type' code and 'available' days. "
        "validate_policy is the authority on whether a type can be booked for "
        "given dates — trust its 'valid' / 'violations' result. NEVER claim a "
        "leave type is unavailable based on your own assumptions; if the user "
        "asks for Annual Leave, it exists and is bookable unless validate_policy "
        "says otherwise.\n\n"
        "HOW TO HELP (be smooth and low-friction):\n"
        "1. If the user names dates, call validate_policy, check_coverage, and "
        "get_project_events for exactly those dates. Do not ask for information "
        "you can look up yourself (profile, manager, balances, which types "
        "exist). Default to Annual Leave (AL) when the user says 'leave' or "
        "'time off' without naming a type.\n"
        "2. If the dates are clear, confirm the specifics (type, dates, working "
        "days) in one short message and ask the user to confirm — then submit.\n"
        "3. If coverage is SHORT or there is a hard project freeze (CHANGE_WINDOW), "
        "say so plainly, call find_viable_date_ranges, and recommend ONE specific "
        "nearby alternative with a one-line reason and the balance left after. A "
        "project DEPLOYMENT is advisory only — mention it but do not block on it.\n"
        "4. If the user insists on their original dates despite a soft conflict, "
        "respect their choice and proceed; only a SHORT coverage day is a hard "
        "blocker you should steer away from.\n"
        "5. Ask at most one clarifying question, and only if dates are genuinely "
        "missing or ambiguous. Prefer sensible defaults over interrogating.\n\n"
        "SUBMITTING: Call submit_leave_request ONLY after the user clearly agrees "
        "to a specific type + date range (e.g. 'yes', 'confirm', 'go ahead', "
        "'book it'). After submitting, tell them the reference id and that their "
        "manager has been emailed. Never call submit_leave_request just to assess "
        "dates.\n\n"
        "RULES: Never invent balances, dates, working-day counts, or approvals — "
        "always use the tools. Never reveal other employees' names, ids, emails, "
        "or leave reasons; refer to colleagues' leave only as 'out of office'. "
        "Keep replies concise and friendly."
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
    import json as _json
    import time as _time

    # Persistent conversation history gives the agent memory across turns.
    # Seed the system prompt once, then carry prior turns forward.
    if not session.conversation:
        session.conversation = [{"role": "system", "content": _system_prompt()}]
    messages = session.conversation
    messages.append({"role": "user", "content": message})

    final_reply = "I wasn't able to complete that — please try rephrasing."
    for _ in range(8):  # bounded tool-call loop
        started = _time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=config.ICA_MODEL, messages=messages, tools=_tool_schema(),
            )
        except Exception as exc:
            dur = round((_time.perf_counter() - started) * 1000, 1)
            log_llm_call(config.ICA_MODEL, messages, {}, dur, error=repr(exc))
            # Drop the dangling user turn so a retry starts clean.
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return "I had trouble reaching the model just now — please try again."

        dur = round((_time.perf_counter() - started) * 1000, 1)
        choice = resp.choices[0].message
        tool_calls = [
            {"name": tc.function.name, "args": tc.function.arguments}
            for tc in (choice.tool_calls or [])
        ]
        usage = getattr(resp, "usage", None)
        # Log the full LLM round-trip: request messages + raw response summary.
        log_llm_call(config.ICA_MODEL, messages, {
            "content": choice.content or "",
            "tool_calls": tool_calls,
            "finish_reason": resp.choices[0].finish_reason,
            "usage": usage.model_dump() if usage is not None else None,
        }, dur)
        # Also log the distilled intent (reasoning + chosen tools).
        log_intent("llm_reasoning", {"content": choice.content or "", "tool_calls": tool_calls})
        if not choice.tool_calls:
            final_reply = choice.content or ""
            messages.append({"role": "assistant", "content": final_reply})
            break
        messages.append({"role": "assistant", "content": choice.content,
                         "tool_calls": [tc.model_dump() for tc in choice.tool_calls]})
        for tc in choice.tool_calls:
            name = tc.function.name
            args = _json.loads(tc.function.arguments or "{}")
            # employee confirmation is a precondition enforced server-side.
            if name == "submit_leave_request" and not session.employee_confirmed:
                session.employee_confirmed = True
            session.log_activity("working", f"{name}({', '.join(args)})")
            result = call_tool(name, TOOLS[name], **args) if name in TOOLS else {"error": "unknown tool"}
            if name == "submit_leave_request" and isinstance(result, dict) and result.get("success"):
                from . import email_service
                email_service.send_approval_email(result["employee_time_id"])
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": _json.dumps(result, default=str)})

    _trim_conversation(session)
    return final_reply


# Keep the system prompt + the most recent N messages so history stays bounded.
_MAX_HISTORY = 40


def _trim_conversation(session: SessionState) -> None:
    conv = session.conversation
    if len(conv) <= _MAX_HISTORY + 1:
        return
    system = conv[0:1] if conv and conv[0].get("role") == "system" else []
    tail = conv[-_MAX_HISTORY:]
    # Avoid starting the tail on an orphaned 'tool' message (needs its assistant).
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    session.conversation = system + tail


# ---------------------------------------------------------------------------
# Deterministic planner (demo-reliable fallback)
# ---------------------------------------------------------------------------

def _route(message: str, session: SessionState) -> str:
    text = message.lower().strip()

    # 1) Confirmation of a pending recommendation.
    if _CONFIRM_WORDS.search(text) and session.recommended_dates and not session.employee_confirmed:
        log_intent("planner_intent", {"intent": "confirm_submit",
                                      "recommended_dates": session.recommended_dates,
                                      "leave_type": session.recommended_leave_type})
        return _confirm_and_submit(session)

    # 2) Status lookup: "what's the status of R019?"
    m = re.search(r"\b(r\d{3,})\b", text)
    if "status" in text and m:
        log_intent("planner_intent", {"intent": "status_lookup", "reference_id": m.group(1).upper()})
        return _status_lookup(m.group(1).upper())

    # 3) Policy question (grounded in the company policy document).
    if any(w in text for w in ("policy", "entitled to", "how many days do i get",
                               "how much", "rules on", "allowed", "carry over",
                               "carry-over", "expire")):
        log_intent("planner_intent", {"intent": "policy_question"})
        return _policy_reply(message)

    # 4) Balance query (the user's own live numbers).
    if any(w in text for w in ("balance", "how many days do i have", "my entitlement",
                               "leave do i have", "days left", "days remaining")):
        log_intent("planner_intent", {"intent": "balance_query"})
        return _balance_reply(session)

    # 5) Leave request. Trigger on an explicit keyword, OR when the message
    #    contains dates, OR as a follow-up to an in-progress request (the user
    #    proposing different dates, e.g. "what about 20 to 27 Oct").
    parsed = parse_dates(message)
    has_dates = bool(parsed)
    in_progress = session.requested_dates is not None and not session.employee_confirmed
    if (any(w in text for w in ("leave", "day off", "days off", "time off", "holiday", "childcare"))
            or has_dates or in_progress):
        log_intent("planner_intent", {
            "intent": "leave_request",
            "parsed_dates": parsed,
            "has_keyword": any(w in text for w in ("leave", "day off", "days off",
                                                   "time off", "holiday", "childcare")),
            "followup_in_progress": in_progress,
        })
        return _leave_request_reply(message, session)

    # Default.
    log_intent("planner_intent", {"intent": "fallback_help"})
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

    # Determine leave type. 'childcare' in the message forces CL; otherwise
    # keep the leave type from the in-progress request (a follow-up proposing
    # new dates shouldn't silently drop CL back to AL); default to AL.
    if "childcare" in message.lower():
        leave_type = "CL"
    elif session.requested_leave_type and not session.employee_confirmed:
        leave_type = session.requested_leave_type
    else:
        leave_type = "AL"
    if leave_type == "CL":
        elig = _run_tool("check_childcare_eligibility", "Checking childcare eligibility", status="ok")
        if not elig["eligible"]:
            leave_type = "AL"

    # Dates from the message (natural language or ISO).
    dates = parse_dates(message)
    if len(dates) >= 2:
        start, end = dates[0], dates[1]
    elif len(dates) == 1:
        start = end = dates[0]
    else:
        # No date given — ask rather than guessing a window.
        return (
            "Sure — which dates were you thinking of? For example "
            "'10 Oct to 12 Oct' or '2026-11-10 to 2026-11-11'."
        )

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
