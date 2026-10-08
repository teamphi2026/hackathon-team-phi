"""Tests for the policy RAG tool (Task 8)."""
from __future__ import annotations

import pytest

from backend.state import get_session
from backend.tools import policy_rag


@pytest.fixture(autouse=True)
def _session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    policy_rag._index.cache_clear()
    yield
    s.reset()


def test_annual_leave_question_cites_al_section():
    result = policy_rag.search_policy("How many days of Annual Leave do I get?")
    assert result["company"] == "IBM"
    assert result["citations"]
    assert result["citations"][0]["section"] == "Annual Leave"
    assert "ibm_leave_policy.md" in result["citations"][0]["source"]


def test_childcare_question_cites_childcare_section():
    result = policy_rag.search_policy("What is the childcare leave entitlement for young children?")
    sections = [c["section"] for c in result["citations"]]
    assert "Childcare Leave" in sections


def test_ibm_user_never_reads_contractor_policy():
    result = policy_rag.search_policy("annual leave carry over rules")
    for c in result["citations"]:
        assert c["source"] == "ibm_leave_policy.md"


def test_answer_contains_citation_reference():
    result = policy_rag.search_policy("Do I need approval for annual leave?")
    assert "ibm_leave_policy.md" in result["answer"]
