"""In-memory session + conversation state.

A single-process in-memory store is sufficient for the hackathon demo.
Session identity (`user_id`) is set server-side at startup and is never
taken from the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import DEMO_USER_ID


@dataclass
class SessionState:
    """Per-session conversation and workflow state (see design section 7)."""

    session_user_id: str = DEMO_USER_ID

    # intent
    user_goal: str | None = None
    requested_leave_type: str | None = None
    requested_dates: tuple[str, str] | None = None
    requested_duration: int | None = None
    flexibility: str | None = None

    # cached context
    employee_profile: dict[str, Any] | None = None
    entitlements: dict[str, Any] | None = None

    # options / recommendation
    original_option: dict[str, Any] | None = None
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    recommended_leave_type: str | None = None
    recommended_dates: tuple[str, str] | None = None
    recommendation_reason: str | None = None

    # workflow (mutated by application logic only, never the LLM)
    employee_confirmed: bool = False
    employee_time_id: str | None = None
    approval_status: str | None = None
    reference_id: str | None = None

    # {token: {employee_time_id, action, expiry, used}} — managed by email_service
    approval_token_map: dict[str, Any] = field(default_factory=dict)

    # activity log for the Agent Activity panel
    activity: list[dict[str, Any]] = field(default_factory=list)

    # LLM conversation history (OpenAI message dicts) — gives the agent memory
    # of earlier turns within the session.
    conversation: list[dict[str, Any]] = field(default_factory=list)

    def reset(self) -> None:
        """Reset to a fresh demo state (used by the Demo Reset button)."""
        fresh = SessionState(session_user_id=self.session_user_id)
        self.__dict__.update(fresh.__dict__)

    def log_activity(self, status: str, message: str) -> dict[str, Any]:
        """Append a tool/agent event for the Agent Activity stream."""
        event = {"seq": len(self.activity), "status": status, "message": message}
        self.activity.append(event)
        return event


# Single demo session. A real app would key these by session id.
SESSION = SessionState()


def get_session() -> SessionState:
    return SESSION
