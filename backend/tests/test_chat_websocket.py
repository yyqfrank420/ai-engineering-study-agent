import asyncio
import base64
from io import BytesIO

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from starlette.websockets import WebSocketDisconnect

import api.chat_websocket as chat_websocket
from adapters.database_adapter import init_db
from api.chat_websocket import (
    _SingleWaitDiagramEvaluationChannel,
    _origin_allowed,
    _receive_object,
)
from config import settings
from main import create_app
from storage import runtime_state_store
from storage.message_store import get_history
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, delete_thread, persist_turn


def _png(width: int = 1440, height: int = 960) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "black").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _layout_report(**overrides):
    return {
        "viewport_width": 1440,
        "viewport_height": 960,
        "rendered_nodes": 0,
        "rendered_edges": 0,
        "overlap_count": 0,
        "clipped_nodes": 0,
        "clipped_edges": 0,
        "minimum_text_px": 12,
        "overview_required_edge_labels": 0,
        "visible_overview_required_edge_labels": 0,
        "grouped_nodes": 0,
        "group_labelled_nodes": 0,
        "visible_group_boundaries": 0,
        "group_boundary_overlap_count": 0,
        **overrides,
    }


def _ready_app(temp_data_dir, monkeypatch):
    init_db()
    user = {"id": "ws-user", "email": "ws@example.com"}
    upsert_profile(user["id"], user["email"])
    thread = create_thread(user["id"])
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "agent design"}]
    monkeypatch.setattr(
        "api.chat_websocket.get_current_user", lambda authorization: user
    )
    return app, user, thread


def _receive_until(socket, event_type: str, *, limit: int = 20) -> list[dict]:
    events = []
    for _ in range(limit):
        event = socket.receive_json()
        events.append(event)
        if event.get("type") == event_type:
            return events
    raise AssertionError(f"Did not receive {event_type}: {events}")


@pytest.mark.asyncio
async def test_diagram_evaluation_uses_one_correlated_wait_and_ignores_mismatched_id():
    channel = _SingleWaitDiagramEvaluationChannel(
        timeout_s=1,
        max_screenshot_bytes=100_000,
    )
    graph = {"version": "graph-v1", "nodes": [], "edges": []}
    candidate_events = []

    async def send(event):
        candidate_events.append(event)
        evaluation_id = event["evaluation_id"]
        assert event["criteria"] == {
            "viewport_width": 1440,
            "viewport_height": 960,
            "minimum_text_px": 11.0,
        }
        wrong_id = "wrong-evaluation-id"
        channel.accept(
            {
                "type": "diagram_evaluation_start",
                "evaluation_id": wrong_id,
                "graph_version": "graph-v1",
                "total_chunks": 1,
                "report": {},
            }
        )
        channel.accept(
            {
                "type": "diagram_evaluation_chunk",
                "evaluation_id": wrong_id,
                "index": 0,
                "data": base64.b64encode(b"wrong").decode(),
            }
        )
        channel.accept(
            {
                "type": "diagram_evaluation_complete",
                "evaluation_id": wrong_id,
            }
        )
        assert not channel._waiters[evaluation_id].future.done()

        encoded = base64.b64encode(_png()).decode()
        chunks = [
            encoded[offset : offset + 8_000] for offset in range(0, len(encoded), 8_000)
        ]
        channel.accept(
            {
                "type": "diagram_evaluation_start",
                "evaluation_id": evaluation_id,
                "graph_version": "graph-v1",
                "media_type": "image/png",
                "total_chunks": len(chunks),
                "report": _layout_report(),
            }
        )
        for index, data in enumerate(chunks):
            channel.accept(
                {
                    "type": "diagram_evaluation_chunk",
                    "evaluation_id": evaluation_id,
                    "index": index,
                    "data": data,
                }
            )
        channel.accept(
            {
                "type": "diagram_evaluation_complete",
                "evaluation_id": evaluation_id,
            }
        )

    result = await channel.request(graph, send)

    assert result["report"] == _layout_report()
    assert len(candidate_events) == 1
    assert channel._waiters == {}
    assert channel._uploads == {}


@pytest.mark.asyncio
async def test_diagram_evaluation_cleans_pending_correlation_on_timeout_and_cancel():
    timeout_channel = _SingleWaitDiagramEvaluationChannel(
        timeout_s=0.001,
        max_screenshot_bytes=1_024,
    )

    async def send_without_result(_event):
        return None

    with pytest.raises(TimeoutError):
        await timeout_channel.request({"version": "timeout-v1"}, send_without_result)
    assert timeout_channel._waiters == {}
    assert timeout_channel._uploads == {}

    cancel_channel = _SingleWaitDiagramEvaluationChannel(
        timeout_s=30,
        max_screenshot_bytes=1_024,
    )
    candidate_sent = asyncio.Event()
    pending_future = None

    async def send_then_block(event):
        nonlocal pending_future
        pending_future = cancel_channel._waiters[event["evaluation_id"]].future
        candidate_sent.set()

    request_task = asyncio.create_task(
        cancel_channel.request({"version": "cancel-v1"}, send_then_block)
    )
    await candidate_sent.wait()
    request_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request_task

    assert pending_future is not None and pending_future.cancelled()
    assert cancel_channel._waiters == {}
    assert cancel_channel._uploads == {}


