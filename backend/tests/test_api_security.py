import pytest
from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from api.sse_handler import ChatRequest, chat_endpoint
from config import settings
from main import create_app
from storage import message_store
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, get_graph, get_thread


def _authed_app(*, with_resources: bool = True):
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1", "email": "friend@example.com"}
    if with_resources:
        app.state.vectorstore = object()
        app.state.parent_docs = [{"page_content": "placeholder"}]
    return app


def _parse_sse_events(response_text: str) -> list[dict]:
    import json

    events: list[dict] = []
    for chunk in response_text.split("\n\n"):
        line = chunk.strip()
        if not line.startswith("data: "):
            continue
        events.append(json.loads(line[6:]))
    return events


def test_cors_allows_vercel_preview_origin():
    app = create_app(load_resources=False)
    client = TestClient(app)

    response = client.options(
        "/api/chat",
        headers={
            "Origin": "https://prototype-branch.vercel.app",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://prototype-branch.vercel.app"


def test_cors_allows_delete_for_vercel_preview_origin():
    app = create_app(load_resources=False)
    client = TestClient(app)

    response = client.options(
        "/api/threads/thread-123",
        headers={
            "Origin": "https://prototype-branch.vercel.app",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    allow_methods = response.headers["access-control-allow-methods"]
    assert "DELETE" in allow_methods


def test_health_reports_faiss_not_loaded_when_resources_missing():
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "faiss_loaded": False}


def test_health_reports_faiss_loaded_when_vectorstore_present():
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "placeholder"}]

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "faiss_loaded": True}


def test_health_reports_not_loaded_when_parent_docs_missing():
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = []

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "faiss_loaded": False}


def test_prepare_returns_503_when_faiss_not_loaded():
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.get("/api/prepare")

    assert response.status_code == 503
    assert "warming up" in response.json()["detail"].lower()


def test_prepare_returns_ready_when_vectorstore_present():
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "placeholder"}]

    with TestClient(app) as client:
        response = client.get("/api/prepare")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "faiss_loaded": True}


def test_prepare_returns_503_when_parent_docs_missing():
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = []

    with TestClient(app) as client:
        response = client.get("/api/prepare")

    assert response.status_code == 503
    assert "warming up" in response.json()["detail"].lower()


def test_cloud_run_refuses_sqlite_fallback(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "agent-backend")
    monkeypatch.setattr(settings, "supabase_db_url", "")
    app = create_app(load_resources=False)

    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL"):
        with TestClient(app):
            pass


def test_chat_requires_auth():
    app = create_app(load_resources=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"thread_id": "missing", "content": "hello"},
    )

    assert response.status_code == 401


def test_chat_rejects_oversized_message(temp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "max_message_bytes", 8)
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"thread_id": thread["id"], "content": "message-too-large"},
        )

    assert response.status_code == 200
    assert "Message too large" in response.text


def test_node_selected_rejects_oversized_payload(temp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "max_node_text_bytes", 12)
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/node-selected",
            json={
                "thread_id": thread["id"],
                "node_id": "n1",
                "title": "Transformers",
                "description": "attention everywhere",
            },
        )

    assert response.status_code == 200
    assert "Selected node payload too large" in response.text


def test_node_selected_applies_rate_limit(temp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_per_hour", 10)
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/node-selected",
            json={
                "thread_id": thread["id"],
                "node_id": "n1",
                "title": "RAG",
                "description": "retrieval",
            },
        )

    assert response.status_code == 200
    assert "Rate limit exceeded" in response.text


@pytest.mark.asyncio
async def test_chat_rejects_thread_at_message_limit_before_generation(temp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "max_messages_per_thread", 2)
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    message_store.append("user-1", thread["id"], "user", "first")
    message_store.append("user-1", thread["id"], "assistant", "second")
    request = type(
        "RequestStub",
        (),
        {
            "app": type(
                "AppStub",
                (),
                {
                    "state": type(
                        "StateStub",
                        (),
                        {"vectorstore": object(), "parent_docs": [{"page_content": "placeholder"}]},
                    )()
                },
            )()
        },
    )()

    response = await chat_endpoint(
        ChatRequest(thread_id=thread["id"], content="one more"),
        request,
        {"id": "user-1", "email": "friend@example.com"},
    )

    first_chunk = await anext(response.body_iterator)
    first_text = first_chunk if isinstance(first_chunk, str) else first_chunk.decode()

    assert "Thread message limit reached" in first_text


