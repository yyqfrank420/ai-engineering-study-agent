import time

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


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"graph_changed": True, "graph_data": {}}, "unreviewed"),
        ({"graph_changed": False, "graph_data": {}}, "unchanged"),
        (
            {
                "graph_changed": False,
                "graph_data": {},
                "approved_graph_data": {},
                "graph_operation": {"status": "failed"},
            },
            "preserved",
        ),
        ({"graph_changed": False, "graph_data": None}, "none"),
    ],
)
def test_draft_graph_publication_is_explicit(state, expected):
    from agent.graph import _draft_graph_publication

    assert _draft_graph_publication(state) == expected


def test_failed_review_gets_two_semantic_repair_rounds():
    from agent.graph import (
        _repair_attempt_summary,
        _route_after_review,
        _route_after_revision,
    )

    assert _repair_attempt_summary(0) == "before a bounded repair could complete"
    assert _repair_attempt_summary(1) == "after 1 bounded repair attempt"
    assert _repair_attempt_summary(2) == "after 2 bounded repair attempts"

    failed = {
        "graph_changed": True,
        "graph_data": {"design_origin": "applied"},
        "graph_review": {"approved": False},
    }

    assert _route_after_review({**failed, "graph_repair_round_count": 0}) == "revise"
    assert _route_after_review({**failed, "graph_repair_round_count": 1}) == "revise"
    assert _route_after_review({**failed, "graph_repair_round_count": 2}) == "reject"
    assert (
        _route_after_review(
            {
                **failed,
                "graph_repair_round_count": 0,
                "graph_review": {"approved": False, "terminal": True},
            }
        )
        == "reject"
    )
    assert (
        _route_after_revision(
            {**failed, "graph_repair_round_count": 1, "graph_changed": True}
        )
        == "review"
    )
    assert (
        _route_after_revision(
            {**failed, "graph_repair_round_count": 2, "graph_changed": True}
        )
        == "review"
    )
    assert (
        _route_after_revision(
            {**failed, "graph_repair_round_count": 3, "graph_changed": True}
        )
        == "reject"
    )
    assert _route_after_revision({**failed, "graph_changed": False}) == "reject"


def test_invalid_patch_routes_once_to_contract_correction_before_rejecting():
    from agent.graph import _route_after_revision

    state = {
        "graph_changed": False,
        "graph_data": {"design_origin": "applied", "nodes": [], "edges": []},
        "graph_repair_round_count": 0,
        "graph_contract_correction_count": 0,
        "graph_contract_correction_pending": True,
        "graph_review": {
            "approved": False,
            "terminal": False,
        },
        "graph_operation": {
            "status": "failed",
            "kind": "create",
            "failure_code": "graph_patch_no_effect",
        },
    }

    assert _route_after_revision(state) == "correct"
    assert (
        _route_after_revision(
            {
                **state,
                "graph_contract_correction_count": 1,
                "graph_contract_correction_pending": False,
            }
        )
        == "reject"
    )
    assert (
        _route_after_revision(
            {
                **state,
                "graph_contract_correction_pending": False,
                "graph_operation": {
                    "status": "failed",
                    "kind": "create",
                    "failure_code": "graph_patch_contract_invalid",
                },
            }
        )
        == "reject"
    )


def test_repair_round_and_contract_correction_counters_are_separate():
    from agent.graph import _route_after_review

    failed = {
        "graph_changed": True,
        "graph_data": {"design_origin": "applied"},
        "graph_review": {"approved": False},
    }

    assert (
        _route_after_review(
            {
                **failed,
                "graph_revision_count": 9,
                "graph_repair_round_count": 0,
                "graph_contract_correction_count": 1,
            }
        )
        == "revise"
    )
    assert (
        _route_after_review(
            {
                **failed,
                "graph_revision_count": 0,
                "graph_repair_round_count": 1,
                "graph_contract_correction_count": 0,
            }
        )
        == "revise"
    )
    assert (
        _route_after_review(
            {
                **failed,
                "graph_revision_count": 0,
                "graph_repair_round_count": 2,
                "graph_contract_correction_count": 0,
            }
        )
        == "reject"
    )


