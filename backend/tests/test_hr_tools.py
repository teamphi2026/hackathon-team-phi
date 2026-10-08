"""Unit tests for HR context tools (Task 3 / spec Task 1.1)."""
from __future__ import annotations

from datetime import date

import pytest

from backend.state import get_session
from backend.tools import hr


@pytest.fixture(autouse=True)
def _demo_session():
    """Pin the session to Wei Ling (E005) and reset after each test."""
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield
    s.reset()


# --- profile / dependents --------------------------------------------------

def test_profile_is_wei_ling():
    p = hr.get_employee_profile()
    assert p["user_id"] == "E005"
    assert p["manager_id"] == "E004"
    assert p["project_id"] == "PROJ_ENG"
    assert "T02" in p["home_team_id"]


def test_dependents_has_child():
    deps = hr.get_dependents(reference_year=2026)
    assert len(deps) == 1
    assert deps[0]["relationship"] == "Child"
    # Born 2020-03-15 -> age 5 at 1 Jan 2026.
    assert deps[0]["age_at_jan1"] == 5


# --- childcare eligibility -------------------------------------------------

def test_e005_cl_eligibility():
    result = hr.check_childcare_eligibility(reference_year=2026)
    assert result["eligible"] is True
    assert result["quota_days"] == 6


def test_cl_ineligible_for_user_without_children():
    get_session().session_user_id = "E006"
    result = hr.check_childcare_eligibility(reference_year=2026)
    assert result["eligible"] is False
    assert result["quota_days"] == 0


# --- working-day counting --------------------------------------------------

def test_working_days_9_to_13_nov_is_4():
    # 9 Nov 2026 is the Deepavali in-lieu public holiday (Monday) -> excluded.
    days = hr.count_working_days(
        date(2026, 11, 9), date(2026, 11, 13), "SG_STD", "SG"
    )
    assert days == 4


def test_working_days_27_to_28_oct_is_2():
    days = hr.count_working_days(
        date(2026, 10, 27), date(2026, 10, 28), "SG_STD", "SG"
    )
    assert days == 2


# --- entitlements ----------------------------------------------------------

def test_entitlements_include_cl_with_6_days():
    ent = hr.get_entitlements()
    cl = next(a for a in ent["accounts"] if a["account_type"] == "ACC_CL")
    assert cl["available"] == 6.0


# --- validate_policy -------------------------------------------------------

def test_validate_policy_rejects_past_dates():
    result = hr.validate_policy("AL", "2026-01-05", "2026-01-06")
    assert result["valid"] is False
    assert any("past" in v.lower() for v in result["violations"])


def test_validate_policy_rejects_insufficient_balance():
    # E005 has only 5 AL available; request a long future window with no holidays.
    result = hr.validate_policy("AL", "2026-12-01", "2026-12-18")
    assert result["valid"] is False
    assert any("insufficient" in v.lower() for v in result["violations"])


def test_validate_policy_detects_overlap():
    # E005 has R009 pending 26-30 Oct 2026.
    result = hr.validate_policy("AL", "2026-10-27", "2026-10-28")
    assert result["valid"] is False
    assert any("overlap" in v.lower() for v in result["violations"])