def test_websocket_steer_cancels_draft_restarts_and_persists_combined_turn(
    temp_data_dir, monkeypatch
):
    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    approved_graph = {
        "version": "approved-v1",
        "title": "Approved baseline",
        "nodes": [],
        "edges": [],
        "sequence": [],
    }
    approved_graph_contract = {
        "graph_version": "approved-v1",
        "resolved_complexity": "prototype",
        "component_fingerprint": "component-fingerprint",
    }
    monkeypatch.setattr(
        "api.chat_websocket.thread_store.get_graph_artifact",
        lambda _user_id, _thread_id: (approved_graph, approved_graph_contract),
    )
    calls: list[str] = []
    input_graphs: list[dict | None] = []
    terminal_deadlines: list[float] = []
    approved_baselines: list[dict] = []
    input_contracts: list[dict | None] = []
    approved_contracts: list[dict | None] = []
    persisted_contracts: list[dict | None] = []
    first_cancelled = False

    original_persist_turn = chat_websocket.thread_store.persist_turn

    def capture_persist_turn(*args, **kwargs):
        persisted_contracts.append(kwargs.get("graph_contract"))
        return original_persist_turn(*args, **kwargs)

    monkeypatch.setattr(
        "api.chat_websocket.thread_store.persist_turn", capture_persist_turn
    )

    async def fake_run_agent(state, _rag_tools, _graph_tools, _detail_tools):
        nonlocal first_cancelled
        calls.append(state["user_message"])
        input_graphs.append(state["graph_data"])
        terminal_deadlines.append(state["terminal_deadline_s"])
        approved_baselines.append(state["approved_graph_data"])
        input_contracts.append(state["graph_contract"])
        approved_contracts.append(state["approved_graph_contract"])
        if len(calls) == 1:
            await state["send"](
                {
                    "type": "graph_data",
                    "data": {
                        "title": "Mutable draft",
                        "nodes": [],
                        "edges": [],
                        "sequence": [],
                    },
                }
            )
            await state["send"]({"type": "response_delta", "content": "generic draft"})
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                first_cancelled = True
                raise

        assert (
            "focus on attribution and approval boundaries"
            in state["user_message"].lower()
        )
        await state["send"](
            {"type": "response_delta", "content": "specific revised answer"}
        )
        await state["send"]({"type": "done"})
        return {
            **state,
            "response_text": "specific revised answer",
            "graph_data": approved_graph,
        }

    monkeypatch.setattr("api.chat_websocket.run_agent", fake_run_agent)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design a growth marketing agent system",
                    "complexity": "production",
                    "graph_mode": "on",
                    "research_enabled": False,
                    "client_request_id": "client-ws-1",
                }
            )
            initial = _receive_until(socket, "response_delta")
            assert initial[-1]["content"] == "generic draft"
            assert any(event["type"] == "graph_preview" for event in initial)
            assert not any(event["type"] == "graph_data" for event in initial)

            socket.send_json(
                {
                    "type": "steer",
                    "content": "Focus on attribution and approval boundaries",
                    "client_request_id": "client-ws-1",
                }
            )
            events = _receive_until(socket, "done")

    assert first_cancelled is True
    assert len(calls) == 2
    assert terminal_deadlines[0] == terminal_deadlines[1]
    assert approved_baselines == [approved_graph, approved_graph]
    assert approved_baselines[0] is not approved_graph
    assert approved_baselines[1] is not approved_graph
    assert approved_baselines[0] is not approved_baselines[1]
    assert approved_contracts == [approved_graph_contract, approved_graph_contract]
    assert input_contracts == [approved_graph_contract, approved_graph_contract]
    assert approved_contracts[0] is not approved_graph_contract
    assert approved_contracts[1] is not approved_graph_contract
    assert approved_contracts[0] is not approved_contracts[1]
    assert input_graphs == [approved_graph, approved_graph]
    assert persisted_contracts == [approved_graph_contract]
    reset_index = next(
        index for index, event in enumerate(events) if event["type"] == "response_reset"
    )
    assert events[reset_index - 1] == {
        "type": "graph_data",
        "data": approved_graph,
    }
    assert any(event["type"] == "response_reset" for event in events)
    assert any(event["type"] == "steer_applied" for event in events)
    assert any(
        event.get("type") == "response_delta"
        and event.get("content") == "specific revised answer"
        for event in events
    )
    assert all("graph_contract" not in event for event in events)
    history = get_history(user["id"], thread["id"])
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert "User steering update 1" in history[0]["content"]
    assert history[1]["content"] == "specific revised answer"


