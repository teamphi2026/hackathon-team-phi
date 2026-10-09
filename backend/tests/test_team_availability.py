"""Regression coverage for named, read-only team availability in chat."""
from datetime import date

import pandas as pd
import pytest

from backend import agent
from backend.state import get_session
from backend.tools import team_project as tp


@pytest.fixture(autouse=True)
def session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield s
    s.reset()


def test_team_tool_is_advertised_to_model():
    schema = next(t["function"] for t in agent._tool_schema()
                  if t["function"]["name"] == "get_team_leave")
    assert set(schema["parameters"]["required"]) == {"start_date", "end_date"}
    assert set(schema["parameters"]["properties"]) == {"start_date", "end_date"}
    prompt = agent._system_prompt()
    assert "call get_team_leave" in prompt
    assert "Never reveal other employees' names" not in prompt


@pytest.mark.parametrize("today, start, end", [
    (date(2026, 10, 9), "2026-10-12", "2026-10-18"),
    (date(2026, 10, 12), "2026-10-19", "2026-10-25"),
    (date(2026, 12, 27), "2026-12-28", "2027-01-03"),
])
def test_next_week_lookup_is_read_only(monkeypatch, session, today, start, end):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return today
    monkeypatch.setattr(agent, "date", FixedDate)
    calls = []
    def lookup(**kwargs):
        calls.append(kwargs)
        return {"teams": [{"out_of_office": [{
            "name": "Rahul Menon", "is_self": False,
            "start_date": start, "end_date": start, "status": "Pending", "half_day": "AM",
        }]}]}
    monkeypatch.setitem(agent.TOOLS, "get_team_leave", lookup)
    session.requested_dates = ("2026-11-17", "2026-11-18")
    out = agent.handle_message("Who on my team is off next week?")
    assert calls == [{"start_date": start, "end_date": end}]
    assert "Rahul Menon" in out["reply"]
    assert "Pending" in out["reply"] and "AM half-day" in out["reply"]
    assert session.turn_tools == ["get_team_leave"]
    assert session.requested_dates == ("2026-11-17", "2026-11-18")
    assert session.reference_id is None


def test_explicit_dates_return_named_colleagues(session):
    out = agent.handle_message("Who is on leave 27 to 28 Oct?")
    assert "Rahul Menon" in out["reply"]
    assert "Sarah Koh" in out["reply"]
    assert "You:" in out["reply"]
    assert session.turn_tools == ["get_team_leave"]


def test_empty_range_and_missing_dates(session):
    out = agent.handle_message("Who on my team is off 2026-02-01?")
    assert "No team leave is recorded" in out["reply"]
    out = agent.handle_message("Who on my team is off?")
    assert "Which dates" in out["reply"]
    assert session.turn_tools == []


def test_team_scope_status_and_overlap(monkeypatch):
    original_load = tp._load
    rows = []
    for uid, status, start, end in [
        ("E006", "Approved", "2026-10-10", "2026-10-12"),
        ("E007", "Pending", "2026-10-18", "2026-10-20"),
        ("E004", "Cancelled", "2026-10-12", "2026-10-18"),
        ("E006", "Rejected", "2026-10-12", "2026-10-18"),
        ("E003", "Approved", "2026-10-12", "2026-10-18"),
        ("E006", "Approved", "2026-10-19", "2026-10-20"),
    ]:
        rows.append(dict(user_id=uid, approval_status=status, start_date=start,
                         end_date=end, half_day="None", reason="private"))
    monkeypatch.setattr(tp, "_load", lambda name: pd.DataFrame(rows)
                        if name == "13_Employee_Time.csv" else original_load(name))
    result = tp.get_team_leave("2026-10-12", end_date="2026-10-18")
    entries = [e for t in result["teams"] for e in t["out_of_office"]]
    assert {e["name"] for e in entries} == {"Rahul Menon", "Sarah Koh"}
    assert len(entries) == 2
    assert {e["status"] for e in entries} == {"Approved", "Pending"}
    assert all(set(e) == {"label", "name", "is_self", "half_day", "start_date", "end_date", "status"}
               for e in entries)


def test_personal_planning_mentioning_team_keeps_its_route(monkeypatch, session):
    monkeypatch.setattr(agent, "_leave_request_reply", lambda message, session: "personal planning")
    out = agent.handle_message("I want leave 27 to 28 Oct if my team has coverage")
    assert out["reply"] == "personal planning"
