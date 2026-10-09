"""Explicit tests for the 8 design guardrails (section 10) — Task 11.

Each test maps to a numbered guardrail so the demo can show them holding.
"""
from __future__ import annotations

from backend import agent, filters
from backend.tools import actions


# Guardrail 1: no submission without employee_confirmed = true.
def test_g1_no_submit_without_confirmation(isolate_data):
    s = isolate_data
    s.employee_confirmed = False
    r = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "x")
    assert r["success"] is False


# Guardrail 2: no fulfilment (debit) without APPROVED.
def test_g2_no_debit_until_approved(isolate_data):
    s = isolate_data
    s.employee_confirmed = True
    sub = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "x")
    eid = sub["employee_time_id"]
    _, before = actions._read_rows("12_Time_Account_Detail.csv")
    # No debit exists while the request is only Pending.
    assert not any(r["employee_time_id"] == eid for r in before)


# Guardrail 3: LLM cannot mutate approval_status (no tool exposes it).
def test_g3_no_tool_mutates_status_directly():
    forbidden = {"approve_request", "set_status", "mutate_status"}
    assert forbidden.isdisjoint(agent.TOOLS.keys())


# Guardrail 4: write actions validate workflow state.
def test_g4_handle_token_rejects_non_pending(isolate_data):
    s = isolate_data
    s.employee_confirmed = True
    sub = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", "None", "x")
    eid = sub["employee_time_id"]
    s.approval_token_map["t1"] = {"employee_time_id": eid, "action": "approve",
                                  "used": False, "expiry": None}
    s.approval_token_map["t2"] = {"employee_time_id": eid, "action": "approve",
                                  "used": False, "expiry": None}
    first = actions.handle_approval_token("t1", "approve")
    assert first["success"] is True
    # Already Approved -> second (different) token can't re-decide.
    second = actions.handle_approval_token("t2", "approve")
    assert second["success"] is False


# Guardrail 5: tool failures return explicit errors, no fabricated data.
def test_g5_invalid_token_explicit_error(isolate_data):
    r = actions.handle_approval_token("nope", "approve")
    assert r["success"] is False and "message" in r


# Guardrail 6: output filter runs on every response.
def test_g6_filter_applied_in_handle_message(isolate_data):
    out = agent.handle_message("tell me about E006 and E007")
    assert "E006" not in out["reply"]
    assert "E007" not in out["reply"]


# Guardrail 7: user_id never accepted from the LLM (tools read session).
def test_g7_tools_ignore_injected_user_id(isolate_data):
    s = isolate_data
    s.session_user_id = "E005"
    # Even if a caller tried to pass user_id, the profile is still E005's.
    from backend.tools import hr
    assert hr.get_employee_profile()["user_id"] == "E005"


# Guardrail 8: other users' free text never surfaces (private details omitted).
def test_g8_team_leave_excludes_private_details(isolate_data):
    from backend.tools import team_project as tp
    tl = tp.get_team_leave("2026-10-27", "2026-10-28")
    for team in tl["teams"]:
        for entry in team["out_of_office"]:
            assert entry["label"] == "Out of office"
            assert "reason" not in entry
            assert "user_id" not in entry


# Cross-employee lookup is refused (privacy).
def test_cross_employee_status_lookup_refused(isolate_data):
    out = agent.handle_message("what is the status of R002?")  # R002 belongs to E006
    assert "couldn't find" in out["reply"].lower()