def test_websocket_steer_reuses_graph_review_budget_after_cancellation(
    temp_data_dir, monkeypatch
):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)
    budgets = []
    first_cancelled = False

    async def fake_run_agent(state, _rag_tools, _graph_tools, _detail_tools):
        nonlocal first_cancelled
        budget = state["_graph_review_budget"]
        budgets.append(budget)
        if len(budgets) == 1:
            budget.claim_provider_call(correction="contract")
            await state["send"]({"type": "response_delta", "content": "draft"})
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                first_cancelled = True
                raise

        assert budget.critic_calls == 1
        assert budget.contract_corrections == 1
        budget.claim_provider_call(correction=None)
        await state["send"]({"type": "response_delta", "content": "revised"})
        return {**state, "response_text": "revised", "graph_data": None}

    monkeypatch.setattr("api.chat_websocket.run_agent", fake_run_agent)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design an approval workflow",
                    "complexity": "prototype",
                    "graph_mode": "on",
                    "research_enabled": False,
                    "client_request_id": "client-ws-budget",
                }
            )
            _receive_until(socket, "response_delta")
            socket.send_json(
                {
                    "type": "steer",
                    "content": "Include the approval boundary",
                    "client_request_id": "client-ws-budget",
                }
            )
            _receive_until(socket, "done")

    assert first_cancelled is True
    assert len(budgets) == 2
    assert budgets[0] is budgets[1]
    assert budgets[0].state_counters() == {
        "graph_critic_call_count": 2,
        "graph_protocol_correction_count": 0,
        "graph_contract_correction_count": 1,
    }


def test_websocket_stop_restores_request_start_graph_without_exposing_contract(
    temp_data_dir, monkeypatch
):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)
    approved_graph = {
        "version": "approved-v1",
        "title": "Approved baseline",
        "nodes": [],
        "edges": [],
        "sequence": [],
    }
    approved_graph_contract = {
        "graph_version": "approved-v1",
        "resolved_complexity": "prototype",
    }
    monkeypatch.setattr(
        "api.chat_websocket.thread_store.get_graph_artifact",
        lambda _user_id, _thread_id: (approved_graph, approved_graph_contract),
    )
    observed_states: list[dict] = []
    cancelled = False

    async def fake_run_agent(state, _rag_tools, _graph_tools, _detail_tools):
        nonlocal cancelled
        observed_states.append(state)
        await state["send"](
            {
                "type": "graph_data",
                "data": {
                    "version": "candidate-v1",
                    "title": "Candidate",
                    "nodes": [],
                    "edges": [],
                    "sequence": [],
                },
                "graph_contract": {"secret": "must stay server-side"},
            }
        )
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr("api.chat_websocket.run_agent", fake_run_agent)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design an approval flow",
                    "client_request_id": "client-ws-stop-contract",
                }
            )
            candidate_events = _receive_until(socket, "graph_preview")
            socket.send_json(
                {
                    "type": "stop",
                    "client_request_id": "client-ws-stop-contract",
                }
            )
            stopped_events = _receive_until(socket, "stopped")

    events = [*candidate_events, *stopped_events]
    assert cancelled is True
    assert len(observed_states) == 1
    assert observed_states[0]["graph_contract"] == approved_graph_contract
    assert observed_states[0]["approved_graph_contract"] == approved_graph_contract
    assert any(
        event == {"type": "graph_data", "data": approved_graph} for event in events
    )
    assert all("graph_contract" not in event for event in events)


def test_websocket_rejects_untrusted_browser_origin(temp_data_dir, monkeypatch):
    app, _user, _thread = _ready_app(temp_data_dir, monkeypatch)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/chat/ws", headers={"origin": "https://attacker.example"}
            ):
                pass
    assert exc_info.value.code == 1008


def test_websocket_replays_completed_idempotent_turn_without_running_agent(
    temp_data_dir, monkeypatch
):
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
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Explain RAG",
                    "client_request_id": "client-replay-1",
                }
            )
            events = _receive_until(socket, "done")

    assert events == [
        {"type": "response_delta", "content": "Canonical stored answer"},
        {"type": "graph_data", "data": None},
        {"type": "done"},
    ]


