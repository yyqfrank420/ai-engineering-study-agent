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

from typing import Any, Callable, Awaitable

from adapters.llm_adapter import stream_response, stream_response_compat


async def stream_llm(
    *,
    model: str,
    system: str,
    messages: list[dict],
    thinking_budget: int | None = None,
    temperature: float,
    top_p: float | None = None,
    top_k: int | None = None,
    telemetry: dict | None = None,
    send: Callable[[dict], Awaitable[None]] | None = None,
    stream_deltas: bool = False,
    stream_thinking: bool = False,
) -> str:
    """Stream an LLM response, handle provider switches, return accumulated text.

    Args:
        send:             SSE callback. If None, provider_switch events are silently dropped.
        stream_deltas:    When True, forward each text chunk as a response_delta SSE event.
        stream_thinking:  When True, forward thinking chunks as thinking_delta SSE events.
    """
    accumulated = ""
    async for event_type, content in stream_response_compat(
        stream_response,
        model=model,
        system=system,
        messages=messages,
        thinking_budget=thinking_budget,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        telemetry=telemetry,
    ):
        if event_type == "provider_switch" and send:
            await send({"type": "provider_switch", "provider": content})
        elif event_type == "thinking" and stream_thinking and send:
            await send({"type": "thinking_delta", "content": content})
        elif event_type == "text":
            accumulated += content
            if stream_deltas and send:
                await send({"type": "response_delta", "content": content})
    return accumulated
