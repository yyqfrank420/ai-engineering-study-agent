import time

import pytest


def _state(send):
    async def accept_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph.get("nodes") or []),
                "rendered_edges": len(graph.get("edges") or []),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

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
        "await_diagram_evaluation": accept_diagram,
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
        ("Fix the typo in the cache label", True),
        ("Replace the current diagram", True),
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
    from agent.deadlines import (
        MAX_GRAPH_REPAIR_ROUNDS,
        StageAdmissionDenied,
        patch_timeout_seconds,
    )
    from config import GRAPH_MAX_CONTRACT_CORRECTIONS, settings

    following_reserve_s = (
        settings.graph_critic_timeout_s
        + (MAX_GRAPH_REPAIR_ROUNDS - 1)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + GRAPH_MAX_CONTRACT_CORRECTIONS
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
        + settings.agent_orchestration_reserve_s
    )
    first_repair_state = {"graph_revision_count": 1}
    with pytest.raises(StageAdmissionDenied):
        patch_timeout_seconds(
            {
                **first_repair_state,
                "terminal_deadline_s": time.monotonic() + following_reserve_s - 1,
            }
        )

    timeout_s = patch_timeout_seconds(
        {
            **first_repair_state,
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
            **first_repair_state,
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
            **first_repair_state,
        }
    )
    assert max_timeout_s == settings.graph_builder_max_timeout_s


def test_initial_design_uses_the_visible_preview_deadline(monkeypatch):
    from agent import deadlines
    from config import settings

    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100.0)
    timeout_s = deadlines.design_timeout_seconds(
        {
            "graph_revision_count": 0,
            "graph_preview_deadline_s": 270.0,
            "terminal_deadline_s": 1_000.0,
        }
    )

    assert timeout_s == settings.graph_preview_design_timeout_s
    assert (
        timeout_s
        + settings.diagram_evaluation_timeout_s
        + settings.graph_preview_finalization_reserve_s
        <= settings.graph_preview_timeout_s
    )


def test_initial_design_rejects_when_preview_reserve_is_exhausted(monkeypatch):
    from agent import deadlines

    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100.0)
    with pytest.raises(
        deadlines.StageAdmissionDenied, match="visible preview deadline"
    ):
        deadlines.design_timeout_seconds(
            {
                "graph_revision_count": 0,
                "graph_preview_deadline_s": 110.0,
                "terminal_deadline_s": 1_000.0,
            }
        )


def test_architecture_admission_preserves_the_complete_downstream_path():
    from agent.deadlines import (
        MAX_GRAPH_REPAIR_ROUNDS,
        StageAdmissionDenied,
        architecture_timeout_seconds,
    )
    from config import GRAPH_MAX_CONTRACT_CORRECTIONS, settings

    downstream_reserve_s = (
        settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + (MAX_GRAPH_REPAIR_ROUNDS + GRAPH_MAX_CONTRACT_CORRECTIONS)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
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
        MAX_GRAPH_REPAIR_ROUNDS,
        StageAdmissionDenied,
        critic_timeout_seconds,
        design_timeout_seconds,
    )
    from config import GRAPH_MAX_CONTRACT_CORRECTIONS, settings

    after_initial_design_s = (
        settings.graph_critic_timeout_s
        + (MAX_GRAPH_REPAIR_ROUNDS + GRAPH_MAX_CONTRACT_CORRECTIONS)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
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
            {
                "graph_repair_round_count": MAX_GRAPH_REPAIR_ROUNDS,
                "terminal_deadline_s": time.monotonic() + after_initial_review_s - 1,
            }
        )


