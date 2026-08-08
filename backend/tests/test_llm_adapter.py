import pytest
import sys
import hashlib
import asyncio
import json
from types import SimpleNamespace

from config import Settings, settings


@pytest.fixture(autouse=True)
def clear_cached_clients():
    import adapters.llm_adapter as llm

    _clear_client_caches(llm)
    yield
    _clear_client_caches(llm)


def _clear_client_caches(llm):
    for client_factory in (
        llm._get_anthropic_client,
        llm._get_openai_client,
        llm._get_kimi_client,
        llm.get_posthog_client,
    ):
        clear = getattr(client_factory, "cache_clear", None)
        if clear:
            clear()


class _Delta:
    def __init__(self, type_: str, *, text: str = "", thinking: str = ""):
        self.type = type_
        self.text = text
        self.thinking = thinking


class _Event:
    def __init__(self, type_: str, delta: _Delta):
        self.type = type_
        self.delta = delta


async def _collect(async_iterable):
    return [event async for event in async_iterable]


def test_build_telemetry_includes_optional_fields():
    from adapters.llm_adapter import build_telemetry

    assert build_telemetry("route") == {"operation": "route"}
    assert build_telemetry(
        "synth",
        user_id="user-1",
        thread_id="thread-1",
        metadata={"request_id": "req-1"},
    ) == {
        "operation": "synth",
        "user_id": "user-1",
        "thread_id": "thread-1",
        "metadata": {"request_id": "req-1"},
    }


def test_get_posthog_client_logs_loudly_but_does_not_break_llm_calls_locally(
    monkeypatch, caplog
):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "posthog_api_key", "")
    monkeypatch.setattr(settings, "k_service", "")

    with caplog.at_level("ERROR", logger="adapters.llm_adapter"):
        client = llm.get_posthog_client()

    assert client is None
    assert "POSTHOG_API_KEY" in caplog.text


def test_get_posthog_client_is_a_silent_noop_in_cloud_run_when_unconfigured(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "posthog_api_key", "")
    monkeypatch.setattr(settings, "k_service", "agent-backend")

    assert llm.get_posthog_client() is None


def test_get_posthog_client_constructs_when_configured(monkeypatch):
    import adapters.llm_adapter as llm

    class _PosthogModule:
        class Posthog:
            def __init__(self, api_key, host=None):
                self.api_key = api_key
                self.host = host
                self.shutdown_called = False

            def shutdown(self):
                self.shutdown_called = True

    monkeypatch.setitem(sys.modules, "posthog", _PosthogModule)
    monkeypatch.setattr(settings, "posthog_api_key", "phc_test-key")
    monkeypatch.setattr(settings, "posthog_host", "https://eu.i.posthog.com")

    client = llm.get_posthog_client()
    assert client.api_key == "phc_test-key"
    assert client.host == "https://eu.i.posthog.com"


def test_lazy_clients_and_semaphore_branches(monkeypatch):
    import adapters.llm_adapter as llm

    class _PosthogAnthropicModule:
        class AsyncAnthropic:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    class _PosthogOpenAIModule:
        class AsyncOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    llm._get_anthropic_client.cache_clear()
    llm._get_openai_client.cache_clear()
    llm._get_kimi_client.cache_clear()
    monkeypatch.setitem(sys.modules, "posthog.ai.anthropic", _PosthogAnthropicModule)
    monkeypatch.setitem(sys.modules, "posthog.ai.openai", _PosthogOpenAIModule)
    monkeypatch.setattr(llm, "get_posthog_client", lambda: None)
    monkeypatch.setattr(settings, "anthropic_api_key", "anthropic-key")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_max_concurrent_streams", 0)

    assert llm._get_anthropic_client().kwargs == {
        "api_key": "anthropic-key",
        "max_retries": 0,
        "posthog_client": None,
    }
    assert llm._get_openai_client() is None
    assert llm._get_anthropic_stream_semaphore() is None

    llm._get_openai_client.cache_clear()
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "anthropic_max_concurrent_streams", 3)

    assert llm._get_openai_client().kwargs == {
        "api_key": "openai-key",
        "max_retries": 0,
        "posthog_client": None,
    }
    first = llm._get_anthropic_stream_semaphore()
    second = llm._get_anthropic_stream_semaphore()
    assert first is second


