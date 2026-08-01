# ─────────────────────────────────────────────────────────────────────────────
# File: backend/adapters/llm_adapter.py
# Purpose: Thin wrapper around Anthropic and OpenAI SDKs for streaming LLM calls.
#          Retries transient Anthropic failures, then falls back to OpenAI GPT
#          equivalents if configured. Non-retryable 4xx failures fall back once.
#          Yields a ("provider_switch", "openai") tuple before the first OpenAI
#          token so calling nodes can forward a browser notification.
# Language: Python
# Connects to: config.py (model names, API keys), agent nodes, api/sse_handler.py
# Inputs:  model name, system prompt, messages list, optional thinking budget
# Outputs: async generator yielding (event_type, content) tuples:
#          ("thinking", text) | ("text", token) | ("done", "") |
#          ("provider_switch", provider)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from functools import lru_cache
import hashlib
import inspect
import json
import logging
import time

from config import settings

logger = logging.getLogger(__name__)

# ── Clients (lazy-initialised and reused) ────────────────────────────────────


@lru_cache(maxsize=1)
def _get_anthropic_client():
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


@lru_cache(maxsize=1)
def _get_openai_client():
    if not settings.openai_api_key:
        return None
    import openai

    return openai.AsyncOpenAI(api_key=settings.openai_api_key)

# Maps Anthropic model name → OpenAI fallback model name.
# Populated from settings so a config change is all that's needed to swap models.
_FALLBACK_MODELS: dict[str, str] = {
    settings.orchestrator_model: settings.orchestrator_fallback_model,
}
if settings.worker_model != settings.orchestrator_model:
    _FALLBACK_MODELS[settings.worker_model] = settings.worker_fallback_model
if settings.graph_repair_model not in _FALLBACK_MODELS:
    _FALLBACK_MODELS[settings.graph_repair_model] = settings.orchestrator_fallback_model

_anthropic_stream_semaphore: asyncio.Semaphore | None = None
_anthropic_stream_limit: int | None = None