def test_chat_rejects_when_knowledge_base_not_loaded(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app(with_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"thread_id": thread["id"], "content": "hello"},
        )

    assert response.status_code == 200
    assert "Knowledge base is still loading" in response.text


def test_request_otp_requires_captcha_after_burst(monkeypatch):
    monkeypatch.setattr(settings, "otp_request_per_email_limit", 1)
    monkeypatch.setattr(settings, "otp_request_per_ip_limit", 100)
    app = create_app(load_resources=False)

    calls: list[str] = []

    async def fake_request_otp(email: str):
        calls.append(email)

    import api.auth_route as auth_route
    monkeypatch.setattr(auth_route, "request_email_otp", fake_request_otp)

    with TestClient(app) as client:
        first = client.post("/api/auth/request-otp", json={"email": "friend@example.com"})
        second = client.post("/api/auth/request-otp", json={"email": "friend@example.com"})

    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert second.status_code == 200
    assert second.json()["captcha_required"] is True
    assert calls == ["friend@example.com"]


def test_chat_stream_persists_messages_and_graph(temp_data_dir, monkeypatch):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()

    async def fake_run_agent(state, rag_tools, graph_tools, node_detail_tools):
        await state["send"]({"type": "worker_status", "worker": "rag", "status": "Searching book…"})
        await state["send"]({"type": "graph_data", "data": {"title": "Study graph", "nodes": [], "edges": [], "sequence": []}})
        await state["send"]({"type": "response_delta", "content": "Hello"})
        await state["send"]({"type": "response_delta", "content": " world"})
        await state["send"]({"type": "done"})
        return {
            **state,
            "response_text": "Hello world",
            "graph_data": {"title": "Study graph", "nodes": [], "edges": [], "sequence": []},
        }

    import api.sse_handler as sse_handler
    monkeypatch.setattr(sse_handler, "run_agent", fake_run_agent)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"thread_id": thread["id"], "content": "Teach me RAG"},
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event["type"] for event in events[:2]] == ["worker_status", "worker_status"]
    assert any(event["type"] == "graph_data" for event in events)
    assert "".join(event["content"] for event in events if event["type"] == "response_delta") == "Hello world"
    assert events[-1]["type"] == "done"

    saved_messages = message_store.get_messages("user-1", thread["id"])
    assert [message["role"] for message in saved_messages] == ["user", "assistant"]
    assert saved_messages[0]["content"] == "Teach me RAG"
    assert saved_messages[1]["content"] == "Hello world"
    assert get_graph("user-1", thread["id"]) == {"title": "Study graph", "nodes": [], "edges": [], "sequence": []}
    assert get_thread("user-1", thread["id"])["title"] == "Teach me RAG"


def test_chat_agent_error_emits_error_and_skips_persistence(temp_data_dir, monkeypatch):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()

    async def fake_run_agent(state, rag_tools, graph_tools, node_detail_tools):
        await state["send"]({"type": "worker_status", "worker": "rag", "status": "Searching book…"})
        raise RuntimeError("agent exploded")

    import api.sse_handler as sse_handler
    monkeypatch.setattr(sse_handler, "run_agent", fake_run_agent)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"thread_id": thread["id"], "content": "Teach me RAG"},
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert any(event["type"] == "error" and "agent exploded" in event["content"] for event in events)
    assert message_store.get_messages("user-1", thread["id"]) == []
    assert get_graph("user-1", thread["id"]) is None


def test_chat_stream_appends_done_when_agent_omits_it(temp_data_dir, monkeypatch):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()

    async def fake_run_agent(state, rag_tools, graph_tools, node_detail_tools):
        await state["send"]({"type": "worker_status", "worker": "orchestrator", "status": "Writing the explanation…"})
        await state["send"]({"type": "response_delta", "content": "Partial but valid"})
        return {
            **state,
            "response_text": "Partial but valid",
            "graph_data": None,
        }

    import api.sse_handler as sse_handler
    monkeypatch.setattr(sse_handler, "run_agent", fake_run_agent)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"thread_id": thread["id"], "content": "Teach me RAG"},
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert any(event["type"] == "response_delta" for event in events)
    assert events[-1]["type"] == "done"

    saved_messages = message_store.get_messages("user-1", thread["id"])
    assert [message["role"] for message in saved_messages] == ["user", "assistant"]
    assert saved_messages[1]["content"] == "Partial but valid"
