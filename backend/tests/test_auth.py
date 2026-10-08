"""Tests for authentication (register / login / token identity)."""
from __future__ import annotations

import shutil

import pytest

from backend import auth
from backend.config import data_file


@pytest.fixture(autouse=True)
def _isolate_users(tmp_path):
    # Register writes to the users CSV; back it up and restore.
    users = data_file("21_Users.csv")
    backup = tmp_path / "users.csv"
    shutil.copy(users, backup)
    auth._TOKENS.clear()
    yield
    shutil.copy(backup, users)
    auth._TOKENS.clear()


def test_login_with_seed_account():
    result = auth.login("weiling", "password")
    assert result["success"] is True
    assert result["user_id"] == "E005"
    assert result["token"]


def test_login_wrong_password():
    result = auth.login("weiling", "nope")
    assert result["success"] is False


def test_login_unknown_user():
    assert auth.login("ghost", "x")["success"] is False


def test_token_resolves_to_user():
    token = auth.login("marcus", "password")["token"]
    assert auth.user_id_for_token(token) == "E004"


def test_logout_invalidates_token():
    token = auth.login("weiling", "password")["token"]
    auth.logout(token)
    assert auth.user_id_for_token(token) is None


def test_register_creates_user_mapped_to_employee():
    result = auth.register("rahul", "pw", "E006")
    assert result["success"] is True
    assert result["user_id"] == "E006"
    # New user can log in.
    login = auth.login("rahul", "pw")
    assert login["success"] is True
    assert login["user_id"] == "E006"


def test_register_rejects_duplicate_username():
    auth.register("dup", "pw", "E006")
    second = auth.register("dup", "pw", "E007")
    assert second["success"] is False
    assert "taken" in second["error"].lower()


def test_register_rejects_unknown_employee():
    result = auth.register("newbie", "pw", "E999")
    assert result["success"] is False
    assert "E999" in result["error"]


def test_password_not_stored_in_plaintext():
    auth.register("secret", "mypassword", "E006")
    user = auth._find_user("secret")
    assert user["password_hash"] != "mypassword"
    assert "mypassword" not in user["password_hash"]
