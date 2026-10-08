"""Unit tests for the approval state machine + action tools (Task 5 / spec Task 1.3).

These tests mutate CSV files, so each test backs up and restores the two
affected files to keep the demo data pristine.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta

import pytest

from backend.config import data_file
from backend.state import get_session
from backend.tools import actions

_FILES = ["13_Employee_Time.csv", "12_Time_Account_Detail.csv"]


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    # Backup data files.
    backups = {}
    for f in _FILES:
        p = data_file(f)
        b = tmp_path / f
        shutil.copy(p, b)
        backups[f] = b
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    actions._invalidate_caches()
    yield
    # Restore.
    for f, b in backups.items():
        shutil.copy(b, data_file(f))
    actions._invalidate_caches()
    s.reset()


def _register_token(employee_time_id, action, used=False, expiry=None):
    s = get_session()
    token = f"tok-{action}"
    s.approval_token_map[token] = {
        "employee_time_id": employee_time_id,
        "action": action,
        "used": used,
        "expiry": expiry,
    }
    return token


# --- submit_leave_request --------------------------------------------------

def test_submit_blocked_without_confirmation():
    s = get_session()
    s.employee_confirmed = False
    result = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "Childcare")
    assert result["success"] is False
    assert "confirm" in result["error"].lower()


def test_submit_writes_pending_row_after_confirmation():
    s = get_session()
    s.employee_confirmed = True
    result = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "Childcare")
    assert result["success"] is True
    assert result["status"] == "Pending"
    assert result["approver_id"] == "E004"
    # Session reflects the new state.
    assert s.approval_status == "PENDING_MANAGER_APPROVAL"
    assert s.reference_id == result["employee_time_id"]


# --- handle_approval_token -------------------------------------------------

def _submit_one():
    s = get_session()
    s.employee_confirmed = True
    r = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "Childcare")
    return r["employee_time_id"]


def test_approve_token_sets_approved_and_writes_debit():
    eid = _submit_one()
    token = _register_token(eid, "approve")

    _, before = actions._read_rows("12_Time_Account_Detail.csv")
    result = actions.handle_approval_token(token, "approve")
    assert result["success"] is True

    _, et_rows = actions._read_rows("13_Employee_Time.csv")
    row = next(r for r in et_rows if r["employee_time_id"] == eid)
    assert row["approval_status"] == "Approved"

    _, after = actions._read_rows("12_Time_Account_Detail.csv")
    assert len(after) == len(before) + 1
    debit = next(r for r in after if r["employee_time_id"] == eid)
    assert float(debit["booking_amount"]) < 0


def test_token_is_single_use():
    eid = _submit_one()
    token = _register_token(eid, "approve")
    first = actions.handle_approval_token(token, "approve")
    assert first["success"] is True
    second = actions.handle_approval_token(token, "approve")
    assert second["success"] is False
    assert "already been used" in second["message"].lower()


def test_expired_token_returns_error():
    eid = _submit_one()
    token = _register_token(eid, "approve", expiry=datetime.now() - timedelta(hours=1))
    result = actions.handle_approval_token(token, "approve")
    assert result["success"] is False
    assert "expired" in result["message"].lower()


def test_invalid_token_returns_error():
    result = actions.handle_approval_token("does-not-exist", "approve")
    assert result["success"] is False
    assert "invalid" in result["message"].lower()


def test_reject_token_sets_rejected_no_debit():
    eid = _submit_one()
    token = _register_token(eid, "reject")
    _, before = actions._read_rows("12_Time_Account_Detail.csv")
    result = actions.handle_approval_token(token, "reject")
    assert result["success"] is True

    _, et_rows = actions._read_rows("13_Employee_Time.csv")
    row = next(r for r in et_rows if r["employee_time_id"] == eid)
    assert row["approval_status"] == "Rejected"
    # No debit written on reject.
    _, after = actions._read_rows("12_Time_Account_Detail.csv")
    assert len(after) == len(before)
