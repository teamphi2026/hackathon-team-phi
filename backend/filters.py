"""Output filter (PII stripping) — Task 7 / guardrails 6 & 8.

Runs on every LLM response before it reaches the browser. Deterministic
post-processing, not an LLM instruction.

Rules:
  1. Redact any E### employee id that is not the session user or their manager.
  2. Redact any email address that is not the session user's or their manager's.
  3. Helper to scrub other users' free-text (leave reasons / decision notes)
     before it can enter a prompt.
"""
from __future__ import annotations

import re

from .state import get_session
from .tools import actions, hr

_EMP_ID = re.compile(r"\bE\d{3}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

_REDACTED_ID = "[redacted]"
_REDACTED_EMAIL = "[redacted-email]"


def _allowed_ids_and_emails() -> tuple[set[str], set[str]]:
    """The session user and their direct manager are the only allowed identities."""
    profile = hr.get_employee_profile()
    uid = profile.get("user_id", "")
    manager_id = profile.get("manager_id", "") or ""
    allowed_ids = {uid}
    allowed_emails = {profile.get("email", "")}

    if manager_id:
        allowed_ids.add(manager_id)
        _, rows = actions._read_rows("02_Job_Information.csv")
        mgr = next((r for r in rows if r["user_id"] == manager_id), None)
        if mgr:
            allowed_emails.add(mgr.get("email", ""))

    allowed_ids.discard("")
    allowed_emails.discard("")
    return allowed_ids, allowed_emails


def filter_output(text: str) -> str:
    """Redact employee ids and emails that don't belong to the session user/manager."""
    if not text:
        return text
    allowed_ids, allowed_emails = _allowed_ids_and_emails()

    def _id_sub(m: re.Match) -> str:
        return m.group(0) if m.group(0) in allowed_ids else _REDACTED_ID

    def _email_sub(m: re.Match) -> str:
        return m.group(0) if m.group(0).lower() in {e.lower() for e in allowed_emails} else _REDACTED_EMAIL

    text = _EMP_ID.sub(_id_sub, text)
    text = _EMAIL.sub(_email_sub, text)
    return text


def scrub_other_users_freetext(text: str) -> str:
    """Remove free text sourced from OTHER employees' reasons/decision notes.

    Used before team data enters a prompt. Returns a neutral placeholder so no
    other employee's words reach the model.
    """
    return "Out of office"
