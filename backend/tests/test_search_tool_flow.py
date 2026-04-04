import asyncio

import pytest
from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from main import create_app
from storage.profile_store import upsert_profile
from storage.runtime_state_store import create_search_tool_request, is_search_tool_requested
from storage.thread_store import create_thread


def _authed_app():
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1", "email": "friend@example.com"}
    return app


def test_rag_worker_marks_empty_results_as_weak():
    from agent.nodes.rag_worker import _assess_retrieval_relevance

    relevance, notice = _assess_retrieval_relevance("How do I deploy a customer service graph database?", [])

    assert relevance == "weak"
    assert "search tool" in notice.lower() or "web search" in notice.lower()


def test_use_search_tool_endpoint_marks_request_in_runtime_store(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    app = _authed_app()
    request_id = "req-123"
    create_search_tool_request(
        request_id,
        "user-1",
        thread["id"],
        expires_at_epoch=10**12,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/use-search-tool",
            json={"thread_id": thread["id"], "request_id": request_id},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert is_search_tool_requested(request_id, "user-1", thread["id"]) is True


@pytest.mark.asyncio
async def test_run_agent_uses_search_tool_after_weak_retrieval(monkeypatch):
    import agent.graph as agent_graph

    events = []
    graph_calls = []

    async def send(event):
        events.append(event)

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search_phase(state, rag_tools):
        async def wait_task():
            return True

        updated_state = {
            **state,
            "rag_chunks": [],
            "retrieval_relevance": "weak",
            "retrieval_notice": "Book retrieval is weak. Use search tool?",
        }
        await send({
            "type": "retrieval_notice",
            "request_id": updated_state["request_id"],
            "message": updated_state["retrieval_notice"],
        })
        return updated_state, asyncio.create_task(wait_task())

    async def fake_apply_graph(state, graph_tools):
        graph_calls.append(state.get("research_context", ""))
        if state.get("research_context"):
            return {**state, "graph_data": {"title": "Researched graph", "nodes": [], "edges": [], "sequence": []}}
        return {**state, "graph_data": {"title": "Book-only graph", "nodes": [], "edges": [], "sequence": []}}

    async def fake_expand_with_search(state, graph_tools, search_tool_wait_task):
        assert await search_tool_wait_task is True
        await send({"type": "worker_status", "worker": "research", "status": "Searching the web…"})
        expanded = {**state, "research_context": "- [example.com] External support"}
        return await fake_apply_graph(expanded, graph_tools)

    async def fake_synth(state):
        await send({"type": "done"})
        return {**state, "response_text": "answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search_phase)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand_with_search)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    state = {
        "session_id": "thread-1",
        "user_id": "user-1",
        "user_email": "friend@example.com",
        "request_id": "req-1",
        "user_message": "Need broader context",
        "history": [],
        "complexity": "auto",
        "graph_mode": "auto",
        "research_enabled": False,
        "route": "",
        "rag_chunks": [],
        "retrieval_relevance": "strong",
        "retrieval_notice": "",
        "graph_data": None,
        "graph_changed": False,
        "research_context": "",
        "response_text": "",
        "send": send,
        "await_search_tool_request": lambda *_args, **_kwargs: None,
    }

    result = await agent_graph.run_agent(state, rag_tools=[], graph_tools=[], node_detail_tools=[])

    assert any(event.get("type") == "retrieval_notice" for event in events)
    assert any(
        event.get("type") == "worker_status" and event.get("worker") == "research"
        for event in events
    )
    assert graph_calls == ["", "- [example.com] External support"]
    assert result["research_context"] == "- [example.com] External support"
    assert result["graph_data"]["title"] == "Researched graph"


@pytest.mark.asyncio
async def test_run_agent_warns_when_it_can_answer_but_cannot_build_graph(monkeypatch):
    import agent.graph as agent_graph

    events = []

    async def send(event):
        events.append(event)

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search_phase(state, rag_tools):
        return {
            **state,
            "rag_chunks": [{"text": "Agents use tools and planning logic.", "chapter": 10, "page_number": 473}],
            "retrieval_relevance": "strong",
            "retrieval_notice": "",
        }, None

    async def fake_apply_graph(state, graph_tools):
        if state.get("graph_data") is None and not state.get("research_context"):
            await send({
                "type": "graph_notice",
                "message": "I found enough related material to explain this, but not enough grounded detail from the book to draw a trustworthy graph for this exact question.",
            })
            return {**state, "graph_data": None, "graph_notice_sent": True}
        return {**state, "graph_data": None}

    async def fake_synth(state):
        await send({"type": "response_delta", "content": "Answer"})
        await send({"type": "done"})
        return {**state, "response_text": "Answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search_phase)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    state = {
        "session_id": "thread-1",
        "user_id": "user-1",
        "user_email": "friend@example.com",
        "request_id": "req-1",
        "user_message": "What is Amazon AgentCore and how can we build one with open source code?",
        "history": [],
        "complexity": "auto",
        "graph_mode": "auto",
        "research_enabled": False,
        "route": "",
        "rag_chunks": [],
        "retrieval_relevance": "strong",
        "retrieval_notice": "",
        "graph_data": None,
        "graph_changed": False,
        "graph_notice_sent": False,
        "research_context": "",
        "response_text": "",
        "send": send,
        "await_search_tool_request": lambda *_args, **_kwargs: None,
    }

    result = await agent_graph.run_agent(state, rag_tools=[], graph_tools=[], node_detail_tools=[])

    assert any(event.get("type") == "graph_notice" for event in events)
    assert result["graph_data"] is None
    assert result["graph_notice_sent"] is True
