"""FastAPI application entry point.

Wires the orchestrator agent, the approval token callback, session-state
polling for the manager UI, the Agent Activity SSE stream, and a demo reset.

Run with:
    uvicorn backend.main:app --reload
"""
from __future__ import annotations

import asyncio
import json

from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import agent, auth, email_service
from .state import get_session
from .tools import actions
from .tools import team_project as tp

app = FastAPI(title="Project-Aware Leave Planning Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Identity: resolve the logged-in employee from the bearer token and pin the
# session to them. The LLM/tools read identity from the session, never input.
# ---------------------------------------------------------------------------

def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return authorization


def _require_identity(authorization: str | None) -> str:
    """Resolve + apply the session identity, or 401 if the token is invalid."""
    token = _bearer(authorization)
    user_id = auth.user_id_for_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    s = get_session()
    if s.session_user_id != user_id:
        # Switching identity starts a clean session for that user.
        s.reset()
        s.session_user_id = user_id
    return user_id


class ChatRequest(BaseModel):
    message: str


class Credentials(BaseModel):
    username: str
    password: str


class Registration(BaseModel):
    username: str
    password: str
    user_id: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/api/register")
def register(req: Registration) -> dict:
    result = auth.register(req.username, req.password, req.user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/login")
def login(req: Credentials) -> dict:
    result = auth.login(req.username, req.password)
    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result["error"])
    return result


@app.post("/api/logout")
def logout(authorization: Optional[str] = Header(default=None)) -> dict:
    return auth.logout(_bearer(authorization) or "")


@app.get("/api/me")
def me(authorization: Optional[str] = Header(default=None)) -> dict:
    user_id = _require_identity(authorization)
    return auth.user_info(user_id)


@app.post("/api/chat")
def chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)) -> dict:
    """Main chat endpoint — delegates to the orchestrator agent."""
    _require_identity(authorization)
    return agent.handle_message(req.message)


@app.post("/api/approval/{token}")
def approval(token: str, action: str = "approve") -> dict:
    """Manager Approve/Reject token callback.

    Applies the decision via the state machine, then emails the employee.
    """
    result = actions.handle_approval_token(token, action)
    if result.get("success"):
        eid = result["employee_time_id"]
        if result["action"] == "approve":
            email_service.send_confirmation_email(eid)
        else:
            email_service.send_rejection_email(eid, reason="Rejected by manager")
    return result


class UIApproval(BaseModel):
    action: str


@app.post("/api/ui-approval")
def ui_approval(req: UIApproval, authorization: Optional[str] = Header(default=None)) -> dict:
    """Manager decision made in the UI card (not via an email token).

    Acts on the session's current pending request. Mirrors the token path:
    applies the state transition then emails the employee.
    """
    _require_identity(authorization)
    s = get_session()
    if not s.reference_id:
        return {"success": False, "message": "No pending request to decide on."}
    result = actions.handle_ui_decision(s.reference_id, req.action)
    if result.get("success"):
        eid = result["employee_time_id"]
        if result["action"] == "approve":
            email_service.send_confirmation_email(eid)
        else:
            email_service.send_rejection_email(eid, reason="Rejected by manager")
    return result


@app.get("/api/team-calendar")
def team_calendar(year: int, month: int,
                  authorization: Optional[str] = Header(default=None)) -> dict:
    """Month calendar of the logged-in user's teams: named leave + coverage."""
    _require_identity(authorization)
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1-12.")
    return tp.get_team_calendar(year, month)


@app.get("/api/session-state")
def session_state(authorization: Optional[str] = Header(default=None)) -> dict:
    """Snapshot of workflow state for the manager approval UI card."""
    _require_identity(authorization)
    s = get_session()
    return {
        "user_id": s.session_user_id,
        "employee_confirmed": s.employee_confirmed,
        "employee_time_id": s.employee_time_id,
        "approval_status": s.approval_status,
        "reference_id": s.reference_id,
        "activity": s.activity,
    }


@app.post("/api/reset")
def reset() -> dict[str, str]:
    get_session().reset()
    return {"status": "reset"}


@app.get("/api/activity")
async def activity_stream() -> StreamingResponse:
    """SSE stream of Agent Activity events for the right-hand panel."""

    async def event_gen():
        session = get_session()
        last = 0
        for _ in range(1200):  # ~10 min at 0.5s cadence
            events = session.activity[last:]
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
            last = len(session.activity)
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
