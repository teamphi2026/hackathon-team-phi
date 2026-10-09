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
EMAIL_LOG_FILE = LOG_DIR / "email_events.jsonl"
FORECAST_LOG_FILE = LOG_DIR / "leave_forecast.jsonl"

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


def _write_record(record: dict[str, Any], path: Path | None = None) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(path or LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    except Exception as exc:  # never let logging break a request
        logger.warning("failed to write tool-call log: %s", exc)


email_logger = logging.getLogger("leave.email")
if not email_logger.handlers:
    _eh = logging.StreamHandler()
    _eh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    email_logger.addHandler(_eh)
    email_logger.setLevel(logging.INFO)


def log_email(event: str, detail: dict[str, Any], *, level: int = logging.INFO) -> None:
    """Log an email lifecycle event to stderr and logs/email_events.jsonl.

    `event` is one of: attempt, sent, dry_run, failed, skipped, tokens_issued.
    Callers must never put passwords, approval tokens or message bodies in
    `detail`; as a safety net, redacted keys are masked here too.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": get_session().session_user_id,
        "email_event": event,
        **_redact_args(detail),
    }
    email_logger.log(level, "✉ email.%s %s", event, _safe(_redact_args(detail)))
    _write_record(record, EMAIL_LOG_FILE)


forecast_logger = logging.getLogger("leave.forecast")
if not forecast_logger.handlers:
    _fh = logging.StreamHandler()
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    forecast_logger.addHandler(_fh)
    forecast_logger.setLevel(logging.INFO)


def log_forecast(event: str, detail: dict[str, Any], *, level: int = logging.INFO) -> None:
    """Log a leave-forecast sheet event to stderr and logs/leave_forecast.jsonl.

    `event` is one of: updated, unchanged, skipped, failed. Never log credentials.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": get_session().session_user_id,
        "forecast_event": event,
        **_redact_args(detail),
    }
    forecast_logger.log(level, "▦ forecast.%s %s", event, _safe(_redact_args(detail)))
    _write_record(record, FORECAST_LOG_FILE)


def log_intent(kind: str, detail: dict[str, Any]) -> None:
    """Log a planner/LLM intent decision (not a tool call).

    `kind` is a short label such as 'user_message', 'planner_intent',
    'llm_reasoning', or 'llm_tool_calls'. `detail` is a JSON-able dict.
    """
    user = get_session().session_user_id
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "intent": kind,
        "detail": detail,
    }
    logger.info("◆ intent[%s] %s", kind, _safe(detail))
    _write_record(record)


def log_llm_call(
    model: str,
    messages: list[dict[str, Any]],
    response: dict[str, Any],
    duration_ms: float,
    *,
    error: str | None = None,
) -> None:
    """Log one raw LLM round-trip: request (model + messages) and response.

    `messages` is the full chat history sent; `response` is a compact dict
    (content, tool calls, finish reason, usage). Previews are truncated.
    """
    user = get_session().session_user_id
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "llm_call": model,
        "request_messages": _safe(messages),
        "response": response if error is None else None,
        "error": error,
        "duration_ms": duration_ms,
    }
    if error is None:
        logger.info("◆ llm %s in %sms (usage=%s, finish=%s)", model, duration_ms,
                    response.get("usage"), response.get("finish_reason"))
    else:
        logger.error("◆ llm %s FAILED in %sms: %s", model, duration_ms, error)
    _write_record(record)


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