def test_kimi_client_uses_the_moonshot_openai_compatible_endpoint(monkeypatch):
    import adapters.llm_adapter as llm

    calls = []

    class _PosthogOpenAIModule:
        class AsyncOpenAI:
            def __init__(self, **kwargs):
                calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "posthog.ai.openai", _PosthogOpenAIModule)
    monkeypatch.setattr(llm, "get_posthog_client", lambda: None)
    monkeypatch.setattr(settings, "moonshot_api_key", "moonshot-key")
    monkeypatch.setattr(settings, "moonshot_base_url", "https://api.moonshot.ai/v1")

    assert llm._get_kimi_client() is not None
    assert calls == [{
        "api_key": "moonshot-key",
        "base_url": "https://api.moonshot.ai/v1",
        "max_retries": 0,
        "posthog_client": None,
    }]


def test_stream_response_compat_only_passes_telemetry_when_supported():
    from adapters.llm_adapter import stream_response_compat

    def no_telemetry(model):
        return {"model": model}

    def explicit(model, telemetry=None):
        return {"model": model, "telemetry": telemetry}

    assert stream_response_compat(no_telemetry, telemetry={"x": 1}, model="m") == {
        "model": "m",
    }
    assert stream_response_compat(explicit, telemetry={"x": 1}, model="m") == {
        "model": "m",
        "telemetry": {"x": 1},
    }


def _patch_llm_telemetry(monkeypatch):
    telemetry_records = []
    metric_records = []
    monkeypatch.setattr(
        "storage.telemetry_store.record_llm_telemetry",
        lambda **kwargs: telemetry_records.append(kwargs),
    )
    monkeypatch.setattr(
        "observability.record_llm_metrics",
        lambda **kwargs: metric_records.append(kwargs),
    )
    monkeypatch.setattr(
        "observability.current_trace_context",
        lambda: {"trace_id": "trace-1", "span_id": "span-1"},
    )
    return telemetry_records, metric_records


