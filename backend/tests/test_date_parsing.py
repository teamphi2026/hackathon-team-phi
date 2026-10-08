"""Tests for natural-language date parsing in the orchestrator."""
from __future__ import annotations

import pytest

from backend import agent
from backend.state import get_session


@pytest.fixture(autouse=True)
def _session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield
    s.reset()


@pytest.mark.parametrize("text,expected", [
    ("from 10 Oct to 12 Oct 2026", ["2026-10-10", "2026-10-12"]),
    ("I need leave 2026-11-10 to 2026-11-11", ["2026-11-10", "2026-11-11"]),
    ("October 10 to October 12", ["2026-10-10", "2026-10-12"]),
    ("10th November 2026", ["2026-11-10"]),
    ("12/10/2026 to 14/10/2026", ["2026-10-12", "2026-10-14"]),
    ("book me off Dec 1 to Dec 3", ["2026-12-01", "2026-12-03"]),
    # Shared-month ranges: first day borrows the month from the second.
    ("what about 20 to 27 oct", ["2026-10-20", "2026-10-27"]),
    ("20-27 October 2026", ["2026-10-20", "2026-10-27"]),
    ("3rd to 5th Dec", ["2026-12-03", "2026-12-05"]),
])
def test_parse_dates(text, expected):
    assert agent.parse_dates(text) == expected


def test_parse_dates_dedupes_and_orders():
    assert agent.parse_dates("2026-10-12 and again 2026-10-12") == ["2026-10-12"]


def test_requested_dates_are_honored_not_defaulted():
    # A specific clear window must be assessed as given, not replaced by 27-28 Oct.
    out = agent.handle_message("please apply leave from 10 Oct to 12 Oct 2026")
    assert "2026-10-10" in out["reply"]
    assert "2026-10-27" not in out["reply"]
    assert get_session().requested_dates == ("2026-10-10", "2026-10-12")


def test_no_date_asks_instead_of_guessing():
    out = agent.handle_message("I want to take some annual leave")
    assert "which dates" in out["reply"].lower()
    # Nothing was assessed/recommended.
    assert get_session().requested_dates is None


def test_followup_dates_without_keyword_are_routed():
    # Start a request, then a bare follow-up proposing new dates (no leave word).
    agent.handle_message("I'd like some leave 10 Oct to 12 Oct 2026")
    out = agent.handle_message("what about 20 to 27 oct")
    assert get_session().requested_dates == ("2026-10-20", "2026-10-27")
    # It assessed the new window (not the generic help fallback).
    assert "2026-10-20" in out["reply"]
    assert "What would you like to do?" not in out["reply"]


def test_followup_preserves_childcare_leave_type():
    agent.handle_message("I need childcare leave 10 Oct to 11 Oct 2026")
    agent.handle_message("what about 20 to 21 oct")
    assert get_session().requested_leave_type == "CL"


def test_demo_conflict_window_still_detected():
    # The golden demo: 27-28 Oct still surfaces the T02 SHORT + change freeze.
    out = agent.handle_message("I need 2 days off from 27 Oct to 28 Oct 2026")
    statuses = [e["status"] for e in out["activity"]]
    assert "fail" in statuses  # coverage SHORT and/or project event
    assert "confirm" in out["reply"].lower()  # an alternative is offered
