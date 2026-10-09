"""Disambiguate employee records from the authenticated user's approval queue.

Recognises explicit read-only queries before personal leave planning. Unmatched
language remains with the LLM; these rules also support the offline planner.
Only query scope is remembered, never records or statuses.
"""
from __future__ import annotations

import re

from .state import SessionState
from .tools import leave_queries

CLARIFICATION = "Would you like to see your own pending leave requests or leave requests awaiting your approval?"


def recognize(message: str, session: SessionState) -> dict | None:
    text = message.lower().strip().replace("’", "'")
    # Leave submission/confirmation stays with the established workflow.
    if re.match(r"(?:please )?(?:submit|book|apply|cancel|approve|reject)\b", text):
        return None
    if ((session.recommended_dates or session.last_assessed)
            and re.search(r"\b(confirm|proceed|go ahead|book it|yes)\b", text)):
        return None
    if session.awaiting_query_scope:
        if re.search(r"\b(my own|mine|personal|own requests)\b", text):
            return {"name": "get_employee_leave_requests", "args": {"status": "Pending"}, "scope": "employee"}
        if re.search(r"\b(team|manager|approvals?|approve)\b", text):
            return {"name": "get_pending_manager_approvals", "args": {}, "scope": "manager"}

    # Policy questions about how approval works are not requests for a live queue.
    if re.search(r"\b(policy|rules|how to|how does|who approves)\b", text):
        return None

    manager = (re.search(r"\b(my approval|my action|i (?:need to |have .*to |have to )?approve)\b", text)
               or re.search(r"\b(outstanding approvals|pending (?:manager )?approvals|leave to approve)\b", text)
               or ("for me" in text and re.search(r"\b(waiting|pending)\b", text))
               or (re.search(r"\b(team|employees)\b", text) and re.search(r"\b(pending|waiting)\b", text)))
    if manager:
        return {"name": "get_pending_manager_approvals", "args": {}, "scope": "manager"}

    # Explicit balances take priority over mentions of pending days in the same ask.
    if ("balance" in text or (re.search(r"\b(days|leave)\b.*\b(left|remaining|do i have)\b", text)
                              and not re.search(r"\brequests?\b", text))):
        return {"name": "get_entitlements", "args": {}, "scope": "employee"}

    ref = re.search(r"\br\d{3,}\b", text)
    if ref and re.search(r"\b(status|approved|pending|request)\b", text):
        return {"name": "get_request_status", "args": {"reference_id": ref.group().upper()}, "scope": "employee"}

    if re.fullmatch(r"(?:any |show |show me )?pending(?: leave| requests| leave requests)?[?.!]*", text):
        scope = session.leave_query_scope
        if scope is None and leave_queries.is_manager():
            return {"clarify": True}
        return {"name": "get_pending_manager_approvals" if scope == "manager" else "get_employee_leave_requests",
                "args": {} if scope == "manager" else {"status": "Pending"}, "scope": scope or "employee"}

    personal = (re.search(r"\b(my|i|me)\b", text)
                and re.search(r"\b(pending|requests?|history|submitted|submit|raise|raised|approved|status)\b", text)
                and not re.search(r"\b(i (?:want|need|would like)|please submit|can (?:you|i) submit)\b", text))
    if personal:
        args = {"status": "Pending"} if "pending" in text else {}
        return {"name": "get_employee_leave_requests", "args": args, "scope": "employee"}

    return None
