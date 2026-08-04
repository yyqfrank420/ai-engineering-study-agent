import pytest

import api.internal_dashboard_route as dashboard


def _event(event_type: str, *, actor: str = "anon-1", ts: float = 1000.0, properties=None):
    return {
        "event_type": event_type,
        "anonymous_id": actor,
        "user_id": None,
        "created_at_epoch": ts,
        "properties": properties or {},
    }


def _http(path: str, status: int, latency: int, *, ts: float = 1000.0, metadata=None):
    return {
        "path": path,
        "status_code": status,
        "latency_ms": latency,
        "created_at_epoch": ts,
        "metadata": metadata or {},
    }


def _llm(operation: str, provider: str, model: str, *, ts: float = 1000.0, fallback=False, status="success", duration=100, metadata=None):
    return {
        "operation": operation,
        "provider": provider,
        "model": model,
        "created_at_epoch": ts,
        "used_fallback": fallback,
        "status": status,
        "duration_ms": duration,
        "metadata": metadata or {},
    }


def _analytics(event_name: str, event_category: str, *, ts: float = 1000.0, value=None, properties=None, request_id="r1"):
    return {
        "event_name": event_name,
        "event_category": event_category,
        "user_id": "user-1",
        "anonymous_id": None,
        "session_id": "thread-1",
        "thread_id": "thread-1",
        "request_id": request_id,
        "trace_id": "trace-1",
        "client_request_id": None,
        "schema_version": 1,
        "app_version": "0.1.0",
        "environment": "test",
        "numeric_value": value,
        "unit": "ms" if value is not None else None,
        "properties": properties or {},
        "created_at_epoch": ts,
    }


@pytest.fixture
def dashboard_data(monkeypatch):
    now = 10_000.0
    events = [
        _event("auth_viewed", actor="anon-1", ts=now - 100),
        _event("otp_requested", actor="anon-1", ts=now - 90),
        _event("otp_verified", actor="user-1", ts=now - 80),
        _event("prepare_clicked", actor="user-1", ts=now - 70),
        _event("prepare_succeeded", actor="user-1", ts=now - 60),
        _event("chat_sent", actor="user-1", ts=now - 50, properties={"complexity": "deep", "graph_mode": "on", "research_enabled": True}),
        _event("chat_stream_completed", actor="user-1", ts=now - 40),
        _event("chat_sent", actor="user-2", ts=now - 30, properties={"complexity": "auto", "graph_mode": "auto", "research_enabled": False}),
        _event("chat_stream_failed", actor="user-2", ts=now - 20),
        _event("chat_stopped", actor="user-2", ts=now - 10),
        _event("search_tool_requested", actor="user-2", ts=now - 5),
    ]
    http_logs = [
        _http("/api/chat", 200, 1200, ts=now - 50, metadata={"request_id": "r1", "trace_id": "t1"}),
        _http("/api/chat", 500, 2400, ts=now - 20, metadata={"request_id": "r2", "trace_id": "t2", "client_request_id": "c2"}),
        _http("/health", 200, 15, ts=now - 5),
    ]
    llm_rows = [
        _llm("synthesis", "anthropic", "claude", ts=now - 50, duration=900),
        _llm("synthesis", "openai", "gpt", ts=now - 20, fallback=True, status="error", duration=1300, metadata={"request_id": "r2", "trace_id": "t2"}),
        _llm("routing", "anthropic", "claude", ts=now - 10, duration=100),
    ]
    analytics_rows = [
        _analytics("stream_first_token", "stream", ts=now - 50, value=320),
        _analytics("stream_first_token", "stream", ts=now - 20, value=900, request_id="r2"),
        _analytics(
            "stream_completed",
            "stream",
            ts=now - 40,
            value=1400,
            properties={"output_type": "chat_response", "graph_emitted": True, "retrieval_relevance": "strong"},
        ),
        _analytics(
            "retrieval_quality",
            "quality_score",
            ts=now - 30,
            value=0.3,
            properties={"score_name": "retrieval_relevance", "retrieval_relevance": "weak"},
            request_id="r3",
        ),
        _analytics(
            "stream_failed",
            "stream",
            ts=now - 10,
            properties={"error_type": "RuntimeError"},
            request_id="r4",
        ),
    ]

    monkeypatch.setattr(dashboard.time, "time", lambda: now)
    monkeypatch.setattr(dashboard, "list_recent_product_analytics_events", lambda since_epoch: [row for row in events if row["created_at_epoch"] >= since_epoch])
    monkeypatch.setattr(dashboard, "list_recent_http_request_logs", lambda since_epoch: [row for row in http_logs if row["created_at_epoch"] >= since_epoch])
    monkeypatch.setattr(dashboard, "list_recent_llm_telemetry", lambda since_epoch: [row for row in llm_rows if row["created_at_epoch"] >= since_epoch])
    monkeypatch.setattr(dashboard, "list_recent_analytics_events", lambda since_epoch, event_category=None: [
        row for row in analytics_rows
        if row["created_at_epoch"] >= since_epoch and (event_category is None or row["event_category"] == event_category)
    ])
    return {"events": events, "http_logs": http_logs, "llm_rows": llm_rows, "analytics_rows": analytics_rows}


