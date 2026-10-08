"""End-to-end orchestrator flow (Tasks 7 + 9 + 3.3 golden path).

Exercises the deterministic planner through the full demo scenario. Mutating
steps are isolated by backing up and restoring the data files.
"""
from __future__ import annotations

import shutil

import pytest

from backend import agent, email_service
from backend.config import data_file
from backend.state import get_session
from backend.tools import actions

_FILES = ["13_Employee_Time.csv", "12_Time_Account_Detail.csv"]


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    backups = {}
    for f in _FILES:
        shutil.copy(data_file(f), tmp_path / f)
        backups[f] = tmp_path / f
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    actions._invalidate_caches()
    yield
    for f, b in backups.items():
        shutil.copy(b, data_file(f))
    actions._invalidate_caches()
    s.reset()


def test_balance_query():
    out = agent.handle_message("What's my leave balance?")
    assert "Annual Leave" in out["reply"]
    assert "Childcare Leave" in out["reply"]


def test_request_surfaces_conflict_and_alternative():
    out = agent.handle_message("I'd like 2 days off on 2026-10-27 to 2026-10-28")
    reply = out["reply"]
    # Conflict surfaced.
    assert "Empty'em" in reply or "on duty" in reply
    # An alternative is recommended with a 'confirm' prompt.
    assert "confirm" in reply.lower()
    # Activity shows a SHORT coverage event and a recommendation.
    statuses = [e["status"] for e in out["activity"]]
    assert "fail" in statuses
    assert "rec" in statuses


def test_full_golden_path_approve():
    s = get_session()
    agent.handle_message("I need 2 days off around 2026-10-27 to 2026-10-28")
    assert s.recommended_dates is not None

    confirm = agent.handle_message("confirm")
    assert "submitted" in confirm["reply"].lower()
    eid = s.reference_id
    assert eid is not None

    # Manager approves via the email token.
    tokens = s.approval_token_map
    approve_token = next(t for t, v in tokens.items()
                         if v["employee_time_id"] == eid and v["action"] == "approve")
    result = actions.handle_approval_token(approve_token, "approve")
    email_service.send_confirmation_email(eid)
    assert result["success"] is True

    _, rows = actions._read_rows("13_Employee_Time.csv")
    row = next(r for r in rows if r["employee_time_id"] == eid)
    assert row["approval_status"] == "Approved"

    # Status lookup reports Approved.
    status = agent.handle_message(f"what's the status of {eid}?")
    assert "approved" in status["reply"].lower()


def test_status_lookup_privacy_other_user_request():
    # R002 belongs to E006, not the session user E005.
    out = agent.handle_message("what is the status of R002?")
    assert "couldn't find" in out["reply"].lower()