def test_initial_revision_failures_still_reject_without_graph_change():
    from agent.graph import _route_after_review, _route_after_revision

    state = {
        "graph_changed": False,
        "graph_data": {"nodes": [], "edges": []},
        "graph_revision_count": 0,
        "graph_review": {"approved": True, "terminal": False},
        "graph_operation": {
            "status": "failed",
            "kind": "create",
            "failure_code": "graph_design_rejected",
        },
    }

    assert _route_after_review(state) == "reject"
    assert _route_after_revision(state) == "reject"


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


def test_initial_design_preserves_patch_path_and_review_preserves_finalization():
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
        settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    with pytest.raises(StageAdmissionDenied):
        critic_timeout_seconds(
            {"terminal_deadline_s": time.monotonic() + after_initial_review_s - 1}
        )


def test_critics_prioritize_the_verdict_and_preserve_finalization():
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
    borrowed_timeout_s = critic_timeout_seconds(
        {
            "terminal_deadline_s": (
                time.monotonic() + final_reserve_s + settings.graph_critic_timeout_s + 5
            ),
        }
    )
    assert borrowed_timeout_s == pytest.approx(settings.graph_critic_timeout_s + 5)

    max_timeout_s = critic_timeout_seconds(
        {
            "terminal_deadline_s": (
                time.monotonic()
                + final_reserve_s
                + settings.graph_critic_max_timeout_s
                + 5
            ),
        }
    )
    assert max_timeout_s == settings.graph_critic_max_timeout_s

    assert design_timeout_seconds({}) == settings.graph_design_timeout_s
    assert patch_timeout_seconds({}) == settings.graph_patch_timeout_s
    assert critic_timeout_seconds({}) == settings.graph_critic_max_timeout_s


def test_measured_completion_path_preserves_patch_and_final_review_time(monkeypatch):
    from agent import deadlines
    from config import settings

    clock = {"now": 386.0}
    monkeypatch.setattr(deadlines.time, "monotonic", lambda: clock["now"])
    state = {
        "terminal_deadline_s": (
            settings.agent_timeout_s - settings.agent_terminal_headroom_s
        )
    }

    initial_critic_s = deadlines.critic_timeout_seconds(state)
    assert initial_critic_s == 195.0
    clock["now"] += initial_critic_s

    patch_s = deadlines.patch_timeout_seconds(state)
    assert patch_s >= 98.0
    clock["now"] += 98.0

    final_critic_s = deadlines.critic_timeout_seconds(state)
    assert final_critic_s >= 101.0
    clock["now"] += 101.0

    assert (
        deadlines.synthesis_timeout_seconds(state) == settings.graph_synthesis_timeout_s
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

    assert all_stage_caps_s == 873
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
    assert restored["graph_publication"] == "preserved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("review_status", "failure_code"),
    [
        ("completed", "graph_review_rejected"),
        ("unavailable", "semantic_review_timeout"),
    ],
)
async def test_rejected_expansion_preserves_baseline_without_publication(
    monkeypatch,
    review_status,
    failure_code,
):
    import agent.graph as agent_graph

    events = []
    approved_graph = {
        "design_origin": "applied",
        "title": "Approved customer support graph",
        "nodes": [],
        "edges": [],
        "sequence": [],
        "version": "approved-v1",
    }

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
                **approved_graph,
                "title": "Rejected expanded customer support graph",
                "version": "candidate-v2",
            },
            "graph_operation": {
                "kind": "edit",
                "status": "candidate",
                "failure_code": None,
            },
        }

    async def fake_review(state):
        assert state["graph_publication"] == "unreviewed"
        return {
            **state,
            "graph_review": {
                "approved": False,
                "terminal": True,
                "review_status": review_status,
                "failure_code": failure_code,
            },
        }

    async def fake_architect(_state):
        return {}

    async def fake_challenger(_state):
        return {}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_synth(state):
        assert state["graph_data"] == approved_graph
        assert state["graph_publication"] == "preserved"
        assert state["graph_changed"] is False
        return {**state, "response_text": "The expansion was withheld."}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    state = _state(send)
    state.update(
        {
            "user_message": "expand on all the agents",
            "graph_data": approved_graph,
            "approved_graph_data": approved_graph,
        }
    )
    result = await agent_graph.run_agent(state, [], [], [])

    assert result["graph_data"] == approved_graph
    assert result["graph_operation"]["status"] == "failed"
    assert result["graph_publication"] == "preserved"
    assert not any(event.get("type") == "graph_data" for event in events)


