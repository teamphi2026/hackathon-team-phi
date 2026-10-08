"""Unit tests for team / project context tools (Task 4 / spec Task 1.2)."""
from __future__ import annotations

import pytest

from backend.state import get_session
from backend.tools import team_project as tp


@pytest.fixture(autouse=True)
def _demo_session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    yield
    s.reset()


def _team(cov, team_id):
    return next(t for t in cov["teams"] if t["team_id"] == team_id)


# --- check_coverage --------------------------------------------------------

def test_coverage_27_28_oct_t02_short():
    cov = tp.check_coverage("2026-10-27", "2026-10-28")
    t02 = _team(cov, "T02")
    assert t02["status"] == "SHORT"
    assert t02["on_duty"] == 2
    assert t02["min_required"] == 3
    assert t02["headcount"] == 5


def test_coverage_clean_november_t02_ok():
    # Mid-November window with no other T02 absences.
    cov = tp.check_coverage("2026-11-17", "2026-11-18")
    t02 = _team(cov, "T02")
    assert t02["status"] in ("OK", "AT_MIN")
    # Only E005 away -> 4 on duty, min 3 -> OK.
    assert t02["on_duty"] == 4
    assert t02["status"] == "OK"


# --- get_project_events ----------------------------------------------------

def test_project_events_change_freeze_27_28_oct():
    ev = tp.get_project_events("2026-10-27", "2026-10-28")
    assert ev["project_id"] == "PROJ_ENG"
    assert any(e["event_type"] == "CHANGE_WINDOW" for e in ev["events"])


def test_project_events_empty_for_clean_window():
    ev = tp.get_project_events("2026-11-17", "2026-11-18")
    assert ev["events"] == []


# --- find_viable_date_ranges ----------------------------------------------

def test_find_viable_avoids_27_28_oct():
    result = tp.find_viable_date_ranges("AL", 2, "2026-10-27", search_days=28)
    assert len(result["candidates"]) >= 1
    for c in result["candidates"]:
        # No candidate should sit on the blocked 27-28 Oct window.
        assert not (c["start_date"] == "2026-10-27" and c["end_date"] == "2026-10-28")
        # Every candidate is coverage-safe.
        for team in c["coverage"]:
            assert team["status"] != "SHORT"


def test_get_team_leave_anonymised():
    tl = tp.get_team_leave("2026-10-27", "2026-10-28")
    t02 = next(t for t in tl["teams"] if t["team_id"] == "T02")
    assert len(t02["out_of_office"]) >= 1
    # Output is anonymised — no employee ids or names leak.
    for entry in t02["out_of_office"]:
        assert entry["label"] == "Out of office"
        assert "user_id" not in entry