def test_websocket_replays_completed_idempotent_turn_with_graph_before_done(
    temp_data_dir, monkeypatch
):
    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    graph = {
        "version": "graph-v1",
        "nodes": [{"id": "n1", "title": "Start"}],
        "edges": [],
    }
    persist_turn(
        user["id"],
        thread["id"],
        title="Stored",
        user_content="Explain RAG",
        assistant_content="Canonical stored answer",
        graph_data=graph,
        client_request_id="client-replay-2",
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("an idempotent replay must not call the model")

    monkeypatch.setattr("api.chat_websocket.run_agent", fail_if_called)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Explain RAG",
                    "client_request_id": "client-replay-2",
                }
            )
            events = _receive_until(socket, "done")

    assert events == [
        {"type": "response_delta", "content": "Canonical stored answer"},
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]


def test_internal_eval_websocket_acquires_a_thread_scoped_guard(
    temp_data_dir, monkeypatch
):
    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    user["claims"] = {"app_metadata": {"provider": "internal_test"}}
    observed: dict[str, str | None] = {}
    original_acquire = runtime_state_store.try_acquire_active_stream

    def acquire(*args, **kwargs):
        observed["scope_id"] = kwargs.get("scope_id")
        return original_acquire(*args, **kwargs)

    async def fake_run_agent(state, _rag_tools, _graph_tools, _detail_tools):
        await state["send"]({"type": "response_delta", "content": "ok"})
        await state["send"]({"type": "done"})
        return {**state, "response_text": "ok", "graph_data": None}

    monkeypatch.setattr(runtime_state_store, "try_acquire_active_stream", acquire)
    monkeypatch.setattr("api.chat_websocket.run_agent", fake_run_agent)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "run eval",
                    "client_request_id": "client-eval-scope",
                }
            )
            _receive_until(socket, "done")

    assert observed["scope_id"] == thread["id"]


def test_websocket_keeps_candidate_private_until_browser_evaluation(
    temp_data_dir, monkeypatch
):
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
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design an evaluated architecture",
                    "complexity": "prototype",
                    "graph_mode": "on",
                    "research_enabled": False,
                    "client_request_id": "client-eval-1",
                }
            )
            candidate_events = _receive_until(socket, "graph_candidate")
            assert not any(
                event.get("type") == "graph_data" for event in candidate_events
            )
            candidate = candidate_events[-1]
            assert candidate["criteria"] == {
                "viewport_width": 1440,
                "viewport_height": 960,
                "minimum_text_px": 11.0,
            }
            encoded = base64.b64encode(_png()).decode()
            chunks = [
                encoded[offset : offset + 8_000]
                for offset in range(0, len(encoded), 8_000)
            ]
            socket.send_json(
                {
                    "type": "diagram_evaluation_start",
                    "evaluation_id": candidate["evaluation_id"],
                    "graph_version": "graph-v1",
                    "media_type": "image/png",
                    "total_chunks": len(chunks),
                    "report": _layout_report(),
                }
            )
            for index, data in enumerate(chunks):
                socket.send_json(
                    {
                        "type": "diagram_evaluation_chunk",
                        "evaluation_id": candidate["evaluation_id"],
                        "index": index,
                        "data": data,
                    }
                )
            socket.send_json(
                {
                    "type": "diagram_evaluation_complete",
                    "evaluation_id": candidate["evaluation_id"],
                }
            )
            published = _receive_until(socket, "done")

    preview_index = next(
        index
        for index, event in enumerate(published)
        if event.get("type") == "graph_preview"
    )
    graph_data_index = next(
        index
        for index, event in enumerate(published)
        if event.get("type") == "graph_data"
    )
    assert preview_index < graph_data_index < len(published) - 1
    assert published[graph_data_index]["data"] == graph
    assert any(
        event.get("type") == "response_delta" and event.get("content") == "approved"
        for event in published
    )