def test_critics_prioritize_the_verdict_and_preserve_finalization():
    from agent.deadlines import (
        MAX_GRAPH_REPAIR_ROUNDS,
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
            "graph_repair_round_count": MAX_GRAPH_REPAIR_ROUNDS,
            "terminal_deadline_s": (
                time.monotonic() + final_reserve_s + settings.graph_critic_timeout_s + 5
            ),
        }
    )
    assert borrowed_timeout_s == pytest.approx(settings.graph_critic_timeout_s + 5)

    max_timeout_s = critic_timeout_seconds(
        {
            "graph_repair_round_count": MAX_GRAPH_REPAIR_ROUNDS,
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

    clock = {"now": 0.0}
    monkeypatch.setattr(deadlines.time, "monotonic", lambda: clock["now"])
    state = {
        "terminal_deadline_s": (
            settings.agent_timeout_s - settings.agent_terminal_headroom_s
        )
    }

    architecture_s = deadlines.architecture_timeout_seconds(state, review=False)
    assert architecture_s == settings.architecture_role_timeout_s
    clock["now"] += architecture_s

    design_s = deadlines.design_timeout_seconds(state)
    assert design_s == settings.graph_design_timeout_s + 7
    clock["now"] += design_s

    initial_critic_s = deadlines.critic_timeout_seconds(state)
    assert initial_critic_s == settings.graph_critic_timeout_s
    clock["now"] += initial_critic_s

    state["graph_revision_count"] = 1
    failed_patch_s = deadlines.patch_timeout_seconds(state)
    assert failed_patch_s == settings.graph_patch_timeout_s
    clock["now"] += failed_patch_s

    state["graph_revision_count"] = 0
    state["graph_contract_correction_pending"] = True
    correction_critic_s = deadlines.critic_timeout_seconds(state)
    assert correction_critic_s == settings.graph_critic_timeout_s
    clock["now"] += correction_critic_s

    state["graph_contract_correction_pending"] = False
    state["graph_contract_correction_count"] = 1
    state["graph_revision_count"] = 1
    first_patch_s = deadlines.patch_timeout_seconds(state)
    assert first_patch_s == settings.graph_patch_timeout_s
    clock["now"] += first_patch_s

    state["graph_repair_round_count"] = 1
    first_repair_critic_s = deadlines.critic_timeout_seconds(state)
    assert first_repair_critic_s == settings.graph_critic_timeout_s
    clock["now"] += first_repair_critic_s

    state["graph_revision_count"] = 2
    second_patch_s = deadlines.patch_timeout_seconds(state)
    assert second_patch_s == settings.graph_patch_timeout_s
    clock["now"] += second_patch_s

    state["graph_repair_round_count"] = 2
    final_critic_s = deadlines.critic_timeout_seconds(state)
    assert final_critic_s == settings.graph_critic_timeout_s
    clock["now"] += final_critic_s

    assert (
        deadlines.synthesis_timeout_seconds(state) == settings.graph_synthesis_timeout_s
    )
    clock["now"] += settings.graph_synthesis_timeout_s
    assert state["terminal_deadline_s"] - clock["now"] == pytest.approx(
        settings.graph_finalization_reserve_s + settings.agent_orchestration_reserve_s
    )


def test_graph_stage_caps_for_two_complete_patches_fit_terminal_window():
    from config import settings

    stage_caps_s = (
        settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + 2 * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert stage_caps_s <= terminal_window_s


def test_architecture_pass_leaves_a_complete_first_candidate_budget():
    from config import settings

    first_candidate_caps_s = (
        settings.architecture_role_timeout_s
        + settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert first_candidate_caps_s <= terminal_window_s


def test_architecture_and_two_complete_patches_fit_the_request_deadline():
    from config import (
        GRAPH_MAX_CONTRACT_CORRECTIONS,
        GRAPH_MAX_REPAIR_ROUNDS,
        settings,
    )

    all_stage_caps_s = (
        settings.architecture_role_timeout_s
        + settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + (GRAPH_MAX_REPAIR_ROUNDS + GRAPH_MAX_CONTRACT_CORRECTIONS)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    terminal_window_s = settings.agent_timeout_s - settings.agent_terminal_headroom_s

    assert all_stage_caps_s == 873
    assert terminal_window_s - all_stage_caps_s == 37
    assert (
        all_stage_caps_s + settings.agent_orchestration_reserve_s <= terminal_window_s
    )


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
    critic_calls = 0
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

    async def fake_review(state, **_kwargs):
        nonlocal critic_calls
        critic_calls += 1
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
        return {"architect_plan": {"interpretation": "expand approved graph"}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_early_design_frame(state):
        assert state["challenger_review"] == {}
        return {**state, "early_response_text": ""}

    async def fake_synth(state):
        assert state["graph_data"] == approved_graph
        assert state["graph_publication"] == "preserved"
        assert state["graph_changed"] is False
        return {**state, "response_text": "The expansion was withheld."}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "early_design_frame_node", fake_early_design_frame)
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
    assert critic_calls == 1
    assert not any(event.get("type") == "graph_data" for event in events)


@pytest.mark.asyncio
async def test_preserved_graph_is_not_previewed_but_unchanged_graph_resyncs(
    monkeypatch,
):
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
    assert not any(event.get("type") == "graph_preview" for event in preserved_events)
    assert resynced_result["graph_data"] == graph
    assert [
        event for event in resynced_events if event.get("type") == "graph_preview"
    ] == [{"type": "graph_preview", "data": graph}]


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
        if state.get("graph_revision_count", 0) == 0:
            assert "architect_plan" not in state
        else:
            assert state["architect_plan"]["interpretation"] == "growth system"
            assert state["challenger_review"] == {}
        assert state["_graph_stage_deadline_s"] > time.monotonic()
        role_order.append("graph_builder")
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

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_review(state, **_kwargs):
        assert state["_graph_stage_deadline_s"] > time.monotonic()
        role_order.append("critic")
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

    async def fake_render(graph):
        role_order.append("private_render")
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    initial_state = _state(send)
    initial_state["challenger_review"] = {
        "risks": [{"risk": "stale prior-turn risk", "mitigation": "ignore"}]
    }
    initial_state["await_diagram_evaluation"] = fake_render
    result = await agent_graph.run_agent(initial_state, [], [], [])

    assert reviews == [
        "First draft",
        *(f"Repair {round_number}" for round_number in range(1, approval_round + 1)),
    ]
    assert result["graph_revision_count"] == approval_round
    assert result["graph_data"]["title"] == f"Repair {approval_round}"
    assert result["graph_publication"] == "approved"
    assert result["graph_notice_sent"] is False
    assert result["response_text"] == "reviewed answer"
    assert role_order[:4] == [
        "graph_builder",
        "private_render",
        "architect",
        "critic",
    ]
    assert "challenger" not in role_order
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
async def test_outer_review_timeout_returns_the_charged_shared_budget(monkeypatch):
    import asyncio

    import agent.graph as agent_graph
    from agent.graph_review_budget import GraphReviewBudget

    async def send(_event):
        return None

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "test system"}}

    async def fake_early_design_frame(_state):
        return {"early_response_text": ""}

    async def fake_apply(state, _tools):
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": "Private candidate",
                "nodes": [],
                "edges": [],
                "sequence": [],
            },
        }

    async def fake_review(state, *, review_budget):
        review_budget.claim_provider_call(correction=None)
        await asyncio.sleep(30)
        return state

    async def fake_synth(state):
        return {**state, "response_text": "The private candidate was withheld."}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "early_design_frame_node", fake_early_design_frame)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    monkeypatch.setattr(agent_graph, "critic_timeout_seconds", lambda _state: 0.001)

    review_budget = GraphReviewBudget()
    state = _state(send)
    state["_graph_review_budget"] = review_budget

    result = await agent_graph.run_agent(state, [], [], [])

    assert review_budget.critic_calls == 1
    assert result["graph_critic_call_count"] == 1
    assert result["graph_contract_correction_count"] == 0
    assert result["graph_review"]["failure_code"] == "semantic_review_timeout"
    assert result["graph_publication"] == "withheld"


