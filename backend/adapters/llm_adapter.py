# ─────────────────────────────────────────────────────────────────────────────
# File: backend/adapters/llm_adapter.py
# Purpose: Thin wrapper around Anthropic and OpenAI SDKs for streaming LLM calls.
#          Implements automatic retry (up to llm_max_retries) on any Anthropic
#          failure, then falls back to OpenAI GPT equivalents if configured.
#          Yields a ("provider_switch", "openai") tuple before the first OpenAI
#          token so calling nodes can forward a browser notification.
# Language: Python
# Connects to: config.py (model names, API keys), agent nodes, api/sse_handler.py
# Inputs:  model name, system prompt, messages list, optional thinking budget
# Outputs: async generator yielding (event_type, content) tuples:
#          ("thinking", text) | ("text", token) | ("done", "") |
#          ("provider_switch", provider)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
from collections.abc import AsyncGenerator
from functools import lru_cache
import inspect
import time

import anthropic
import openai

from config import settings
from storage.telemetry_store import record_llm_telemetry

# ── Clients (lazy-initialised and reused) ────────────────────────────────────


@lru_cache(maxsize=1)
def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


@lru_cache(maxsize=1)
def _get_openai_client() -> openai.AsyncOpenAI | None:
    if not settings.openai_api_key:
        return None
    return openai.AsyncOpenAI(api_key=settings.openai_api_key)

# Maps Anthropic model name → OpenAI fallback model name.
# Populated from settings so a config change is all that's needed to swap models.
_FALLBACK_MODELS: dict[str, str] = {
    settings.orchestrator_model: settings.orchestrator_fallback_model,
    settings.worker_model:       settings.worker_fallback_model,
}


