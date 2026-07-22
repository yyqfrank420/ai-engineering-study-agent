import asyncio

import pytest

from agent.pipeline_steps import (
    apply_graph_worker,
    maybe_expand_with_search_tool,
    maybe_start_node_enrichment,
    run_parallel_research_phase,
    run_search_phase,
    should_run_graph_worker,
)
from config import settings


def _state(**overrides):
    events = []

    async def send(event):
        events.append(event)

    async def await_search_tool_request(_request_id, _timeout_s):
        return False

    state = {
        "route": "search",
        "graph_mode": "auto",
        "graph_data": None,
        "graph_changed": False,
        "graph_notice_sent": False,
        "user_message": "How do agents use tools?",
        "user_id": "user-1",
        "session_id": "thread-1",
        "request_id": "req-1",
        "send": send,
        "await_search_tool_request": await_search_tool_request,
        "rag_chunks": [],
        "retrieval_relevance": "strong",
        "retrieval_notice": "",
        "research_context": "",
    }
    state.update(overrides)
    return state, events


def test_should_run_graph_worker_modes():
    assert should_run_graph_worker({"graph_mode": "off", "route": "search"}, None) is False
    assert should_run_graph_worker({"graph_mode": "on", "route": "chat"}, {"nodes": []}) is True
    assert should_run_graph_worker({"graph_mode": "auto", "route": "search"}, {"nodes": []}) is True
    assert should_run_graph_worker({"graph_mode": "auto", "route": "chat"}, None) is True
    assert should_run_graph_worker({"graph_mode": "auto", "route": "chat"}, {"nodes": []}) is False


@pytest.mark.asyncio
async def test_apply_graph_worker_preserves_existing_graph_when_worker_returns_none(monkeypatch):
    existing_graph = {"nodes": [{"id": "n1"}], "edges": []}
    state, events = _state(graph_data=existing_graph)

    async def fake_graph_worker_node(incoming_state, tools):
        assert tools == ["graph-tool"]
        return {**incoming_state, "graph_data": None}

    monkeypatch.setattr("agent.pipeline_steps.graph_worker_node", fake_graph_worker_node)

    result = await apply_graph_worker(state, ["graph-tool"])

    assert result["graph_data"] == existing_graph
    assert result["graph_changed"] is False
    assert events == []


@pytest.mark.asyncio
async def test_apply_graph_worker_treats_version_only_reuse_as_unchanged(monkeypatch):
    existing_graph = {
        "version": "approved-v1",
        "nodes": [{"id": "n1"}],
        "edges": [],
        "sequence": [],
    }
    state, _events = _state(graph_data=existing_graph)

    async def fake_graph_worker_node(incoming_state, _tools):
        return {
            **incoming_state,
            "graph_data": {**existing_graph, "version": "generated-v2"},
        }

    monkeypatch.setattr("agent.pipeline_steps.graph_worker_node", fake_graph_worker_node)

    result = await apply_graph_worker(state, [])

    assert result["graph_data"] is existing_graph
    assert result["graph_changed"] is False


@pytest.mark.asyncio
async def test_apply_graph_worker_sends_notice_when_search_has_no_graph(monkeypatch):
    state, events = _state(graph_data=None, route="search", graph_notice_sent=False)

    async def fake_graph_worker_node(incoming_state, tools):
        return {**incoming_state, "graph_data": None}

    monkeypatch.setattr("agent.pipeline_steps.graph_worker_node", fake_graph_worker_node)

    result = await apply_graph_worker(state, [])

    assert result["graph_data"] is None
    assert result["graph_changed"] is False
    assert result["graph_notice_sent"] is True
    assert events[0]["type"] == "graph_notice"


@pytest.mark.asyncio
async def test_applied_graph_failure_notice_does_not_misreport_weak_grounding(monkeypatch):
    state, events = _state(
        graph_data=None,
        route="search",
        graph_notice_sent=False,
        is_applied_design=True,
    )

    async def fake_graph_worker_node(incoming_state, _tools):
        return {**incoming_state, "graph_data": None}

    monkeypatch.setattr("agent.pipeline_steps.graph_worker_node", fake_graph_worker_node)

    result = await apply_graph_worker(state, [])

    assert result["graph_notice_sent"] is True
    assert "structural quality checks" in events[0]["message"]
    assert "grounded detail from the book" not in events[0]["message"]


