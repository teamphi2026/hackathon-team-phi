"""Regression tests for shared live status, role routing and approval-panel parity."""
from datetime import date
import shutil

import pytest
from fastapi.testclient import TestClient

from backend import agent, auth, config, email_service, leave_intents
from backend.main import app
from backend.state import get_session
from backend.tools import actions, hr, leave_queries


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    shutil.copytree(config.DATA_DIR, tmp_path / "data")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    actions._invalidate_caches()
    s = get_session()
    s.reset()
    s.session_user_id = "E004"
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 9)
    monkeypatch.setattr(hr, "date", Today)
    yield s
    actions._invalidate_caches()
    auth._TOKENS.clear()
    s.reset()


def _al():
    return next(a for a in hr.get_entitlements()["accounts"] if a["leave_type"] == "AL")


def _change(ref, status):
    header, rows = actions._read_rows(actions.EMPLOYEE_TIME)
    next(r for r in rows if r["employee_time_id"] == ref)["approval_status"] = status
    actions._write_rows(actions.EMPLOYEE_TIME, header, rows)


def test_balance_and_history_share_pending_personal_request(data):
    ent = hr.get_entitlements()
    assert ent["pending_request_count"] == 1
    assert [r["reference_id"] for r in ent["pending_requests"]] == ["R019"]
    assert _al()["pending_requests"] == 3  # days, not requests
    assert _al()["available"] == 8.5  # 12.5 credit balance - 1 approved - 3 pending
    balance = agent.handle_message("What's my leave balance?")["reply"]
    assert "| Annual Leave | 8.5 |" in balance
    assert "R019" in balance and "Priya Nair" in balance
    history = agent.handle_message("Did I raise any requests?")["reply"]
    assert "R019" in history and "Pending approval from Priya Nair" in history
    assert "R021" in history and "R007" in history


@pytest.mark.parametrize("message", [
    "Any leave pending my approval?", "Do I have any leave to approve?",
    "Show me my team's pending leave.", "Who is waiting for my approval?",
    "Are there any outstanding approvals?", "Any requests requiring my action?",
    "Who needs my approval?", "Show me pending team requests.",
    "Do I need to approve anything?", "Which employees are waiting for me?",
])
def test_manager_intents_match_panel_without_personal_leave(data, message):
    panel = actions.list_pending_for_approver("E004")
    assert {r["employee_time_id"] for r in panel} == {"R009", "R010", "R011"}
    out = agent.handle_message(message)
    assert data.turn_tools == ["get_pending_manager_approvals"]
    for row in panel:
        assert row["employee_time_id"] in out["reply"]
        assert row["employee_name"] in out["reply"]
    assert "R019" not in out["reply"]
    assert "Manager Approval Required panel" in out["reply"]


@pytest.mark.parametrize("message", [
    "Do I have any pending leave?", "Do I have any leave pending?",
    "Did I submit any requests?", "What's the status of my leave?",
    "Has my manager approved my leave?", "Show me my leave history.",
])
def test_personal_queries_stay_personal_for_manager(data, message):
    reply = agent.handle_message(message)["reply"]
    assert "R019" in reply
    assert "R009" not in reply
    assert data.turn_tools == ["get_employee_leave_requests"]


def test_ambiguous_query_and_clarification_followup(data):
    reply = agent.handle_message("Any pending leave?")["reply"]
    assert reply == leave_intents.CLARIFICATION
    assert data.turn_tools == []
    reply = agent.handle_message("My own, please")["reply"]
    assert "R019" in reply and "R009" not in reply
    reply = agent.handle_message("Any pending leave?")["reply"]
    assert "R019" in reply  # clear immediately preceding employee scope
    agent.handle_message("Any leave pending my approval?")
    reply = agent.handle_message("Any pending leave?")["reply"]
    assert "R009" in reply and "R019" not in reply


def test_no_manager_queue_does_not_fall_back_to_personal(data):
    for ref in ("R009", "R010", "R011"):
        _change(ref, "Rejected")
    assert leave_queries.is_manager()  # role doesn't depend on a nonempty queue
    reply = agent.handle_message("Anything waiting for my approval?")["reply"]
    assert reply == "You currently have no leave requests awaiting your approval."
    assert "R019" in agent.handle_message("Do I have any pending leave?")["reply"]


def test_unprivileged_user_and_identity_injection(data):
    data.session_user_id = "E005"
    assert leave_queries.get_pending_manager_approvals()["requests"] == []
    assert "R010" not in agent.handle_message("Show me pending manager approvals.")["reply"]
    data.reset()  # no preceding manager-query context
    assert "R009" in agent.handle_message("Any pending leave?")["reply"]
    with pytest.raises(TypeError):
        leave_queries.get_pending_manager_approvals(manager_id="E004")
    with pytest.raises(TypeError):
        leave_queries.get_employee_leave_requests(employee_id="E004")
    assert not leave_queries.get_employee_leave_requests(reference_id="R019")["found"]
    assert not actions.get_request_status("R019")["found"]