@pytest.mark.asyncio
async def test_stream_response_success_records_thinking_text_and_done(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    telemetry_records, metric_records = _patch_llm_telemetry(monkeypatch)

    async def fake_anthropic_stream_once(kwargs):
        assert kwargs["output_config"] == {"effort": "high"}
        assert "temperature" not in kwargs
        yield _Event("content_block_delta", _Delta("thinking_delta", thinking="plan"))
        yield _Event("content_block_delta", _Delta("text_delta", text="answer"))

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    events = await _collect(
        llm.stream_response(
            model=settings.worker_model,
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            telemetry={"operation": "test", "user_id": "user-1", "metadata": {"request_id": "req-1"}},
        )
    )

    assert events == [("thinking", "plan"), ("text", "answer"), ("done", "")]
    assert telemetry_records[0]["status"] == "success"
    assert telemetry_records[0]["output_chars"] == len("answer")
    assert telemetry_records[0]["metadata"]["trace_id"] == "trace-1"
    assert telemetry_records[0]["metadata"]["prompt_sha256"] == hashlib.sha256(
        b"system"
    ).hexdigest()
    assert telemetry_records[0]["metadata"]["input_tokens"] == 0
    assert telemetry_records[0]["metadata"]["output_tokens"] == 0
    assert telemetry_records[0]["metadata"]["provider_attempts"] == 1
    assert metric_records[0]["status"] == "success"


@pytest.mark.asyncio
async def test_stream_response_records_outer_deadline_cancellation(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    telemetry_records, metric_records = _patch_llm_telemetry(monkeypatch)

    async def delayed_anthropic_stream(_kwargs):
        await asyncio.Event().wait()
        if False:
            yield None

    monkeypatch.setattr(llm, "_anthropic_stream_once", delayed_anthropic_stream)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await _collect(
                llm.stream_response(
                    model=settings.architecture_model,
                    system="system",
                    messages=[{"role": "user", "content": "design"}],
                    effort="xhigh",
                    telemetry={"operation": "architecture_architect"},
                    allow_fallback=False,
                )
            )

    assert telemetry_records[0]["status"] == "error"
    assert telemetry_records[0]["error_type"] == "CancelledError"
    assert telemetry_records[0]["metadata"]["provider_attempts"] == 1
    assert telemetry_records[0]["metadata"]["attempts"][0]["status"] == "cancelled"
    assert metric_records[0]["status"] == "error"


def test_opus_5_is_an_adaptive_effort_model():
    from adapters.llm_adapter import _uses_adaptive_effort

    assert _uses_adaptive_effort("claude-opus-5") is True


def test_application_model_roles_default_to_calibrated_models():
    import adapters.llm_adapter as llm

    configured = Settings(_env_file=None)

    assert configured.orchestrator_model == "claude-opus-5"
    assert configured.worker_model == "claude-opus-5"
    assert configured.architecture_model == "claude-opus-5"
    assert configured.graph_builder_model == "kimi-k3"
    assert configured.graph_qa_model == "claude-sonnet-5"
    assert configured.graph_builder_model not in llm._FALLBACK_MODELS
    assert configured.graph_qa_model not in llm._FALLBACK_MODELS
    assert configured.anthropic_max_concurrent_streams == 4


@pytest.mark.asyncio
async def test_stream_response_ignores_non_mapping_telemetry_metadata(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    telemetry_records, _ = _patch_llm_telemetry(monkeypatch)

    async def fake_anthropic_stream_once(_kwargs):
        yield _Event("content_block_delta", _Delta("text_delta", text="answer"))

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    events = await _collect(
        llm.stream_response(
            model=settings.worker_model,
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            telemetry={"operation": "test", "metadata": None},
        )
    )

    assert events == [("text", "answer"), ("done", "")]
    assert telemetry_records[0]["metadata"]["request_id"] is None


@pytest.mark.asyncio
async def test_anthropic_stream_once_without_semaphore(monkeypatch):
    import adapters.llm_adapter as llm

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if getattr(self, "_done", False):
                raise StopAsyncIteration
            self._done = True
            return _Event("content_block_delta", _Delta("text_delta", text="ok"))

    class _Messages:
        def stream(self, **kwargs):
            return _Stream()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(llm, "_get_anthropic_stream_semaphore", lambda: None)
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: _Client())

    events = await _collect(llm._anthropic_stream_once({"model": "m"}))

    assert events[0].delta.text == "ok"


@pytest.mark.asyncio
async def test_stream_response_retries_before_tokens_then_succeeds(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_delay_s", 0)
    _patch_llm_telemetry(monkeypatch)
    attempts = 0

    async def fake_anthropic_stream_once(_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("connect failed")
        yield _Event("content_block_delta", _Delta("text_delta", text="ok"))

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    assert await _collect(llm.stream_response("model", "system", [])) == [("text", "ok"), ("done", "")]
    assert attempts == 2


@pytest.mark.asyncio
async def test_stream_response_accounts_usage_for_every_anthropic_attempt(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_delay_s", 0)
    telemetry_records, _ = _patch_llm_telemetry(monkeypatch)
    attempts = 0

    async def fake_anthropic_stream_once(kwargs):
        nonlocal attempts
        attempts += 1
        kwargs["_queue_wait_observer"](attempts * 10)
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=100 * attempts,
                    cache_creation_input_tokens=1_000 if attempts == 1 else 0,
                    cache_read_input_tokens=2_000 if attempts == 2 else 0,
                )
            ),
        )
        if attempts == 1:
            raise RuntimeError("retry after accepted request")
        yield SimpleNamespace(
            type="message_delta",
            usage=SimpleNamespace(output_tokens=25),
        )
        yield _Event("content_block_delta", _Delta("text_delta", text="ok"))

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    assert await _collect(llm.stream_response("claude-opus-5", "system", [])) == [
        ("text", "ok"),
        ("done", ""),
    ]
    metadata = telemetry_records[0]["metadata"]
    assert metadata["input_tokens"] == 300
    assert metadata["cache_creation_input_tokens"] == 1_000
    assert metadata["cache_read_input_tokens"] == 2_000
    assert metadata["output_tokens"] == 25
    assert metadata["queue_wait_ms"] == 30
    assert [attempt["status"] for attempt in metadata["attempts"]] == [
        "error_incomplete_usage",
        "success",
    ]
    assert metadata["attempts"][0]["accepted"] is True
    assert metadata["attempts"][0]["usage_complete"] is False


@pytest.mark.asyncio
async def test_stream_response_does_not_retry_non_retryable_anthropic_4xx(
    monkeypatch,
    caplog,
):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 3)
    monkeypatch.setattr(llm, "_FALLBACK_MODELS", {"anthropic-model": "openai-model"})
    monkeypatch.setattr(llm, "_get_openai_client", lambda: object())
    _patch_llm_telemetry(monkeypatch)
    attempts = 0

    class BadRequestError(Exception):
        status_code = 400
        request_id = "req_schema"
        body = {
            "error": {
                "type": "invalid_request_error",
                "message": "The compiled grammar is too large.\nSimplify the schema."
            }
        }

    async def failing_anthropic(_kwargs):
        nonlocal attempts
        attempts += 1
        if False:
            yield
        raise BadRequestError("invalid model configuration")

    async def fake_openai_stream(*_args):
        yield ("text", "fallback")
        yield ("done", "")

    monkeypatch.setattr(llm, "_anthropic_stream_once", failing_anthropic)
    monkeypatch.setattr(llm, "_openai_stream", fake_openai_stream)

    events = await _collect(llm.stream_response("anthropic-model", "system", []))

    assert attempts == 1
    assert events == [
        ("provider_switch", "openai"),
        ("text", "fallback"),
        ("done", ""),
    ]
    assert "status=400 request_id=req_schema" in caplog.text
    assert "provider_error=invalid_request_error" in caplog.text
    assert "diagnostic=schema_compilation_too_large" in caplog.text
    assert "Simplify the schema" not in caplog.text


@pytest.mark.asyncio
async def test_stream_response_continues_when_telemetry_write_fails(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(
        "storage.telemetry_store.record_llm_telemetry",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("telemetry down")),
    )
    monkeypatch.setattr("observability.record_llm_metrics", lambda **_kwargs: None)
    monkeypatch.setattr("observability.current_trace_context", lambda: {})

    async def fake_anthropic_stream_once(_kwargs):
        yield _Event("content_block_delta", _Delta("text_delta", text="ok"))

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    assert await _collect(llm.stream_response("model", "system", [])) == [("text", "ok"), ("done", "")]


@pytest.mark.asyncio
async def test_stream_response_midstream_error_is_not_replayed(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 3)
    _patch_llm_telemetry(monkeypatch)

    async def fake_anthropic_stream_once(_kwargs):
        yield _Event("content_block_delta", _Delta("text_delta", text="partial"))
        raise RuntimeError("drop")

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    with pytest.raises(RuntimeError, match="drop"):
        await _collect(llm.stream_response("model", "system", []))


@pytest.mark.asyncio
async def test_stream_response_falls_back_to_openai_after_anthropic_exhaustion(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "llm_max_tokens", 400)
    monkeypatch.setattr(llm, "_FALLBACK_MODELS", {"anthropic-model": "openai-model"})
    monkeypatch.setattr(llm, "_get_openai_client", lambda: object())
    telemetry_records, _metric_records = _patch_llm_telemetry(monkeypatch)
    openai_calls = []

    async def failing_anthropic(_kwargs):
        if False:
            yield
        raise RuntimeError("anthropic down")

    async def fake_openai_stream(*args):
        openai_calls.append(args)
        yield ("text", "fallback")
        yield ("done", "")

    monkeypatch.setattr(llm, "_anthropic_stream_once", failing_anthropic)
    monkeypatch.setattr(llm, "_openai_stream", fake_openai_stream)

    events = await _collect(
        llm.stream_response(
            "anthropic-model",
            "system",
            [{"role": "user", "content": "hi"}],
            temperature=0.4,
            top_p=0.9,
            max_output_tokens=321,
        )
    )

    assert events == [("provider_switch", "openai"), ("text", "fallback"), ("done", "")]
    assert openai_calls == [("openai-model", "system", [{"role": "user", "content": "hi"}], None, 0.4, 0.9, 321)]
    assert telemetry_records[-1]["provider"] == "openai"
    assert telemetry_records[-1]["used_fallback"] is True


@pytest.mark.asyncio
async def test_stream_response_accounts_fallback_usage_separately(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(llm, "_FALLBACK_MODELS", {"claude-opus-5": "gpt-5.4"})
    monkeypatch.setattr(llm, "_get_openai_client", lambda: object())
    telemetry_records, _ = _patch_llm_telemetry(monkeypatch)

    async def failing_anthropic(kwargs):
        kwargs["_queue_wait_observer"](7)
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(usage=SimpleNamespace(input_tokens=120)),
        )
        raise RuntimeError("anthropic down after accepting request")

    async def fake_openai_stream(*_args):
        yield (
            "usage",
            '{"input_tokens": 80, "output_tokens": 20}',
        )
        yield ("text", "fallback")
        yield ("done", "")

    monkeypatch.setattr(llm, "_anthropic_stream_once", failing_anthropic)
    monkeypatch.setattr(llm, "_openai_stream", fake_openai_stream)

    await _collect(llm.stream_response("claude-opus-5", "system", []))

    metadata = telemetry_records[0]["metadata"]
    assert metadata["input_tokens"] == 200
    assert metadata["output_tokens"] == 20
    assert metadata["provider_attempts"] == 2
    assert metadata["attempts"][0]["model"] == "claude-opus-5"
    assert metadata["attempts"][0]["input_tokens"] == 120
    assert metadata["attempts"][1]["model"] == "gpt-5.4"
    assert metadata["attempts"][1]["input_tokens"] == 80


@pytest.mark.asyncio
async def test_stream_response_raises_last_exception_when_no_fallback(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(llm, "_FALLBACK_MODELS", {})
    _patch_llm_telemetry(monkeypatch)

    async def failing_anthropic(_kwargs):
        if False:
            yield
        raise RuntimeError("no fallback")

    monkeypatch.setattr(llm, "_anthropic_stream_once", failing_anthropic)

    with pytest.raises(RuntimeError, match="no fallback"):
        await _collect(llm.stream_response("unknown-model", "system", []))


@pytest.mark.asyncio
async def test_openai_stream_builds_reasoning_or_sampling_kwargs(monkeypatch):
    import adapters.llm_adapter as llm

    calls = []

    class _ChoiceDelta:
        content = "token"

    class _Choice:
        delta = _ChoiceDelta()

    class _Chunk:
        choices = [_Choice()]

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)

            async def stream():
                yield _Chunk()

            return stream()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(llm, "_get_openai_client", lambda: _Client())

    assert await _collect(llm._openai_stream("gpt", "system", [], reasoning_effort="medium")) == [
        ("text", "token"),
        ("done", ""),
    ]
    assert calls[0]["reasoning_effort"] == "medium"

    await _collect(llm._openai_stream("gpt", "system", [], temperature=0.3, top_p=0.8))
    assert calls[1]["temperature"] == 0.3
    assert calls[1]["top_p"] == 0.8


@pytest.mark.asyncio
async def test_kimi_routes_directly_with_max_reasoning_and_strict_schema(monkeypatch):
    import adapters.llm_adapter as llm

    calls = []
    telemetry_records, _ = _patch_llm_telemetry(monkeypatch)

    class _Stream:
        def __init__(self):
            self.chunks = iter([
                SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            reasoning_content="reasoning",
                            content=None,
                        ),
                    )],
                ),
                SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(
                            reasoning_content=None,
                            content='{"ok":true}',
                        ),
                    )],
                ),
                SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            reasoning_content=None,
                            content=None,
                        ),
                        usage={
                            "prompt_tokens": 120,
                            "cached_tokens": 80,
                            "completion_tokens": 9,
                        },
                    )],
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return _Stream()

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions()),
    )
    monkeypatch.setattr(llm, "_get_kimi_client", lambda: client)
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    events = await _collect(llm.stream_response(
        "kimi-k3",
        "system",
        [{"role": "user", "content": "build"}],
        effort="max",
        temperature=0.1,
        top_p=0.8,
        max_output_tokens=500,
        response_schema=schema,
        allow_fallback=False,
        telemetry={"operation": "graph_worker", "thread_id": "thread-1"},
    ))

    assert calls[0]["reasoning_effort"] == "max"
    assert calls[0]["max_completion_tokens"] == 500
    assert "temperature" not in calls[0]
    assert "top_p" not in calls[0]
    assert calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "structured_response",
            "strict": True,
            "schema": schema,
        },
    }
    assert events[:2] == [
        ("thinking", "reasoning"),
        ("text", '{"ok":true}'),
    ]
    assert json.loads(events[2][1]) == {
        "finish_reason": "end_turn",
        "input_tokens": 40,
        "output_tokens": 9,
        "provider": "kimi",
        "model": "kimi-k3",
    }
    assert events[3] == ("done", "")
    assert telemetry_records[0]["provider"] == "kimi"
    assert telemetry_records[0]["metadata"]["input_tokens"] == 40
    assert telemetry_records[0]["metadata"]["cache_read_input_tokens"] == 80


