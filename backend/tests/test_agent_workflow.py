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


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Fix the typo in the cache label", False),
        ("Replace the current diagram", False),
        ("Design a fraud detection system", True),
        ("Explain RAG", False),
    ],
)
def test_architecture_roles_follow_graph_request_intent(message, expected):
    from agent.graph import _should_run_applied_design_roles

    state = {
        "graph_mode": "auto",
        "user_message": message,
        "design_query": message,
        "graph_data": {
            "design_origin": "applied",
            "nodes": [{"id": "cache", "label": "Cache"}],
        },
    }

    assert _should_run_applied_design_roles(state) is expected


def test_failed_review_gets_at_most_one_bounded_revision():
    from agent.graph import (
        _repair_attempt_summary,
        _route_after_review,
        _route_after_revision,
    )

    assert _repair_attempt_summary(0) == "before a reviewed revision could complete"
    assert _repair_attempt_summary(1) == "after 1 reviewed revision"
    assert _repair_attempt_summary(3) == "after 3 reviewed revisions"

    failed = {
        "graph_changed": True,
        "graph_data": {"design_origin": "applied"},
        "graph_review": {"approved": False},
    }

    assert _route_after_review({**failed, "graph_revision_count": 0}) == "revise"
    assert _route_after_review({**failed, "graph_revision_count": 1}) == "reject"
    assert (
        _route_after_review(
            {
                **failed,
                "graph_revision_count": 0,
                "graph_review": {"approved": False, "terminal": True},
            }
        )
        == "reject"
    )
    assert _route_after_revision({**failed, "graph_changed": True}) == "review"
    assert _route_after_revision({**failed, "graph_changed": False}) == "reject"