def test_old_pending_request_not_hidden_by_recent_history(data):
    header, rows = actions._read_rows(actions.EMPLOYEE_TIME)
    template = next(r for r in rows if r["employee_time_id"] == "R007")
    for i in range(6):
        rows.append({**template, "employee_time_id": f"R{100+i}", "approval_status": "Cancelled"})
    actions._write_rows(actions.EMPLOYEE_TIME, header, rows)
    assert "R019" in {r["reference_id"] for r in actions.get_request_status()["requests"]}
    assert hr.get_entitlements()["pending_request_count"] == 1


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_ui_decision_refreshes_panel_chat_balances_and_sends_notification(data, monkeypatch, decision):
    client = TestClient(app)
    auth._TOKENS.update({"manager-test": "E004", "employee-test": "E005"})
    manager_headers = {"Authorization": "Bearer manager-test"}
    employee_headers = {"Authorization": "Bearer employee-test"}
    notifications = []
    monkeypatch.setattr(email_service, "send_confirmation_email", lambda eid: notifications.append(eid) or {"sent": True})
    monkeypatch.setattr(email_service, "send_rejection_email", lambda eid, **kw: notifications.append(eid) or {"sent": True})
    # Warm data and conversation before approval to exercise stale-cache scenarios.
    client.post("/api/chat", json={"message": "What's my leave balance?"}, headers=employee_headers)
    before = _al()["available"]
    chat = client.post("/api/chat", json={"message": "Any leave pending my approval?"}, headers=manager_headers).json()
    panel = client.get("/api/pending-approvals", headers=manager_headers).json()["pending"]
    assert all(r["employee_time_id"] in chat["reply"] for r in panel)
    denied = client.post("/api/ui-approval", headers=employee_headers,
                         json={"employee_time_id": "R010", "action": decision}).json()
    assert not denied["success"]
    result = client.post("/api/ui-approval", headers=manager_headers,
                         json={"employee_time_id": "R009", "action": decision}).json()
    assert result["success"] and result["employee_emailed"]
    assert notifications == ["R009"]
    panel = client.get("/api/pending-approvals", headers=manager_headers).json()["pending"]
    assert {r["employee_time_id"] for r in panel} == {"R010", "R011"}
    reply = client.post("/api/chat", headers=manager_headers,
                        json={"message": "Any leave pending my approval?"}).json()["reply"]
    assert "R009" not in reply and "R010" in reply
    client.get("/api/me", headers=employee_headers)
    ent = hr.get_entitlements()
    assert ent["pending_request_count"] == 0
    assert _al()["available"] == (before if decision == "approve" else before + 5)
    assert actions.get_request_status("R009")["requests"][0]["status"] == ("Approved" if decision == "approve" else "Rejected")


def test_submission_reserves_and_cancellation_releases_days(data):
    data.session_user_id = "E005"
    data.employee_confirmed = True
    before = next(a for a in hr.get_entitlements()["accounts"] if a["leave_type"] == "CL")["available"]
    sub = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18")
    assert sub["success"]
    ent = hr.get_entitlements()
    assert ent["pending_request_count"] == 2
    assert next(a for a in ent["accounts"] if a["leave_type"] == "CL")["available"] == before - 2
    validation = hr.validate_policy("CL", "2026-12-01", "2026-12-07")
    assert not validation["valid"]  # five days won't fit after reservation
    _change(sub["employee_time_id"], "Cancelled")  # no cancellation endpoint exists
    assert next(a for a in hr.get_entitlements()["accounts"] if a["leave_type"] == "CL")["available"] == before
    assert hr.get_entitlements()["pending_request_count"] == 1


@pytest.mark.parametrize("message, tool, expected_refs", [
    ("What's my leave balance?", "get_entitlements", {"R019"}),
    ("Any leave pending my approval?", "get_pending_manager_approvals", {"R009", "R010", "R011"}),
    ("Did I raise any requests?", "get_employee_leave_requests", {"R007", "R019", "R021"}),
    ("Do I have any leave pending?", "get_employee_leave_requests", {"R019"}),
])
def test_llm_uses_live_scoped_tool_despite_stale_conversation(data, monkeypatch, message, tool, expected_refs):
    import json
    from types import SimpleNamespace
    import openai
    from backend.tests.test_llm_logging import _Resp, _Msg, _ToolCall
    captured = []
    class Completions:
        def create(self, **kwargs):
            captured.append(kwargs)
            if len(captured) == 1:
                assert kwargs["tool_choice"]["function"]["name"] == tool
                assert {t["function"]["name"] for t in kwargs["tools"]} == {tool}
                # Simulate the original wrong tool selection / identity injection.
                return _Resp(_Msg(tool_calls=[_ToolCall("get_request_status", '{"employee_id":"E001"}')]), "tool_calls")
            assert kwargs["tool_choice"] == "none"
            result = json.loads(kwargs["messages"][-1]["content"])
            rows = result["pending_requests"] if tool == "get_entitlements" else result["requests"]
            assert {r["reference_id"] for r in rows} == expected_refs
            return _Resp(_Msg(content=agent._format_query_result(tool, result)), "stop")
    monkeypatch.setattr(config, "ICA_API_KEY", "test-key")
    monkeypatch.setattr(config, "ICA_BASE_URL", "https://example.test")
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    data.conversation = [{"role": "system", "content": "old"},
                         {"role": "user", "content": message},
                         {"role": "assistant", "content": "You have no pending requests."}]
    reply = agent.handle_message(message)["reply"]
    assert all(ref in reply for ref in expected_refs)
    assert data.turn_tools == [tool]
    assert len(captured) == 2


