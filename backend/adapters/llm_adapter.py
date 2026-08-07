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

    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        max_retries=0,
    )


@lru_cache(maxsize=1)
def _get_openai_client():
    if not settings.openai_api_key:
        return None
    import openai

    return openai.AsyncOpenAI(
        api_key=settings.openai_api_key,
        max_retries=0,
    )


@lru_cache(maxsize=1)
def _get_kimi_client():
    if not settings.moonshot_api_key:
        return None
    import openai

    return openai.AsyncOpenAI(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
        max_retries=0,
    )

# Maps Anthropic model name → OpenAI fallback model name.
# Populated from settings so a config change is all that's needed to swap models.
_FALLBACK_MODELS: dict[str, str] = {
    settings.orchestrator_model: settings.orchestrator_fallback_model,
}
if settings.worker_model != settings.orchestrator_model:
    _FALLBACK_MODELS[settings.worker_model] = settings.worker_fallback_model

_anthropic_stream_semaphore: asyncio.Semaphore | None = None
_anthropic_stream_limit: int | None = None

_NON_RETRYABLE_ANTHROPIC_ERRORS = {
    "AuthenticationError",
    "BadRequestError",
    "NotFoundError",
    "PermissionDeniedError",
    "UnprocessableEntityError",
}


def _field(value: object, name: str, default=0):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _aggregate_attempt_token_usage(
    attempts: list[dict[str, object]],
) -> tuple[int, int, int, int]:
    fields = (
        "input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
    )
    return tuple(
        sum(int(attempt.get(field) or 0) for attempt in attempts)
        for field in fields
    )


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


def _is_non_retryable_chat_error(exc: Exception) -> bool:
    if isinstance(exc, (TypeError, ValueError)):
        return True
    if isinstance(exc, RuntimeError) and "not initialised" in str(exc):
        return True
    return getattr(exc, "status_code", None) in {400, 401, 403, 404, 422}


