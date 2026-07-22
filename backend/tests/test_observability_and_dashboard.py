import asyncio

from fastapi.testclient import TestClient

from config import settings
from observability import configure_observability, get_metrics_snapshot, get_recorded_spans, reset_observability_test_state
from storage.telemetry_store import list_recent_http_request_logs


def _internal_login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/internal-login",
        json={"email": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return response.json()["session"]["access_token"]


def test_request_logging_includes_correlation_metadata_when_otel_enabled(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "otel_enabled", True)
    reset_observability_test_state()
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.get("/api/prepare")

    assert response.status_code == 503
    logs = list_recent_http_request_logs(since_epoch=0)
    assert logs
    assert logs[0]["metadata"]["request_id"]
    assert logs[0]["metadata"]["trace_id"]
    assert get_metrics_snapshot()["request_count"] >= 1


def test_internal_dashboard_allowlist_and_overview(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "correct horse battery staple")
    monkeypatch.setattr(
        settings,
        "internal_test_email_allowlist_raw",
        "friend@example.com,admin@example.com",
    )
    monkeypatch.setattr(settings, "internal_dashboard_allowlist_raw", "admin@example.com")

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        outsider_token = _internal_login(client, "friend@example.com")
        forbidden = client.get(
            "/api/internal/dashboard/overview",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert forbidden.status_code == 403

        insider_token = _internal_login(client, "admin@example.com")
        for event_type in ("prepare_succeeded", "chat_sent", "chat_stream_completed"):
            captured = client.post(
                "/api/analytics/capture",
                headers={"Authorization": f"Bearer {insider_token}"},
                json={
                    "anonymous_id": "anon-1",
                    "event_type": event_type,
                    "properties": {"thread_id": "thread-1"},
                },
            )
            assert captured.status_code == 200

        from analytics import events

        if events._queue is not None:
            client.portal.call(events._queue.join)

        response = client.get(
            "/api/internal/dashboard/overview",
            headers={"Authorization": f"Bearer {insider_token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["prepares"] == 1
    assert payload["kpis"]["chats_sent"] == 1
    assert payload["kpis"]["chats_completed"] == 1


def test_analytics_capture_requires_auth_for_non_public_events(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "correct horse battery staple")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "admin@example.com")

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        public_ok = client.post(
            "/api/analytics/capture",
            json={
                "anonymous_id": "anon-1",
                "event_type": "auth_viewed",
                "properties": {},
            },
        )
        assert public_ok.status_code == 200

        private_denied = client.post(
            "/api/analytics/capture",
            json={
                "anonymous_id": "anon-1",
                "event_type": "chat_sent",
                "properties": {"thread_id": "thread-1"},
            },
        )
        assert private_denied.status_code == 401


def test_analytics_capture_accepts_local_dev_auth(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "dev_bypass_auth", True)
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/analytics/capture",
            headers={"Authorization": "Bearer dev-local"},
            json={
                "anonymous_id": "anon-local",
                "event_type": "chat_sent",
                "properties": {"thread_id": "thread-local"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_internal_dashboard_accepts_local_dev_auth_only_when_bypass_is_enabled(
    temp_data_dir,
    monkeypatch,
):
    from main import create_app

    monkeypatch.setattr(settings, "dev_bypass_auth", True)
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.get(
            "/api/internal/dashboard/overview",
            headers={"Authorization": "Bearer dev-local"},
        )

    assert response.status_code == 200


def test_analytics_capture_survives_storage_write_failure(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(
        "analytics.events.record_product_analytics_event",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/analytics/capture",
            json={
                "anonymous_id": "anon-1",
                "event_type": "auth_viewed",
                "properties": {"request_id": "request-1"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_public_analytics_rate_limit_is_ip_based(temp_data_dir, monkeypatch):
    from main import create_app
    import api.analytics_route as analytics_route

    monkeypatch.setattr(analytics_route, "_CAPTURE_LIMIT_PER_KEY", 1)
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        first = client.post(
            "/api/analytics/capture",
            json={"anonymous_id": "anon-1", "event_type": "auth_viewed", "properties": {}},
        )
        second = client.post(
            "/api/analytics/capture",
            json={"anonymous_id": "anon-2", "event_type": "auth_viewed", "properties": {}},
        )

    assert first.status_code == 200
    assert second.status_code == 429


def test_run_agent_records_phase_spans(monkeypatch):
    from agent.graph import run_agent

    monkeypatch.setattr(settings, "otel_enabled", True)
    configure_observability()
    reset_observability_test_state()

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search_phase(state, rag_tools):
        return {**state, "rag_chunks": []}, None

    async def fake_apply_graph(state, graph_tools):
        return state

    async def fake_expand(state, graph_tools, search_tool_wait_task):
        return state

    async def fake_synth(state):
        return {**state, "response_text": "ok"}

    async def fake_node_enrichment(state, tools):
        return None

    monkeypatch.setattr("agent.graph.orchestrator_route", fake_route)
    monkeypatch.setattr("agent.graph.run_search_phase", fake_search_phase)
    monkeypatch.setattr("agent.graph.apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr("agent.graph.maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr("agent.graph.orchestrator_synthesise", fake_synth)
    monkeypatch.setattr("agent.graph.maybe_start_node_enrichment", fake_node_enrichment)

    async def _run():
        return await run_agent(
            {
                "session_id": "thread-1",
                "user_id": "user-1",
                "user_email": "user@example.com",
                "user_message": "hello",
                "history": [],
                "complexity": "auto",
                "graph_mode": "auto",
                "research_enabled": False,
                "route": "",
                "request_id": "req-1",
                "client_request_id": "client-1",
                "rag_chunks": [],
                "retrieval_relevance": "strong",
                "retrieval_notice": "",
                "graph_data": None,
                "graph_changed": False,
                "graph_notice_sent": False,
                "research_context": "",
                "response_text": "",
                "send": lambda event: asyncio.sleep(0),
                "await_search_tool_request": lambda request_id, timeout_s: asyncio.sleep(0),
            },
            [],
            [],
            [],
        )

    result = asyncio.run(_run())

    assert result["response_text"] == "ok"
    span_names = [span["name"] for span in get_recorded_spans()]
    assert "agent.orchestrator_route" in span_names
    assert "agent.rag_phase" in span_names
    assert "agent.graph_phase" in span_names
    assert "agent.synthesis_phase" in span_names