def test_llm_ignoring_tool_choice_cannot_reuse_old_status(data, monkeypatch):
    from types import SimpleNamespace
    import openai
    from backend.tests.test_llm_logging import _Resp, _Msg
    monkeypatch.setattr(config, "ICA_API_KEY", "test-key")
    monkeypatch.setattr(config, "ICA_BASE_URL", "https://example.test")
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: _Resp(_Msg(content="You have no pending requests."), "stop")))))
    reply = agent.handle_message("What's my leave balance?")["reply"]
    assert "R019" in reply and "no pending" not in reply
    _change("R019", "Rejected")
    reply = agent.handle_message("What's my leave balance?")["reply"]
    assert "R019" not in reply and "no pending" in reply


def test_queries_do_not_reclassify_leave_planning_or_policy(data):
    for text in ("I need 2 days off on 2026-10-27", "Yes, confirm", "Who approves my leave?",
                 "What is the approval policy?", "Who on my team is off next week?"):
        assert leave_intents.recognize(text, data) is None


def test_manager_chat_projection_matches_panel_and_omits_private_text(data):
    public = leave_queries.get_pending_manager_approvals()["requests"]
    panel = actions.list_pending_for_approver(data.session_user_id)
    for record, card in zip(public, panel):
        assert all(record[k] == card[k] for k in record)
        assert not {"reason", "employee_id", "approver_id", "decision_note"} & record.keys()


@pytest.mark.parametrize("message", ["Any pending leave?", "Show me pending leave", "Any pending requests?"])
def test_ambiguous_manager_query_never_defaults_to_personal(data, message):
    assert agent.handle_message(message)["reply"] == leave_intents.CLARIFICATION


def test_for_me_in_planning_is_not_an_approval_query(data):
    assert leave_intents.recognize("Plan annual leave for me next week", data) is None
    assert leave_intents.recognize("Can I submit leave for November?", data) is None
    result = leave_intents.recognize("How many leave requests do I have?", data)
    assert result["name"] == "get_employee_leave_requests"


def test_approved_cancellation_and_legacy_duplicate_debits(data):
    data.session_user_id = "E005"
    assert _al()["available"] == 2  # R020 counts once despite multiple debit rows
    _change("R020", "Cancelled")
    assert _al()["available"] == 5  # request status overrides stale ledger debits
    data.session_user_id = "E007"
    assert _al()["pending_requests"] == 2
    assert _al()["available"] == 5.5  # R011 is Pending despite an old debit row


def test_email_approval_releases_reservation_without_double_deduction(data):
    data.session_user_id = "E005"
    before = _al()["available"]
    data.approval_token_map["test-token"] = {"employee_time_id": "R009", "action": "approve", "used": False}
    assert actions.handle_approval_token("test-token")["success"]
    assert _al()["available"] == before
    assert hr.get_entitlements()["pending_request_count"] == 0
    data.session_user_id = "E004"
    assert "R009" not in {r["reference_id"] for r in leave_queries.get_pending_manager_approvals()["requests"]}


def test_confirmation_and_submission_keep_existing_workflow(data):
    data.recommended_dates = ("2026-11-17", "2026-11-18")
    assert leave_intents.recognize("Yes, confirm my request", data) is None
    assert leave_intents.recognize("Please submit my leave request", data) is None


def test_pending_approval_panel_is_empty_for_employee_login(data):
    auth._TOKENS["employee-test"] = "E005"
    client = TestClient(app)
    headers = {"Authorization": "Bearer employee-test"}
    panel = client.get("/api/pending-approvals", headers=headers)
    assert panel.status_code == 200 and panel.json()["pending"] == []
    chat = client.post("/api/chat", headers=headers,
                       json={"message": "Show me pending manager approvals."})
    assert "no leave requests awaiting your approval" in chat.json()["reply"]
    assert "R010" not in chat.json()["reply"]
