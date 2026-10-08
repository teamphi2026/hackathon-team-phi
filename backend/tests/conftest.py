"""Shared pytest fixtures."""
from __future__ import annotations

import shutil

import pytest

from backend.config import data_file
from backend.state import get_session
from backend.tools import actions

# Data files that mutating tests may touch.
MUTABLE_FILES = ["13_Employee_Time.csv", "12_Time_Account_Detail.csv"]


@pytest.fixture
def isolate_data(tmp_path):
    """Back up and restore the mutable CSVs around a test, pin session to E005."""
    backups = {}
    for f in MUTABLE_FILES:
        shutil.copy(data_file(f), tmp_path / f)
        backups[f] = tmp_path / f
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    actions._invalidate_caches()
    yield s
    for f, b in backups.items():
        shutil.copy(b, data_file(f))
    actions._invalidate_caches()
    s.reset()