def stream_response_compat(streamer, **kwargs):
    optional = {
        "telemetry": kwargs.pop("telemetry", None),
        "effort": kwargs.pop("effort", None),
        "max_output_tokens": kwargs.pop("max_output_tokens", None),
        "response_schema": kwargs.pop("response_schema", None),
        "allow_fallback": kwargs.pop("allow_fallback", None),
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


async def _chat_completions_stream(
    client,
    provider: str,
    model: str,
    system: str,
    messages: list[dict],
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
    response_schema: dict | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """Stream one OpenAI-compatible Chat Completions response."""
    completion_messages = [
        {"role": "system", "content": system},
        *_to_openai_messages(messages),
    ]

    kwargs: dict = {
        "model": model,
        "messages": completion_messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning_effort:
        if provider == "kimi" and reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("Kimi reasoning_effort must be low, high, or max")
        kwargs["reasoning_effort"] = reasoning_effort
    elif provider != "kimi":
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
    if max_output_tokens is not None:
        kwargs["max_completion_tokens"] = max_output_tokens
    if response_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "strict": True,
                "schema": response_schema,
            },
        }

    stream = await client.chat.completions.create(**kwargs)
    finish_reason: str | None = None
    input_tokens = 0
    cache_read_input_tokens = 0
    output_tokens = 0
    try:
        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            usage = getattr(chunk, "usage", None)
            if provider == "kimi" and choice is not None:
                usage = _field(choice, "usage", None) or usage
            if usage:
                prompt_tokens = int(_field(usage, "prompt_tokens") or 0)
                prompt_details = _field(usage, "prompt_tokens_details", None)
                cached_tokens = int(
                    _field(usage, "cached_tokens")
                    or _field(prompt_details, "cached_tokens")
                    or 0
                )
                input_tokens = max(0, prompt_tokens - cached_tokens)
                cache_read_input_tokens = cached_tokens
                output_tokens = int(
                    _field(usage, "completion_tokens") or 0
                )
                yield (
                    "usage",
                    json.dumps(
                        {
                            "input_tokens": input_tokens,
                            "cache_read_input_tokens": cache_read_input_tokens,
                            "output_tokens": output_tokens,
                        }
                    ),
                )
            if choice is not None:
                if isinstance(getattr(choice, "finish_reason", None), str):
                    finish_reason = choice.finish_reason
                delta = getattr(choice, "delta", None)
                reasoning_content = getattr(delta, "reasoning_content", None)
                if isinstance(reasoning_content, str) and reasoning_content:
                    yield ("thinking", reasoning_content)
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    yield ("text", content)
    finally:
        try:
            close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
            if close is not None:
                close_result = close()
                if inspect.isawaitable(close_result):
                    await close_result
        except Exception as exc:
            logger.warning(
                "%s stream close failed: %s", provider, type(exc).__name__
            )

    if response_schema is not None:
        yield (
            "response_metadata",
            json.dumps({
                "finish_reason": _normalise_finish_reason(finish_reason),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "provider": provider,
                "model": model,
            }),
        )
    yield ("done", "")


async def _openai_stream(
    model: str,
    system: str,
    messages: list[dict],
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
    response_schema: dict | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    client = _get_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client not initialised (OPENAI_API_KEY not set)")
    async for event in _chat_completions_stream(
        client,
        "openai",
        model,
        system,
        messages,
        reasoning_effort,
        temperature,
        top_p,
        max_output_tokens,
        response_schema,
    ):
        yield event


async def _kimi_stream(
    model: str,
    system: str,
    messages: list[dict],
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
    response_schema: dict | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    client = _get_kimi_client()
    if client is None:
        raise RuntimeError("Kimi client not initialised (MOONSHOT_API_KEY not set)")
    async for event in _chat_completions_stream(
        client,
        "kimi",
        model,
        system,
        messages,
        reasoning_effort or "max",
        temperature,
        top_p,
        max_output_tokens,
        response_schema,
    ):
        yield event


async def _anthropic_stream_once(kwargs: dict) -> AsyncGenerator[object, None]:
    sdk_kwargs = dict(kwargs)
    queue_wait_observer = sdk_kwargs.pop("_queue_wait_observer", None)
    semaphore = _get_anthropic_stream_semaphore()
    if semaphore is None:
        if queue_wait_observer:
            queue_wait_observer(0)
        async with _get_anthropic_client().messages.stream(**sdk_kwargs) as stream:
            async for event in stream:
                yield event
        return

    queued_at = time.perf_counter()
    async with semaphore:
        if queue_wait_observer:
            queue_wait_observer(max(0, int((time.perf_counter() - queued_at) * 1000)))
        async with _get_anthropic_client().messages.stream(**sdk_kwargs) as stream:
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
    max_output_tokens: int | None = None,
    response_schema: dict | None = None,
    allow_fallback: bool = True,
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
    if max_output_tokens is not None and max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive")
    effective_max_output_tokens = min(
        (
            max_output_tokens
            if max_output_tokens is not None
            else settings.llm_default_max_tokens
        ),
        settings.llm_max_tokens,
    )
    prompt_sha256 = hashlib.sha256(system.encode("utf-8")).hexdigest()
    system_block: dict[str, object] = {
        "type": "text",
        "text": system,
    }
    if settings.anthropic_prompt_cache_enabled:
        # Protected evaluation repeats stable role prompts often enough to
        # recover Anthropic's cache-write premium within the cache lifetime.
        system_block["cache_control"] = {"type": "ephemeral"}
    kwargs: dict = {
        "model":      model,
        "max_tokens": effective_max_output_tokens,
        "system":     [system_block],
        "messages":   messages,
    }
    uses_adaptive_effort = _uses_adaptive_effort(model)
    effective_effort = effort or _effort_from_legacy_budget(thinking_budget)
    if uses_adaptive_effort:
        # Current adaptive-thinking Claude models reject manual thinking budgets
        # and non-default sampling. Effort is their quality/cost control.
        kwargs["output_config"] = {"effort": effective_effort or "high"}
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
    if response_schema is not None:
        output_config = dict(kwargs.get("output_config") or {})
        output_config["format"] = {
            "type": "json_schema",
            "schema": _anthropic_response_schema(response_schema),
        }
        kwargs["output_config"] = output_config

    last_exc: Exception | None = None
    started_at = time.perf_counter()
    output_chars = 0
    input_tokens = 0
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0
    output_tokens = 0
    provider_attempts = 0
    attempts: list[dict[str, object]] = []
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
            **details_metadata,
            "message_count": len(messages),
            "thinking_budget": thinking_budget,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "effort": effective_effort,
            "max_output_tokens": effective_max_output_tokens,
            "structured_output": response_schema is not None,
            "prompt_sha256": prompt_sha256,
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "output_tokens": output_tokens,
            "provider_attempts": provider_attempts,
            "queue_wait_ms": sum(
                int(attempt.get("queue_wait_ms") or 0) for attempt in attempts
            ),
            "attempts": [dict(attempt) for attempt in attempts],
            "request_id": details_metadata.get("request_id"),
            "client_request_id": details_metadata.get("client_request_id"),
            "trace_id": trace_context.get("trace_id"),
            "span_id": trace_context.get("span_id"),
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
                "provider_attempts": provider_attempts,
                "queue_wait_ms": metadata["queue_wait_ms"],
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

    async def _stream_chat_completions_route(
        chat_model: str,
        *,
        provider: str,
        is_fallback: bool,
    ) -> AsyncGenerator[tuple[str, str], None]:
        nonlocal final_model, final_provider, input_tokens, output_chars
        nonlocal cache_creation_input_tokens, cache_read_input_tokens
        nonlocal output_tokens, provider_attempts, used_fallback

        used_fallback = is_fallback
        final_provider = provider
        final_model = chat_model
        if is_fallback:
            yield ("provider_switch", provider)
        reasoning_effort = (
            "max" if provider == "kimi" and effort is None else effective_effort
        )
        if reasoning_effort is None and thinking_budget is not None:
            reasoning_effort = (
                "high"
                if thinking_budget >= settings.production_thinking_budget_tokens
                else "medium"
            )
        if reasoning_effort is None and model in {
            settings.orchestrator_model,
            settings.architecture_model,
        }:
            reasoning_effort = settings.orchestrator_fallback_reasoning_effort
        streamer = _kimi_stream if provider == "kimi" else _openai_stream
        attempt_limit = (
            settings.llm_max_retries
            if provider == "kimi" and not is_fallback
            else 1
        )
        for route_attempt in range(1, attempt_limit + 1):
            provider_attempts += 1
            attempt_started = time.perf_counter()
            attempt_usage: dict[str, object] = {
                "attempt": provider_attempts,
                "provider": provider,
                "model": chat_model,
                "status": "started",
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
                "queue_wait_ms": 0,
                "accepted": False,
                "usage_complete": False,
            }
            attempts.append(attempt_usage)
            try:
                stream_args = (
                    chat_model,
                    system,
                    messages,
                    reasoning_effort,
                    temperature,
                    top_p,
                    effective_max_output_tokens,
                )
                response = (
                    streamer(*stream_args, response_schema=response_schema)
                    if response_schema is not None
                    else streamer(*stream_args)
                )
                async for event in response:
                    if event[0] == "text":
                        attempt_usage["accepted"] = True
                        output_chars += len(event[1])
                    elif event[0] == "thinking":
                        attempt_usage["accepted"] = True
                    elif event[0] == "usage":
                        attempt_usage["accepted"] = True
                        attempt_usage["usage_complete"] = True
                        usage = json.loads(event[1])
                        attempt_usage["input_tokens"] = int(
                            usage.get("input_tokens") or 0
                        )
                        attempt_usage["cache_read_input_tokens"] = int(
                            usage.get("cache_read_input_tokens") or 0
                        )
                        attempt_usage["output_tokens"] = int(
                            usage.get("output_tokens") or 0
                        )
                        (
                            input_tokens,
                            cache_creation_input_tokens,
                            cache_read_input_tokens,
                            output_tokens,
                        ) = _aggregate_attempt_token_usage(attempts)
                        continue
                    yield event
                attempt_usage["status"] = (
                    "success_incomplete_usage"
                    if attempt_usage["accepted"]
                    and not attempt_usage["usage_complete"]
                    else "success"
                )
                attempt_usage["duration_ms"] = max(
                    1, int((time.perf_counter() - attempt_started) * 1000)
                )
                _record("success")
                return
            except Exception as exc:
                accepted = bool(attempt_usage["accepted"])
                attempt_usage["status"] = (
                    "error_incomplete_usage"
                    if accepted and not attempt_usage["usage_complete"]
                    else "error"
                )
                attempt_usage["error_type"] = type(exc).__name__
                attempt_usage["duration_ms"] = max(
                    1, int((time.perf_counter() - attempt_started) * 1000)
                )
                can_retry = (
                    not accepted
                    and not _is_non_retryable_chat_error(exc)
                    and route_attempt < attempt_limit
                )
                if can_retry:
                    await asyncio.sleep(settings.llm_retry_delay_s)
                    continue
                _record("error", error_type=type(exc).__name__)
                raise

    if _is_openai_model(model):
        async for event in _stream_chat_completions_route(
            model,
            provider="openai",
            is_fallback=False,
        ):
            yield event
        return

    if _is_kimi_model(model):
        async for event in _stream_chat_completions_route(
            model,
            provider="kimi",
            is_fallback=False,
        ):
            yield event
        return

    for attempt in range(1, settings.llm_max_retries + 1):
        tokens_yielded = False
        finish_reason: str | None = None
        provider_attempts += 1
        attempt_started = time.perf_counter()
        attempt_usage: dict[str, object] = {
            "attempt": provider_attempts,
            "provider": "anthropic",
            "model": model,
            "status": "started",
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 0,
            "queue_wait_ms": 0,
            "accepted": False,
            "usage_complete": False,
        }
        attempts.append(attempt_usage)

        def observe_queue_wait(queue_wait_ms: int) -> None:
            attempt_usage["queue_wait_ms"] = queue_wait_ms

        try:
            async for event in _anthropic_stream_once(
                {**kwargs, "_queue_wait_observer": observe_queue_wait}
            ):
                if event.type == "message_start":
                    attempt_usage["accepted"] = True
                    usage = getattr(getattr(event, "message", None), "usage", None)
                    attempt_usage["input_tokens"] = int(
                        getattr(usage, "input_tokens", 0) or 0
                    )
                    attempt_usage["cache_creation_input_tokens"] = int(
                        getattr(usage, "cache_creation_input_tokens", 0) or 0
                    )
                    attempt_usage["cache_read_input_tokens"] = int(
                        getattr(usage, "cache_read_input_tokens", 0) or 0
                    )
                    (
                        input_tokens,
                        cache_creation_input_tokens,
                        cache_read_input_tokens,
                        output_tokens,
                    ) = _aggregate_attempt_token_usage(attempts)
                elif event.type == "message_delta":
                    attempt_usage["accepted"] = True
                    attempt_usage["usage_complete"] = True
                    usage = getattr(event, "usage", None)
                    attempt_usage["output_tokens"] = int(
                        getattr(usage, "output_tokens", 0) or 0
                    )
                    (
                        input_tokens,
                        cache_creation_input_tokens,
                        cache_read_input_tokens,
                        output_tokens,
                    ) = _aggregate_attempt_token_usage(attempts)
                    stop_reason = getattr(getattr(event, "delta", None), "stop_reason", None)
                    if isinstance(stop_reason, str):
                        finish_reason = stop_reason
                if event.type == "content_block_delta":
                    attempt_usage["accepted"] = True
                    tokens_yielded = True
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        yield ("thinking", delta.thinking)
                    elif delta.type == "text_delta":
                        output_chars += len(delta.text)
                        yield ("text", delta.text)
            attempt_usage["status"] = (
                "success_incomplete_usage"
                if attempt_usage["accepted"]
                and not attempt_usage["usage_complete"]
                else "success"
            )
            attempt_usage["duration_ms"] = max(
                1, int((time.perf_counter() - attempt_started) * 1000)
            )
            _record("success")
            if response_schema is not None:
                yield (
                    "response_metadata",
                    json.dumps({
                        "finish_reason": finish_reason,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "provider": "anthropic",
                        "model": model,
                    }),
                )
            yield ("done", "")
            return   # Anthropic succeeded

        except Exception as exc:
            last_exc = exc
            attempt_usage["status"] = (
                "error_incomplete_usage"
                if attempt_usage["accepted"]
                and not attempt_usage["usage_complete"]
                else "error"
            )
            attempt_usage["error_type"] = type(exc).__name__
            attempt_usage["duration_ms"] = max(
                1, int((time.perf_counter() - attempt_started) * 1000)
            )
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
    if allow_fallback and fallback_model and _get_openai_client():
        logger.warning("Falling back to OpenAI model %s", fallback_model)
        async for event in _stream_chat_completions_route(
            fallback_model,
            provider="openai",
            is_fallback=True,
        ):
            yield event
        return
    else:
        if last_exc is not None:
            _record("error", error_type=type(last_exc).__name__)
        raise last_exc  # type: ignore[misc]


def _anthropic_response_schema(value):
    if isinstance(value, dict):
        return {
            key: _anthropic_response_schema(child)
            for key, child in value.items()
            if key not in {"minItems", "maxItems"}
        }
    if isinstance(value, list):
        return [_anthropic_response_schema(child) for child in value]
    return value


def _uses_adaptive_effort(model: str) -> bool:
    return model.startswith((
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-opus-5",
    ))


def _is_openai_model(model: str) -> bool:
    return model.startswith("gpt-") or model.startswith("o")


def _is_kimi_model(model: str) -> bool:
    return model.startswith("kimi-")


def _normalise_finish_reason(finish_reason: str | None) -> str | None:
    return {
        "stop": "end_turn",
        "length": "max_tokens",
    }.get(finish_reason, finish_reason)


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