@pytest.mark.asyncio
async def test_kimi_rejects_unsupported_reasoning_effort(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(llm, "_get_kimi_client", lambda: object())
    with pytest.raises(ValueError, match="low, high, or max"):
        await _collect(llm._kimi_stream(
            "kimi-k3",
            "system",
            [],
            reasoning_effort="medium",
        ))


@pytest.mark.asyncio
async def test_kimi_retries_only_before_any_provider_output(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_delay_s", 0)
    telemetry_records, _ = _patch_llm_telemetry(monkeypatch)
    calls = []

    async def fake_kimi(*args, **_kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("transient failure")
        yield "text", "graph"
        yield "usage", json.dumps({
            "input_tokens": 10,
            "cache_read_input_tokens": 0,
            "output_tokens": 4,
        })
        yield "done", ""

    monkeypatch.setattr(llm, "_kimi_stream", fake_kimi)

    events = await _collect(llm.stream_response(
        "kimi-k3",
        "system",
        [],
        thinking_budget=1000,
        telemetry={"operation": "graph_worker"},
    ))

    assert events == [("text", "graph"), ("done", "")]
    assert len(calls) == 2
    assert all(call[3] == "max" for call in calls)
    attempts = telemetry_records[0]["metadata"]["attempts"]
    assert [attempt["status"] for attempt in attempts] == ["error", "success"]


@pytest.mark.asyncio
async def test_kimi_does_not_replay_after_a_reasoning_delta(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 2)
    telemetry_records, _ = _patch_llm_telemetry(monkeypatch)
    calls = 0

    async def failing_kimi(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        yield "thinking", "partial reasoning"
        raise RuntimeError("stream dropped")

    monkeypatch.setattr(llm, "_kimi_stream", failing_kimi)

    with pytest.raises(RuntimeError, match="stream dropped"):
        await _collect(llm.stream_response(
            "kimi-k3",
            "system",
            [],
            effort="max",
            telemetry={"operation": "graph_worker"},
        ))

    assert calls == 1
    attempt = telemetry_records[0]["metadata"]["attempts"][0]
    assert attempt["status"] == "error_incomplete_usage"
    assert attempt["accepted"] is True


@pytest.mark.asyncio
async def test_stream_response_records_openai_fallback_error(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(llm, "_FALLBACK_MODELS", {"anthropic-model": "openai-model"})
    monkeypatch.setattr(llm, "_get_openai_client", lambda: object())
    telemetry_records, _metric_records = _patch_llm_telemetry(monkeypatch)

    async def failing_anthropic(_kwargs):
        if False:
            yield
        raise RuntimeError("anthropic down")

    async def failing_openai(*_args):
        if False:
            yield
        raise RuntimeError("openai down")

    monkeypatch.setattr(llm, "_anthropic_stream_once", failing_anthropic)
    monkeypatch.setattr(llm, "_openai_stream", failing_openai)

    with pytest.raises(RuntimeError, match="openai down"):
        await _collect(llm.stream_response("anthropic-model", "system", []))

    assert telemetry_records[-1]["provider"] == "openai"
    assert telemetry_records[-1]["status"] == "error"


def test_stream_response_compat_filters_max_output_tokens():
    from adapters.llm_adapter import stream_response_compat

    def legacy(model):
        return {"model": model}

    def current(model, max_output_tokens=None):
        return {"model": model, "max_output_tokens": max_output_tokens}

    assert stream_response_compat(
        legacy, model="claude", max_output_tokens=123
    ) == {"model": "claude"}
    assert stream_response_compat(
        current, model="claude", max_output_tokens=123
    ) == {"model": "claude", "max_output_tokens": 123}


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_enabled", [False, True])
async def test_anthropic_structured_output_merges_schema_effort_and_metadata(
    monkeypatch,
    cache_enabled,
):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "anthropic_prompt_cache_enabled", cache_enabled)
    _patch_llm_telemetry(monkeypatch)
    calls = []

    async def fake_anthropic_stream_once(kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(usage=SimpleNamespace(input_tokens=12)),
        )
        yield _Event("content_block_delta", _Delta("text_delta", text='{"ok":true}'))
        yield SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="end_turn"),
            usage=SimpleNamespace(output_tokens=5),
        )

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "items": {"type": "array", "minItems": 1, "maxItems": 2},
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "name": {"type": "string", "minLength": 1, "maxLength": 20},
        },
    }

    events = await _collect(llm.stream_response(
        "claude-sonnet-5",
        "system",
        [],
        effort="low",
        response_schema=schema,
        allow_fallback=False,
    ))

    output_config = calls[0]["output_config"]
    expected_system = {"type": "text", "text": "system"}
    if cache_enabled:
        expected_system["cache_control"] = {"type": "ephemeral"}
    assert calls[0]["system"] == [expected_system]
    assert output_config["effort"] == "low"
    assert output_config["format"]["type"] == "json_schema"
    assert "minItems" not in json.dumps(output_config["format"]["schema"])
    assert "maxItems" not in json.dumps(output_config["format"]["schema"])
    assert "minimum" not in json.dumps(output_config["format"]["schema"])
    assert "maximum" not in json.dumps(output_config["format"]["schema"])
    assert "minLength" not in json.dumps(output_config["format"]["schema"])
    assert "maxLength" not in json.dumps(output_config["format"]["schema"])
    assert events[0] == ("text", '{"ok":true}')
    metadata = json.loads(events[1][1])
    assert metadata == {
        "finish_reason": "end_turn",
        "input_tokens": 12,
        "output_tokens": 5,
        "provider": "anthropic",
        "model": "claude-sonnet-5",
    }
    assert events[2] == ("done", "")


