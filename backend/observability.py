from __future__ import annotations

import contextvars
from contextlib import contextmanager
from threading import Lock
from typing import Any
import uuid

try:
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        SimpleSpanProcessor,
        SpanExporter,
        SpanExportResult,
    )
    from opentelemetry.trace import SpanKind

    _OTEL_IMPORT_OK = True
except Exception:
    metrics = None
    trace = None
    OTLPMetricExporter = None
    OTLPSpanExporter = None
    MeterProvider = None
    PeriodicExportingMetricReader = None
    Resource = None
    ReadableSpan = Any
    TracerProvider = None
    BatchSpanProcessor = None
    SimpleSpanProcessor = None
    SpanExporter = object
    SpanExportResult = None

    class SpanKind:
        INTERNAL = "internal"
        SERVER = "server"

    _OTEL_IMPORT_OK = False

from config import settings

_LOCK = Lock()
_CONFIGURED = False
_ENABLED = False

_RECORDED_SPANS: list[dict[str, Any]] = []
_MAX_RECORDED_SPANS = 1000
_FALLBACK_TRACE_CONTEXT: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "fallback_trace_context",
    default=None,
)
_METRIC_SNAPSHOT: dict[str, Any] = {
    "request_count": 0,
    "fallback_count": 0,
    "timeout_count": 0,
    "cancel_count": 0,
    "active_chat_streams": 0,
    "request_latency_ms": [],
    "agent_duration_ms": [],
    "llm_duration_ms": [],
}

_REQUEST_COUNTER = None
_REQUEST_LATENCY = None
_ACTIVE_CHAT_STREAMS = None
_AGENT_DURATION = None
_LLM_DURATION = None
_FALLBACK_COUNTER = None
_TIMEOUT_COUNTER = None
_CANCEL_COUNTER = None


def _record_span_snapshot(name: str, attributes: dict[str, Any]) -> None:
    _RECORDED_SPANS.append({"name": name, "attributes": attributes})
    if len(_RECORDED_SPANS) > _MAX_RECORDED_SPANS:
        del _RECORDED_SPANS[: len(_RECORDED_SPANS) - _MAX_RECORDED_SPANS]


class _RecordingSpanExporter(SpanExporter):
    def export(self, spans: list[ReadableSpan]):  # type: ignore[override]
        for span in spans:
            _record_span_snapshot(span.name, dict(span.attributes))
        return SpanExportResult.SUCCESS if SpanExportResult is not None else None


def _resource():
    assert Resource is not None
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.otel_service_version,
            "deployment.environment": settings.otel_environment,
        }
    )


def _trace_endpoint() -> str:
    base = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def _metric_endpoint() -> str:
    base = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1/metrics") else f"{base}/v1/metrics"


def _normalise_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    if not attributes:
        return cleaned
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def configure_observability() -> None:
    global _CONFIGURED, _ENABLED
    global _REQUEST_COUNTER, _REQUEST_LATENCY, _ACTIVE_CHAT_STREAMS
    global _AGENT_DURATION, _LLM_DURATION, _FALLBACK_COUNTER, _TIMEOUT_COUNTER, _CANCEL_COUNTER

    _ENABLED = settings.otel_enabled
    if not _ENABLED:
        return
    if not _OTEL_IMPORT_OK:
        _CONFIGURED = True
        return

    with _LOCK:
        if _CONFIGURED:
            return

        tracer_provider = TracerProvider(resource=_resource())
        tracer_provider.add_span_processor(SimpleSpanProcessor(_RecordingSpanExporter()))

        trace_endpoint = _trace_endpoint()
        if trace_endpoint:
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=trace_endpoint,
                        headers=settings.otel_exporter_otlp_headers,
                    )
                )
            )

        trace.set_tracer_provider(tracer_provider)

        metric_readers = []
        metric_endpoint = _metric_endpoint()
        if metric_endpoint:
            metric_readers.append(
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(
                        endpoint=metric_endpoint,
                        headers=settings.otel_exporter_otlp_headers,
                    )
                )
            )

        metrics.set_meter_provider(MeterProvider(resource=_resource(), metric_readers=metric_readers))
        meter = metrics.get_meter(settings.otel_service_name)
        _REQUEST_COUNTER = meter.create_counter("http.server.request.count")
        _REQUEST_LATENCY = meter.create_histogram("http.server.request.duration.ms")
        _ACTIVE_CHAT_STREAMS = meter.create_up_down_counter("app.chat.active_streams")
        _AGENT_DURATION = meter.create_histogram("app.agent.duration.ms")
        _LLM_DURATION = meter.create_histogram("app.llm.duration.ms")
        _FALLBACK_COUNTER = meter.create_counter("app.llm.fallback.count")
        _TIMEOUT_COUNTER = meter.create_counter("app.agent.timeout.count")
        _CANCEL_COUNTER = meter.create_counter("app.agent.cancel.count")

        _CONFIGURED = True


def is_enabled() -> bool:
    return _ENABLED


