"""Policy RAG tool — Task 8.

search_policy(question) returns the best-matching policy section(s) with a
heading citation, bound to the session user's company (resolved server-side —
the model cannot choose which policy to read).

Embedding backend:
  * sentence-transformers (all-MiniLM-L6-v2) when installed.
  * A dependency-free TF-IDF cosine fallback otherwise, so the tool works
    offline and in CI without downloading model weights. Same interface either way.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from ..config import POLICIES_DIR
from ..state import get_session
from . import actions

# Map the session user's company to its policy file. For the hackathon all demo
# employees are IBM; contractors (P1) resolve to the ContractCo policy.
_COMPANY_POLICY = {
    "IBM": "ibm_leave_policy.md",
    "ContractCo": "contractco_leave_policy.md",
}
_DEFAULT_POLICY = "ibm_leave_policy.md"


# ---------------------------------------------------------------------------
# Company resolution (server-side, never from the LLM)
# ---------------------------------------------------------------------------

def _company_for_user(uid: str) -> str:
    """Resolve the user's company from their email domain / Companies table."""
    _, people = actions._read_rows("02_Job_Information.csv")
    person = next((r for r in people if r["user_id"] == uid), None)
    if person is None:
        return "IBM"
    email = person.get("email", "")
    try:
        _, companies = actions._read_rows("20_Companies.csv")
    except FileNotFoundError:
        return "IBM"
    for c in companies:
        hr_email = c.get("contract_hr_email", "")
        domain = hr_email.split("@")[-1] if "@" in hr_email else ""
        if domain and email.endswith("@" + domain):
            return c["company_id"]
    return "IBM"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_policy(path) -> list[dict[str, str]]:
    """Split a markdown policy into (heading, text) chunks by ## sections."""
    text = path.read_text(encoding="utf-8")
    chunks: list[dict[str, str]] = []
    current_heading = "Overview"
    buffer: list[str] = []

    def flush():
        body = " ".join(" ".join(buffer).split())
        if body:
            chunks.append({"heading": current_heading, "text": body})

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip()
            buffer = []
        elif line.startswith("# ") or line.startswith(">"):
            continue
        else:
            buffer.append(line)
    flush()
    return chunks


# ---------------------------------------------------------------------------
# Vectorisation (sentence-transformers if present, else TF-IDF)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _st_model():
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        return None


def _tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z]+", s.lower())


def _tfidf_vectors(docs: list[str]) -> tuple[list[dict[str, float]], dict[str, float]]:
    tf_list = []
    df: dict[str, int] = {}
    for d in docs:
        toks = _tokenize(d)
        tf: dict[str, float] = {}
        for t in toks:
            tf[t] = tf.get(t, 0.0) + 1.0
        for t in tf:
            df[t] = df.get(t, 0) + 1
        tf_list.append(tf)
    n = len(docs)
    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    vecs = []
    for tf in tf_list:
        vecs.append({t: f * idf.get(t, 0.0) for t, f in tf.items()})
    return vecs, idf


def _cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Index (per policy file, cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _index(policy_file: str) -> dict[str, Any] | None:
    path = POLICIES_DIR / policy_file
    if not path.exists():
        return None
    chunks = _chunk_policy(path)
    if not chunks:
        return None
    model = _st_model()
    if model is not None:
        emb = model.encode([c["text"] for c in chunks], normalize_embeddings=True)
        return {"backend": "st", "chunks": chunks, "emb": emb, "model": True}
    docs = [c["heading"] + " " + c["text"] for c in chunks]
    vecs, idf = _tfidf_vectors(docs)
    return {"backend": "tfidf", "chunks": chunks, "vecs": vecs, "idf": idf}


# ---------------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------------

def search_policy(question: str, top_k: int = 2) -> dict[str, Any]:
    """Return the top matching policy section(s) with heading citations."""
    uid = get_session().session_user_id
    company = _company_for_user(uid)
    policy_file = _COMPANY_POLICY.get(company, _DEFAULT_POLICY)

    idx = _index(policy_file)
    if idx is None:
        return {"answer": "Policy document not yet loaded.", "citations": [], "company": company}

    chunks = idx["chunks"]
    if idx["backend"] == "st":
        model = _st_model()
        q = model.encode([question], normalize_embeddings=True)[0]
        scores = [float((q * e).sum()) for e in idx["emb"]]
    else:
        q_tf: dict[str, float] = {}
        for t in _tokenize(question):
            q_tf[t] = q_tf.get(t, 0.0) + 1.0
        q_vec = {t: f * idx["idf"].get(t, 0.0) for t, f in q_tf.items()}
        scores = [_cosine_sparse(q_vec, v) for v in idx["vecs"]]

    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:top_k]
    citations = [
        {
            "section": chunks[i]["heading"],
            "text": chunks[i]["text"],
            "score": round(scores[i], 4),
            "source": policy_file,
        }
        for i in ranked
        if scores[i] > 0
    ]
    if not citations:
        return {
            "answer": "I couldn't find a relevant policy section for that question.",
            "citations": [],
            "company": company,
        }
    top = citations[0]
    return {
        "answer": f"{top['text']} (See '{top['section']}' in {policy_file}.)",
        "citations": citations,
        "company": company,
    }
