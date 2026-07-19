import asyncio

import pytest


def _state(send):
    return {
        "session_id": "thread-1",
        "user_id": "user-1",
        "user_email": "friend@example.com",
        "request_id": "req-1",
        "client_request_id": "client-1",
        "user_message": "Design a growth marketing agent system",
        "history": [],
        "complexity": "prototype",
        "graph_mode": "on",
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


def test_graph_off_skips_paid_applied_design_roles():
    from agent.graph import _should_run_applied_design_roles

    state = {
        "graph_mode": "off",
        "user_message": "Design a growth marketing agent system",
    }

    assert _should_run_applied_design_roles(state) is False


@pytest.mark.asyncio
async def test_langgraph_rejects_a_failed_review_without_a_paid_revision(monkeypatch):
    import agent.graph as agent_graph

    events = []
    reviews = []
    parallel_roles = set()
    both_roles_started = asyncio.Event()

    async def send(event):
        events.append(event)

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_apply(state, _tools):
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": "First draft",
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
        }

    async def fake_architect(state):
        parallel_roles.add("architect")
        if len(parallel_roles) == 2:
            both_roles_started.set()
        await asyncio.wait_for(both_roles_started.wait(), timeout=1)
        return {"architect_plan": {"interpretation": "growth system"}}

    async def fake_challenger(state):
        parallel_roles.add("challenger")
        if len(parallel_roles) == 2:
            both_roles_started.set()
        await asyncio.wait_for(both_roles_started.wait(), timeout=1)
        return {"challenger_review": {"risks": []}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_review(state):
        reviews.append(state["graph_data"]["title"])
        return {
            **state,
            "graph_review": {
                "approved": False,
                "score": 0.4,
                "missing": ["Missing approval boundary"],
                "revision_instruction": "Add a concrete approval boundary",
            },
        }

    async def fake_synth(state):
        return {**state, "response_text": "reviewed answer"}

    async def fake_enrich(_state, _tools):
        return None

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    monkeypatch.setattr(agent_graph, "maybe_start_node_enrichment", fake_enrich)

    result = await agent_graph.run_agent(_state(send), [], [], [])

    assert reviews == ["First draft"]
    assert result["graph_revision_count"] == 0
    assert result["graph_data"] is None
    assert result["graph_notice_sent"] is True
    assert result["response_text"] == "reviewed answer"
    assert parallel_roles == {"architect", "challenger"}
    assert any(event.get("type") == "graph_notice" for event in events)
