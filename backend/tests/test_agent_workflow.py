import pytest
import time


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


def test_failed_review_gets_at_most_three_bounded_revisions():
    from agent.graph import _repair_attempt_summary, _route_after_review, _route_after_revision

    assert _repair_attempt_summary(0) == "before a focused repair could complete"
    assert _repair_attempt_summary(1) == "after 1 focused repair"
    assert _repair_attempt_summary(3) == "after 3 focused repairs"

    failed = {
        "graph_changed": True,
        "graph_data": {"design_origin": "applied"},
        "graph_review": {"approved": False},
    }

    assert _route_after_review({**failed, "graph_revision_count": 0}) == "revise"
    assert _route_after_review({**failed, "graph_revision_count": 1}) == "revise"
    assert _route_after_review({**failed, "graph_revision_count": 2}) == "revise"
    assert _route_after_review({**failed, "graph_revision_count": 3}) == "reject"
    assert _route_after_review({
        **failed,
        "graph_revision_count": 0,
        "graph_review": {"approved": False, "terminal": True},
    }) == "reject"
    assert _route_after_revision({**failed, "graph_changed": True}) == "review"
    assert _route_after_revision({**failed, "graph_changed": False}) == "reject"


def test_patch_admission_requires_patch_critic_and_synthesis_reserve():
    from agent.deadlines import StageAdmissionDenied, patch_timeout_seconds
    from config import settings

    following_reserve_s = (
        settings.graph_critic_revision_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    required_s = settings.graph_patch_timeout_s + following_reserve_s

    with pytest.raises(StageAdmissionDenied):
        patch_timeout_seconds({
            "terminal_deadline_s": time.monotonic() + required_s - 1,
        })

    timeout_s = patch_timeout_seconds({
        "terminal_deadline_s": time.monotonic() + required_s + 5,
    })
    assert 0 < timeout_s <= settings.graph_patch_timeout_s


def test_one_repair_path_stage_caps_fit_terminal_window():
    from config import settings

    stage_caps_s = (
        settings.graph_design_timeout_s
        + settings.graph_critic_initial_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_revision_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert stage_caps_s <= terminal_window_s


def test_rejected_candidate_restores_immutable_approved_graph_baseline():
    from agent.graph import _restore_approved_graph_state

    approved = {"title": "Approved", "nodes": [], "edges": [], "sequence": []}
    rejected = {"title": "Rejected", "nodes": [], "edges": [], "sequence": []}
    restored = _restore_approved_graph_state({
        "approved_graph_data": approved,
        "graph_data": rejected,
        "graph_changed": True,
    })

    assert restored["graph_data"] == approved
    assert restored["graph_data"] is not approved
    assert restored["graph_changed"] is False


@pytest.mark.asyncio
async def test_langgraph_can_verify_three_bounded_repairs_then_publish(monkeypatch):
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
        assert state["_graph_stage_deadline_s"] > time.monotonic()
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
        assert state["_graph_stage_deadline_s"] > time.monotonic()
        reviews.append(state["graph_data"]["title"])
        if state.get("graph_revision_count") == 3:
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

    assert reviews == ["First draft", "Repair 1", "Repair 2", "Repair 3"]
    assert result["graph_revision_count"] == 3
    assert result["graph_data"]["title"] == "Repair 3"
    assert result["graph_notice_sent"] is False
    assert result["response_text"] == "reviewed answer"
    assert set(role_order) == {"architect", "challenger"}
    repair_events = [
        event
        for event in events
        if event.get("phase") == "revise" and event.get("status") == "retry"
    ]
    assert [event["detail"].split(",", 1)[0] for event in repair_events] == [
        "Applying bounded clarity repair 1 of 3",
        "Applying bounded clarity repair 2 of 3",
        "Applying bounded clarity repair 3 of 3",
    ]
    assert not any(event.get("type") == "graph_notice" for event in events)