@pytest.mark.asyncio
async def test_preserved_graph_is_not_emitted_but_unchanged_graph_resyncs(monkeypatch):
    import agent.nodes.orchestrator_node as orchestrator

    graph = {
        "design_origin": "applied",
        "title": "Approved customer support graph",
        "nodes": [{"id": "support", "label": "Customer support"}],
        "edges": [],
        "sequence": [],
        "version": "approved-v1",
    }

    async def fake_stream_blocks(**kwargs):
        await kwargs["send"](
            {
                "type": "explanation_block",
                "title": "Overview",
                "content": "The approved graph remains available.",
                "related_node_ids": ["support"],
            }
        )
        return "The approved graph remains available."

    monkeypatch.setattr(orchestrator, "stream_explanation_blocks", fake_stream_blocks)

    async def run_synthesis(publication: str | None):
        events = []

        async def send(event):
            events.append(event)

        state = {
            "send": send,
            "history": [],
            "user_message": "expand on all the agents",
            "rag_chunks": [],
            "graph_data": graph,
            "graph_changed": False,
        }
        if publication is not None:
            state["graph_publication"] = publication
        result = await orchestrator.orchestrator_synthesise(state)
        return result, events

    preserved_result, preserved_events = await run_synthesis("preserved")
    resynced_result, resynced_events = await run_synthesis("unchanged")

    assert preserved_result["graph_data"] == graph
    assert not any(event.get("type") == "graph_data" for event in preserved_events)
    assert resynced_result["graph_data"] == graph
    assert [
        event for event in resynced_events if event.get("type") == "graph_data"
    ] == [{"type": "graph_data", "data": graph}]


@pytest.mark.asyncio
@pytest.mark.parametrize("approval_round", [1, 2])
async def test_langgraph_can_verify_bounded_repairs_then_publish(
    monkeypatch,
    approval_round,
):
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
        if state.get("graph_revision_count") == approval_round:
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

    assert reviews == [
        "First draft",
        *(f"Repair {round_number}" for round_number in range(1, approval_round + 1)),
    ]
    assert result["graph_revision_count"] == approval_round
    assert result["graph_data"]["title"] == f"Repair {approval_round}"
    assert result["graph_publication"] == "approved"
    assert result["graph_notice_sent"] is False
    assert result["response_text"] == "reviewed answer"
    assert role_order == ["architect", "challenger"]
    repair_events = [
        event
        for event in events
        if event.get("phase") == "revise" and event.get("status") == "retry"
    ]
    assert [event["detail"].split(".", 1)[0] for event in repair_events] == [
        f"Repair round {round_number} of 2"
        for round_number in range(1, approval_round + 1)
    ]
    assert not any(event.get("type") == "graph_notice" for event in events)