@pytest.mark.asyncio
async def test_two_distinct_connection_repairs_apply_exact_terminal_edges_and_publish(
    monkeypatch,
):
    import agent.graph as agent_graph
    import agent.nodes.graph_critic as graph_critic
    from agent.nodes.graph_worker import (
        _apply_applied_graph_patch,
        _normalise_applied_graph,
    )

    events = []
    critic_rounds = []
    applied_patches = []
    rendered_edge_counts = []

    async def send(event):
        events.append(event)

    def layer(*, status="pass", score=0.9, findings=None, **selectors):
        return {
            "status": status,
            "score": score,
            "blocking_findings": list(findings or []),
            "deterministic_finding_ids": [],
            "node_ids": [],
            "edge_selectors": [],
            "group_ids": [],
            "composition_fields": [],
            "sequence_indexes": [],
            "assumption_indexes": [],
            "reason": "The scorecard grants only the records needed for this repair.",
            "context_node_ids": list(selectors.get("context_node_ids") or []),
            "addition_count": len(
                selectors.get("connection_addition_obligations") or []
            ),
            "connection_addition_obligations": list(
                selectors.get("connection_addition_obligations") or []
            ),
            "composition_append_counts": {},
        }

    def repair_contract(*, findings, obligations):
        layers = {
            "components": layer(),
            "connections": layer(
                status="fail",
                score=0.7,
                findings=findings,
                context_node_ids=sorted(
                    {
                        endpoint
                        for obligation in obligations
                        for endpoint in (obligation["source"], obligation["target"])
                    }
                ),
                connection_addition_obligations=obligations,
            ),
            "composition": layer(),
            "render": layer(),
        }
        return {"repair_scope": "local", "layers": layers}

    initial_graph = _normalise_applied_graph(
        {
            "title": "Campaign decision branches",
            "assumptions": ["The approval policy returns a durable decision."],
            "nodes": [
                {
                    "id": node_id,
                    "label": label,
                    "type": "service",
                    "technology": "Domain service",
                    "description": description,
                }
                for node_id, label, description in (
                    ("request", "Campaign request", "Receives one campaign request."),
                    (
                        "gate",
                        "Approval gate",
                        "Classifies the requested campaign action.",
                    ),
                    ("accepted", "Accepted action", "Owns approved action handling."),
                    ("rejected", "Rejected action", "Owns rejected action handling."),
                    (
                        "recovery",
                        "Recovery action",
                        "Owns retryable recovery handling.",
                    ),
                    (
                        "outcome",
                        "Campaign outcome",
                        "Records the observable campaign result.",
                    ),
                )
            ],
            "edges": [
                {
                    "source": source,
                    "target": target,
                    "label": label,
                    "technology": "Domain event",
                    "sync": "async",
                    "flow": "runtime",
                    "description": "Routes one bounded campaign decision.",
                }
                for source, target, label in (
                    ("request", "gate", "submits campaign request"),
                    ("gate", "accepted", "routes accepted action"),
                    ("gate", "rejected", "routes rejected action"),
                    ("gate", "recovery", "routes recovery action"),
                    ("outcome", "request", "returns measured campaign outcome"),
                )
            ],
            "groups": [],
            "sequence": [],
        },
        safety_max_nodes=6,
        resolved_complexity="prototype",
    )
    initial_obligations = [
        {
            "source": "accepted",
            "target": "outcome",
            "required_contract": "records accepted campaign outcome",
        },
        {
            "source": "rejected",
            "target": "outcome",
            "required_contract": "records rejected campaign outcome",
        },
    ]
    second_obligations = [
        {
            "source": "recovery",
            "target": "outcome",
            "required_contract": "records recovered campaign outcome",
        }
    ]
    logical_flow = {
        "id": "blocker_v1:rubric:connections:logical_flow",
        "kind": "rubric",
        "layer": "connections",
        "key": {"code": "logical_flow"},
        "message": "Route the primary path to an observable campaign outcome.",
        "repair_fingerprint": "initial-logical-flow",
    }
    initial_branch_completion = {
        "id": "blocker_v1:rubric:connections:branch_completion",
        "kind": "rubric",
        "layer": "connections",
        "key": {"code": "branch_completion"},
        "message": "Route accepted and rejected campaign branches to outcomes.",
        "repair_fingerprint": "initial-branch-completion",
    }
    distinct_branch_completion = {
        **initial_branch_completion,
        "message": "Route the recovery branch to an observable campaign outcome.",
        "repair_fingerprint": "recovery-branch-completion",
    }

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "campaign control path"}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_apply(state, _tools):
        revision_count = state.get("graph_revision_count", 0)
        if revision_count == 0:
            return {
                **state,
                "graph_data": initial_graph,
                "graph_changed": True,
                "graph_operation": {"kind": "create", "status": "candidate"},
            }

        contract = state["graph_review"]["repair_contract"]
        obligations = initial_obligations if revision_count == 1 else second_obligations
        patch = {
            "add_edges": [
                {
                    "source": obligation["source"],
                    "target": obligation["target"],
                    "label": obligation["required_contract"],
                    "technology": "Campaign outcome event",
                    "sync": "async",
                    "flow": "runtime",
                    "description": "Records a terminal campaign result.",
                }
                for obligation in obligations
            ]
        }
        applied_patches.append(patch)
        patched_graph = _apply_applied_graph_patch(
            state["graph_data"],
            patch,
            safety_max_nodes=6,
            resolved_complexity="prototype",
            repair_contract=contract,
        )
        return {
            **state,
            "graph_data": patched_graph,
            "graph_changed": True,
            "graph_operation": {"kind": "create", "status": "candidate"},
        }

    def review_for_state(state):
        revision_count = state.get("graph_repair_round_count", 0)
        critic_rounds.append(revision_count)
        if revision_count == 0:
            return {
                **state,
                "graph_review": {
                    "approved": False,
                    "review_status": "completed",
                    "repair_contract": repair_contract(
                        findings=[
                            logical_flow["message"],
                            initial_branch_completion["message"],
                        ],
                        obligations=initial_obligations,
                    ),
                    "hard_blockers": [logical_flow, initial_branch_completion],
                    "prior_obligation_dispositions": [],
                },
            }
        if revision_count == 1:
            assert {edge["label"] for edge in state["graph_data"]["edges"]} >= {
                item["required_contract"] for item in initial_obligations
            }
            return {
                **state,
                "graph_review": {
                    "approved": False,
                    "review_status": "completed",
                    "repair_contract": repair_contract(
                        findings=[distinct_branch_completion["message"]],
                        obligations=second_obligations,
                    ),
                    "hard_blockers": [distinct_branch_completion],
                    "prior_obligation_dispositions": [
                        {
                            "prior_obligation_id": logical_flow["id"],
                            "status": "resolved",
                        },
                        {
                            "prior_obligation_id": initial_branch_completion["id"],
                            "status": "still_fail",
                        },
                    ],
                },
            }
        assert revision_count == 2
        assert {edge["label"] for edge in state["graph_data"]["edges"]} >= {
            item["required_contract"] for item in second_obligations
        }
        return {
            **state,
            "graph_review": {
                "approved": True,
                "review_status": "completed",
                "repair_contract": {
                    "repair_scope": "none",
                    "layers": {
                        "components": layer(),
                        "connections": layer(),
                        "composition": layer(),
                        "render": layer(),
                    },
                },
                "hard_blockers": [],
                "prior_obligation_dispositions": [
                    {
                        "prior_obligation_id": distinct_branch_completion["id"],
                        "status": "resolved",
                    }
                ],
            },
        }

    critic_states = []

    async def fake_request_critic(state, **_kwargs):
        critic_states.append(state)
        return type("CriticResponse", (), {"text": "{}"})()

    def fake_completed_review(*_args, **_kwargs):
        return review_for_state(critic_states[-1])["graph_review"]

    async def fake_render(graph):
        rendered_edge_counts.append(len(graph["edges"]))
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def fake_synth(state):
        assert state["graph_publication"] == "approved"
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    monkeypatch.setattr(graph_critic, "_request_critic_scorecard", fake_request_critic)
    monkeypatch.setattr(graph_critic, "_completed_critic_review", fake_completed_review)
    monkeypatch.setattr(
        graph_critic, "_validate_review_protocol", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        graph_critic, "_enforce_local_repair_admission", lambda review, _graph: review
    )

    state = _state(send)
    state["await_diagram_evaluation"] = fake_render
    result = await agent_graph.run_agent(state, [], [], [])

    assert critic_rounds == [0, 1, 2]
    assert rendered_edge_counts == [5, 7, 8]
    assert [len(patch["add_edges"]) for patch in applied_patches] == [2, 1]
    assert result["graph_repair_round_count"] == 2
    assert result["graph_publication"] == "approved"
    assert {edge["label"] for edge in result["graph_data"]["edges"]} >= {
        item["required_contract"]
        for item in [*initial_obligations, *second_obligations]
    }
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

    async def fake_review(state, **_kwargs):
        if state.get("graph_contract_correction_pending"):
            review_budget = _kwargs["review_budget"]
            review_budget.claim_provider_call(correction="contract")
            call_order.append("critic-contract-correction")
            assert state["graph_patch_validation_error"] == {
                "path": "layers.composition.group_ids",
                "rule": "group_membership_scope",
            }
            return {
                **state,
                **review_budget.state_counters(),
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

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_synth(state):
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
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
async def test_protocol_correction_does_not_consume_patch_contract_correction_budget(
    monkeypatch,
):
    import agent.graph as agent_graph
    from agent.graph_review_budget import GraphReviewBudget

    call_order = []

    async def send(_event):
        return None

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "bounded repair workflow"}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_apply(state, _tools):
        revision_count = int(state.get("graph_revision_count", 0))
        call_order.append(f"kimi-{revision_count}")
        if call_order == [
            "kimi-0",
            "critic-initial",
            "critic-protocol-correction",
            "kimi-1",
        ]:
            return {
                **state,
                "graph_changed": False,
                "graph_operation": {
                    "kind": "create",
                    "status": "failed",
                    "failure_code": "graph_patch_invalid_preserved_existing_graph",
                },
                "graph_patch_validation_error": {
                    "path": "patch.add_edges",
                    "rule": "addition_obligation_mismatch",
                },
            }
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": "Initial candidate"
                if revision_count == 0
                else "Corrected repair",
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

    async def fake_review(state, *, review_budget):
        if state.get("graph_contract_correction_pending"):
            assert state["graph_patch_validation_error"] == {
                "path": "patch.add_edges",
                "rule": "addition_obligation_mismatch",
            }
            review_budget.claim_provider_call(correction="contract")
            call_order.append("critic-contract-correction")
            return {
                **state,
                **review_budget.state_counters(),
                "graph_review": {"approved": False, "terminal": False},
                "graph_operation": {
                    "kind": "create",
                    "status": "candidate",
                    "failure_code": None,
                },
            }
        if state.get("graph_repair_round_count", 0) == 1:
            review_budget.claim_provider_call(correction=None)
            call_order.append("critic-final")
            return {
                **state,
                **review_budget.state_counters(),
                "graph_review": {"approved": True},
            }

        review_budget.claim_provider_call(correction=None)
        call_order.append("critic-initial")
        review_budget.claim_provider_call(correction="protocol")
        call_order.append("critic-protocol-correction")
        return {
            **state,
            **review_budget.state_counters(),
            "graph_review": {"approved": False, "terminal": False},
        }

    async def fake_synth(state):
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    budget = GraphReviewBudget()
    state = _state(send)
    state["_graph_review_budget"] = budget
    result = await agent_graph.run_agent(state, [], [], [])

    assert call_order == [
        "kimi-0",
        "critic-initial",
        "critic-protocol-correction",
        "kimi-1",
        "critic-contract-correction",
        "kimi-1",
        "critic-final",
    ]
    assert budget.critic_calls == 4
    assert result["graph_repair_round_count"] == 1
    assert result["graph_operation"]["status"] == "applied"
    assert result["graph_publication"] == "approved"
    assert result["graph_data"]["title"] == "Corrected repair"


