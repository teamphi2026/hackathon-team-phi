"""Verify the LLM path logs raw calls, intent, and tool use (with a mock client).

The real IBM ICA endpoint isn't available in tests, so we inject a fake OpenAI
client that returns a scripted tool call then a final answer, and assert the
logger records the full round-trip.
"""
from __future__ import annotations

import json
import shutil
import types

import pytest

from backend import agent, config
from backend import tool_logger
from backend.config import data_file
from backend.state import get_session


# --- Minimal fakes mimicking the openai client response shape ---------------

class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, name, arguments):
        self.id = "call_1"
        self.function = _Fn(name, arguments)

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message, finish_reason):
        self.message = message
        self.finish_reason = finish_reason


class _Usage:
    def model_dump(self):
        return {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49}


class _Resp:
    def __init__(self, message, finish_reason):
        self.choices = [_Choice(message, finish_reason)]
        self.usage = _Usage()


class _FakeCompletions:
    def __init__(self, scripted):
        self._scripted = scripted
        self._i = 0

    def create(self, **kwargs):
        r = self._scripted[self._i]
        self._i += 1
        return r


class _FakeClient:
    def __init__(self, scripted):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(scripted))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    for f in ["13_Employee_Time.csv", "12_Time_Account_Detail.csv"]:
        shutil.copy(data_file(f), tmp_path / f)
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    # Point the log file at a temp location so we can read it back cleanly.
    monkeypatch.setattr(tool_logger, "LOG_FILE", tmp_path / "log.jsonl")
    monkeypatch.setattr(tool_logger, "LOG_DIR", tmp_path)
    yield s
    for f in ["13_Employee_Time.csv", "12_Time_Account_Detail.csv"]:
        shutil.copy(tmp_path / f, data_file(f))
    s.reset()


def _read_records(tmp_path):
    return [json.loads(l) for l in open(tmp_path / "log.jsonl")]


def test_llm_path_logs_call_intent_and_tool(tmp_path, monkeypatch):
    # Script: turn 1 -> call get_entitlements; turn 2 -> final answer.
    scripted = [
        _Resp(_Msg(content="Let me check your balance.",
                   tool_calls=[_ToolCall("get_entitlements", "{}")]), "tool_calls"),
        _Resp(_Msg(content="You have 5 days of Annual Leave.", tool_calls=None), "stop"),
    ]

    # Enable LLM mode (overrides the deterministic default from conftest).
    monkeypatch.setattr(config, "ICA_API_KEY", "test-key")
    monkeypatch.setattr(config, "ICA_BASE_URL", "https://example.test")
    # Inject the fake client by patching the OpenAI symbol imported inside _route_llm.
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _FakeClient(scripted))

    out = agent.handle_message("what's my balance?")
    assert "Annual Leave" in out["reply"]

    records = _read_records(tmp_path)
    kinds = [r.get("llm_call") or r.get("intent") or r.get("tool") for r in records]

    # Raw LLM round-trips logged (two turns).
    llm_calls = [r for r in records if r.get("llm_call")]
    assert len(llm_calls) == 2
    assert llm_calls[0]["response"]["finish_reason"] == "tool_calls"
    assert llm_calls[0]["response"]["usage"]["total_tokens"] == 49
    assert "duration_ms" in llm_calls[0]

    # The tool the model chose was actually executed and logged.
    tool_records = [r for r in records if r.get("tool") == "get_entitlements"]
    assert tool_records and tool_records[0]["ok"] is True

    # Intent (reasoning) logged too.
    assert any(r.get("intent") == "llm_reasoning" for r in records)


def test_conversation_memory_persists_across_turns(tmp_path, monkeypatch):
    # Two independent turns, each a single final answer (no tool calls).
    scripted = [
        _Resp(_Msg(content="Noted — mid-November.", tool_calls=None), "stop"),
        _Resp(_Msg(content="You said mid-November.", tool_calls=None), "stop"),
    ]
    monkeypatch.setattr(config, "ICA_API_KEY", "test-key")
    monkeypatch.setattr(config, "ICA_BASE_URL", "https://example.test")
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _FakeClient(scripted))

    s = get_session()
    agent.handle_message("I want leave in mid-November")
    # After turn 1: system + user + assistant.
    assert [m["role"] for m in s.conversation] == ["system", "user", "assistant"]

    agent.handle_message("when did I say?")
    # Turn 2 appended user + assistant, preserving earlier turns.
    roles = [m["role"] for m in s.conversation]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    # The first user message is still present — the agent has memory of it.
    assert any(m["role"] == "user" and "mid-November" in m["content"] for m in s.conversation)


def test_reset_clears_conversation(tmp_path, monkeypatch):
    scripted = [_Resp(_Msg(content="hi", tool_calls=None), "stop")]
    monkeypatch.setattr(config, "ICA_API_KEY", "test-key")
    monkeypatch.setattr(config, "ICA_BASE_URL", "https://example.test")
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _FakeClient(scripted))

    s = get_session()
    agent.handle_message("hello")
    assert len(s.conversation) > 0
    s.reset()
    assert s.conversation == []


def test_llm_error_is_logged_and_handled(tmp_path, monkeypatch):
    class _Boom:
        def create(self, **kw):
            raise RuntimeError("endpoint down")

    class _BoomClient:
        chat = types.SimpleNamespace(completions=_Boom())

    monkeypatch.setattr(config, "ICA_API_KEY", "test-key")
    monkeypatch.setattr(config, "ICA_BASE_URL", "https://example.test")
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _BoomClient())

    out = agent.handle_message("what's my balance?")
    assert "trouble reaching the model" in out["reply"].lower()

    records = _read_records(tmp_path)
    errored = [r for r in records if r.get("llm_call") and r.get("error")]
    assert errored and "endpoint down" in errored[0]["error"]
