"""Tests for the system prompt and entitlement labelling.

These guard the fixes for: (1) the model assuming the wrong year, and
(2) the model failing to recognise bookable leave types.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend import agent
from backend.state import get_session
from backend.tools import hr


@pytest.fixture(autouse=True)
def _session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield
    s.reset()


def test_prompt_states_todays_date():
    prompt = agent._system_prompt()
    assert date.today().isoformat() in prompt


def test_prompt_states_leave_year():
    prompt = agent._system_prompt()
    assert str(agent.LEAVE_YEAR) in prompt
    assert "2024" not in prompt  # must not anchor on a stale year


def test_prompt_explains_relative_dates_and_submission():
    prompt = agent._system_prompt().lower()
    assert "relative dates" in prompt
    assert "submit_leave_request" in prompt
    assert "confirm" in prompt


def test_prompt_mentions_annual_leave_is_bookable():
    # Directly addresses the earlier hallucination that AL wasn't available.
    prompt = agent._system_prompt().lower()
    assert "annual leave" in prompt
    assert "validate_policy" in prompt


def test_entitlements_expose_bookable_leave_type_codes():
    accounts = hr.get_entitlements()["accounts"]
    codes = {a["leave_type"] for a in accounts}
    # Annual Leave must be present and labelled 'AL' so the agent can book it.
    assert "AL" in codes
    assert "CL" in codes
    al = next(a for a in accounts if a["leave_type"] == "AL")
    assert al["available"] == 5.0
