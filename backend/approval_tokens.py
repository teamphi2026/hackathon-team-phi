"""Durable email approval tokens; only SHA-256 token digests are stored in Sheets."""
import hashlib
from datetime import datetime

from . import storage


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def save(token: str, entry: dict) -> None:
    header, rows = storage.read_rows(storage.TOKEN_FILE)
    rows.append({"token_hash": _digest(token), "employee_time_id": entry["employee_time_id"],
                 "action": entry["action"], "expiry": entry["expiry"].isoformat(), "used": "false"})
    storage.write_rows(storage.TOKEN_FILE, header, rows)


def lookup(token: str) -> dict | None:
    _, rows = storage.read_rows(storage.TOKEN_FILE)
    row = next((r for r in rows if r["token_hash"] == _digest(token)), None)
    if row is None:
        return None
    return {"employee_time_id": row["employee_time_id"], "action": row["action"],
            "expiry": datetime.fromisoformat(row["expiry"]), "used": row["used"].lower() == "true"}


def consume(token: str) -> None:
    header, rows = storage.read_rows(storage.TOKEN_FILE)
    row = next(r for r in rows if r["token_hash"] == _digest(token))
    row["used"] = "true"
    storage.write_rows(storage.TOKEN_FILE, header, rows)
