from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from config import settings
from main import create_app
from storage.message_store import append
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, get_graph, get_thread, list_threads


def _app():
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-1",
        "email": "friend@example.com",
    }
    return app


def _setup_user():
    init_db()
    upsert_profile("user-1", "friend@example.com")


def test_thread_routes_create_list_latest_get_update_and_delete(temp_data_dir):
    _setup_user()
    app = _app()

    with TestClient(app) as client:
        created = client.post("/api/threads", json={"title": "  Launch plan  "})
        assert created.status_code == 200
        thread_id = created.json()["thread"]["id"]
        assert created.json()["thread"]["title"] == "Launch plan"

        append("user-1", thread_id, "user", "hello")
        append("user-1", thread_id, "assistant", "hi")

        listed = client.get("/api/threads")
        assert listed.status_code == 200
        assert [thread["id"] for thread in listed.json()["threads"]] == [thread_id]

        latest = client.get("/api/threads/latest")
        assert latest.status_code == 200
        assert latest.json()["thread"]["id"] == thread_id
        assert [message["content"] for message in latest.json()["messages"]] == ["hello", "hi"]

        graph = {
            "title": "Agent graph",
            "nodes": [{"id": "agent", "label": "Agent"}],
            "edges": [],
            "sequence": [],
        }
        updated = client.put(f"/api/threads/{thread_id}/graph", json={"graph_data": graph})
        assert updated.status_code == 204
        assert get_graph("user-1", thread_id) == graph

        fetched = client.get(f"/api/threads/{thread_id}")
        assert fetched.status_code == 200
        assert fetched.json()["thread"]["graph_data"] == graph
        assert [message["role"] for message in fetched.json()["messages"]] == ["user", "assistant"]

        deleted = client.delete(f"/api/threads/{thread_id}")
        assert deleted.status_code == 204
        assert get_thread("user-1", thread_id) is None


def test_latest_thread_endpoint_creates_thread_when_none_exists(temp_data_dir):
    _setup_user()
    app = _app()

    with TestClient(app) as client:
        response = client.get("/api/threads/latest")

    assert response.status_code == 200
    assert response.json()["thread"]["title"] == "New chat"
    assert response.json()["messages"] == []
    assert len(list_threads("user-1")) == 1


def test_thread_routes_reject_missing_thread_and_oversized_payloads(temp_data_dir, monkeypatch):
    _setup_user()
    monkeypatch.setattr(settings, "max_thread_title_bytes", 5)
    monkeypatch.setattr(settings, "max_graph_data_bytes", 20)
    thread = create_thread("user-1", "Existing")
    app = _app()

    with TestClient(app) as client:
        oversized_title = client.post("/api/threads", json={"title": "title too long"})
        missing_get = client.get("/api/threads/missing")
        missing_delete = client.delete("/api/threads/missing")
        missing_graph = client.put("/api/threads/missing/graph", json={"graph_data": {"title": "x"}})
        oversized_graph = client.put(
            f"/api/threads/{thread['id']}/graph",
            json={"graph_data": {"title": "x" * 100}},
        )

    assert oversized_title.status_code == 413
    assert missing_get.status_code == 404
    assert missing_delete.status_code == 404
    assert missing_graph.status_code == 404
    assert oversized_graph.status_code == 413
    assert get_graph("user-1", thread["id"]) is None


def test_thread_route_defaults_blank_title(temp_data_dir):
    _setup_user()
    app = _app()

    with TestClient(app) as client:
        response = client.post("/api/threads", json={"title": "   "})

    assert response.status_code == 200
    assert response.json()["thread"]["title"] == "New chat"
