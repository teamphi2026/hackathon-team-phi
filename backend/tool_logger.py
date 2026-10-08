"""Structured logging of every tool call — for debugging and audit.

Every orchestrator tool invocation is routed through `call_tool`, which:
  * logs to the Python logger "leave.tools" (stderr by default), and
  * appends a JSON line to logs/tool_calls.jsonl

Each record captures: timestamp, session user, tool name, arguments, whether
it succeeded, a compact result preview (or the error), and the duration in ms.

Arguments and results are truncated so a stray large payload can't bloat the
log, and known-sensitive argument keys are redacted.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import REPO_ROOT
from .state import get_session

LOG_DIR = REPO_ROOT / "logs"
LOG_FILE = LOG_DIR / "tool_calls.jsonl"

_MAX_FIELD = 800  # chars; truncate long arg/result previews
_REDACT_KEYS = {"token", "password", "api_key", "smtp_password"}

logger = logging.getLogger("leave.tools")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_FIELD else text[:_MAX_FIELD] + f"... <+{len(text) - _MAX_FIELD} chars>"


def _safe(obj: Any) -> str:
    try:
        return _truncate(json.dumps(obj, default=str, ensure_ascii=False))
    except Exception:
        return _truncate(repr(obj))


def _redact_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: ("<redacted>" if k.lower() in _REDACT_KEYS else v) for k, v in kwargs.items()}


def _write_record(record: dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    except Exception as exc:  # never let logging break a request
        logger.warning("failed to write tool-call log: %s", exc)


def call_tool(name: str, func: Callable[..., Any], **kwargs: Any) -> Any:
    """Invoke a tool with structured logging. Returns the tool's result.

    Exceptions are logged and re-raised so callers see real failures.
    """
    user = get_session().session_user_id
    safe_args = _redact_args(kwargs)
    started = time.perf_counter()
    base = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "tool": name,
        "args": safe_args,
    }

    logger.info("→ %s(%s) user=%s", name, _safe(safe_args), user)
    try:
        result = func(**kwargs)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        record = {**base, "ok": False, "error": repr(exc), "duration_ms": duration_ms}
        logger.exception("✗ %s raised after %sms: %s", name, duration_ms, exc)
        _write_record(record)
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    record = {**base, "ok": True, "result": _safe(result), "duration_ms": duration_ms}
    logger.info("← %s ok in %sms", name, duration_ms)
    _write_record(record)
    return result
