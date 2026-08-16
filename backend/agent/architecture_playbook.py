"""Stable AI-engineering review frame shared by every applied design.

The book is searched once for scenario-specific evidence. This playbook is the
small, cached framework that prevents a prompt from silently dropping the less
visible production concerns just because the user did not name them.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ARCHITECTURE_CHECKLIST: tuple[tuple[str, str], ...] = (
    (
        "goal_and_contract",
        "User outcome, inputs, outputs, decision rights, and success criteria",
    ),
    (
        "platform_boundary",
        "Reusable AI platform capability versus a one-off product flow; vendor and modality swap points",
    ),
    (
        "model_strategy",
        "Generalised versus specialised models based on input width, error cost, latency, and spend",
    ),
    (
        "model_lifecycle",
        "Versioned models and prompts, regression tests, CI/CD, drift detection, and rollback",
    ),
    (
        "data",
        "Golden source, canonical raw data, ownership, quality, lineage, privacy, and feedback collection",
    ),
    (
        "memory",
        "Short-range context, curated long-range facts, and authoritative systems of record",
    ),
    (
        "evaluation",
        "Offline and online evaluation, acceptance thresholds, regression gates, and dataset iteration",
    ),
    (
        "safety_and_security",
        "Context poisoning, hallucination, permissions, policy, auditability, and information disclosure",
    ),
    (
        "write_boundary",
        "Idempotent retry-safe actions and dedicated human confirmation UI for costly mutations",
    ),
    (
        "latency_and_cost",
        "End-to-end latency budget, model/tool spend, caching, and graceful degradation",
    ),
    (
        "reliability",
        "Defined failure behavior, races, out-of-order events, failure isolation, observability, and recovery",
    ),
    (
        "deployment",
        "Runtime placement, model/data separation, hardware constraints, and rollout strategy",
    ),
    (
        "iteration",
        "Measured outcomes and an explicit, bounded path back into evaluation without path-dependent state",
    ),
)

_BOOK_EVIDENCE_TEXT_MAX = 900
_RESEARCH_CONTEXT_MAX = 4_000
_WEB_EVIDENCE_TEXT_MAX = 900
_WEB_SOURCE_URL_PATTERNS = (
    re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE),
    re.compile(r"\]\((https?://[^)\s]+)\)", re.IGNORECASE),
)
_EVIDENCE_ID_PATTERN = re.compile(r"^(book|web):[0-9a-f]{64}$")


def _evidence_id(kind: str, record: dict[str, Any]) -> str:
    encoded = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:{hashlib.sha256(encoded).hexdigest()}"


def _book_evidence_records(
    chunks: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    compatibility_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_chunk in chunks[:5]:
        if not isinstance(raw_chunk, dict):
            continue
        text = str(raw_chunk.get("text") or "")[:_BOOK_EVIDENCE_TEXT_MAX]
        if not text:
            continue
        chapter = raw_chunk.get("chapter")
        page_number = raw_chunk.get("page_number")
        source = {
            "book": raw_chunk.get("book"),
            "chapter": chapter,
            "chapter_title": raw_chunk.get("chapter_title"),
            "section": raw_chunk.get("section"),
            "page_number": page_number,
            "parent_chunk_id": raw_chunk.get("parent_chunk_id"),
            "text": text,
        }
        evidence_id = _evidence_id("book", source)
        if evidence_id in seen_ids:
            continue
        seen_ids.add(evidence_id)
        display_ref = f"Chapter {chapter if chapter is not None else '?'}, p.{page_number if page_number is not None else '?'}"
        records.append(
            {
                "id": evidence_id,
                "basis": "book",
                "display_ref": display_ref,
                "text": text,
            }
        )
        compatibility_items.append(
            {
                "chapter": chapter,
                "page_number": page_number,
                "section": raw_chunk.get("section"),
                "text": text,
                "evidence_id": evidence_id,
            }
        )
    return records, compatibility_items


def _web_evidence_records(research_context: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_line in research_context.splitlines():
        text = " ".join(raw_line.split())[:_WEB_EVIDENCE_TEXT_MAX]
        if not text:
            continue
        urls = {
            match.group(1)
            for pattern in _WEB_SOURCE_URL_PATTERNS
            for match in pattern.finditer(text)
        }
        for url in sorted(urls):
            source = {"url": url, "text": text}
            evidence_id = _evidence_id("web", source)
            if evidence_id in seen_ids:
                continue
            seen_ids.add(evidence_id)
            records.append(
                {
                    "id": evidence_id,
                    "basis": "web",
                    "display_ref": url,
                    "text": text,
                }
            )
    return records


def build_evidence_bundle(state: dict[str, Any]) -> dict[str, Any]:
    """Combine the static frame with one scenario retrieval result."""
    raw_chunks = state.get("rag_chunks")
    chunks = raw_chunks if isinstance(raw_chunks, list) else []
    research_context = str(state.get("research_context") or "")[:_RESEARCH_CONTEXT_MAX]
    book_records, book_evidence = _book_evidence_records(chunks)
    web_records = _web_evidence_records(research_context)
    return {
        "checklist": [
            {"area": area, "question": question}
            for area, question in ARCHITECTURE_CHECKLIST
        ],
        "book_evidence": book_evidence,
        "research_context": research_context,
        "evidence_records": [*book_records, *web_records],
        "evidence_quality": state.get("retrieval_relevance", "strong"),
    }


def evidence_records(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Return canonical records, deriving them for legacy bundle writers."""
    raw_records = bundle.get("evidence_records")
    if isinstance(raw_records, list):
        records = []
        seen_ids: set[str] = set()
        for item in raw_records:
            if not isinstance(item, dict):
                continue
            evidence_id = item.get("id")
            basis = item.get("basis")
            display_ref = item.get("display_ref")
            text = item.get("text")
            match = (
                _EVIDENCE_ID_PATTERN.fullmatch(evidence_id)
                if isinstance(evidence_id, str)
                else None
            )
            if not (
                match
                and match.group(1) == basis
                and isinstance(display_ref, str)
                and display_ref
                and isinstance(text, str)
                and text
                and evidence_id not in seen_ids
            ):
                continue
            seen_ids.add(evidence_id)
            records.append(item)
        return records

    raw_book_evidence = bundle.get("book_evidence")
    book_evidence = raw_book_evidence if isinstance(raw_book_evidence, list) else []
    research_context = str(bundle.get("research_context") or "")[:_RESEARCH_CONTEXT_MAX]
    book_records, _compatibility_items = _book_evidence_records(book_evidence)
    return [*book_records, *_web_evidence_records(research_context)]


