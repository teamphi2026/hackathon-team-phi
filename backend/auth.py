"""Authentication — register, login, token sessions.

Hackathon-grade auth (deliberately beyond the original "no auth" design):
  * Users live in hr_data/21_Users.csv, each mapped to an existing employee E###.
  * Passwords are salted SHA-256 (no plaintext stored). No complexity rule.
  * Login issues an opaque in-memory bearer token mapped to the user_id.
  * Register creates a brand-new user row; it must map to an existing employee
    so the leave data (balances, team, manager) resolves.

NOTE: salted SHA-256 and in-memory tokens are fine for a demo but are NOT
production-grade (use a slow KDF like bcrypt/argon2 and persistent, signed
sessions for production).
"""
from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any

from . import storage

USERS_FILE = "21_Users.csv"
_FIELDS = ["username", "salt", "password_hash", "user_id", "display_name"]

# token -> user_id (in-memory; cleared on restart)
_TOKENS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

def _read_users() -> list[dict[str, str]]:
    try:
        return storage.read_rows(USERS_FILE)[1]
    except FileNotFoundError:
        return []


def _write_users(rows: list[dict[str, str]]) -> None:
    try:
        header = storage.read_rows(USERS_FILE)[0]
    except FileNotFoundError:
        header = _FIELDS
    storage.write_rows(USERS_FILE, header, rows)


def _find_user(username: str) -> dict[str, str] | None:
    uname = username.strip().lower()
    return next((u for u in _read_users() if u["username"].lower() == uname), None)


def _employee_exists(user_id: str) -> dict[str, str] | None:
    return next((r for r in storage.read_rows("02_Job_Information.csv")[1]
                 if r["user_id"] == user_id), None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@storage.mutation
def register(username: str, password: str, user_id: str) -> dict[str, Any]:
    """Create a new user mapped to an existing employee. Returns {success,...}."""
    username = (username or "").strip()
    user_id = (user_id or "").strip().upper()
    if not username or not password or not user_id:
        return {"success": False, "error": "username, password and employee id are required."}
    if _find_user(username):
        return {"success": False, "error": "That username is already taken."}
    employee = _employee_exists(user_id)
    if employee is None:
        return {"success": False, "error": f"No employee {user_id} exists to map to."}

    salt = os.urandom(16).hex()
    row = {
        "username": username,
        "salt": salt,
        "password_hash": _hash(password, salt),
        "user_id": user_id,
        "display_name": employee.get("full_name", username),
    }
    users = _read_users()
    users.append(row)
    _write_users(users)
    return {"success": True, "username": username, "user_id": user_id,
            "display_name": row["display_name"]}


@storage.scoped
def login(username: str, password: str) -> dict[str, Any]:
    """Validate credentials and issue a bearer token. Returns {success, token,...}."""
    user = _find_user(username or "")
    if user is None or _hash(password or "", user["salt"]) != user["password_hash"]:
        return {"success": False, "error": "Invalid username or password."}
    token = secrets.token_urlsafe(24)
    _TOKENS[token] = user["user_id"]
    return {"success": True, "token": token, "user_id": user["user_id"],
            "display_name": user.get("display_name", username)}


def logout(token: str) -> dict[str, Any]:
    _TOKENS.pop(token, None)
    return {"success": True}


def user_id_for_token(token: str | None) -> str | None:
    """Resolve the employee id behind a bearer token, or None."""
    if not token:
        return None
    return _TOKENS.get(token)


def user_info(user_id: str) -> dict[str, Any]:
    employee = _employee_exists(user_id) or {}
    return {
        "user_id": user_id,
        "display_name": employee.get("full_name", user_id),
        "email": employee.get("email", ""),
        "job_title": employee.get("job_title", ""),
    }
