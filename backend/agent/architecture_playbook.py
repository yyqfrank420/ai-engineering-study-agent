"""Stable AI-engineering review frame shared by every applied design.

The book is searched once for scenario-specific evidence. This playbook is the
small, cached framework that prevents a prompt from silently dropping the less
visible production concerns just because the user did not name them.
"""

from __future__ import annotations

from typing import Any


ARCHITECTURE_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("goal_and_contract", "User outcome, inputs, outputs, decision rights, and success criteria"),
    ("platform_boundary", "Reusable AI platform capability versus a one-off product flow; vendor and modality swap points"),
    ("model_strategy", "Generalised versus specialised models based on input width, error cost, latency, and spend"),
    ("model_lifecycle", "Versioned models and prompts, regression tests, CI/CD, drift detection, and rollback"),
    ("data", "Golden source, canonical raw data, ownership, quality, lineage, privacy, and feedback collection"),
    ("memory", "Short-range context, curated long-range facts, and authoritative systems of record"),
    ("evaluation", "Offline and online evaluation, acceptance thresholds, regression gates, and dataset iteration"),
    ("safety_and_security", "Context poisoning, hallucination, permissions, policy, auditability, and information disclosure"),
    ("write_boundary", "Idempotent retry-safe actions and dedicated human confirmation UI for costly mutations"),
    ("latency_and_cost", "End-to-end latency budget, model/tool spend, caching, and graceful degradation"),
    ("reliability", "Defined failure behavior, races, out-of-order events, failure isolation, observability, and recovery"),
    ("deployment", "Runtime placement, model/data separation, hardware constraints, and rollout strategy"),
    ("iteration", "Measured outcomes and an explicit, bounded path back into evaluation without path-dependent state"),
)


def build_evidence_bundle(state: dict[str, Any]) -> dict[str, Any]:
    """Combine the static frame with one scenario retrieval result."""
    chunks = state.get("rag_chunks") or []
    return {
        "checklist": [
            {"area": area, "question": question}
            for area, question in ARCHITECTURE_CHECKLIST
        ],
        "book_evidence": [
            {
                "chapter": chunk.get("chapter"),
                "page_number": chunk.get("page_number"),
                "section": chunk.get("section"),
                "text": str(chunk.get("text") or "")[:900],
            }
            for chunk in chunks[:5]
        ],
        "research_context": str(state.get("research_context") or "")[:4000],
        "evidence_quality": state.get("retrieval_relevance", "strong"),
    }


def format_evidence_bundle(bundle: dict[str, Any]) -> str:
    checklist = "\n".join(
        f"- {item['area']}: {item['question']}"
        for item in bundle.get("checklist") or []
    )
    evidence_parts = []
    for item in bundle.get("book_evidence") or []:
        evidence_parts.append(
            f"[Chapter {item.get('chapter', '?')}, p.{item.get('page_number', '?')}] "
            f"{item.get('text', '')}"
        )
    evidence = "\n\n".join(evidence_parts) or "(no direct passage; mark recommendations as assumptions)"
    research = bundle.get("research_context") or "(no external research supplied)"
    return (
        f"Stable review frame:\n{checklist}\n\n"
        f"Scenario-specific book evidence:\n{evidence}\n\n"
        f"Optional external evidence:\n{research}"
    )
