# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/nodes/rag_worker.py
# Purpose: Phase 1 RAG worker — searches FAISS for relevant book sections and
#          returns them as structured Chunk objects for the orchestrator.
#          Also applies a lightweight relevance heuristic so the UI can offer
#          an in-flight web-search escalation when book support looks weak.
# Language: Python
# Connects to: agent/tools/rag_worker_tools/, agent/state.py, config.py
# Inputs:  AgentState (user_message, vectorstore/parent_docs via app.state)
# Outputs: AgentState update: rag_chunks, retrieval_relevance, retrieval_notice
# ─────────────────────────────────────────────────────────────────────────────

import json
import re

from agent.state import AgentState
from config import settings

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "how", "in", "into", "is", "it", "of", "on", "or", "that", "the", "their",
    "this", "to", "what", "when", "where", "which", "why", "with", "you", "your",
}

_EVAL_EVIDENCE_MAX_CHUNKS = 8
_EVAL_EVIDENCE_MAX_TEXT_CHARS = 4_000


async def rag_worker_node(state: AgentState, tools: list) -> AgentState:
    """
    Run the RAG worker. Searches the FAISS index and returns matching parent sections.

    Args:
        state: current AgentState
        tools: [rag_search_tool, get_section_tool] bound at startup
    """
    send = state["send"]
    await send({"type": "worker_status", "worker": "rag", "status": "Searching book…"})

    tool_map = {t.name: t for t in tools}
    rag_chunks: list[dict] = []

    search_tool = tool_map.get("rag_search")
    if search_tool:
        result_json = search_tool.invoke({"query": state["user_message"], "k": settings.rag_top_k})
        rag_chunks = json.loads(result_json)

    if _may_emit_eval_evidence(state):
        await send({
            "type": "retrieval_evidence",
            "query": str(state["user_message"])[: settings.max_message_bytes],
            "chunks": _bounded_eval_evidence(rag_chunks),
        })

    relevance, notice = _assess_retrieval_relevance(state["user_message"], rag_chunks)
    return {
        **state,
        "rag_chunks": rag_chunks,
        "retrieval_relevance": relevance,
        "retrieval_notice": notice,
    }


def _may_emit_eval_evidence(state: AgentState) -> bool:
    """Keep source passages inside the isolated, allowlisted staging evaluator."""
    email = str(state.get("user_email") or "").strip().lower()
    return settings.db_schema == "staging" and email in settings.internal_test_email_allowlist


def _bounded_eval_evidence(rag_chunks: list[dict]) -> list[dict]:
    evidence: list[dict] = []
    for chunk in rag_chunks[:_EVAL_EVIDENCE_MAX_CHUNKS]:
        evidence.append({
            "book": str(chunk.get("book") or "")[:200],
            "chapter": chunk.get("chapter"),
            "chapter_title": str(chunk.get("chapter_title") or "")[:300],
            "section": str(chunk.get("section") or "")[:300],
            "page_number": chunk.get("page_number"),
            "parent_chunk_id": str(chunk.get("parent_chunk_id") or "")[:200],
            "text": str(chunk.get("text") or "")[:_EVAL_EVIDENCE_MAX_TEXT_CHARS],
        })
    return evidence


def _assess_retrieval_relevance(query: str, rag_chunks: list[dict]) -> tuple[str, str]:
    """
    Lightweight heuristic for "is the book retrieval probably good enough?"
    It intentionally fails conservative: only flag weak when coverage looks thin.
    """
    if not rag_chunks:
        return (
            "weak",
            "I did not find a direct book match, so I will apply the closest book patterns. You can use the search tool if you want broader context.",
        )

    query_terms = _meaningful_terms(query)
    if not query_terms:
        return ("strong", "")

    combined_text = "\n".join(chunk.get("text", "") for chunk in rag_chunks[:3]).lower()
    matched_terms = [term for term in query_terms if term in combined_text]
    coverage = len(matched_terms) / max(len(query_terms), 1)

    if len(rag_chunks) < 2 and coverage < 0.34:
        return (
            "weak",
            "The book match is indirect, so I will map the nearest book concepts onto your question. You can use the search tool for broader context.",
        )

    if coverage < 0.2:
        return (
            "weak",
            "I found an indirect book match, so I will use the closest book ideas as the foundation. You can use the search tool to widen the context.",
        )

    return ("strong", "")


def _meaningful_terms(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
    return [word for word in words if word not in _STOP_WORDS]