@pytest.mark.asyncio
async def test_dashboard_overview_computes_kpis(dashboard_data):
    payload = await dashboard.dashboard_overview(_user={"email": "admin@example.com"})

    assert payload["window_hours"] == 24
    assert payload["kpis"]["dau"] == 3
    assert payload["kpis"]["wau"] == 3
    assert payload["kpis"]["prepares"] == 1
    assert payload["kpis"]["chats_sent"] == 2
    assert payload["kpis"]["chats_completed"] == 1
    assert payload["kpis"]["chats_failed"] == 1
    assert payload["kpis"]["stop_rate"] == 0.5
    assert payload["kpis"]["search_tool_request_rate"] == 0.5
    assert payload["kpis"]["avg_chat_latency_ms"] == 1800
    assert payload["kpis"]["avg_first_token_latency_ms"] == 610
    assert payload["kpis"]["p95_first_token_latency_ms"] == 900
    assert payload["kpis"]["quality_scores"] == 1
    assert payload["providers"] == {"anthropic": 2, "openai": 1}


@pytest.mark.asyncio
async def test_dashboard_trends_buckets_events_latency_and_provider_usage(dashboard_data):
    payload = await dashboard.dashboard_trends(bucket="hour", _user={"email": "admin@example.com"})

    assert payload["bucket"] == "hour"
    non_empty = [point for point in payload["points"] if point["chat_sent"] or point["chat_failed"] or point["provider_usage"]]
    assert len(non_empty) == 1
    point = non_empty[0]
    assert point["chat_sent"] == 2
    assert point["chat_completed"] == 1
    assert point["chat_failed"] == 1
    assert point["completion_rate"] == 0.5
    assert point["avg_chat_latency_ms"] == 1800
    assert point["provider_usage"] == {"anthropic": 2, "openai": 1}


@pytest.mark.asyncio
async def test_dashboard_funnel_reports_actor_conversion(dashboard_data):
    payload = await dashboard.dashboard_funnel(_user={"email": "admin@example.com"})

    by_step = {step["event_type"]: step for step in payload["steps"]}
    assert payload["window_days"] == 7
    assert by_step["auth_viewed"]["actors"] == 1
    assert by_step["chat_sent"]["actors"] == 2
    assert by_step["chat_stream_completed"]["conversion_from_previous"] == 0.5


@pytest.mark.asyncio
async def test_dashboard_failures_shapes_operational_debug_payloads(dashboard_data):
    payload = await dashboard.dashboard_failures(_user={"email": "admin@example.com"})

    assert payload["recent_failed_requests"] == [
        {
            "path": "/api/chat",
            "status_code": 500,
            "latency_ms": 2400,
            "created_at_epoch": 9980.0,
            "request_id": "r2",
            "trace_id": "t2",
            "client_request_id": "c2",
        }
    ]
    assert payload["slow_requests"][0]["latency_ms"] == 2400
    assert payload["provider_fallbacks"][0]["provider"] == "openai"
    assert payload["most_used_modes"] == [
        {"label": "deep / on / research-on", "count": 1},
        {"label": "auto / auto / research-off", "count": 1},
    ]