def build_telemetry(
    operation: str,
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    payload = {"operation": operation}
    if user_id:
        payload["user_id"] = user_id
    if thread_id:
        payload["thread_id"] = thread_id
    if metadata:
        payload["metadata"] = metadata
    return payload


def stream_response_compat(streamer, **kwargs):
    telemetry = kwargs.pop("telemetry", None)
    if telemetry is not None:
        try:
            params = inspect.signature(streamer).parameters.values()
            accepts_telemetry = any(
                param.kind == inspect.Parameter.VAR_KEYWORD or param.name == "telemetry"
                for param in params
            )
        except (TypeError, ValueError):
            accepts_telemetry = True
        if accepts_telemetry:
            kwargs["telemetry"] = telemetry
    return streamer(**kwargs)


async def _openai_stream(
    model: str,
    system: str,
    messages: list[dict],
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """
    Stream a response from the OpenAI Chat Completions API.
    Normalises output to the same (event_type, content) tuple format as
    the Anthropic path so all callers are provider-agnostic.

    Args:
        model:            OpenAI model ID (e.g. "gpt-5.4")
        system:           System prompt — prepended as role="system" message
        messages:         Chat history in {"role": ..., "content": ...} format
        reasoning_effort: Optional reasoning depth for thinking models
                          ("low" | "medium" | "high" | "xhigh")
    """
    openai_client = _get_openai_client()
    assert openai_client is not None, "OpenAI client not initialised (OPENAI_API_KEY not set)"

    # OpenAI takes the system prompt as the first message in the list
    openai_messages = [{"role": "system", "content": system}, *messages]

    kwargs: dict = {
        "model":    model,
        "messages": openai_messages,
        "stream":   True,
    }
    if reasoning_effort:
        # Supported on gpt-5.4 and o-series thinking models
        kwargs["reasoning_effort"] = reasoning_effort
    else:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p

    stream = await openai_client.chat.completions.create(**kwargs)
    async for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta.content:
                yield ("text", delta.content)

    yield ("done", "")


async def stream_response(
    model: str,
    system: str,
    messages: list[dict],
    thinking_budget: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    telemetry: dict | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """
    Stream a response with automatic retry + OpenAI fallback.

    Retry behaviour:
    - Tries Anthropic up to settings.llm_max_retries times with
      settings.llm_retry_delay_s seconds between attempts.
    - Only retries if the failure occurred before any tokens were yielded
      (connection / auth errors). Mid-stream drops are re-raised immediately
      since partial output can't be safely replayed.
    - On full exhaustion, falls back to OpenAI if configured.
    - Yields ("provider_switch", "openai") before the first OpenAI token
      so callers can surface a "falling back to GPT" UI notice.
    - If no OpenAI client is configured, raises the last Anthropic exception.

    Yields (event_type, content) tuples:
    - ("thinking", text)             — extended thinking deltas (Anthropic only)
    - ("text", token)                — response text deltas
    - ("done", "")                   — signals stream completion
    - ("provider_switch", provider)  — signals fallback to another provider
    """
    kwargs: dict = {
        "model":      model,
        "max_tokens": settings.llm_max_tokens,
        "system":     system,
        "messages":   messages,
    }
    if temperature is not None and thinking_budget is None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if top_k is not None and thinking_budget is None:
        kwargs["top_k"] = top_k
    if thinking_budget is not None:
        # Extended thinking is native in claude-sonnet-4-6 (no beta header needed)
        kwargs["thinking"] = {
            "type":          "enabled",
            "budget_tokens": max(thinking_budget, 1000),
        }

    last_exc: Exception | None = None
    started_at = time.perf_counter()
    output_chars = 0
    used_fallback = False
    final_provider = "anthropic"
    final_model = model

    def _record(status: str, *, error_type: str | None = None) -> None:
        details = telemetry or {}
        try:
            record_llm_telemetry(
                operation=details.get("operation", "unknown"),
                provider=final_provider,
                model=final_model,
                status=status,
                duration_ms=max(1, int((time.perf_counter() - started_at) * 1000)),
                output_chars=output_chars,
                used_fallback=used_fallback,
                user_id=details.get("user_id"),
                thread_id=details.get("thread_id"),
                error_type=error_type,
                metadata={
                    "message_count": len(messages),
                    "thinking_budget": thinking_budget,
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    **(details.get("metadata") or {}),
                },
            )
        except Exception as exc:
            print(f"[llm] Telemetry write failed: {type(exc).__name__}: {exc}")

    for attempt in range(1, settings.llm_max_retries + 1):
        tokens_yielded = False
        try:
            async with _get_anthropic_client().messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        tokens_yielded = True
                        delta = event.delta
                        if delta.type == "thinking_delta":
                            yield ("thinking", delta.thinking)
                        elif delta.type == "text_delta":
                            output_chars += len(delta.text)
                            yield ("text", delta.text)
            _record("success")
            yield ("done", "")
            return   # Anthropic succeeded

        except Exception as exc:
            last_exc = exc
            if tokens_yielded:
                # Already sent partial output — can't replay safely, surface the error
                _record("error", error_type=type(exc).__name__)
                raise
            print(
                f"[llm] Anthropic attempt {attempt}/{settings.llm_max_retries} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            if attempt < settings.llm_max_retries:
                await asyncio.sleep(settings.llm_retry_delay_s)

    # All Anthropic attempts exhausted — try OpenAI fallback
    fallback_model = _FALLBACK_MODELS.get(model)
    if fallback_model and _get_openai_client():
        print(f"[llm] Falling back to OpenAI {fallback_model}")
        used_fallback = True
        final_provider = "openai"
        final_model = fallback_model
        yield ("provider_switch", "openai")
        # Only the orchestrator path uses reasoning_effort
        reasoning_effort = (
            settings.orchestrator_fallback_reasoning_effort
            if model == settings.orchestrator_model
            else None
        )
        try:
            async for event in _openai_stream(
                fallback_model,
                system,
                messages,
                reasoning_effort,
                temperature,
                top_p,
            ):
                if event[0] == "text":
                    output_chars += len(event[1])
                yield event
            _record("success")
        except Exception as exc:
            _record("error", error_type=type(exc).__name__)
            raise
    else:
        if last_exc is not None:
            _record("error", error_type=type(last_exc).__name__)
        raise last_exc  # type: ignore[misc]
