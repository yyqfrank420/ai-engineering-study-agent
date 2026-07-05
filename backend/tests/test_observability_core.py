import importlib

from config import settings


def test_observability_endpoint_helpers(monkeypatch):
    import observability

    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    assert observability._trace_endpoint() == ""
    assert observability._metric_endpoint() == ""

    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "https://otel.example")
    assert observability._trace_endpoint() == "https://otel.example/v1/traces"
    assert observability._metric_endpoint() == "https://otel.example/v1/metrics"

    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "https://otel.example/v1/traces")
    assert observability._trace_endpoint() == "https://otel.example/v1/traces"


def test_observability_normalises_attributes():
    import observability

    assert observability._normalise_attributes(
        {
            "none": None,
            "bool": True,
            "int": 1,
            "float": 1.2,
            "str": "ok",
            "list": ["x"],
        }
    ) == {
        "bool": True,
        "int": 1,
        "float": 1.2,
        "str": "ok",
        "list": "['x']",
    }


def test_configure_observability_disabled(monkeypatch):
    import observability

    monkeypatch.setattr(settings, "otel_enabled", False)
    monkeypatch.setattr(observability, "_CONFIGURED", False)
    monkeypatch.setattr(observability, "_ENABLED", True)

    observability.configure_observability()

    assert observability.is_enabled() is False


def test_fallback_span_records_snapshot_and_trace_context(monkeypatch):
    import observability

    observability.reset_observability_test_state()
    monkeypatch.setattr(observability, "_ENABLED", True)
    monkeypatch.setattr(observability, "trace", None)

    with observability.start_span("outer", attributes={"a": ["list"]}) as span:
        span.set_attribute("b", {"dict": True})
        context = observability.current_trace_context()
        assert context["trace_id"]
        assert context["span_id"]
        with observability.start_span("inner", attributes={"c": 1}):
            inner_context = observability.current_trace_context()
            assert inner_context["trace_id"] == context["trace_id"]
            assert inner_context["span_id"] != context["span_id"]

    spans = observability.get_recorded_spans()
    assert [span["name"] for span in spans] == ["inner", "outer"]
    assert spans[-1]["attributes"] == {"a": "['list']", "b": "{'dict': True}"}


def test_disabled_span_is_noop(monkeypatch):
    import observability

    monkeypatch.setattr(observability, "_ENABLED", False)

    with observability.start_span("noop") as span:
        assert span is None
    assert observability.current_trace_context() == {}


def test_metric_snapshot_records_all_local_metrics(monkeypatch):
    import observability

    observability.reset_observability_test_state()
    monkeypatch.setattr(observability, "_ENABLED", False)

    observability.record_request_metrics(route="/api/chat", method="POST", status_code=200, latency_ms=123)
    observability.change_active_chat_streams(2)
    observability.record_agent_duration(456, route="/api/chat")
    observability.record_llm_metrics(
        operation="synthesis",
        provider="anthropic",
        model="claude",
        duration_ms=789,
        used_fallback=True,
        status="success",
    )
    observability.record_timeout()
    observability.record_cancel()

    snapshot = observability.get_metrics_snapshot()
    assert snapshot["request_count"] == 1
    assert snapshot["active_chat_streams"] == 2
    assert snapshot["fallback_count"] == 1
    assert snapshot["timeout_count"] == 1
    assert snapshot["cancel_count"] == 1
    assert snapshot["request_latency_ms"] == [123]
    assert snapshot["agent_duration_ms"] == [456]
    assert snapshot["llm_duration_ms"] == [789]

    snapshot["request_latency_ms"].append(999)
    assert observability.get_metrics_snapshot()["request_latency_ms"] == [123]


def test_enabled_metric_instruments_are_called(monkeypatch):
    import observability

    calls = []

    class _Instrument:
        def __init__(self, name):
            self.name = name

        def add(self, value, attrs=None):
            calls.append((self.name, "add", value, attrs))

        def record(self, value, attrs=None):
            calls.append((self.name, "record", value, attrs))

    monkeypatch.setattr(observability, "_ENABLED", True)
    monkeypatch.setattr(observability, "_REQUEST_COUNTER", _Instrument("request_counter"))
    monkeypatch.setattr(observability, "_REQUEST_LATENCY", _Instrument("request_latency"))
    monkeypatch.setattr(observability, "_ACTIVE_CHAT_STREAMS", _Instrument("active"))
    monkeypatch.setattr(observability, "_AGENT_DURATION", _Instrument("agent"))
    monkeypatch.setattr(observability, "_LLM_DURATION", _Instrument("llm"))
    monkeypatch.setattr(observability, "_FALLBACK_COUNTER", _Instrument("fallback"))
    monkeypatch.setattr(observability, "_TIMEOUT_COUNTER", _Instrument("timeout"))
    monkeypatch.setattr(observability, "_CANCEL_COUNTER", _Instrument("cancel"))

    observability.record_request_metrics(route="/x", method="GET", status_code=204, latency_ms=7)
    observability.change_active_chat_streams(1)
    observability.record_agent_duration(8, route="/x")
    observability.record_llm_metrics(
        operation="op",
        provider="anthropic",
        model="m",
        duration_ms=9,
        used_fallback=True,
        status="success",
    )
    observability.record_timeout()
    observability.record_cancel()

    assert ("request_counter", "add", 1, {"http.route": "/x", "http.request.method": "GET", "http.response.status_code": 204}) in calls
    assert ("request_latency", "record", 7, {"http.route": "/x", "http.request.method": "GET", "http.response.status_code": 204}) in calls
    assert ("active", "add", 1, None) in calls
    assert ("agent", "record", 8, {"app.route": "/x"}) in calls
    assert any(call[0] == "llm" and call[1] == "record" for call in calls)
    assert any(call[0] == "fallback" and call[1] == "add" for call in calls)
    assert ("timeout", "add", 1, None) in calls
    assert ("cancel", "add", 1, None) in calls


