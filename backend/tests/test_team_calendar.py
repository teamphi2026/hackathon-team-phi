"""Tests for the team calendar tool (named entries + per-day coverage)."""
from __future__ import annotations

import pytest

from backend.state import get_session
from backend.tools import team_project as tp


@pytest.fixture(autouse=True)
def _session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield
    s.reset()


def _team(cal, team_id):
    return next(t for t in cal["teams"] if t["team_id"] == team_id)


def test_calendar_includes_user_teams():
    cal = tp.get_team_calendar(2026, 10)
    team_ids = {t["team_id"] for t in cal["teams"]}
    # E005 is in T02 (primary) and T04 (secondary).
    assert "T02" in team_ids and "T04" in team_ids


def test_calendar_has_named_entries():
    cal = tp.get_team_calendar(2026, 10)
    t02 = _team(cal, "T02")
    names = {e["name"] for e in t02["entries"]}
    # Real names appear (this view is not anonymised).
    assert "Wei Ling Chua" in names
    assert any(e["is_self"] for e in t02["entries"])


def test_calendar_marks_short_days():
    cal = tp.get_team_calendar(2026, 10)
    t02 = _team(cal, "T02")
    assert t02["day_status"]["2026-10-27"] == "SHORT"
    assert t02["day_status"]["2026-10-28"] == "SHORT"


def test_calendar_clean_month_no_short():
    cal = tp.get_team_calendar(2026, 1)  # January: no demo conflicts for T02
    t02 = _team(cal, "T02")
    assert all(v != "SHORT" for v in t02["day_status"].values())


def test_calendar_only_own_teams():
    # T03 (Sales) is not E005's team and must not appear.
    cal = tp.get_team_calendar(2026, 10)
    assert "T03" not in {t["team_id"] for t in cal["teams"]}
