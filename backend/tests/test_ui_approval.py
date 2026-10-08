"""Tests for the UI manager-decision path (handle_ui_decision) — Task 10/11."""
from __future__ import annotations

from backend.tools import actions


def _submit(session):
    session.employee_confirmed = True
    return actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "x")["employee_time_id"]


def test_ui_approve_sets_approved_and_debits(isolate_data):
    eid = _submit(isolate_data)
    _, before = actions._read_rows("12_Time_Account_Detail.csv")
    result = actions.handle_ui_decision(eid, "approve")
    assert result["success"] is True
    _, rows = actions._read_rows("13_Employee_Time.csv")
    assert next(r for r in rows if r["employee_time_id"] == eid)["approval_status"] == "Approved"
    _, after = actions._read_rows("12_Time_Account_Detail.csv")
    assert len(after) == len(before) + 1


def test_ui_reject_sets_rejected_no_debit(isolate_data):
    eid = _submit(isolate_data)
    _, before = actions._read_rows("12_Time_Account_Detail.csv")
    result = actions.handle_ui_decision(eid, "reject")
    assert result["success"] is True
    _, rows = actions._read_rows("13_Employee_Time.csv")
    assert next(r for r in rows if r["employee_time_id"] == eid)["approval_status"] == "Rejected"
    _, after = actions._read_rows("12_Time_Account_Detail.csv")
    assert len(after) == len(before)


def test_ui_decision_idempotent(isolate_data):
    eid = _submit(isolate_data)
    actions.handle_ui_decision(eid, "approve")
    second = actions.handle_ui_decision(eid, "reject")
    assert second["success"] is False


def test_ui_unknown_action(isolate_data):
    eid = _submit(isolate_data)
    assert actions.handle_ui_decision(eid, "maybe")["success"] is False