def test_websocket_persists_approved_overview_when_explanation_is_unavailable(
    temp_data_dir, monkeypatch
):
    import agent.explanation_blocks as explanation_blocks
    from agent.nodes.orchestrator_node import orchestrator_synthesise
    from adapters.supabase_auth_adapter import get_current_user
    from storage.thread_store import get_graph_artifact

    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: user
    graph = {
        "graph_type": "architecture",
        "design_origin": "applied",
        "version": "approved-overview-v1",
        "detail_level": "overview",
        "title": "Payment overview",
        "nodes": [
            {
                "id": "gateway",
                "label": "Payment gateway",
                "type": "gateway",
                "technology": "HTTP",
                "description": "Accepts payment requests.",
            }
        ],
        "edges": [],
        "sequence": [],
    }
    contract = {
        "graph_version": graph["version"],
        "source": "staged",
        "stage": "accepted",
        "maturity": "prototype",
    }
    provider_calls = []

    async def empty_explanation(**kwargs):
        provider_calls.append(kwargs)
        yield ("text", "")

    async def approved_agent(state, *_tools):
        approved_state = {
            **state,
            "graph_data": graph,
            "graph_contract": contract,
            "graph_changed": True,
            "graph_publication": "approved",
            "graph_operation": {
                "kind": "create",
                "status": "applied",
                "failure_code": None,
            },
        }
        return await orchestrator_synthesise(approved_state)

    monkeypatch.setattr(explanation_blocks, "stream_response", empty_explanation)
    monkeypatch.setattr(chat_websocket, "run_agent", approved_agent)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design a payment request path",
                    "graph_mode": "on",
                    "client_request_id": "approved-overview-explanation-fallback",
                }
            )
            events = _receive_until(socket, "done")

        reloaded = client.get(f"/api/threads/{thread['id']}")

    assert len(provider_calls) == 1
    assert provider_calls[0]["allow_fallback"] is False
    assert provider_calls[0]["provider_attempt_limit"] == 1
    assert events[-2:] == [{"type": "graph_data", "data": graph}, {"type": "done"}]
    assert [event["data"] for event in events if event["type"] == "graph_preview"] == [
        graph
    ]
    assert all("graph_contract" not in event for event in events)
    fallback = next(event for event in events if event["type"] == "explanation_block")
    assert fallback["graph_version"] == graph["version"]
    assert fallback["title"] == "Diagram ready"
    assert fallback["content"].startswith(
        "This is an overview of the core workflow, with supporting detail simplified."
    )
    assert "The diagram is ready to inspect." in fallback["content"]
    assert get_graph_artifact(user["id"], thread["id"]) == (graph, contract)
    assert reloaded.status_code == 200
    assert reloaded.json()["thread"]["graph_data"] == graph
    assert "graph_contract" not in reloaded.json()["thread"]
    assert reloaded.json()["messages"][-1]["content"] == (
        f"## {fallback['title']}\n\n{fallback['content']}"
    )


def test_websocket_persists_approved_overview_after_explanation_provider_error(
    temp_data_dir, monkeypatch
):
    import agent.explanation_blocks as explanation_blocks
    import agent.graph as agent_graph
    from adapters.supabase_auth_adapter import get_current_user
    from storage.thread_store import get_graph_artifact

    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(settings, "graph_pipeline_mode", "staged")
    graph = {
        "graph_type": "architecture",
        "design_origin": "applied",
        "version": "provider-error-approved-v1",
        "detail_level": "overview",
        "title": "Payment overview",
        "nodes": [{"id": "gateway", "label": "Payment gateway"}],
        "edges": [],
        "sequence": [],
    }
    contract = {
        "graph_version": graph["version"],
        "source": "staged",
        "stage": "accepted",
        "maturity": "prototype",
    }
    provider_calls = []

    async def route(state):
        return {**state, "route": "search"}

    async def search(state, _tools):
        return state, None

    async def staged(state):
        return {
            **state,
            "graph_data": graph,
            "graph_contract": contract,
            "graph_changed": True,
            "graph_publication": "approved",
            "graph_operation": {"kind": "create", "status": "applied"},
        }

    async def failed_explanation(**kwargs):
        provider_calls.append(kwargs)
        yield ("text", "")
        raise RuntimeError("explanation provider unavailable")

    monkeypatch.setattr(agent_graph, "orchestrator_route", route)
    monkeypatch.setattr(agent_graph, "run_search_phase", search)
    monkeypatch.setattr(agent_graph, "run_staged_graph_pipeline", staged)
    monkeypatch.setattr(explanation_blocks, "stream_response", failed_explanation)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design a payment request path",
                    "graph_mode": "on",
                    "diagram_requested": True,
                    "client_request_id": "approved-overview-provider-error",
                }
            )
            events = _receive_until(socket, "done")

        reloaded = client.get(f"/api/threads/{thread['id']}")

    assert len(provider_calls) == 1
    assert provider_calls[0]["allow_fallback"] is False
    assert provider_calls[0]["provider_attempt_limit"] == 1
    assert events[-2:] == [{"type": "graph_data", "data": graph}, {"type": "done"}]
    assert [event["data"] for event in events if event["type"] == "graph_preview"] == [
        graph
    ]
    assert [event["data"] for event in events if event["type"] == "graph_data"] == [
        graph
    ]
    assert not any(event["type"] == "error" for event in events)
    assert all("graph_contract" not in event for event in events)
    fallback = next(event for event in events if event["type"] == "explanation_block")
    assert fallback["graph_version"] == graph["version"]
    assert fallback["title"] == "Architecture overview"
    assert fallback["content"].startswith(
        "Your overview is ready, with supporting detail simplified."
    )
    assert get_graph_artifact(user["id"], thread["id"]) == (graph, contract)
    assert reloaded.status_code == 200
    assert reloaded.json()["thread"]["graph_data"] == graph
    assert "graph_contract" not in reloaded.json()["thread"]
    assert reloaded.json()["messages"][-1]["content"] == (
        f"## {fallback['title']}\n\n{fallback['content']}"
    )