def test_anthropic_schema_transform_preserves_property_names():
    from adapters.llm_adapter import _anthropic_response_schema

    schema = {
        "type": "object",
        "required": ["minimum"],
        "properties": {
            "minimum": {"type": "integer", "minimum": 1},
            "nested": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 2},
            },
        },
    }

    transformed = _anthropic_response_schema(schema)

    assert transformed["required"] == ["minimum"]
    assert transformed["properties"]["minimum"] == {"type": "integer"}
    assert transformed["properties"]["nested"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_evaluation_provider_attempt_reservation_uses_shared_atomic_store(monkeypatch):
    import adapters.llm_adapter as llm
    import storage.rate_limit_store as rate_limit_store

    captured = []
    monkeypatch.setattr(settings, "evaluation_run_id", "run-123-attempt-1")
    monkeypatch.setattr(settings, "evaluation_provider_attempt_limit", 64)
    monkeypatch.setattr(
        rate_limit_store,
        "reserve_rate_limit",
        lambda dimensions: captured.append(dimensions) or ("reservation",),
    )

    llm._reserve_evaluation_provider_attempt()

    assert len(captured) == 1
    assert captured[0][0].identifier == "run-123-attempt-1"
    assert captured[0][0].event_type == "llm_provider_attempt"
    assert captured[0][0].limit == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["kimi-k3", "claude-opus-5"])
