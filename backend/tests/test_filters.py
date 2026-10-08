"""Tests for the output filter (Task 7 / guardrails 6 & 8)."""
from __future__ import annotations

import pytest

from backend import filters
from backend.state import get_session


@pytest.fixture(autouse=True)
def _session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield
    s.reset()


def test_allows_own_id_and_manager_id():
    # E005 is the session user; E004 is the manager.
    out = filters.filter_output("Your id is E005 and your manager is E004.")
    assert "E005" in out
    assert "E004" in out


def test_redacts_other_employee_ids():
    out = filters.filter_output("Colleague E006 and E007 are also off.")
    assert "E006" not in out
    assert "E007" not in out
    assert "[redacted]" in out


def test_allows_own_and_manager_email():
    # E005's own email and E004 (manager) email, per 02_Job_Information.csv.
    out = filters.filter_output(
        "chuaweiling1@outlook.com and marcuslim94@proton.me"
    )
    assert "chuaweiling1@outlook.com" in out
    assert "marcuslim94@proton.me" in out


def test_redacts_other_emails():
    out = filters.filter_output("Contact rahul.menon@i-be-yam.com for details.")
    assert "rahul.menon@i-be-yam.com" not in out
    assert "[redacted-email]" in out


def test_scrub_freetext_returns_placeholder():
    assert filters.scrub_other_users_freetext("Family trip to Bali") == "Out of office"


def test_empty_input_is_safe():
    assert filters.filter_output("") == ""