@pytest.mark.asyncio
async def test_dashboard_llm_performance_groups_by_operation_provider_model(dashboard_data):
    payload = await dashboard.dashboard_llm_performance(_user={"email": "admin@example.com"})

    operations = {
        (row["operation"], row["provider"], row["model"]): row
        for row in payload["operations"]
    }
    assert operations[("synthesis", "anthropic", "claude")]["calls"] == 1
    assert operations[("synthesis", "openai", "gpt")]["fallback_rate"] == 1.0
    assert operations[("synthesis", "openai", "gpt")]["error_rate"] == 1.0
    assert payload["recent_fallbacks"] == [
        {
            "operation": "synthesis",
            "provider": "openai",
            "model": "gpt",
            "duration_ms": 1300,
            "created_at_epoch": 9980.0,
            "request_id": "r2",
            "trace_id": "t2",
        }
    ]


@pytest.mark.asyncio
async def test_eval_telemetry_is_thread_scoped_bounded_and_sanitized(monkeypatch):
    rows = [
        _llm(
            "synthesis",
            "anthropic",
            "claude",
            metadata={
                "input_tokens": 12,
                "output_tokens": 5,
                "queue_wait_ms": 23,
                "request_id": "request-1",
                "client_request_id": "secret/path",
                "attempts": [
                    {
                        "attempt": 1,
                        "provider": "anthropic",
                        "model": "claude-opus-5",
                        "status": "success",
                        "input_tokens": 12,
                        "output_tokens": 5,
                        "queue_wait_ms": 23,
                        "duration_ms": 100,
                        "secret": "never-return",
                    }
                ],
                "secret": "never-return",
            },
        )
        | {"thread_id": "thread-1"},
        _llm("routing", "openai", "gpt") | {"thread_id": "another-thread"},
    ]
    monkeypatch.setattr(dashboard, "list_recent_llm_telemetry", lambda since_epoch: rows)

    payload = await dashboard.dashboard_eval_telemetry(
        since_epoch=900,
        thread_id=["thread-1"],
        _user={"email": "admin@example.com"},
    )

    assert payload == {
        "calls": [
            {
                "thread_id": "thread-1",
                "operation": "synthesis",
                "provider": "anthropic",
                "model": "claude",
                "status": "success",
                "latency_ms": 100,
                "fallback": False,
                "input_tokens": 12,
                "output_tokens": 5,
                "provider_attempts": 1,
                "queue_wait_ms": 23,
                "attempts": [
                    {
                        "attempt": 1,
                        "provider": "anthropic",
                        "model": "claude-opus-5",
                        "status": "success",
                        "input_tokens": 12,
                        "output_tokens": 5,
                        "queue_wait_ms": 23,
                        "duration_ms": 100,
                    }
                ],
                "request_id": "request-1",
                "client_request_id": None,
                "created_at_epoch": 1000.0,
            }
        ]
    }
    assert await dashboard.dashboard_eval_telemetry(
        since_epoch=900,
        thread_id=[str(index) for index in range(41)],
        _user={"email": "admin@example.com"},
    ) == {"calls": []}


@pytest.mark.asyncio
async def test_dashboard_self_improvement_surfaces_latency_scores_and_errors(dashboard_data):
    payload = await dashboard.dashboard_self_improvement(_user={"email": "admin@example.com"})

    assert payload["window_days"] == 7
    assert payload["queues"]["slow_first_token"][0]["latency_ms"] == 900
    assert payload["queues"]["low_quality_scores"][0]["score_name"] == "retrieval_relevance"
    assert payload["queues"]["recent_operational_errors"][0]["event_name"] == "stream_failed"
    assert payload["output_shapes"] == [
        {"label": "chat_response / graph:True / retrieval:strong", "count": 1}
    ]