@pytest.mark.asyncio
async def test_run_search_phase_emits_notice_and_starts_wait_task(monkeypatch):
    monkeypatch.setattr(settings, "search_tool_decision_timeout_s", 0.25)
    wait_calls = []

    async def await_search_tool_request(request_id, timeout_s):
        wait_calls.append((request_id, timeout_s))
        return True

    state, events = _state(await_search_tool_request=await_search_tool_request)

    async def fake_rag_worker_node(incoming_state, tools):
        assert tools == ["rag-tool"]
        return {
            **incoming_state,
            "rag_chunks": [{"text": "indirect"}],
            "retrieval_relevance": "weak",
            "retrieval_notice": "Use search?",
        }

    monkeypatch.setattr("agent.pipeline_steps.rag_worker_node", fake_rag_worker_node)

    result, wait_task = await run_search_phase(state, ["rag-tool"])
    assert result["rag_chunks"] == [{"text": "indirect"}]
    assert result["retrieval_relevance"] == "weak"
    assert events == [{"type": "retrieval_notice", "request_id": "req-1", "message": "Use search?"}]
    assert wait_task is not None
    assert await wait_task is True
    assert wait_calls == [("req-1", 0.25)]


@pytest.mark.asyncio
async def test_run_search_phase_skips_when_route_is_not_search(monkeypatch):
    state, _events = _state(route="chat", graph_mode="auto")

    async def should_not_call(*_args, **_kwargs):
        raise AssertionError("rag worker should not run")

    monkeypatch.setattr("agent.pipeline_steps.rag_worker_node", should_not_call)

    result, wait_task = await run_search_phase(state, [])

    assert result is state
    assert wait_task is None


@pytest.mark.asyncio
async def test_parallel_research_phase_merges_rag_and_research(monkeypatch):
    state, _events = _state()

    async def fake_rag_worker_node(incoming_state, tools):
        await asyncio.sleep(0)
        return {
            **incoming_state,
            "rag_chunks": [{"text": "book"}],
            "retrieval_relevance": "strong",
            "retrieval_notice": "",
        }

    async def fake_research_worker_node(incoming_state):
        await asyncio.sleep(0)
        return {**incoming_state, "research_context": "- source", "research_status": "ready"}

    monkeypatch.setattr("agent.pipeline_steps.rag_worker_node", fake_rag_worker_node)
    monkeypatch.setattr("agent.pipeline_steps.research_worker_node", fake_research_worker_node)

    result = await run_parallel_research_phase(state, ["rag-tool"])

    assert result["rag_chunks"] == [{"text": "book"}]
    assert result["research_context"] == "- source"
    assert result["research_status"] == "ready"


@pytest.mark.asyncio
async def test_maybe_expand_with_search_tool_rebuilds_canonical_evidence_before_design(monkeypatch):
    state, _events = _state()

    async def fake_research_worker_node(incoming_state):
        return {**incoming_state, "research_context": "- external", "research_status": "ready"}

    monkeypatch.setattr("agent.pipeline_steps.research_worker_node", fake_research_worker_node)

    result = await maybe_expand_with_search_tool(state, ["graph-tool"], asyncio.create_task(asyncio.sleep(0, True)))

    assert result["research_context"] == "- external"
    assert result["research_status"] == "ready"
    assert result["evidence_bundle"]["research_context"] == "- external"
    assert result["graph_data"] is None


@pytest.mark.asyncio
async def test_maybe_expand_with_search_tool_skips_when_user_declines():
    state, _events = _state()

    result = await maybe_expand_with_search_tool(
        state,
        ["graph-tool"],
        asyncio.create_task(asyncio.sleep(0, False)),
    )

    assert result is state


@pytest.mark.asyncio
async def test_node_enrichment_requires_graph_and_tool(monkeypatch):
    state, events = _state(graph_data={"version": 3, "nodes": [{"id": "n1"}], "edges": [{"source": "n1", "target": "n2"}]})
    calls = []

    async def fake_enrich_all_nodes(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("agent.pipeline_steps.enrich_all_nodes", fake_enrich_all_nodes)

    await maybe_start_node_enrichment(state, ["rag-search"])

    assert calls[0]["nodes"] == [{"id": "n1"}]
    assert calls[0]["edges"] == [{"source": "n1", "target": "n2"}]
    assert calls[0]["rag_search_tool"] == "rag-search"
    assert calls[0]["send"] is state["send"]
    assert calls[0]["graph_version"] == 3
    assert calls[0]["user_id"] == state["user_id"]
    assert calls[0]["thread_id"] == state["session_id"]
    assert events == []
