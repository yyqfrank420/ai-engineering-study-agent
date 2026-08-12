# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/stream_utils.py
# Purpose: Shared helper for streaming LLM responses with consistent event
#          dispatch. Wraps stream_response_compat with provider_switch handling,
#          optional response_delta / thinking_delta forwarding, and text accumulation.
# Language: Python
# Connects to: adapters/llm_adapter.py (stream_response, stream_response_compat)
# Inputs:  model, system prompt, messages, sampling params, send callback
# Outputs: accumulated text string from the LLM response
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
import json
from typing import Callable, Awaitable

from adapters.llm_adapter import stream_response, stream_response_compat
from agent.prompt_security import protect_system_prompt


@dataclass(frozen=True)
class StructuredLLMResponse:
    text: str
    finish_reason: str | None
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


async def stream_structured_llm(
    *,
    model: str,
    system: str,
    messages: list[dict],
    response_schema: dict,
    temperature: float,
    effort: str,
    telemetry: dict | None = None,
    timeout_seconds: float | None = None,
    max_output_tokens: int | None = None,
    provider_attempt_limit: int | None = None,
) -> StructuredLLMResponse:
    """Run one schema-constrained provider call with ordinary telemetry."""
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    accumulated = ""
    metadata: dict = {}
    async with asyncio.timeout(timeout_seconds):
        response = stream_response_compat(
            stream_response,
            model=model,
            system=protect_system_prompt(system),
            messages=messages,
            thinking_budget=None,
            temperature=temperature,
            effort=effort,
            telemetry=telemetry,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
            allow_fallback=False,
            provider_attempt_limit=provider_attempt_limit,
        )
        async with aclosing(response):
            async for event_type, content in response:
                if event_type == "text":
                    accumulated += content
                elif event_type == "response_metadata":
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        metadata = parsed
    return StructuredLLMResponse(
        text=accumulated,
        finish_reason=metadata.get("finish_reason"),
        input_tokens=int(metadata.get("input_tokens") or 0),
        output_tokens=int(metadata.get("output_tokens") or 0),
        provider=str(metadata.get("provider") or "unknown"),
        model=str(metadata.get("model") or model),
    )


async def stream_llm(
    *,
    model: str,
    system: str,
    messages: list[dict],
    thinking_budget: int | None = None,
    temperature: float,
    top_p: float | None = None,
    top_k: int | None = None,
    effort: str | None = None,
    telemetry: dict | None = None,
    timeout_seconds: float | None = None,
    max_output_tokens: int | None = None,
    allow_fallback: bool = True,
    provider_attempt_limit: int | None = None,
    send: Callable[[dict], Awaitable[None]] | None = None,
    stream_deltas: bool = False,
    stream_thinking: bool = False,
) -> str:
    """Stream an LLM response, handle provider switches, return accumulated text.

    Args:
        send:             SSE callback. If None, provider_switch events are silently dropped.
        timeout_seconds:  Optional deadline for the complete provider retry/fallback chain.
        max_output_tokens: Optional positive provider output cap, bounded globally.
        stream_deltas:    When True, forward each text chunk as a response_delta SSE event.
        stream_thinking:  When True, forward thinking chunks as thinking_delta SSE events.
    """
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    accumulated = ""
    async with asyncio.timeout(timeout_seconds):
        response = stream_response_compat(
            stream_response,
            model=model,
            system=protect_system_prompt(system),
            messages=messages,
            thinking_budget=thinking_budget,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            effort=effort,
            telemetry=telemetry,
            max_output_tokens=max_output_tokens,
            allow_fallback=allow_fallback,
            provider_attempt_limit=provider_attempt_limit,
        )
        async with aclosing(response):
            async for event_type, content in response:
                if event_type == "provider_switch" and send:
                    await send({"type": "provider_switch", "provider": content})
                elif event_type == "thinking" and stream_thinking and send:
                    await send({"type": "thinking_delta", "content": content})
                elif event_type == "text":
                    accumulated += content
                    if stream_deltas and send:
                        await send({"type": "response_delta", "content": content})
    return accumulated