def get_metrics_snapshot() -> dict[str, Any]:
    return {
        **_METRIC_SNAPSHOT,
        "request_latency_ms": list(_METRIC_SNAPSHOT["request_latency_ms"]),
        "agent_duration_ms": list(_METRIC_SNAPSHOT["agent_duration_ms"]),
        "llm_duration_ms": list(_METRIC_SNAPSHOT["llm_duration_ms"]),
    }


def reset_observability_test_state() -> None:
    _RECORDED_SPANS.clear()
    _METRIC_SNAPSHOT["request_count"] = 0
    _METRIC_SNAPSHOT["fallback_count"] = 0
    _METRIC_SNAPSHOT["timeout_count"] = 0
    _METRIC_SNAPSHOT["cancel_count"] = 0
    _METRIC_SNAPSHOT["active_chat_streams"] = 0
    _METRIC_SNAPSHOT["request_latency_ms"].clear()
    _METRIC_SNAPSHOT["agent_duration_ms"].clear()
    _METRIC_SNAPSHOT["llm_duration_ms"].clear()


def get_recorded_spans() -> list[dict[str, Any]]:
    return list(_RECORDED_SPANS)


def current_trace_context() -> dict[str, str]:
    if not _ENABLED:
        return {}
    if trace is None:
        return _FALLBACK_TRACE_CONTEXT.get() or {}
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context or not span_context.is_valid:
        return {}
    return {
        "trace_id": f"{span_context.trace_id:032x}",
        "span_id": f"{span_context.span_id:016x}",
    }


@contextmanager
def start_span(name: str, *, attributes: dict[str, Any] | None = None, kind: SpanKind = SpanKind.INTERNAL):
    if not _ENABLED:
        yield None
        return
    if trace is None:
        cleaned = _normalise_attributes(attributes)
        existing = _FALLBACK_TRACE_CONTEXT.get()
        trace_id = existing["trace_id"] if existing else uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        token = _FALLBACK_TRACE_CONTEXT.set({"trace_id": trace_id, "span_id": span_id})

        class FallbackSpan:
            def set_attribute(self, key: str, value: Any) -> None:
                cleaned.update(_normalise_attributes({key: value}))

        try:
            yield FallbackSpan()
        finally:
            _record_span_snapshot(name, dict(cleaned))
            _FALLBACK_TRACE_CONTEXT.reset(token)
        return
    tracer = trace.get_tracer(settings.otel_service_name)
    with tracer.start_as_current_span(
        name,
        kind=kind,
        attributes=_normalise_attributes(attributes),
    ) as span:
        yield span


def record_request_metrics(*, route: str, method: str, status_code: int, latency_ms: int) -> None:
    attrs = _normalise_attributes(
        {
            "http.route": route,
            "http.request.method": method,
            "http.response.status_code": status_code,
        }
    )
    _METRIC_SNAPSHOT["request_count"] += 1
    _METRIC_SNAPSHOT["request_latency_ms"].append(latency_ms)
    if _ENABLED and _REQUEST_COUNTER and _REQUEST_LATENCY:
        _REQUEST_COUNTER.add(1, attrs)
        _REQUEST_LATENCY.record(latency_ms, attrs)


def change_active_chat_streams(delta: int) -> None:
    _METRIC_SNAPSHOT["active_chat_streams"] += delta
    if _ENABLED and _ACTIVE_CHAT_STREAMS:
        _ACTIVE_CHAT_STREAMS.add(delta)


def record_agent_duration(duration_ms: int, *, route: str) -> None:
    _METRIC_SNAPSHOT["agent_duration_ms"].append(duration_ms)
    if _ENABLED and _AGENT_DURATION:
        _AGENT_DURATION.record(duration_ms, _normalise_attributes({"app.route": route}))


def record_llm_metrics(
    *,
    operation: str,
    provider: str,
    model: str,
    duration_ms: int,
    used_fallback: bool,
    status: str,
) -> None:
    attrs = _normalise_attributes(
        {
            "app.llm.operation": operation,
            "app.llm.provider": provider,
            "app.llm.model": model,
            "app.llm.status": status,
        }
    )
    _METRIC_SNAPSHOT["llm_duration_ms"].append(duration_ms)
    if _ENABLED and _LLM_DURATION:
        _LLM_DURATION.record(duration_ms, attrs)
    if used_fallback:
        _METRIC_SNAPSHOT["fallback_count"] += 1
        if _ENABLED and _FALLBACK_COUNTER:
            _FALLBACK_COUNTER.add(1, attrs)


def record_timeout() -> None:
    _METRIC_SNAPSHOT["timeout_count"] += 1
    if _ENABLED and _TIMEOUT_COUNTER:
        _TIMEOUT_COUNTER.add(1)


def record_cancel() -> None:
    _METRIC_SNAPSHOT["cancel_count"] += 1
    if _ENABLED and _CANCEL_COUNTER:
        _CANCEL_COUNTER.add(1)