@pytest.mark.asyncio
async def test_invalid_patch_feedback_returns_to_critic_before_kimi_retries(
    monkeypatch,
):
    import agent.graph as agent_graph

    call_order = []

    async def send(_event):
        return None

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_apply(state, _tools):
        revision_count = state.get("graph_revision_count", 0)
        call_order.append(f"kimi-{revision_count}")
        if len([call for call in call_order if call.startswith("kimi-")]) == 2:
            return {
                **state,
                "graph_changed": True,
                "graph_operation": {
                    "kind": "create",
                    "status": "failed",
                    "failure_code": "graph_patch_invalid_preserved_existing_graph",
                },
                "graph_patch_validation_error": {
                    "path": "layers.composition.group_ids",
                    "rule": "group_membership_scope",
                },
            }
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": "Initial" if revision_count == 0 else "Corrected repair",
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
            "graph_operation": {
                "kind": "create",
                "status": "candidate",
                "failure_code": None,
            },
        }

    async def fake_review(state):
        if state.get("graph_contract_correction_pending"):
            call_order.append("critic-contract-correction")
            assert state["graph_patch_validation_error"] == {
                "path": "layers.composition.group_ids",
                "rule": "group_membership_scope",
            }
            return {
                **state,
                "graph_review": {"approved": False, "terminal": False},
                "graph_operation": {
                    "kind": "create",
                    "status": "candidate",
                    "failure_code": None,
                },
            }
        if state.get("graph_repair_round_count", 0) == 1:
            call_order.append("critic-post-repair")
            return {**state, "graph_review": {"approved": True}}
        call_order.append("critic-initial")
        return {**state, "graph_review": {"approved": False, "terminal": False}}

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "growth system"}}

    async def fake_challenger(_state):
        return {"challenger_review": {"risks": []}}

    async def fake_expand(state, _tools, _wait_task):
        return state

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

    assert call_order == [
        "kimi-0",
        "critic-initial",
        "kimi-1",
        "critic-contract-correction",
        "kimi-1",
        "critic-post-repair",
    ]
    assert result["graph_repair_round_count"] == 1
    assert result["graph_contract_correction_count"] == 1
    assert result["graph_contract_correction_pending"] is False
    assert result["graph_data"]["title"] == "Corrected repair"


@pytest.mark.asyncio
async def test_langgraph_does_not_emit_graph_notice_when_graph_mode_on(monkeypatch):
    import agent.graph as agent_graph

    events = []

    async def send(event):
        events.append(event)

    state = _state(send)

    async def fake_route(incoming_state):
        return {**incoming_state, "route": "search"}

    async def fake_search(incoming_state, _tools):
        return incoming_state, None

    async def fake_apply_graph(incoming_state, _tools):
        return {
            **incoming_state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": "Draft",
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
        }

    async def fake_review(incoming_state):
        return {**incoming_state, "graph_review": {"approved": False, "terminal": True}}

    async def fake_synth(incoming_state):
        return {**incoming_state, "response_text": "ok"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)

    async def fake_architect(_incoming_state):
        return {}

    async def fake_challenger(_incoming_state):
        return {}

    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)

    async def fake_expand(incoming_state, _graph_tools, _search_tool_wait_task):
        return incoming_state

    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    result = await agent_graph.run_agent(state, [], [], [])

    assert not any(event.get("type") == "graph_notice" for event in events)
    assert result["graph_notice_sent"] is False


@pytest.mark.asyncio
async def test_run_agent_preserves_edit_request_without_applied_graph(
    monkeypatch,
):
    import agent.graph as agent_graph

    events = []

    async def send(event):
        events.append(event)

    async def fake_route(incoming_state):
        return {**incoming_state, "route": "search"}

    async def fake_search(incoming_state, _tools):
        return incoming_state, None

    async def fake_apply_graph(incoming_state, _tools):
        assert incoming_state["graph_intent"] == "edit"
        assert incoming_state["graph_operation"] == {
            "kind": "edit",
            "status": "failed",
            "failure_code": "graph_edit_target_unavailable",
        }
        return {
            **incoming_state,
            "graph_changed": False,
            "graph_data": None,
        }

    async def fake_review(incoming_state):
        return {**incoming_state, "graph_review": {"approved": True}}

    async def fake_synth(incoming_state):
        return {**incoming_state, "response_text": "ok"}

    async def fake_architect(_incoming_state):
        return {}

    async def fake_challenger(_incoming_state):
        return {}

    async def fake_expand(incoming_state, _graph_tools, _search_tool_wait_task):
        return incoming_state

    monkeypatch.setattr(agent_graph, "resolve_graph_operation", lambda *_args: "edit")
    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    state = _state(send)
    state["graph_mode"] = "auto"

    result = await agent_graph.run_agent(state, [], [], [])

    assert result["graph_data"] is None
    assert result["graph_operation"] == {
        "kind": "edit",
        "status": "failed",
        "failure_code": "graph_edit_target_unavailable",
    }
    assert any(event.get("type") == "graph_notice" for event in events)