def test_configure_observability_builds_exporters_and_instruments(monkeypatch):
    import observability

    calls = []

    class _Provider:
        def __init__(self, **kwargs):
            calls.append(("provider", kwargs))

        def add_span_processor(self, processor):
            calls.append(("span_processor", processor))

    class _Processor:
        def __init__(self, exporter):
            calls.append((self.__class__.__name__, exporter))

    class _Exporter:
        def __init__(self, **kwargs):
            calls.append((self.__class__.__name__, kwargs))

    class _Meter:
        def create_counter(self, name):
            calls.append(("counter", name))
            return name

        def create_histogram(self, name):
            calls.append(("histogram", name))
            return name

        def create_up_down_counter(self, name):
            calls.append(("updown", name))
            return name

    class _Trace:
        def set_tracer_provider(self, provider):
            calls.append(("set_tracer_provider", provider))

    class _Metrics:
        def set_meter_provider(self, provider):
            calls.append(("set_meter_provider", provider))

        def get_meter(self, name):
            calls.append(("get_meter", name))
            return _Meter()

    monkeypatch.setattr(settings, "otel_enabled", True)
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "https://otel.example")
    monkeypatch.setattr(settings, "otel_exporter_otlp_headers_raw", "Authorization=Bearer token")
    monkeypatch.setattr(observability, "_CONFIGURED", False)
    monkeypatch.setattr(observability, "_OTEL_IMPORT_OK", True)
    monkeypatch.setattr(observability, "TracerProvider", _Provider)
    monkeypatch.setattr(observability, "MeterProvider", _Provider)
    monkeypatch.setattr(observability, "SimpleSpanProcessor", _Processor)
    monkeypatch.setattr(observability, "BatchSpanProcessor", _Processor)
    monkeypatch.setattr(observability, "PeriodicExportingMetricReader", _Processor)
    monkeypatch.setattr(observability, "OTLPSpanExporter", _Exporter)
    monkeypatch.setattr(observability, "OTLPMetricExporter", _Exporter)
    monkeypatch.setattr(observability, "trace", _Trace())
    monkeypatch.setattr(observability, "metrics", _Metrics())
    monkeypatch.setattr(observability, "_resource", lambda: {"resource": "test"})

    observability.configure_observability()
    observability.configure_observability()

    assert observability._CONFIGURED is True
    assert any(call[0] == "_Exporter" and call[1]["endpoint"].endswith("/v1/traces") for call in calls)
    assert any(call[0] == "_Exporter" and call[1]["endpoint"].endswith("/v1/metrics") for call in calls)
    assert ("counter", "http.server.request.count") in calls


def test_recording_span_exporter_records_spans(monkeypatch):
    import observability

    observability.reset_observability_test_state()

    class _Span:
        name = "exported"
        attributes = {"x": 1}

    exporter = observability._RecordingSpanExporter()
    result = exporter.export([_Span()])

    assert observability.get_recorded_spans() == [{"name": "exported", "attributes": {"x": 1}}]
    if observability.SpanExportResult is not None:
        assert result == observability.SpanExportResult.SUCCESS


def test_configure_observability_when_otel_imports_unavailable(monkeypatch):
    import observability

    monkeypatch.setattr(settings, "otel_enabled", True)
    monkeypatch.setattr(observability, "_OTEL_IMPORT_OK", False)
    monkeypatch.setattr(observability, "_CONFIGURED", False)

    observability.configure_observability()

    assert observability.is_enabled() is True
    assert observability._CONFIGURED is True


def test_resource_uses_service_settings(monkeypatch):
    import observability

    calls = []

    class _Resource:
        @staticmethod
        def create(payload):
            calls.append(payload)
            return {"resource": payload}

    monkeypatch.setattr(observability, "Resource", _Resource)
    monkeypatch.setattr(settings, "otel_service_name", "svc")
    monkeypatch.setattr(settings, "otel_service_version", "1")
    monkeypatch.setattr(settings, "otel_environment", "test")

    assert observability._resource() == {"resource": calls[0]}
    assert calls[0] == {
        "service.name": "svc",
        "service.version": "1",
        "deployment.environment": "test",
    }
