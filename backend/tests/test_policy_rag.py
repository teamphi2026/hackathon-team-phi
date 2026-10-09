"""Tests for the policy RAG tool: policy is chosen by the user's employer."""
from __future__ import annotations

import pytest

from backend.state import get_session
from backend.tools import policy_rag

YAM = "I_Be_Yam_Leave_Plan_Singapore.md"
TOMATO = "He_Be_Tomato_Leave_Policy_Singapore.md"


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
    assert result["citations"][0]["section"] == "1. Vacation - also known as Annual Leave"
    assert YAM in result["citations"][0]["source"]


def test_childcare_question_cites_childcare_section():
    result = policy_rag.search_policy("What is the childcare leave entitlement for young children?")
    sections = [c["section"] for c in result["citations"]]
    assert any("Childcare Leave" in section for section in sections)


def test_i_be_yam_user_never_reads_he_be_tomato_policy():
    result = policy_rag.search_policy("annual leave carry over rules")
    for c in result["citations"]:
        assert c["source"] == YAM


def test_he_be_tomato_user_reads_the_tomato_policy():
    _as("E006")   # Rahul Menon — employer: He Be Tomato
    result = policy_rag.search_policy("Annual leave entitlement by completed years of service")
    assert result["employer"] == "He Be Tomato"
    assert result["citations"][0]["source"] == TOMATO
    assert "| Less than 2 | 14 |" in result["answer"]


def test_employers_get_different_answers_to_the_same_question():
    q = "Am I eligible for childcare leave?"
    yam = policy_rag.search_policy(q)
    _as("E006")
    tomato = policy_rag.search_policy(q)
    assert yam["citations"][0]["source"] == YAM
    assert tomato["citations"][0]["source"] == TOMATO
    assert "3 months of continuous service" in tomato["answer"]


def test_employer_without_a_policy_gets_no_substitute():
    _as("E008")   # Jun Wei Ong — employer: She Be A Pear (no policy on file)
    result = policy_rag.search_policy("How many days of annual leave do I get?")
    assert result["citations"] == []
    assert "She Be A Pear" in result["answer"]


def test_answer_contains_citation_reference():
    result = policy_rag.search_policy("Do I need approval for annual leave?")
    assert YAM in result["answer"]


@pytest.mark.parametrize('uid,old,current', [
    ('E005', 'i_be_yam_leave_policy.md', YAM),
    ('E006', 'he_be_tomato_leave_policy.md', TOMATO),
])
def test_existing_company_records_resolve_renamed_policy(monkeypatch, uid, old, current):
    original = policy_rag.actions._read_rows
    def read_rows(filename):
        header, rows = original(filename)
        if filename == '20_Companies.csv':
            rows = [dict(row, policy_file=old) if row['policy_file'] == current else row for row in rows]
        return header, rows
    monkeypatch.setattr(policy_rag.actions, '_read_rows', read_rows)
    _as(uid)
    result = policy_rag.search_policy('How many days of annual leave do I get?')
    assert result['citations']
    assert all(c['source'] == current for c in result['citations'])