@pytest.mark.parametrize(
    ("first_message", "expected_error"),
    [
        ({"type": "start"}, "Authentication must be the first message"),
        ({"type": "auth", "access_token": "rejected"}, "Authentication failed"),
    ],
)
def test_websocket_rejects_invalid_authentication_protocol(
    temp_data_dir,
    monkeypatch,
    first_message,
    expected_error,
):
    app, _user, _thread = _ready_app(temp_data_dir, monkeypatch)
    if first_message["type"] == "auth":

        def reject_auth(*_args, **_kwargs):
            raise HTTPException(status_code=401)

        monkeypatch.setattr("api.chat_websocket.get_current_user", reject_auth)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws",
            headers={"origin": "http://localhost:5173"},
        ) as socket:
            socket.send_json(first_message)
            assert socket.receive_json() == {
                "type": "error",
                "content": expected_error,
            }


@pytest.mark.parametrize(
    ("start_message", "expected_error"),
    [
        ({"type": "unknown"}, "Expected a start message"),
        ({"type": "start", "content": "missing thread"}, "Invalid chat request"),
    ],
)
def test_websocket_rejects_invalid_start_protocol(
    temp_data_dir,
    monkeypatch,
    start_message,
    expected_error,
):
    app, _user, _thread = _ready_app(temp_data_dir, monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws",
            headers={"origin": "http://localhost:5173"},
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(start_message)
            assert socket.receive_json() == {
                "type": "error",
                "content": expected_error,
            }


def test_websocket_rechecks_draft_after_lease_admission(temp_data_dir, monkeypatch):
    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    acquire = runtime_state_store.try_acquire_active_stream

    def admission_after_eviction(user_id, stream_type, **kwargs):
        if stream_type == "chat-thread":
            delete_thread(user_id, thread["id"])
        return acquire(user_id, stream_type, **kwargs)

    async def fail_if_called(*_args, **_kwargs):
        pytest.fail("model work started for a pruned draft")

    monkeypatch.setattr(
        runtime_state_store, "try_acquire_active_stream", admission_after_eviction
    )
    monkeypatch.setattr(chat_websocket, "run_agent", fail_if_called)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Explain agents",
                }
            )
            assert socket.receive_json() == {
                "type": "error",
                "content": "Thread not found",
            }
            assert socket.receive_json() == {"type": "done"}


@pytest.mark.parametrize(
    ("thread_id", "content", "expected_error"),
    [
        ("missing-thread", "hello", "Thread not found"),
        (None, "", "Empty message"),
        (None, "x" * 20, "Message too large"),
    ],
)
def test_websocket_rejects_invalid_turns_before_model_work(
    temp_data_dir,
    monkeypatch,
    thread_id,
    content,
    expected_error,
):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)
    monkeypatch.setattr(settings, "max_message_bytes", 10)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws",
            headers={"origin": "http://localhost:5173"},
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread_id or thread["id"],
                    "content": content,
                    "client_request_id": "client-invalid-turn",
                }
            )
            events = _receive_until(socket, "done")

    assert events[0]["type"] == "error"
    assert expected_error in events[0]["content"]


def test_websocket_reports_an_incomplete_idempotent_turn(temp_data_dir, monkeypatch):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)

    def fail_incomplete(*_args, **_kwargs):
        raise RuntimeError("stored user message has no assistant result")

    monkeypatch.setattr(
        "api.chat_websocket.thread_store.get_completed_turn",
        fail_incomplete,
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws",
            headers={"origin": "http://localhost:5173"},
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "resume request",
                    "client_request_id": "client-incomplete",
                }
            )
            events = _receive_until(socket, "done")

    assert events[0]["type"] == "error"
    assert events[0]["content"].startswith("Previous request is incomplete")
    assert events[1:] == [{"type": "done"}]


@pytest.mark.parametrize(
    ("patch_target", "patch_value", "expected_error"),
    [
        (
            "api.chat_websocket.message_store.count_messages",
            lambda *_args, **_kwargs: settings.max_messages_per_thread,
            "Thread message limit reached",
        ),
        (
            "api.chat_websocket.check_rate_limit",
            lambda *_args, **_kwargs: "Rate limit exceeded",
            "Rate limit exceeded",
        ),
        (
            "api.chat_websocket.knowledge_base_ready",
            lambda *_args, **_kwargs: False,
            "Knowledge base is still loading",
        ),
        (
            "api.chat_websocket.check_prompt_injection",
            lambda *_args, **_kwargs: False,
            "Message blocked by security filter",
        ),
    ],
)
def test_websocket_preflight_failures_do_not_start_model_work(
    temp_data_dir,
    monkeypatch,
    patch_target,
    patch_value,
    expected_error,
):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)
    monkeypatch.setattr(patch_target, patch_value)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws",
            headers={"origin": "http://localhost:5173"},
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "bounded request",
                    "client_request_id": "client-preflight",
                }
            )
            events = _receive_until(socket, "done")

    assert events[0]["type"] == "error"
    assert expected_error in events[0]["content"]


