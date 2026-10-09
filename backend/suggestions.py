"""Dynamic follow-up suggestion chips for the chat UI.

Chips are derived from what the user has already asked in this session (which
tools ran, whether an option is awaiting confirmation, whether a request was
just submitted) plus their latest request on file. Topics already asked are not
offered again. Deterministic and instant: no extra LLM call.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .state import SessionState
from .tools import leave_queries

MAX_CHIPS = 3

# Tool -> topic the user has explored.
_TOPIC_BY_TOOL = {
    "get_entitlements": "balance",
    "search_policy": "policy",
    "check_childcare_eligibility": "childcare",
    "get_team_leave": "team",
    "validate_policy": "plan",
    "check_coverage": "plan",
    "submit_leave_request": "submit",
}


def _explored(session: SessionState) -> set[str]:
    topics: set[str] = set()
    for turn in session.history:
        for tool in turn.get("tools", []):
            if tool in _TOPIC_BY_TOOL:
                topics.add(_TOPIC_BY_TOOL[tool])
    return topics


def _latest_pending_request(user_id: str) -> str | None:
    """Reference id of the user's most recent request still awaiting a decision."""
    try:
        rows = leave_queries.employee_request_rows(user_id)
    except OSError:
        return None
    mine = [r for r in rows if r["approval_status"] == leave_queries.PENDING]
    return mine[-1]["employee_time_id"] if mine else None


def _next_week_phrase(today: date | None = None) -> str:
    today = today or date.today()
    monday = today + timedelta(days=7 - today.weekday())
    return f"{monday.day} {monday.strftime('%b')}"


def build(session: SessionState, limit: int = MAX_CHIPS) -> list[str]:
    """Return up to `limit` suggestion strings for the next user turn."""
    asked = {h.get("message", "").strip().lower() for h in session.history}
    tools = set(session.turn_tools)
    explored = _explored(session)
    out: list[str] = []

    def add(text: str | None) -> None:
        if text and len(out) < limit and text not in out and text.strip().lower() not in asked:
            out.append(text)

    la = session.last_assessed
    ref = session.reference_id

    # 1) An option is waiting for the user's yes/no.
    if la:
        add(f"Yes, confirm {la.get('date_label') or 'this option'}")
        add("Show me other date options")
        add("Who on my team is off then?")
    # 2) A request was just submitted.
    elif "submit_leave_request" in tools and ref:
        add(f"What's the status of {ref}?")
        add("What's my leave balance now?")
        add("Plan another leave")
    # 3) Follow-ups that build on the topic just discussed.
    elif "get_entitlements" in tools:
        add("Am I eligible for Childcare Leave?")
        add("How much annual leave can I carry over?")
        add("Plan 3 days off next week without affecting my team")
    elif "search_policy" in tools:
        add("What's my leave balance?")
        add("Plan 3 days off next week without affecting my team")
    elif "check_childcare_eligibility" in tools:
        add("What's my leave balance?")
        add("Plan childcare leave around my child's school event")
    elif tools & {"get_team_leave", "check_coverage"}:
        add("Plan 3 days off next week without affecting my team")

    # 4) Fill remaining slots with topics the user hasn't explored yet.
    pending = _latest_pending_request(session.session_user_id)
    if pending and (not ref or pending != ref):
        add(f"What's the status of {pending}?")
    if "balance" not in explored:
        add("What's my leave balance?")
    if "plan" not in explored:
        add(f"I need 3 days off from {_next_week_phrase()} without affecting the project")
    if "childcare" not in explored:
        add("Am I eligible for Childcare Leave?")
    if "policy" not in explored:
        add("What is the carry-over policy?")
    if "team" not in explored:
        add("Who on my team is off next week?")
    add("What's my leave balance?")
    add("Plan 3 days off next week without affecting my team")
    return out