@pytest.mark.asyncio
async def test_initial_unreviewed_candidate_is_withheld_when_review_is_unavailable(
    monkeypatch,
):
    import agent.graph as agent_graph

    events = []

    async def send(event):
        events.append(event)

    async def fake_route(incoming_state):
        return {**incoming_state, "route": "search"}

    async def fake_search(incoming_state, _tools):
        return incoming_state, None

    async def fake_apply_graph(incoming_state, _tools):
        return {
            **incoming_state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": "Rejected candidate",
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
            "graph_operation": {
                "kind": "create",
                "status": "candidate",
                "failure_code": None,
            },
        }

    async def fake_review(incoming_state):
        assert incoming_state["graph_publication"] == "unreviewed"
        return {
            **incoming_state,
            "graph_review": {
                "approved": False,
                "terminal": True,
                "review_status": "unavailable",
                "failure_code": "semantic_review_timeout",
                "revision_instruction": "Keep candidate and retry?",
            },
        }

    async def fake_synth(incoming_state):
        assert incoming_state["graph_data"] is None
        assert incoming_state["graph_publication"] == "withheld"
        return {**incoming_state, "response_text": "ok"}

    async def fake_architect(_incoming_state):
        return {}

    async def fake_challenger(_incoming_state):
        return {}

    async def fake_expand(incoming_state, _graph_tools, _search_tool_wait_task):
        return incoming_state

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    state = _state(send)
    state["user_message"] = "Keep the graph but tighten one path"
    state["graph_mode"] = "auto"

    result = await agent_graph.run_agent(state, [], [], [])

    assert any(event.get("type") == "graph_notice" for event in events)
    assert not any(event.get("type") == "graph_data" for event in events)
    assert result["graph_data"] is None
    assert result["graph_publication"] == "withheld"
    assert result["graph_notice_sent"] is True
    assert result["graph_operation"]["status"] == "failed"


