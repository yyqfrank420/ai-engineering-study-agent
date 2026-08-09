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


def test_failed_review_gets_at_most_two_bounded_revisions():
    from agent.graph import _route_after_review, _route_after_revision

    failed = {
        "graph_changed": True,
        "graph_data": {"design_origin": "applied"},
        "graph_review": {"approved": False},
    }

    assert _route_after_review({**failed, "graph_revision_count": 0}) == "revise"
    assert _route_after_review({**failed, "graph_revision_count": 1}) == "revise"
    assert _route_after_review({**failed, "graph_revision_count": 2}) == "reject"
    assert _route_after_review({
        **failed,
        "graph_revision_count": 0,
        "graph_review": {"approved": False, "terminal": True},
    }) == "reject"
    assert _route_after_revision({**failed, "graph_changed": True}) == "review"
    assert _route_after_revision({**failed, "graph_changed": False}) == "reject"


@pytest.mark.asyncio
async def test_langgraph_can_verify_two_bounded_repairs_then_publish(monkeypatch):
    import asyncio
    import agent.graph as agent_graph

    events = []
    reviews = []
    role_order = []
    architect_started = asyncio.Event()
    challenger_started = asyncio.Event()

    async def send(event):
        events.append(event)

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_apply(state, _tools):
        assert state["architect_plan"]["interpretation"] == "growth system"
        assert state["challenger_review"] == {"risks": []}
        revision_count = state.get("graph_revision_count", 0)
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": (
                    "First draft"
                    if revision_count == 0
                    else f"Repair {revision_count}"
                ),
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
        }

    async def fake_architect(state):
        architect_started.set()
        await asyncio.wait_for(challenger_started.wait(), timeout=1)
        role_order.append("architect")
        return {
            "architect_plan": {
                "interpretation": "growth system",
                "assumptions": ["Channel APIs support bounded writes"],
            }
        }

    async def fake_challenger(state):
        challenger_started.set()
        await asyncio.wait_for(architect_started.wait(), timeout=1)
        role_order.append("challenger")
        return {"challenger_review": {"risks": []}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_review(state):
        reviews.append(state["graph_data"]["title"])
        if state.get("graph_revision_count") == 2:
            return {
                **state,
                "graph_review": {"approved": True, "score": 0.9, "missing": []},
            }
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

    assert reviews == ["First draft", "Repair 1", "Repair 2"]
    assert result["graph_revision_count"] == 2
    assert result["graph_data"]["title"] == "Repair 2"
    assert result["graph_notice_sent"] is False
    assert result["response_text"] == "reviewed answer"
    assert set(role_order) == {"architect", "challenger"}
    assert any(event.get("phase") == "revise" and event.get("status") == "retry" for event in events)
    assert not any(event.get("type") == "graph_notice" for event in events)


@pytest.mark.asyncio
async def test_langgraph_does_not_emit_graph_notice_on_failed_graph_notice_mode(monkeypatch):
    import agent.graph as agent_graph

    events: list[dict] = []

    async def send(event):
        events.append(event)

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return {
            **state,
            "rag_chunks": [],
            "retrieval_relevance": "strong",
            "retrieval_notice": "",
        }, None

    async def fake_apply_graph(state, _tools):
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
        }

    async def fake_review(state):
        return {**state, "graph_review": {"approved": False, "terminal": True}}

    async def fake_synth(state):
        return {**state, "response_text": "ok"}

    async def fake_enrich(_state, _tools):
        return None

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", lambda state, *_: state)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    monkeypatch.setattr(agent_graph, "maybe_start_node_enrichment", fake_enrich)

    state = _state(send)
    state["graph_mode"] = "on"

    result = await agent_graph.run_agent(state, [], [], [])

    assert result["graph_data"] is None
    assert not any(event.get("type") == "graph_notice" for event in events)