_NON_RETRYABLE_ANTHROPIC_ERRORS = {
    "AuthenticationError",
    "BadRequestError",
    "NotFoundError",
    "PermissionDeniedError",
    "UnprocessableEntityError",
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


def _get_anthropic_stream_semaphore() -> asyncio.Semaphore | None:
    global _anthropic_stream_limit, _anthropic_stream_semaphore

    limit = max(0, int(settings.anthropic_max_concurrent_streams))
    if limit == 0:
        return None
    if _anthropic_stream_semaphore is None or _anthropic_stream_limit != limit:
        _anthropic_stream_semaphore = asyncio.Semaphore(limit)
        _anthropic_stream_limit = limit
    return _anthropic_stream_semaphore


def _is_non_retryable_anthropic_error(exc: Exception) -> bool:
    if type(exc).__name__ in _NON_RETRYABLE_ANTHROPIC_ERRORS:
        return True
    return getattr(exc, "status_code", None) in {400, 401, 403, 404, 422}


def stream_response_compat(streamer, **kwargs):
    optional = {
        "telemetry": kwargs.pop("telemetry", None),
        "effort": kwargs.pop("effort", None),
    }
    try:
        params = inspect.signature(streamer).parameters.values()
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params)
        accepted_names = {param.name for param in params}
    except (TypeError, ValueError):
        accepts_kwargs = True
        accepted_names = set()
    for name, value in optional.items():
        if value is not None and (accepts_kwargs or name in accepted_names):
            kwargs[name] = value
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
    if openai_client is None:
        raise RuntimeError("OpenAI client not initialised (OPENAI_API_KEY not set)")

    # OpenAI takes the system prompt as the first message in the list. Convert
    # Anthropic image blocks when a browser-rendered diagram is being judged.
    openai_messages = [{"role": "system", "content": system}, *_to_openai_messages(messages)]

    kwargs: dict = {
        "model":    model,
        "messages": openai_messages,
        "stream":   True,
        "stream_options": {"include_usage": True},
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
        usage = getattr(chunk, "usage", None)
        if usage:
            yield (
                "usage",
                json.dumps(
                    {
                        "input_tokens": int(usage.prompt_tokens or 0),
                        "output_tokens": int(usage.completion_tokens or 0),
                    }
                ),
            )
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta.content:
                yield ("text", delta.content)

    yield ("done", "")


async def _anthropic_stream_once(kwargs: dict) -> AsyncGenerator[object, None]:
    semaphore = _get_anthropic_stream_semaphore()
    if semaphore is None:
        async with _get_anthropic_client().messages.stream(**kwargs) as stream:
            async for event in stream:
                yield event
        return

    async with semaphore:
        async with _get_anthropic_client().messages.stream(**kwargs) as stream:
            async for event in stream:
                yield event


async def stream_response(
    model: str,
    system: str,
    messages: list[dict],
    thinking_budget: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    effort: str | None = None,
    telemetry: dict | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """
    Stream a response with automatic retry + OpenAI fallback.

    Retry behaviour:
    - Tries Anthropic up to settings.llm_max_retries times with
      settings.llm_retry_delay_s seconds between attempts.
    - Only retries transient failures that occur before any tokens are yielded.
      Non-retryable request/auth/model 4xx errors fall back immediately.
      Mid-stream drops are re-raised since partial output can't be safely replayed.
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
    prompt_sha256 = hashlib.sha256(system.encode("utf-8")).hexdigest()
    kwargs: dict = {
        "model":      model,
        "max_tokens": settings.llm_max_tokens,
        "system":     system,
        "messages":   messages,
    }
    uses_adaptive_effort = _uses_adaptive_effort(model)
    effective_effort = effort or _effort_from_legacy_budget(thinking_budget)
    if uses_adaptive_effort:
        # Sonnet 5 rejects manual thinking budgets and non-default sampling.
        # Effort is the supported quality/cost control and adaptive thinking is
        # enabled by default for Sonnet 5.
        kwargs["output_config"] = {"effort": effective_effort or "medium"}
        if model.startswith("claude-opus-4-8"):
            kwargs["thinking"] = {"type": "adaptive"}
    else:
        if temperature is not None and thinking_budget is None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if top_k is not None and thinking_budget is None:
            kwargs["top_k"] = top_k
        if thinking_budget is not None:
            kwargs["thinking"] = {
                "type":          "enabled",
                "budget_tokens": max(thinking_budget, 1000),
            }

    last_exc: Exception | None = None
    started_at = time.perf_counter()
    output_chars = 0
    input_tokens = 0
    output_tokens = 0
    provider_attempts = 0
    used_fallback = False
    final_provider = "anthropic"
    final_model = model

    def _record(status: str, *, error_type: str | None = None) -> None:
        from analytics.events import enqueue_analytics_event
        from observability import current_trace_context, record_llm_metrics
        from storage.telemetry_store import record_llm_telemetry

        details = telemetry or {}
        raw_metadata = details.get("metadata")
        details_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        trace_context = current_trace_context()
        duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
        metadata = {
            "message_count": len(messages),
            "thinking_budget": thinking_budget,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "effort": effective_effort,
            "prompt_sha256": prompt_sha256,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "provider_attempts": provider_attempts,
            "request_id": details_metadata.get("request_id"),
            "client_request_id": details_metadata.get("client_request_id"),
            "trace_id": trace_context.get("trace_id"),
            "span_id": trace_context.get("span_id"),
            **details_metadata,
        }
        try:
            record_llm_telemetry(
                operation=details.get("operation", "unknown"),
                provider=final_provider,
                model=final_model,
                status=status,
                duration_ms=duration_ms,
                output_chars=output_chars,
                used_fallback=used_fallback,
                user_id=details.get("user_id"),
                thread_id=details.get("thread_id"),
                error_type=error_type,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("LLM telemetry write failed: %s", type(exc).__name__)
        enqueue_analytics_event(
            event_name="llm_call_completed",
            event_category="llm",
            user_id=details.get("user_id"),
            thread_id=details.get("thread_id"),
            session_id=details.get("thread_id"),
            request_id=metadata.get("request_id"),
            trace_id=metadata.get("trace_id"),
            client_request_id=metadata.get("client_request_id"),
            numeric_value=duration_ms,
            unit="ms",
            properties={
                "operation": details.get("operation", "unknown"),
                "provider": final_provider,
                "model": final_model,
                "status": status,
                "duration_ms": duration_ms,
                "output_chars": output_chars,
                "used_fallback": used_fallback,
                "error_type": error_type,
                "message_count": len(messages),
                "prompt_sha256": prompt_sha256,
            },
        )
        record_llm_metrics(
            operation=details.get("operation", "unknown"),
            provider=final_provider,
            model=final_model,
            duration_ms=duration_ms,
            used_fallback=used_fallback,
            status=status,
        )

    for attempt in range(1, settings.llm_max_retries + 1):
        tokens_yielded = False
        provider_attempts += 1
        try:
            async for event in _anthropic_stream_once(kwargs):
                if event.type == "message_start":
                    usage = getattr(getattr(event, "message", None), "usage", None)
                    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                elif event.type == "message_delta":
                    usage = getattr(event, "usage", None)
                    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
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
            logger.warning(
                "[llm] Anthropic attempt %s/%s failed: %s",
                attempt,
                settings.llm_max_retries,
                type(exc).__name__,
            )
            if _is_non_retryable_anthropic_error(exc):
                break
            if attempt < settings.llm_max_retries:
                await asyncio.sleep(settings.llm_retry_delay_s)

    # All Anthropic attempts exhausted — try OpenAI fallback
    fallback_model = _FALLBACK_MODELS.get(model)
    if fallback_model and _get_openai_client():
        logger.warning("Falling back to OpenAI model %s", fallback_model)
        used_fallback = True
        final_provider = "openai"
        final_model = fallback_model
        provider_attempts += 1
        yield ("provider_switch", "openai")
        reasoning_effort = effective_effort
        if reasoning_effort is None and thinking_budget is not None:
            reasoning_effort = (
                "high"
                if thinking_budget >= settings.production_thinking_budget_tokens
                else "medium"
            )
        if reasoning_effort is None and model == settings.orchestrator_model:
            reasoning_effort = settings.orchestrator_fallback_reasoning_effort
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
                elif event[0] == "usage":
                    usage = json.loads(event[1])
                    input_tokens = int(usage.get("input_tokens") or 0)
                    output_tokens = int(usage.get("output_tokens") or 0)
                    continue
                yield event
            _record("success")
        except Exception as exc:
            _record("error", error_type=type(exc).__name__)
            raise
    else:
        if last_exc is not None:
            _record("error", error_type=type(last_exc).__name__)
        raise last_exc  # type: ignore[misc]


def _uses_adaptive_effort(model: str) -> bool:
    return model.startswith((
        "claude-sonnet-5",
        "claude-opus-4-8",
    ))


def _effort_from_legacy_budget(thinking_budget: int | None) -> str | None:
    if thinking_budget is None:
        return None
    if thinking_budget >= settings.production_thinking_budget_tokens:
        return "high"
    if thinking_budget >= settings.thinking_budget_tokens:
        return "high"
    return "medium"


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    converted = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            converted.append(message)
            continue
        blocks = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                blocks.append({"type": "text", "text": str(block.get("text") or "")})
                continue
            if block.get("type") == "image":
                source = block.get("source") or {}
                if source.get("type") != "base64":
                    continue
                media_type = str(source.get("media_type") or "image/jpeg")
                data = str(source.get("data") or "")
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                })
        converted.append({**message, "content": blocks})
    return converted