def test_websocket_rejects_commands_then_stops_matching_work(
    temp_data_dir, monkeypatch
):
    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)

    async def blocked_agent(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr("api.chat_websocket.run_agent", blocked_agent)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws",
            headers={"origin": "http://localhost:5173"},
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "long architecture review",
                    "client_request_id": "client-command",
                }
            )
            _receive_until(socket, "worker_status")

            socket.send_json({"type": "unknown"})
            assert socket.receive_json() == {
                "type": "command_rejected",
                "reason": "Unknown command",
            }
            socket.send_json(
                {
                    "type": "steer",
                    "content": "wrong request",
                    "client_request_id": "other-request",
                }
            )
            assert socket.receive_json() == {
                "type": "command_rejected",
                "reason": "Command does not match the active request",
            }
            socket.send_json(
                {
                    "type": "steer",
                    "content": "   ",
                    "client_request_id": "client-command",
                }
            )
            assert socket.receive_json() == {
                "type": "command_rejected",
                "reason": "Steering command was empty, unsafe, too large, or over the limit",
            }
            socket.send_json(
                {
                    "type": "stop",
                    "client_request_id": "client-command",
                }
            )
            assert socket.receive_json() == {"type": "stopped"}


def test_websocket_frame_and_origin_boundaries(monkeypatch):
    class FakeSocket:
        def __init__(self, value):
            self.value = value

        async def receive_text(self):
            return self.value

    assert asyncio.run(_receive_object(FakeSocket('{"type":"auth"}'))) == {
        "type": "auth"
    }
    with pytest.raises(ValueError, match="must be an object"):
        asyncio.run(_receive_object(FakeSocket("[]")))
    with pytest.raises(ValueError, match="frame too large"):
        asyncio.run(_receive_object(FakeSocket("x" * 16_385)))

    assert _origin_allowed(None) is True
    assert _origin_allowed("http://localhost:5173") is True
    monkeypatch.setattr(settings, "vercel_origin_regex", "[")
    assert _origin_allowed("https://preview.example") is False


def test_websocket_rechecks_completed_turn_after_thread_admission(
    temp_data_dir, monkeypatch
):
    from adapters.database_adapter import fetchone
    from storage import thread_store

    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    canonical = {"version": "persisted-v1", "nodes": [], "edges": []}
    original_acquire = runtime_state_store.try_acquire_active_stream

    def acquire_after_commit(*args, **kwargs):
        if args[1] == "chat-thread":
            persist_turn(
                user["id"],
                thread["id"],
                title="Stored",
                user_content="Build an agent",
                assistant_content="Canonical answer",
                graph_data=canonical,
                client_request_id="admission-race",
            )
        return original_acquire(*args, **kwargs)

    async def unexpected_model(*_args):
        pytest.fail("completed request must replay before running the model")

    monkeypatch.setattr(
        runtime_state_store, "try_acquire_active_stream", acquire_after_commit
    )
    monkeypatch.setattr(chat_websocket, "run_agent", unexpected_model)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Build an agent",
                    "client_request_id": "admission-race",
                }
            )
            events = _receive_until(socket, "done")
    assert events == [
        {"type": "response_delta", "content": "Canonical answer"},
        {"type": "graph_data", "data": canonical},
        {"type": "done"},
    ]
    assert thread_store.get_graph(user["id"], thread["id"]) == canonical
    assert len(get_history(user["id"], thread["id"])) == 2
    assert fetchone("SELECT COUNT(*) AS n FROM active_streams")["n"] == 0


