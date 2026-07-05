import json

from fastapi.testclient import TestClient

from config import settings
from main import create_app


def _events(response_text: str) -> list[dict]:
    parsed = []
    for chunk in response_text.split("\n\n"):
        line = chunk.strip()
        if line.startswith("data: "):
            parsed.append(json.loads(line.removeprefix("data: ")))
    return parsed


def _configure_internal_auth(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "correct horse battery staple")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "recruiter@example.com")


def test_recruiter_demo_happy_path_system_workflow(temp_data_dir, monkeypatch):
    _configure_internal_auth(monkeypatch)

    async def fake_run_agent(state, rag_tools, graph_tools, node_detail_tools):
        await state["send"]({"type": "worker_status", "worker": "rag", "status": "Searching book…"})
        await state["send"]({"type": "response_delta", "content": "Agents can plan and use tools."})
        await state["send"]({
            "type": "graph_data",
            "data": {
                "graph_type": "concept",
                "title": "Agent Workflow",
                "nodes": [
                    {
                        "id": "agent",
                        "label": "Agent",
                        "type": "service",
                        "technology": "LLM",
                        "description": "Plans tool use.",
                    }
                ],
                "edges": [],
                "sequence": [],
                "version": 1,
            },
        })
        await state["send"]({"type": "done"})
        return {
            **state,
            "response_text": "Agents can plan and use tools.",
            "graph_data": {
                "graph_type": "concept",
                "title": "Agent Workflow",
                "nodes": [
                    {
                        "id": "agent",
                        "label": "Agent",
                        "type": "service",
                        "technology": "LLM",
                        "description": "Plans tool use.",
                    }
                ],
                "edges": [],
                "sequence": [],
                "version": 1,
            },
        }

    async def fake_stream_suggested_questions(*_args, **_kwargs):
        yield {"type": "suggested_questions", "questions": ["Explain tools", "Expand graph", "Compare planning"]}
        yield {"type": "done"}

    monkeypatch.setattr("api.sse_handler.run_agent", fake_run_agent)
    monkeypatch.setattr("api.sse_handler.stream_suggested_questions", fake_stream_suggested_questions)

    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "Agents use tools."}]

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/internal-login",
            json={"email": "recruiter@example.com", "password": "correct horse battery staple"},
        )
        assert login.status_code == 200
        token = login.json()["session"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/prepare", headers=headers).json() == {
            "status": "ready",
            "faiss_loaded": True,
        }

        created = client.post("/api/threads", headers=headers, json={"title": "Recruiter demo"})
        assert created.status_code == 200
        thread_id = created.json()["thread"]["id"]

        chat = client.post(
            "/api/chat",
            headers=headers,
            json={
                "thread_id": thread_id,
                "content": "How do agents use tools?",
                "complexity": "prototype",
                "graph_mode": "on",
                "research_enabled": False,
                "client_request_id": "client-1",
            },
        )
        assert chat.status_code == 200
        chat_events = _events(chat.text)
        assert {"type": "response_delta", "content": "Agents can plan and use tools."} in chat_events
        assert any(event["type"] == "graph_data" for event in chat_events)
        assert chat_events[-1] == {"type": "done"}

        fetched = client.get(f"/api/threads/{thread_id}", headers=headers)
        assert fetched.status_code == 200
        payload = fetched.json()
        assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
        assert payload["thread"]["graph_data"]["title"] == "Agent Workflow"

        node = client.post(
            "/api/node-selected",
            headers=headers,
            json={
                "thread_id": thread_id,
                "node_id": "agent",
                "title": "Agent",
                "description": "Plans tool use.",
                "client_request_id": "node-1",
            },
        )
        assert node.status_code == 200
        assert _events(node.text) == [
            {
                "type": "suggested_questions",
                "questions": ["Explain tools", "Expand graph", "Compare planning"],
            },
            {"type": "done"},
        ]

        deleted = client.delete(f"/api/threads/{thread_id}", headers=headers)
        assert deleted.status_code == 204
        assert client.get(f"/api/threads/{thread_id}", headers=headers).status_code == 404
