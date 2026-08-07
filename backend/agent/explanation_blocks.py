"""Stream one model call as complete, pausable explanation blocks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any

from adapters.llm_adapter import stream_response, stream_response_compat
from agent.prompt_security import protect_system_prompt


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


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
) -> str:
    """Emit a block as soon as its compact JSON object is complete.

    The provider still receives one request. UI pause only delays browser reveal;
    it never restarts a paid model call.
    """
    raw_output = ""
    parse_buffer = ""
    emitted: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()

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
                raw_output += content
                parse_buffer += content
                parse_buffer, parsed = _decode_available(
                    parse_buffer,
                    decoder,
                    allowed_node_ids,
                )
                for block in parsed:
                    emitted.append(block)
                    await send(_block_event(block, graph_version))
    except TimeoutError:
        timed_out = True
    finally:
        await response_stream.aclose()

    if timed_out:
        await send({
            "type": "workflow_progress",
            "phase": "explain",
            "status": "degraded",
            "title": "Explanation latency budget reached",
            "detail": "Returning the bounded explanation available before the stage deadline.",
        })
    if not emitted:
        fallback = _fallback_block(raw_output)
        emitted.append(fallback)
        await send(_block_event(fallback, graph_version))

    return "\n\n".join(
        f"## {block['title']}\n\n{block['content']}"
        for block in emitted
    )


def _decode_available(
    buffer: str,
    decoder: json.JSONDecoder,
    allowed_node_ids: set[str],
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
        parsed.extend(_normalise_payload(value, allowed_node_ids))
        remaining = candidate[end:]


def _normalise_payload(value: Any, allowed_node_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    nested = value.get("blocks")
    if isinstance(nested, list):
        return [
            block
            for item in nested
            if (block := _normalise_block(item, allowed_node_ids)) is not None
        ]
    block = _normalise_block(value, allowed_node_ids)
    return [block] if block else []


def _normalise_block(value: Any, allowed_node_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    content = "\n".join(line.rstrip() for line in str(value.get("content") or "").splitlines()).strip()
    if not content:
        return None
    title = " ".join(str(value.get("title") or "Architecture note").split())[:100]
    title = title or "Architecture note"
    block_id = " ".join(str(value.get("block_id") or title.lower().replace(" ", "_")).split())[:80]
    block_id = block_id or "architecture_note"
    raw_related = value.get("related_node_ids")
    related_values = raw_related if isinstance(raw_related, list) else []
    related = [
        str(node_id)
        for node_id in related_values[:6]
        if str(node_id) in allowed_node_ids
    ]
    raw_evidence = value.get("evidence_refs")
    evidence_values = raw_evidence if isinstance(raw_evidence, list) else []
    evidence = [
        " ".join(str(reference).split())[:120]
        for reference in evidence_values[:6]
        if str(reference).strip()
    ]
    return {
        "block_id": block_id,
        "title": title,
        "content": content[:4000],
        "related_node_ids": related,
        "evidence_refs": evidence,
    }


def _fallback_block(raw_output: str) -> dict[str, Any]:
    content = raw_output.strip().removeprefix("```json").removesuffix("```").strip()
    return {
        "block_id": "architecture_explanation",
        "title": "Architecture explanation",
        "content": (
            content or "The architecture is ready. Select a node to explore its responsibility."
        )[:4000],
        "related_node_ids": [],
        "evidence_refs": [],
    }


def _block_event(block: dict[str, Any], graph_version: str | None) -> dict[str, Any]:
    return {
        "type": "explanation_block",
        **block,
        "graph_version": graph_version,
    }