@pytest.mark.asyncio
async def test_malformed_patch_correction_and_two_repairs_stay_within_all_ceilings(
    monkeypatch,
):
    import agent.graph as agent_graph
    from agent.graph_review_budget import GraphReviewBudget
    from config import (
        GRAPH_MAX_CONTRACT_CORRECTIONS,
        GRAPH_MAX_CRITIC_CALLS,
        GRAPH_MAX_REPAIR_ROUNDS,
    )

    apply_rounds = []
    review_rounds = []

    async def send(_event):
        return None

    def layer(*, failed=False):
        return {
            "status": "fail" if failed else "pass",
            "score": 0.7 if failed else 0.9,
            "blocking_findings": ["Repair the graph title."] if failed else [],
            "deterministic_finding_ids": [],
            "node_ids": [],
            "edge_selectors": [],
            "group_ids": [],
            "composition_fields": ["title"] if failed else [],
            "sequence_indexes": [],
            "assumption_indexes": [],
            "reason": "The layer was reviewed against the complete candidate.",
            "context_node_ids": [],
            "addition_count": 0,
            "connection_addition_obligations": [],
            "composition_append_counts": {},
        }

    def local_contract():
        return {
            "repair_scope": "local",
            "layers": {
                "components": layer(),
                "connections": layer(),
                "composition": layer(failed=True),
                "render": layer(),
            },
        }

    async def fake_route(state):
        return {**state, "route": "search"}

    async def fake_search(state, _tools):
        return state, None

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "bounded review workflow"}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_apply(state, _tools):
        revision = int(state.get("graph_revision_count", 0))
        apply_rounds.append(revision)
        if revision == 0:
            title = "Initial candidate"
        elif apply_rounds == [0, 1]:
            return {
                **state,
                "graph_changed": False,
                "graph_operation": {
                    "kind": "create",
                    "status": "failed",
                    "failure_code": "graph_patch_invalid_preserved_existing_graph",
                },
                "graph_patch_validation_error": {
                    "path": "patch",
                    "rule": "json_decode",
                },
            }
        else:
            title = f"Successful repair {revision}"
        return {
            **state,
            "graph_changed": True,
            "graph_data": {
                "design_origin": "applied",
                "title": title,
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

    async def fake_review(state, *, review_budget):
        correction = bool(state.get("graph_contract_correction_pending"))
        review_budget.claim_provider_call(correction="contract" if correction else None)
        repair_round = int(state.get("graph_repair_round_count", 0))
        review_rounds.append((repair_round, correction))
        if repair_round == GRAPH_MAX_REPAIR_ROUNDS:
            return {
                **state,
                **review_budget.state_counters(),
                "graph_review": {
                    "approved": True,
                    "review_status": "completed",
                    "repair_contract": {"repair_scope": "none"},
                },
            }
        return {
            **state,
            **review_budget.state_counters(),
            "graph_review": {
                "approved": False,
                "terminal": False,
                "review_status": "completed",
                "repair_contract": local_contract(),
            },
            "graph_operation": {
                "kind": "create",
                "status": "candidate",
                "failure_code": None,
            },
        }

    async def fake_synth(state):
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)

    budget = GraphReviewBudget()
    state = _state(send)
    state["_graph_review_budget"] = budget
    result = await agent_graph.run_agent(state, [], [], [])

    assert apply_rounds == [0, 1, 1, 2]
    assert review_rounds == [(0, False), (0, True), (1, False), (2, False)]
    assert budget.critic_calls == GRAPH_MAX_CRITIC_CALLS == 4
    assert budget.contract_corrections == GRAPH_MAX_CONTRACT_CORRECTIONS == 1
    assert result["graph_critic_call_count"] == budget.critic_calls
    assert result["graph_contract_correction_count"] == budget.contract_corrections
    assert result["graph_repair_round_count"] == GRAPH_MAX_REPAIR_ROUNDS == 2
    assert result["graph_publication"] == "approved"
    assert result["graph_data"]["title"] == "Successful repair 2"


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

    async def fake_review(incoming_state, **_kwargs):
        return {**incoming_state, "graph_review": {"approved": False, "terminal": True}}

    async def fake_synth(incoming_state):
        return {**incoming_state, "response_text": "ok"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)

    async def fake_architect(_incoming_state):
        return {}

    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)

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

    async def fake_review(incoming_state, **_kwargs):
        return {**incoming_state, "graph_review": {"approved": True}}

    async def fake_synth(incoming_state):
        return {**incoming_state, "response_text": "ok"}

    async def fake_architect(_incoming_state):
        return {}

    async def fake_expand(incoming_state, _graph_tools, _search_tool_wait_task):
        return incoming_state

    monkeypatch.setattr(agent_graph, "resolve_graph_operation", lambda *_args: "edit")
    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
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

    async def fake_review(incoming_state, **_kwargs):
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

    async def fake_expand(incoming_state, _graph_tools, _search_tool_wait_task):
        return incoming_state

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply_graph)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
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
                    "path": "groups.group_1.group_2",
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

    async def fake_review(state, **_kwargs):
        if state.get("graph_repair_round_count", 0) == 0 and not state.get(
            "graph_contract_correction_pending"
        ):
            return {
                **state,
                "graph_review": {"approved": False, "terminal": False},
            }
        if state.get("graph_contract_correction_pending"):
            assert state["graph_data"] == initial_candidate
            assert state["graph_changed"] is True
            assert state["graph_publication"] == "unreviewed"
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
            "repair_contract": {
                "repair_scope": "local",
                "layers": {
                    "composition": {"group_ids": ["group_1", "group_2"]},
                },
            },
            "topology_proofs": [],
        }

    async def fake_render(_graph):
        return {"report": {}}

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "test design"}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_synth(state):
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "resolve_graph_operation", lambda *_args: "create")
    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
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


