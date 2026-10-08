"""Tests for the email service + token management (Task 6).

Runs in DRY-RUN mode (no SMTP creds), so emails are built and returned rather
than sent. Mutating tests back up and restore the Employee_Time file.
"""
from __future__ import annotations

import shutil

import pytest

from backend import email_service as es
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


def _submit():
    s = get_session()
    s.employee_confirmed = True
    r = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "Childcare")
    return r["employee_time_id"]


def test_approval_email_generates_two_tokens():
    eid = _submit()
    result = es.send_approval_email(eid)
    # Dry-run returns the built email with action links.
    assert result["dry_run"] is True
    assert "approve" in result["approve_url"]
    assert "reject" in result["reject_url"]
    # Two tokens registered for this request.
    tokens = get_session().approval_token_map
    for_req = [t for t, v in tokens.items() if v["employee_time_id"] == eid]
    assert len(for_req) == 2
    actions_registered = {tokens[t]["action"] for t in for_req}
    assert actions_registered == {"approve", "reject"}


def test_approval_email_goes_to_manager():
    eid = _submit()
    result = es.send_approval_email(eid)
    # Marcus Lim (E004) is Wei Ling's manager.
    assert result["manager_email"] == "marcus.lim@i-be-yam.com"


def test_token_from_email_drives_approval():
    eid = _submit()
    es.send_approval_email(eid)
    tokens = get_session().approval_token_map
    approve_token = next(t for t, v in tokens.items()
                         if v["employee_time_id"] == eid and v["action"] == "approve")
    result = actions.handle_approval_token(approve_token, "approve")
    assert result["success"] is True
    _, rows = actions._read_rows("13_Employee_Time.csv")
    row = next(r for r in rows if r["employee_time_id"] == eid)
    assert row["approval_status"] == "Approved"


def test_confirmation_email_contains_reference():
    eid = _submit()
    result = es.send_confirmation_email(eid)
    assert result["dry_run"] is True
    assert eid in result["html"]


def test_rejection_email_mentions_no_deduction():
    eid = _submit()
    result = es.send_rejection_email(eid, reason="Coverage too low")
    assert "No leave balance has been deducted" in result["html"]
    assert "Coverage too low" in result["html"]