async def _run_invalid_patch_contract_correction_workflow(
    monkeypatch,
    *,
    approved_baseline: dict | None,
):
    import agent.graph as agent_graph
    import agent.nodes.graph_critic as graph_critic

    events = []
    apply_rounds = []
    critic_requests = []
    correction_candidate_titles = []
    initial_candidate = {
        "design_origin": "applied",
        "title": "Initial candidate",
        "nodes": [],
        "edges": [],
        "sequence": [],
    }
    corrected_candidate = {
        **initial_candidate,
        "title": "Corrected candidate",
    }

    async def send(event):
        events.append(event)

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_apply(state, _tools):
        revision_count = state.get("graph_revision_count", 0)
        apply_rounds.append(revision_count)
        if revision_count == 0:
            return {
                **state,
                "graph_data": initial_candidate,
                "graph_changed": True,
                "graph_operation": {
                    "kind": "create",
                    "status": "candidate",
                    "failure_code": None,
                },
            }
        if len(apply_rounds) == 2:
            return {
                **state,
                "graph_data": initial_candidate,
                "graph_changed": False,
                "graph_operation": {
                    "kind": "create",
                    "status": "failed",
                    "failure_code": "graph_patch_invalid_preserved_existing_graph",
                },
                "graph_patch_validation_error": {
                    "path": "groups.group_2",
                    "rule": "locked_record_changed",
                },
            }
        assert revision_count == 1
        return {
            **state,
            "graph_data": corrected_candidate,
            "graph_changed": True,
            "graph_operation": {
                "kind": "create",
                "status": "candidate",
                "failure_code": None,
            },
        }

    async def fake_review(state):
        if state.get("graph_repair_round_count", 0) == 0 and not state.get(
            "graph_contract_correction_pending"
        ):
            return {
                **state,
                "graph_review": {"approved": False, "terminal": False},
            }
        if state.get("graph_contract_correction_pending"):
            assert state["graph_data"] == initial_candidate
            correction_candidate_titles.append(state["graph_data"]["title"])
            return await graph_critic.graph_critic_node(state)
        return {**state, "graph_review": {"approved": True}}

    async def fake_request_critic(*_args, **_kwargs):
        critic_requests.append("contract_correction")
        return type("CriticResponse", (), {"text": "{}"})()

    def fake_completed_review(*_args, **_kwargs):
        return {
            "approved": False,
            "terminal": False,
            "review_status": "completed",
            "repair_contract": {"repair_scope": "local"},
            "topology_proofs": [],
        }

    async def fake_render(_graph):
        return {"report": {}}

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "test design"}}

    async def fake_challenger(_state):
        return {"challenger_review": {"risks": []}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_synth(state):
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "resolve_graph_operation", lambda *_args: "create")
    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "challenger_node", fake_challenger)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    monkeypatch.setattr(
        agent_graph, "validate_local_repair_admission", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(graph_critic, "_request_critic_scorecard", fake_request_critic)
    monkeypatch.setattr(graph_critic, "_completed_critic_review", fake_completed_review)
    monkeypatch.setattr(
        graph_critic, "_deterministic_render_review", lambda *_args: {"approved": True}
    )
    monkeypatch.setattr(
        graph_critic, "_validate_review_protocol", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        graph_critic, "_enforce_local_repair_admission", lambda review, _graph: review
    )

    state = _state(send)
    state.update(
        {
            "graph_data": approved_baseline,
            "approved_graph_data": approved_baseline,
            "await_diagram_evaluation": fake_render,
        }
    )
    result = await agent_graph.run_agent(state, [], [], [])

    return result, apply_rounds, critic_requests, correction_candidate_titles, events


@pytest.mark.asyncio
async def test_approved_baseline_invalid_patch_gets_contract_correction_before_retry(
    monkeypatch,
):
    approved_baseline = {
        "design_origin": "applied",
        "title": "Approved baseline",
        "nodes": [],
        "edges": [],
        "sequence": [],
    }

    (
        result,
        apply_rounds,
        critic_requests,
        correction_candidate_titles,
        _events,
    ) = await _run_invalid_patch_contract_correction_workflow(
        monkeypatch,
        approved_baseline=approved_baseline,
    )

    assert critic_requests == ["contract_correction"]
    assert correction_candidate_titles == ["Initial candidate"]
    assert apply_rounds == [0, 1, 1]
    assert result["graph_data"]["title"] == "Corrected candidate"
    assert result["graph_operation"]["status"] == "applied"
    assert result["graph_repair_round_count"] == 1
    assert result["graph_contract_correction_count"] == 1


@pytest.mark.asyncio
async def test_initial_unpublished_invalid_patch_retains_candidate_for_contract_correction(
    monkeypatch,
):
    (
        result,
        apply_rounds,
        critic_requests,
        correction_candidate_titles,
        _events,
    ) = await _run_invalid_patch_contract_correction_workflow(
        monkeypatch,
        approved_baseline=None,
    )

    assert critic_requests == ["contract_correction"]
    assert correction_candidate_titles == ["Initial candidate"]
    assert apply_rounds == [0, 1, 1]
    assert result["graph_data"]["title"] == "Corrected candidate"
    assert result["graph_operation"]["status"] == "applied"
    assert result["graph_repair_round_count"] == 1
    assert result["graph_contract_correction_count"] == 1
