import asyncio
import base64

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from adapters.database_adapter import init_db
from main import create_app
from storage.message_store import get_history
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, persist_turn


def _ready_app(temp_data_dir, monkeypatch):
    init_db()
    user = {"id": "ws-user", "email": "ws@example.com"}
    upsert_profile(user["id"], user["email"])
    thread = create_thread(user["id"])
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "agent design"}]
    monkeypatch.setattr("api.chat_websocket.get_current_user", lambda authorization: user)
    return app, user, thread


def _receive_until(socket, event_type: str, *, limit: int = 20) -> list[dict]:
    events = []
    for _ in range(limit):
        event = socket.receive_json()
        events.append(event)
        if event.get("type") == event_type:
            return events
    raise AssertionError(f"Did not receive {event_type}: {events}")


def test_websocket_steer_cancels_draft_restarts_and_persists_combined_turn(temp_data_dir, monkeypatch):
    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    calls: list[str] = []
    first_cancelled = False

    async def fake_run_agent(state, _rag_tools, _graph_tools, _detail_tools):
        nonlocal first_cancelled
        calls.append(state["user_message"])
        if len(calls) == 1:
            await state["send"]({"type": "response_delta", "content": "generic draft"})
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                first_cancelled = True
                raise

        assert "focus on attribution and approval boundaries" in state["user_message"].lower()
        await state["send"]({"type": "response_delta", "content": "specific revised answer"})
        await state["send"]({"type": "done"})
        return {**state, "response_text": "specific revised answer", "graph_data": None}

    monkeypatch.setattr("api.chat_websocket.run_agent", fake_run_agent)

    with TestClient(app) as client:
        with client.websocket_connect("/api/chat/ws", headers={"origin": "http://localhost:5173"}) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json({
                "type": "start",
                "thread_id": thread["id"],
                "content": "Design a growth marketing agent system",
                "complexity": "production",
                "graph_mode": "on",
                "research_enabled": False,
                "client_request_id": "client-ws-1",
            })
            initial = _receive_until(socket, "response_delta")
            assert initial[-1]["content"] == "generic draft"

            socket.send_json({
                "type": "steer",
                "content": "Focus on attribution and approval boundaries",
                "client_request_id": "client-ws-1",
            })
            events = _receive_until(socket, "done")

    assert first_cancelled is True
    assert len(calls) == 2
    assert any(event["type"] == "response_reset" for event in events)
    assert any(event["type"] == "steer_applied" for event in events)
    assert any(
        event.get("type") == "response_delta" and event.get("content") == "specific revised answer"
        for event in events
    )
    history = get_history(user["id"], thread["id"])
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert "User steering update 1" in history[0]["content"]
    assert history[1]["content"] == "specific revised answer"


def test_websocket_rejects_untrusted_browser_origin(temp_data_dir, monkeypatch):
    app, _user, _thread = _ready_app(temp_data_dir, monkeypatch)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/chat/ws", headers={"origin": "https://attacker.example"}):
                pass
    assert exc_info.value.code == 1008


def test_websocket_replays_completed_idempotent_turn_without_running_agent(temp_data_dir, monkeypatch):
    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    persist_turn(
        user["id"],
        thread["id"],
        title="Stored",
        user_content="Explain RAG",
        assistant_content="Canonical stored answer",
        graph_data=None,
        client_request_id="client-replay-1",
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("an idempotent replay must not call the model")

    monkeypatch.setattr("api.chat_websocket.run_agent", fail_if_called)

    with TestClient(app) as client:
        with client.websocket_connect("/api/chat/ws", headers={"origin": "http://localhost:5173"}) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json({
                "type": "start",
                "thread_id": thread["id"],
                "content": "Explain RAG",
                "client_request_id": "client-replay-1",
            })
            events = _receive_until(socket, "done")

    assert events == [
        {"type": "response_delta", "content": "Canonical stored answer"},
        {"type": "done"},
    ]


def test_websocket_keeps_candidate_private_until_browser_evaluation(temp_data_dir, monkeypatch):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)
    graph = {
        "graph_type": "architecture",
        "design_origin": "applied",
        "version": "graph-v1",
        "title": "Reviewed design",
        "nodes": [],
        "edges": [],
        "sequence": [],
    }

    async def fake_run_agent(state, _rag_tools, _graph_tools, _detail_tools):
        evaluation = await state["await_diagram_evaluation"](graph)
        assert evaluation["report"]["overlap_count"] == 0
        await state["send"]({"type": "graph_data", "data": graph})
        await state["send"]({"type": "response_delta", "content": "approved"})
        await state["send"]({"type": "done"})
        return {**state, "response_text": "approved", "graph_data": graph}

    monkeypatch.setattr("api.chat_websocket.run_agent", fake_run_agent)

    with TestClient(app) as client:
        with client.websocket_connect("/api/chat/ws", headers={"origin": "http://localhost:5173"}) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json({
                "type": "start",
                "thread_id": thread["id"],
                "content": "Design an evaluated architecture",
                "complexity": "prototype",
                "graph_mode": "on",
                "research_enabled": False,
                "client_request_id": "client-eval-1",
            })
            candidate_events = _receive_until(socket, "graph_candidate")
            assert not any(event.get("type") == "graph_data" for event in candidate_events)
            candidate = candidate_events[-1]
            encoded = base64.b64encode(b"browser-render").decode()
            socket.send_json({
                "type": "diagram_evaluation_start",
                "evaluation_id": candidate["evaluation_id"],
                "graph_version": "graph-v1",
                "media_type": "image/jpeg",
                "total_chunks": 1,
                "report": {
                    "rendered_nodes": 0,
                    "rendered_edges": 0,
                    "overlap_count": 0,
                    "clipped_nodes": 0,
                    "minimum_text_px": 8,
                },
            })
            socket.send_json({
                "type": "diagram_evaluation_chunk",
                "evaluation_id": candidate["evaluation_id"],
                "index": 0,
                "data": encoded,
            })
            socket.send_json({
                "type": "diagram_evaluation_complete",
                "evaluation_id": candidate["evaluation_id"],
            })
            published = _receive_until(socket, "done")

    assert any(event.get("type") == "graph_data" for event in published)
    assert any(event.get("type") == "response_delta" and event.get("content") == "approved" for event in published)