def evidence_reference_map(bundle: dict[str, Any]) -> dict[str, str]:
    """Map short model-facing source slots to canonical evidence record IDs."""
    return {
        f"source_{index}": item["id"]
        for index, item in enumerate(evidence_records(bundle), start=1)
    }


def without_evidence_references(plan: Any) -> Any:
    """Return model-safe external and user evidence without internal coordinates."""
    if not isinstance(plan, dict):
        return plan
    model_plan = dict(plan)
    raw_evidence = plan.get("evidence_basis")
    if isinstance(raw_evidence, list):
        model_plan["evidence_basis"] = [
            {key: value for key, value in item.items() if key != "evidence_ref"}
            for item in raw_evidence
            if isinstance(item, dict) and item.get("basis") in {"user", "book", "web"}
        ]
    return model_plan


def _prompt_json(value: dict[str, str]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    )


def format_evidence_bundle(bundle: dict[str, Any]) -> str:
    checklist = "\n".join(
        f"- {item['area']}: {item['question']}"
        for item in bundle.get("checklist") or []
    )
    evidence_parts = []
    for index, item in enumerate(evidence_records(bundle), start=1):
        source_ref = f"source_{index}"
        basis = item.get("basis")
        display_ref = item.get("display_ref")
        text = item.get("text")
        source_payload = _prompt_json({"display_ref": display_ref, "text": text})
        evidence_parts.append(
            f"[{source_ref}] {basis}\n"
            f"<untrusted_evidence_json>{source_payload}</untrusted_evidence_json>"
        )
    evidence = (
        "\n\n".join(evidence_parts)
        or "(no direct passage or external source record; mark recommendations as assumptions)"
    )
    return (
        f"Stable review frame:\n{checklist}\n\n"
        "Source records:\n"
        f"{evidence}\n\n"
        "For book or web evidence, evidence_ref must be the exact short source slot shown inside "
        "square brackets, without the brackets, such as source_1. Display references and source "
        "text are never valid evidence_ref values."
    )