def test_patch_admission_uses_available_time_after_following_reserve():
    from agent.deadlines import StageAdmissionDenied, patch_timeout_seconds
    from config import settings

    following_reserve_s = (
        settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    with pytest.raises(StageAdmissionDenied):
        patch_timeout_seconds(
            {
                "terminal_deadline_s": time.monotonic() + following_reserve_s - 1,
            }
        )

    timeout_s = patch_timeout_seconds(
        {
            "terminal_deadline_s": time.monotonic() + following_reserve_s + 10,
        }
    )
    assert 0 < timeout_s <= 10

    full_timeout_s = patch_timeout_seconds(
        {
            "terminal_deadline_s": (
                time.monotonic()
                + following_reserve_s
                + settings.graph_patch_timeout_s
                + 5
            ),
        }
    )
    assert full_timeout_s == pytest.approx(settings.graph_patch_timeout_s + 5)

    max_timeout_s = patch_timeout_seconds(
        {
            "terminal_deadline_s": (
                time.monotonic()
                + following_reserve_s
                + settings.graph_builder_max_timeout_s
                + 5
            ),
        }
    )
    assert max_timeout_s == settings.graph_builder_max_timeout_s


def test_architecture_admission_preserves_the_complete_downstream_path():
    from agent.deadlines import (
        StageAdmissionDenied,
        architecture_timeout_seconds,
    )
    from config import settings

    downstream_reserve_s = (
        settings.architecture_role_timeout_s
        + settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    with pytest.raises(StageAdmissionDenied):
        architecture_timeout_seconds(
            {"terminal_deadline_s": time.monotonic() + downstream_reserve_s - 1},
            review=False,
        )

    timeout_s = architecture_timeout_seconds(
        {"terminal_deadline_s": time.monotonic() + downstream_reserve_s + 10},
        review=False,
    )
    assert 0 < timeout_s <= 10


def test_initial_design_and_review_preserve_the_complete_patch_path():
    from agent.deadlines import (
        StageAdmissionDenied,
        critic_timeout_seconds,
        design_timeout_seconds,
    )
    from config import settings

    after_initial_design_s = (
        settings.graph_critic_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    with pytest.raises(StageAdmissionDenied):
        design_timeout_seconds(
            {
                "terminal_deadline_s": time.monotonic() + after_initial_design_s - 1,
            }
        )

    borrowed_timeout_s = design_timeout_seconds(
        {
            "terminal_deadline_s": (
                time.monotonic()
                + after_initial_design_s
                + settings.graph_design_timeout_s
                + 5
            ),
        }
    )
    assert borrowed_timeout_s == pytest.approx(settings.graph_design_timeout_s + 5)

    after_initial_review_s = (
        settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    with pytest.raises(StageAdmissionDenied):
        critic_timeout_seconds(
            {"terminal_deadline_s": time.monotonic() + after_initial_review_s - 1},
            revision_count=0,
        )


def test_critics_borrow_time_without_spending_the_remaining_path():
    from agent.deadlines import (
        critic_timeout_seconds,
        design_timeout_seconds,
        patch_timeout_seconds,
    )
    from config import settings

    final_reserve_s = (
        settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    critic_reserves = {
        0: (
            settings.graph_patch_timeout_s
            + settings.graph_critic_timeout_s
            + final_reserve_s
        ),
        1: final_reserve_s,
    }
    for revision_count, reserve_s in critic_reserves.items():
        borrowed_timeout_s = critic_timeout_seconds(
            {
                "terminal_deadline_s": (
                    time.monotonic() + reserve_s + settings.graph_critic_timeout_s + 5
                ),
            },
            revision_count=revision_count,
        )
        assert borrowed_timeout_s == pytest.approx(settings.graph_critic_timeout_s + 5)

        max_timeout_s = critic_timeout_seconds(
            {
                "terminal_deadline_s": (
                    time.monotonic()
                    + reserve_s
                    + settings.graph_critic_max_timeout_s
                    + 5
                ),
            },
            revision_count=revision_count,
        )
        assert max_timeout_s == settings.graph_critic_max_timeout_s

    assert design_timeout_seconds({}) == settings.graph_design_timeout_s
    assert patch_timeout_seconds({}) == settings.graph_patch_timeout_s
    assert (
        critic_timeout_seconds({}, revision_count=0) == settings.graph_critic_timeout_s
    )
    assert (
        critic_timeout_seconds({}, revision_count=1) == settings.graph_critic_timeout_s
    )


def test_graph_stage_caps_for_one_complete_patch_fit_terminal_window():
    from config import settings

    stage_caps_s = (
        settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert stage_caps_s <= terminal_window_s


def test_two_architecture_passes_leave_a_complete_first_candidate_budget():
    from config import settings

    first_candidate_caps_s = (
        2 * settings.architecture_role_timeout_s
        + settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert first_candidate_caps_s <= terminal_window_s


def test_architecture_and_one_complete_patch_fit_the_request_deadline():
    from config import settings

    all_stage_caps_s = (
        2 * settings.architecture_role_timeout_s
        + settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert all_stage_caps_s == 843
    assert terminal_window_s - all_stage_caps_s == 37


def test_rejected_candidate_restores_immutable_approved_graph_baseline():
    from agent.graph import _restore_approved_graph_state

    approved = {"title": "Approved", "nodes": [], "edges": [], "sequence": []}
    rejected = {"title": "Rejected", "nodes": [], "edges": [], "sequence": []}
    restored = _restore_approved_graph_state(
        {
            "approved_graph_data": approved,
            "graph_data": rejected,
            "graph_changed": True,
        }
    )

    assert restored["graph_data"] == approved
    assert restored["graph_data"] is not approved
    assert restored["graph_changed"] is False


@pytest.mark.asyncio
async def test_langgraph_can_verify_one_bounded_repair_then_publish(monkeypatch):
    import agent.graph as agent_graph

    events = []
    reviews = []
    role_order = []

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
                    "First draft" if revision_count == 0 else f"Repair {revision_count}"
                ),
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
        }

    async def fake_architect(state):
        role_order.append("architect")
        return {
            "architect_plan": {
                "interpretation": "growth system",
                "assumptions": ["Channel APIs support bounded writes"],
            }
        }

    async def fake_challenger(state):
        assert state["architect_plan"]["interpretation"] == "growth system"
        role_order.append("challenger")
        return {"challenger_review": {"risks": []}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_review(state):
        assert state["_graph_stage_deadline_s"] > time.monotonic()
        reviews.append(state["graph_data"]["title"])
        if state.get("graph_revision_count") == 1:
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

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    result = await agent_graph.run_agent(_state(send), [], [], [])

    assert reviews == ["First draft", "Repair 1"]
    assert result["graph_revision_count"] == 1
    assert result["graph_data"]["title"] == "Repair 1"
    assert result["graph_notice_sent"] is False
    assert result["response_text"] == "reviewed answer"
    assert role_order == ["architect", "challenger"]
    repair_events = [
        event
        for event in events
        if event.get("phase") == "revise" and event.get("status") == "retry"
    ]
    assert [event["detail"].split(",", 1)[0] for event in repair_events] == [
        "Reworking the diagram 1 of 1",
    ]
    assert not any(event.get("type") == "graph_notice" for event in events)
