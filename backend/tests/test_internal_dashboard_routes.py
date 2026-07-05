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

    monkeypatch.setattr(dashboard.time, "time", lambda: now)
    monkeypatch.setattr(dashboard, "list_recent_product_analytics_events", lambda since_epoch: [row for row in events if row["created_at_epoch"] >= since_epoch])
    monkeypatch.setattr(dashboard, "list_recent_http_request_logs", lambda since_epoch: [row for row in http_logs if row["created_at_epoch"] >= since_epoch])
    monkeypatch.setattr(dashboard, "list_recent_llm_telemetry", lambda since_epoch: [row for row in llm_rows if row["created_at_epoch"] >= since_epoch])
    return {"events": events, "http_logs": http_logs, "llm_rows": llm_rows}


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