@pytest.mark.parametrize("secondary_transport", ["websocket", "sse"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_chat_thread_serialization_allows_other_threads_with_user_capacity(
    temp_data_dir, monkeypatch, secondary_transport, duplicate
):
    from adapters.database_adapter import fetchone
    from adapters.supabase_auth_adapter import get_current_user
    from test_api_security import _parse_sse_events

    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    other_thread = create_thread(user["id"])
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(settings, "max_active_chat_streams_per_user", 3)
    calls = []

    async def blocking_agent(state, *_tools):
        calls.append(state["session_id"])
        await state["send"]({"type": "response_delta", "content": "running"})
        await asyncio.Event().wait()

    monkeypatch.setattr(chat_websocket, "run_agent", blocking_agent)
    monkeypatch.setattr("api.sse_handler.run_agent", blocking_agent)
    headers = {"origin": "http://localhost:5173"}
    with TestClient(app) as client:
        with client.websocket_connect("/api/chat/ws", headers=headers) as first:
            first.send_json({"type": "auth", "access_token": "test-token"})
            assert first.receive_json() == {"type": "ready"}
            first.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Build an agent",
                    "client_request_id": "first",
                }
            )
            _receive_until(first, "response_delta")
            body = {
                "thread_id": thread["id"],
                "content": "Build an agent",
                "client_request_id": "first" if duplicate else "second",
            }
            if secondary_transport == "websocket":
                with client.websocket_connect(
                    "/api/chat/ws", headers=headers
                ) as second:
                    second.send_json({"type": "auth", "access_token": "test-token"})
                    assert second.receive_json() == {"type": "ready"}
                    second.send_json({"type": "start", **body})
                    rejected = _receive_until(second, "done")
            else:
                rejected = _parse_sse_events(client.post("/api/chat", json=body).text)
            assert rejected[0]["type"] == "error"
            assert "already running" in rejected[0]["content"]
            assert calls == [thread["id"]]
            with client.websocket_connect("/api/chat/ws", headers=headers) as other:
                other.send_json({"type": "auth", "access_token": "test-token"})
                assert other.receive_json() == {"type": "ready"}
                other.send_json(
                    {
                        "type": "start",
                        "thread_id": other_thread["id"],
                        "content": "Build a different agent",
                        "client_request_id": "other",
                    }
                )
                _receive_until(other, "response_delta")
                assert calls == [thread["id"], other_thread["id"]]
                other.send_json({"type": "stop", "client_request_id": "other"})
                _receive_until(other, "stopped")
            first.send_json({"type": "stop", "client_request_id": "first"})
            _receive_until(first, "stopped")
    assert fetchone("SELECT COUNT(*) AS n FROM active_streams")["n"] == 0


def test_websocket_releases_both_leases_on_setup_failure(temp_data_dir, monkeypatch):
    from adapters.database_adapter import fetchone

    app, _user, thread = _ready_app(temp_data_dir, monkeypatch)

    def failed_setup(*_args):
        raise RuntimeError("setup failed")

    monkeypatch.setattr(chat_websocket, "_make_agent_tools", failed_setup)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Build an agent",
                }
            )
            assert _receive_until(socket, "done")[0]["type"] == "error"
    assert fetchone("SELECT COUNT(*) AS n FROM active_streams")["n"] == 0


@pytest.mark.asyncio
async def test_outer_cancellation_cleanup_failure_releases_leases(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    ws = chat_websocket
    started = asyncio.Event()
    acquired, released = [], []
    user = {"id": "user", "email": "user@example.com"}
    monkeypatch.setattr(ws, "_origin_allowed", lambda origin: True)
    monkeypatch.setattr(ws, "get_current_user", lambda **kw: user)
    monkeypatch.setattr(ws, "upsert_profile", lambda *a: None)
    monkeypatch.setattr(ws.thread_store, "get_thread", lambda *a: {"title": "New chat"})
    monkeypatch.setattr(ws.thread_store, "get_completed_turn", lambda *a: None)
    monkeypatch.setattr(ws.thread_store, "get_graph_artifact", lambda *a: (None, None))
    monkeypatch.setattr(ws.message_store, "get_history", lambda *a, **kw: [])
    monkeypatch.setattr(ws, "_request_error", lambda *a: None)
    monkeypatch.setattr(ws, "_new_turn_preflight_error", lambda *a: None)
    monkeypatch.setattr(ws, "_make_agent_tools", lambda *a: (None, None, None))
    monkeypatch.setattr(ws, "enqueue_analytics_event", lambda **kw: None)
    metric_changes = []
    monkeypatch.setattr(ws, "change_active_chat_streams", metric_changes.append)
    monkeypatch.setattr(ws, "record_agent_duration", lambda *a, **kw: None)

    def acquire(*args, **kw):
        acquired.append(args[1])
        return args[1]

    monkeypatch.setattr(ws.runtime_state_store, "try_acquire_active_stream", acquire)
    monkeypatch.setattr(
        ws.runtime_state_store, "release_active_stream", released.append
    )

    async def agent(*args):
        started.set()
        try:
            await asyncio.Future()
        finally:
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(ws, "run_agent", agent)
    socket = SimpleNamespace(
        headers={}, accept=AsyncMock(), close=AsyncMock(), send_json=AsyncMock()
    )
    incoming = iter(
        [
            {"type": "auth", "access_token": "test"},
            {
                "type": "start",
                "thread_id": "thread",
                "content": "hello",
                "client_request_id": "request",
            },
        ]
    )

    async def receive(*args):
        try:
            return next(incoming)
        except StopIteration:
            await asyncio.Future()

    monkeypatch.setattr(ws, "_receive_object", receive)
    task = asyncio.create_task(ws.chat_websocket(socket))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await task
    assert acquired == ["chat", "chat-thread"]
    assert released == ["chat-thread", "chat"]
    assert metric_changes == [1, -1]
    socket.close.assert_awaited_once()
