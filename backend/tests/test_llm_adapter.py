import pytest
import sys
import hashlib
from types import SimpleNamespace

from config import Settings, settings


@pytest.fixture(autouse=True)
def clear_cached_clients():
    import adapters.llm_adapter as llm

    _clear_client_caches(llm)
    yield
    _clear_client_caches(llm)


def _clear_client_caches(llm):
    for client_factory in (llm._get_anthropic_client, llm._get_openai_client):
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


def test_lazy_clients_and_semaphore_branches(monkeypatch):
    import adapters.llm_adapter as llm

    class _AnthropicModule:
        class AsyncAnthropic:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    class _OpenAIModule:
        class AsyncOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    llm._get_anthropic_client.cache_clear()
    llm._get_openai_client.cache_clear()
    monkeypatch.setitem(sys.modules, "anthropic", _AnthropicModule)
    monkeypatch.setitem(sys.modules, "openai", _OpenAIModule)
    monkeypatch.setattr(settings, "anthropic_api_key", "anthropic-key")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_max_concurrent_streams", 0)

    assert llm._get_anthropic_client().kwargs == {"api_key": "anthropic-key"}
    assert llm._get_openai_client() is None
    assert llm._get_anthropic_stream_semaphore() is None

    llm._get_openai_client.cache_clear()
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "anthropic_max_concurrent_streams", 3)

    assert llm._get_openai_client().kwargs == {"api_key": "openai-key"}
    first = llm._get_anthropic_stream_semaphore()
    second = llm._get_anthropic_stream_semaphore()
    assert first is second


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


def test_opus_5_is_an_adaptive_effort_model():
    from adapters.llm_adapter import _uses_adaptive_effort

    assert _uses_adaptive_effort("claude-opus-5") is True


def test_application_model_roles_default_to_opus_5():
    configured = Settings(_env_file=None)

    assert configured.orchestrator_model == "claude-opus-5"
    assert configured.worker_model == "claude-opus-5"
    assert configured.graph_repair_model == "claude-opus-5"


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
            message=SimpleNamespace(usage=SimpleNamespace(input_tokens=100 * attempts)),
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
    assert metadata["output_tokens"] == 25
    assert metadata["queue_wait_ms"] == 30
    assert [attempt["status"] for attempt in metadata["attempts"]] == [
        "error_incomplete_usage",
        "success",
    ]
    assert metadata["attempts"][0]["accepted"] is True
    assert metadata["attempts"][0]["usage_complete"] is False


@pytest.mark.asyncio
async def test_stream_response_does_not_retry_non_retryable_anthropic_4xx(monkeypatch):
    import adapters.llm_adapter as llm

    monkeypatch.setattr(settings, "llm_max_retries", 3)
    monkeypatch.setattr(llm, "_FALLBACK_MODELS", {"anthropic-model": "openai-model"})
    monkeypatch.setattr(llm, "_get_openai_client", lambda: object())
    _patch_llm_telemetry(monkeypatch)
    attempts = 0

    class BadRequestError(Exception):
        status_code = 400

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
        )
    )

    assert events == [("provider_switch", "openai"), ("text", "fallback"), ("done", "")]
    assert openai_calls == [("openai-model", "system", [{"role": "user", "content": "hi"}], None, 0.4, 0.9)]
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