@pytest.mark.asyncio
async def test_contract_correction_approval_publishes_the_retained_private_candidate(
    monkeypatch,
):
    import agent.graph as agent_graph

    candidate = {
        "design_origin": "applied",
        "title": "Initial candidate",
        "nodes": [],
        "edges": [],
        "sequence": [],
        "version": "candidate-v1",
    }
    apply_rounds = []

    async def send(_event):
        return None

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
                "graph_data": candidate,
                "graph_changed": True,
                "graph_operation": {
                    "kind": "create",
                    "status": "candidate",
                    "failure_code": None,
                },
            }
        assert revision_count == 1
        return {
            **state,
            "graph_data": candidate,
            "graph_changed": False,
            "graph_operation": {
                "kind": "create",
                "status": "failed",
                "failure_code": "graph_patch_invalid_preserved_existing_graph",
            },
            "graph_patch_validation_error": {
                "path": "groups.runtime",
                "rule": "locked_record_changed",
            },
        }

    async def fake_architect(_state):
        return {"architect_plan": {"interpretation": "test design"}}

    async def fake_expand(state, _tools, _wait_task):
        return state

    async def fake_review(state, **_kwargs):
        if state.get("graph_contract_correction_pending"):
            assert state["graph_data"] == candidate
            assert state["graph_changed"] is True
            assert state["graph_publication"] == "unreviewed"
            return {
                **state,
                "graph_review": {"approved": True, "review_status": "completed"},
                "graph_operation": {
                    "kind": "create",
                    "status": "candidate",
                    "failure_code": None,
                },
            }
        return {
            **state,
            "graph_review": {
                "approved": False,
                "review_status": "completed",
                "repair_contract": {"repair_scope": "local"},
            },
        }

    async def fake_synth(state):
        assert state["graph_data"] == candidate
        assert state["graph_changed"] is True
        assert state["graph_publication"] == "approved"
        assert state["graph_operation"]["status"] == "applied"
        return {**state, "response_text": "reviewed answer"}

    monkeypatch.setattr(agent_graph, "orchestrator_route", fake_route)
    monkeypatch.setattr(agent_graph, "run_search_phase", fake_search)
    monkeypatch.setattr(agent_graph, "architect_node", fake_architect)
    monkeypatch.setattr(agent_graph, "maybe_expand_with_search_tool", fake_expand)
    monkeypatch.setattr(agent_graph, "apply_graph_worker", fake_apply)
    monkeypatch.setattr(agent_graph, "graph_critic_node", fake_review)
    monkeypatch.setattr(agent_graph, "orchestrator_synthesise", fake_synth)
    monkeypatch.setattr(
        agent_graph, "validate_local_repair_admission", lambda *_args, **_kwargs: None
    )

    result = await agent_graph.run_agent(_state(send), [], [], [])

    assert apply_rounds == [0, 1]
    assert result["graph_publication"] == "approved"
    assert result["graph_changed"] is True
