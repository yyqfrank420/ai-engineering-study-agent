"""Stream one model call as complete, pausable explanation blocks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any

from adapters.llm_adapter import stream_response, stream_response_compat
from agent.prompt_security import protect_system_prompt


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]

_BLOCK_KEYS = {
    "block_id",
    "title",
    "content",
    "related_node_ids",
    "evidence_refs",
}
_MINIMUM_BLOCKS = 3
_MAXIMUM_BLOCKS = 6

_PRESERVED_EDIT_COMPLETION_SENTENCE = "The requested diagram edit was not approved, so the prior approved diagram remains unchanged."
_PRESERVED_CREATE_COMPLETION_SENTENCE = "The requested new diagram was not approved, so the prior approved diagram remains unchanged."


async def stream_explanation_blocks(
    *,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    effort: str,
    max_output_tokens: int,
    timeout_seconds: float,
    telemetry: dict[str, Any],
    send: SendEvent,
    graph_version: str | None,
    allowed_node_ids: set[str],
    allowed_evidence_refs: set[str] | None = None,
    allow_fallback: bool = True,
    provider_attempt_limit: int | None = None,
) -> str:
    """Emit a block as soon as its compact JSON object is complete.

    The provider still receives one request. UI pause only delays browser reveal;
    it never restarts a paid model call.
    """
    parse_buffer = ""
    emitted: list[dict[str, Any]] = []
    emitted_ids: set[str] = set()
    decoder = json.JSONDecoder()
    required_completion_sentence = _required_completion_sentence(messages)
    pending_block: dict[str, Any] | None = None

    async def emit(block: dict[str, Any]) -> None:
        await send(_block_event(block, graph_version))

    async def emit_parsed(block: dict[str, Any]) -> None:
        nonlocal pending_block
        if required_completion_sentence is None:
            await emit(block)
            return
        if pending_block is not None:
            await emit(pending_block)
        pending_block = block

    response_stream = stream_response_compat(
        stream_response,
        model=model,
        system=protect_system_prompt(system),
        messages=messages,
        effort=effort,
        max_output_tokens=max_output_tokens,
        temperature=None,
        top_p=None,
        top_k=None,
        telemetry=telemetry,
        allow_fallback=allow_fallback,
        provider_attempt_limit=provider_attempt_limit,
    )
    timed_out = False
    try:
        async with asyncio.timeout(timeout_seconds):
            async for event_type, content in response_stream:
                if event_type == "provider_switch":
                    await send({"type": "provider_switch", "provider": content})
                    continue
                if event_type != "text":
                    continue
                parse_buffer += content
                parse_buffer, parsed = _decode_available(
                    parse_buffer,
                    decoder,
                    allowed_node_ids,
                    allowed_evidence_refs or set(),
                )
                for block in parsed:
                    if len(emitted) >= _MAXIMUM_BLOCKS:
                        break
                    if block["block_id"] in emitted_ids:
                        continue
                    emitted.append(block)
                    emitted_ids.add(block["block_id"])
                    await emit_parsed(block)
    except TimeoutError:
        timed_out = True
    finally:
        await response_stream.aclose()

    if timed_out:
        await send(
            {
                "type": "workflow_progress",
                "phase": "explain",
                "status": "degraded",
                "title": "Explanation latency budget reached",
                "detail": "Returning the bounded explanation available before the stage deadline.",
            }
        )
    if not emitted:
        if not timed_out:
            await send(
                {
                    "type": "workflow_progress",
                    "phase": "explain",
                    "status": "degraded",
                    "title": "Explanation format unavailable",
                    "detail": "Returning a safe fallback because the model response did not meet the required block contract.",
                }
            )
        fallback = _fallback_block()
        emitted.append(fallback)
        emitted_ids.add(fallback["block_id"])
        await emit_parsed(fallback)

    for block in _supplementary_blocks(emitted_ids):
        emitted.append(block)
        emitted_ids.add(block["block_id"])
        await emit_parsed(block)

    if pending_block is not None:
        _append_required_completion_sentence(
            pending_block,
            required_completion_sentence,
        )
        await emit(pending_block)

    return "\n\n".join(
        f"## {block['title']}\n\n{block['content']}" for block in emitted
    )


def _decode_available(
    buffer: str,
    decoder: json.JSONDecoder,
    allowed_node_ids: set[str],
    allowed_evidence_refs: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    remaining = buffer
    while True:
        stripped = remaining.lstrip()
        if stripped.startswith("```json"):
            stripped = stripped[7:].lstrip()
        elif stripped.startswith("```"):
            stripped = stripped[3:].lstrip()
        object_start = stripped.find("{")
        if object_start < 0:
            return remaining[-32:], parsed
        candidate = stripped[object_start:]
        try:
            value, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            return candidate, parsed
        parsed.extend(
            _normalise_payload(value, allowed_node_ids, allowed_evidence_refs)
        )
        remaining = candidate[end:]


def _normalise_payload(
    value: Any,
    allowed_node_ids: set[str],
    allowed_evidence_refs: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    block = _normalise_block(value, allowed_node_ids, allowed_evidence_refs)
    return [block] if block else []


def _normalise_block(
    value: Any,
    allowed_node_ids: set[str],
    allowed_evidence_refs: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != _BLOCK_KEYS:
        return None
    content = "\n".join(
        line.rstrip() for line in str(value.get("content") or "").splitlines()
    ).strip()
    if not content:
        return None
    title = " ".join(str(value.get("title") or "Architecture note").split())[:100]
    title = title or "Architecture note"
    block_id = " ".join(
        str(value.get("block_id") or title.lower().replace(" ", "_")).split()
    )[:80]
    block_id = block_id or "architecture_note"
    raw_related = value.get("related_node_ids")
    related_values = raw_related if isinstance(raw_related, list) else []
    related = [
        str(node_id)
        for node_id in related_values[:6]
        if str(node_id) in allowed_node_ids
    ]
    raw_evidence = value.get("evidence_refs")
    if not isinstance(raw_evidence, list) or not all(
        isinstance(reference, str) and reference in (allowed_evidence_refs or set())
        for reference in raw_evidence
    ):
        return None
    evidence = raw_evidence[:6]
    return {
        "block_id": block_id,
        "title": title,
        "content": content[:4000],
        "related_node_ids": related,
        "evidence_refs": evidence,
    }


def _fallback_block(_raw_output: str = "") -> dict[str, Any]:
    return {
        "block_id": "architecture_explanation",
        "title": "Explanation unavailable",
        "content": "The explanation response was unavailable. Please retry.",
        "related_node_ids": [],
        "evidence_refs": [],
    }


def _supplementary_blocks(emitted_ids: set[str]) -> list[dict[str, Any]]:
    templates = (
        (
            "design_assumptions",
            "Assumptions to check",
            "The model response did not provide a separate assumptions block.",
        ),
        (
            "runtime_path",
            "Runtime path",
            "The model response did not provide a separate runtime-path block.",
        ),
        (
            "controls",
            "Controls to review",
            "The model response did not provide a separate controls block.",
        ),
        (
            "next_decision",
            "Next decision",
            "The model response did not provide a separate next-decision block.",
        ),
        (
            "trade_offs",
            "Trade-offs",
            "The model response did not provide a separate trade-offs block.",
        ),
    )
    blocks = []
    for block_id, title, content in templates:
        if len(emitted_ids) + len(blocks) >= _MINIMUM_BLOCKS:
            break
        if block_id in emitted_ids:
            continue
        blocks.append(
            {
                "block_id": block_id,
                "title": title,
                "content": content,
                "related_node_ids": [],
                "evidence_refs": [],
            }
        )
    return blocks


def _required_completion_sentence(messages: list[dict[str, Any]]) -> str | None:
    if not messages:
        return None
    content = messages[-1].get("content")
    if not isinstance(content, str):
        return None
    trusted_result = content.partition("<trusted_turn_result>")[2].partition(
        "</trusted_turn_result>"
    )[0]
    if "Publication state: preserved." not in trusted_result:
        return None
    for sentence in (
        _PRESERVED_EDIT_COMPLETION_SENTENCE,
        _PRESERVED_CREATE_COMPLETION_SENTENCE,
    ):
        if sentence in trusted_result:
            return sentence
    return None


def _append_required_completion_sentence(
    block: dict[str, Any],
    required_completion_sentence: str | None,
) -> None:
    if required_completion_sentence is None:
        return
    content = block["content"]
    if required_completion_sentence not in content:
        available_content = 4000 - len(required_completion_sentence) - 2
        block["content"] = (
            f"{content[:available_content]}\n\n{required_completion_sentence}"
        )


def _block_event(block: dict[str, Any], graph_version: str | None) -> dict[str, Any]:
    return {
        "type": "explanation_block",
        **block,
        "graph_version": graph_version,
    }
