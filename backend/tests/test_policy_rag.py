"""Tests for the policy RAG tool: policy is chosen by the user's employer."""
from __future__ import annotations

import pytest

from backend.state import get_session
from backend.tools import policy_rag

YAM = "i_be_yam_leave_policy.md"
TOMATO = "he_be_tomato_leave_policy.md"


@pytest.fixture(autouse=True)
def _session():
    s = get_session()
    s.reset()
    s.session_user_id = "E005"   # Wei Ling Chua — employer: I Be Yam
    policy_rag._index.cache_clear()
    yield
    s.reset()


def _as(uid: str):
    get_session().session_user_id = uid
    policy_rag._index.cache_clear()


def test_annual_leave_question_cites_al_section():
    result = policy_rag.search_policy("How many days of Annual Leave do I get?")
    assert result["employer"] == "I Be Yam"
    assert result["citations"]
    assert result["citations"][0]["section"] == "Annual Leave"
    assert YAM in result["citations"][0]["source"]


def test_childcare_question_cites_childcare_section():
    result = policy_rag.search_policy("What is the childcare leave entitlement for young children?")
    sections = [c["section"] for c in result["citations"]]
    assert "Childcare Leave" in sections


def test_i_be_yam_user_never_reads_he_be_tomato_policy():
    result = policy_rag.search_policy("annual leave carry over rules")
    for c in result["citations"]:
        assert c["source"] == YAM


def test_he_be_tomato_user_reads_the_tomato_policy():
    _as("E006")   # Rahul Menon — employer: He Be Tomato
    result = policy_rag.search_policy("How many days of annual leave do I get?")
    assert result["employer"] == "He Be Tomato"
    assert result["citations"][0]["source"] == TOMATO
    assert "14 days" in result["answer"]


def test_employers_get_different_answers_to_the_same_question():
    q = "Am I eligible for childcare leave?"
    yam = policy_rag.search_policy(q)
    _as("E006")
    tomato = policy_rag.search_policy(q)
    assert yam["citations"][0]["source"] == YAM
    assert tomato["citations"][0]["source"] == TOMATO
    assert "not eligible" in tomato["answer"].lower()


def test_employer_without_a_policy_gets_no_substitute():
    _as("E008")   # Jun Wei Ong — employer: She Be A Pear (no policy on file)
    result = policy_rag.search_policy("How many days of annual leave do I get?")
    assert result["citations"] == []
    assert "She Be A Pear" in result["answer"]


def test_answer_contains_citation_reference():
    result = policy_rag.search_policy("Do I need approval for annual leave?")
    assert YAM in result["answer"]