async def test_evaluation_quota_blocks_before_any_provider_request(monkeypatch, model):
    import adapters.llm_adapter as llm

    provider_started = False

    async def provider_must_not_start(*_args, **_kwargs):
        nonlocal provider_started
        provider_started = True
        if False:
            yield

    def reject_attempt():
        raise llm.EvaluationProviderAttemptLimitExceeded("budget exhausted")

    monkeypatch.setattr(llm, "_reserve_evaluation_provider_attempt", reject_attempt)
    monkeypatch.setattr(llm, "_kimi_stream", provider_must_not_start)
    monkeypatch.setattr(llm, "_anthropic_stream_once", provider_must_not_start)

    with pytest.raises(llm.EvaluationProviderAttemptLimitExceeded):
        await _collect(llm.stream_response(model, "system", []))

    assert provider_started is False


@pytest.mark.asyncio
async def test_anthropic_output_cap_is_positive_and_clamped(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "llm_max_tokens", 100)
    _patch_llm_telemetry(monkeypatch)
    calls = []

    async def fake_anthropic_stream_once(kwargs):
        calls.append(kwargs)
        if False:
            yield

    monkeypatch.setattr(llm, "_anthropic_stream_once", fake_anthropic_stream_once)

    assert await _collect(
        llm.stream_response(
            "claude-test", "system", [], max_output_tokens=250
        )
    ) == [("done", "")]
    assert calls[0]["max_tokens"] == 100

    with pytest.raises(ValueError, match="max_output_tokens must be positive"):
        await _collect(
            llm.stream_response(
                "claude-test", "system", [], max_output_tokens=0
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-5.4", "o3"])
async def test_explicit_openai_model_routes_directly_with_clamped_cap(
    monkeypatch, model
):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_tokens", 100)
    _patch_llm_telemetry(monkeypatch)
    calls = []
    anthropic_calls = 0

    class _ChoiceDelta:
        content = "direct"

    class _Choice:
        delta = _ChoiceDelta()

    class _Chunk:
        usage = None
        choices = [_Choice()]

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)

            async def stream():
                yield _Chunk()

            return stream()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    async def forbidden_anthropic(_kwargs):
        nonlocal anthropic_calls
        anthropic_calls += 1
        if False:
            yield

    monkeypatch.setattr(llm, "_get_openai_client", lambda: _Client())
    monkeypatch.setattr(llm, "_anthropic_stream_once", forbidden_anthropic)

    events = await _collect(
        llm.stream_response(model, "system", [], max_output_tokens=250)
    )

    assert events == [("text", "direct"), ("done", "")]
    assert anthropic_calls == 0
    assert calls[0]["model"] == model
    assert calls[0]["max_completion_tokens"] == 100
    assert "max_tokens" not in calls[0]


@pytest.mark.asyncio
async def test_stream_llm_timeout_closes_complete_provider_chain(monkeypatch):
    import agent.stream_utils as stream_utils

    closed = False

    async def blocked_provider_chain(**_kwargs):
        nonlocal closed
        try:
            yield ("text", "partial")
            await asyncio.Event().wait()
        finally:
            closed = True

    monkeypatch.setattr(stream_utils, "stream_response", blocked_provider_chain)

    with pytest.raises(TimeoutError):
        await stream_utils.stream_llm(
            model="claude-test",
            system="system",
            messages=[],
            temperature=0.0,
            timeout_seconds=0.01,
        )
    assert closed is True


@pytest.mark.asyncio
async def test_stream_llm_external_cancellation_stays_cancelled(monkeypatch):
    import agent.stream_utils as stream_utils

    started = asyncio.Event()
    closed = False

    async def blocked_provider_chain(**_kwargs):
        nonlocal closed
        try:
            started.set()
            await asyncio.Event().wait()
            yield ("done", "")
        finally:
            closed = True

    monkeypatch.setattr(stream_utils, "stream_response", blocked_provider_chain)
    task = asyncio.create_task(
        stream_utils.stream_llm(
            model="claude-test",
            system="system",
            messages=[],
            temperature=0.0,
            timeout_seconds=60,
        )
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed is True


@pytest.mark.asyncio
async def test_stream_llm_translates_provider_events_without_network_calls(monkeypatch):
    import agent.stream_utils as stream_utils

    observed = {}

    async def fake_stream_response(**kwargs):
        observed.update(kwargs)
        yield "provider_switch", "openai"
        yield "thinking", "checking evidence"
        yield "text", "Grounded "
        yield "text", "answer"

    sent = []

    async def send(event):
        sent.append(event)

    monkeypatch.setattr(stream_utils, "stream_response", fake_stream_response)

    result = await stream_utils.stream_llm(
        model="test-model",
        system="system boundary",
        messages=[{"role": "user", "content": "question"}],
        temperature=0,
        send=send,
        stream_deltas=True,
        stream_thinking=True,
        max_output_tokens=500,
    )

    assert result == "Grounded answer"
    assert sent == [
        {"type": "provider_switch", "provider": "openai"},
        {"type": "thinking_delta", "content": "checking evidence"},
        {"type": "response_delta", "content": "Grounded "},
        {"type": "response_delta", "content": "answer"},
    ]
    assert observed["model"] == "test-model"
    assert observed["max_output_tokens"] == 500
    assert "system boundary" in observed["system"]


@pytest.mark.asyncio
async def test_stream_structured_llm_collects_text_and_usage_metadata(monkeypatch):
    import agent.stream_utils as stream_utils

    async def fake_stream_response(**_kwargs):
        yield "text", '{"answer":'
        yield "response_metadata", "[]"
        yield "response_metadata", json.dumps({
            "finish_reason": "end_turn",
            "input_tokens": 42,
            "output_tokens": 17,
            "provider": "anthropic",
            "model": "claude-test",
        })
        yield "text", '"ok"}'

    monkeypatch.setattr(stream_utils, "stream_response", fake_stream_response)

    response = await stream_utils.stream_structured_llm(
        model="configured-model",
        system="structured boundary",
        messages=[{"role": "user", "content": "question"}],
        response_schema={"type": "object"},
        temperature=0,
        effort="low",
    )

    assert response.text == '{"answer":"ok"}'
    assert response.finish_reason == "end_turn"
    assert response.input_tokens == 42
    assert response.output_tokens == 17
    assert response.provider == "anthropic"
    assert response.model == "claude-test"


@pytest.mark.asyncio
async def test_stream_helpers_reject_non_positive_timeouts():
    import agent.stream_utils as stream_utils

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        await stream_utils.stream_llm(
            model="test-model",
            system="system",
            messages=[],
            temperature=0,
            timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        await stream_utils.stream_structured_llm(
            model="test-model",
            system="system",
            messages=[],
            response_schema={"type": "object"},
            temperature=0,
            effort="low",
            timeout_seconds=-1,
        )
@pytest.mark.asyncio
async def test_openai_stream_closes_sdk_stream_after_consumption(monkeypatch):
    import adapters.llm_adapter as llm

    class _Chunk:
        usage = None
        choices = []

    class _Stream:
        def __init__(self):
            self.sent = False
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return _Chunk()

        async def aclose(self):
            self.closed = True

    sdk_stream = _Stream()

    class _Completions:
        async def create(self, **_kwargs):
            return sdk_stream

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(llm, "_get_openai_client", lambda: _Client())

    assert await _collect(llm._openai_stream("gpt", "system", [])) == [
        ("done", "")
    ]
    assert sdk_stream.closed is True
