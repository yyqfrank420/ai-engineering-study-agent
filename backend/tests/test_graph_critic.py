import json

import pytest

from agent.nodes.graph_critic import (
    _GRAPH_CRITIC_SYSTEM,
    _deterministic_render_review,
    _deterministic_review,
    _merge_reviews,
    _normalise_review,
    _reconcile_objective_render_claims,
    graph_critic_node,
)


def _domain_graph():
    return {
        "design_origin": "applied",
        "nodes": [
            {"label": "Campaign Objective", "description": "Defines ROAS objective and spend constraints"},
            {"label": "Event Quality Gate", "description": "Validates conversion and attribution events"},
            {"label": "Creative Optimizer", "description": "Chooses copy variants for an audience"},
            {"label": "Approval Policy", "description": "Approves risky actions and writes an audit record"},
            {"label": "Channel Executor", "description": "Applies idempotent targeting and bid changes"},
            {"label": "Outcome Attribution", "description": "Observes attributed revenue and campaign outcomes"},
        ],
        "edges": [
            {
                "source": "outcome",
                "target": "objective",
                "label": "returns attributed outcomes",
                "description": "Closes the measured optimization loop",
                "type": "loop",
            }
        ],
    }


def test_deterministic_review_accepts_a_domain_control_loop():
    review = _deterministic_review(
        "Design a growth marketing agent that optimizes campaign attribution",
        _domain_graph(),
        "prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []
    assert review["score"] >= 0.78


def test_deterministic_gate_does_not_guess_semantics_from_prose_vocabulary():
    graph = _domain_graph()
    graph["nodes"][-1] = {
        "label": "Outcome Evaluator",
        "description": "Computes campaign performance metrics for the feedback loop",
    }

    review = _deterministic_review(
        "Design a production growth marketing agent for campaign performance",
        graph,
        "production",
    )

    assert review["approved"] is True
    assert review["missing"] == []


def test_generic_book_vocabulary_is_rejected_before_publication():
    graph = {
        "nodes": [
            {"label": label, "description": "Generic book concept"}
            for label in (
                "Agent", "Tool Use", "Planning", "Evaluation", "Foundation Model", "Generation"
            )
        ],
        "edges": [{
            "source": "agent",
            "target": "planning",
            "label": "returns measured outcome",
            "type": "loop",
        }],
    }

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("generic book concepts" in item for item in review["missing"])


def test_one_standalone_generic_label_is_rejected_before_publication():
    graph = _domain_graph()
    graph["nodes"][0] = {"label": "Agent", "description": "Owns the campaign objective"}

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "prototype",
    )

    assert review["approved"] is False
    assert any("generic book concepts" in item for item in review["missing"])


def test_disconnected_architecture_is_rejected_before_publication():
    graph = _domain_graph()
    graph["nodes"] = [
        {**node, "id": f"node_{index}"}
        for index, node in enumerate(graph["nodes"])
    ]

    review = _deterministic_review(
        "Design a growth marketing optimization system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("Connect every component" in item for item in review["missing"])


def test_read_only_design_does_not_invent_an_external_write_boundary():
    graph = {
        "nodes": [
            {"label": "Research Request", "description": "Captures the research question"},
            {"label": "Evidence Retriever", "description": "Retrieves cited source passages"},
            {"label": "Answer Composer", "description": "Builds a grounded answer"},
            {"label": "Quality Feedback", "description": "Observes answer quality and user outcomes"},
        ],
        "edges": [
            {
                "source": "feedback",
                "target": "composer",
                "label": "returns quality outcomes",
                "description": "Closes the measured research quality loop",
                "type": "loop",
            }
        ],
    }

    review = _deterministic_review(
        "Design a research assistant system",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert not any("approval" in item for item in review["missing"])


def test_model_cannot_override_a_failed_local_quality_gate():
    local = {"approved": False, "score": 0.7, "missing": ["Missing approval"], "strengths": []}
    model = _normalise_review({"approved": True, "score": 0.95, "missing": [], "strengths": ["Looks good"]})

    merged = _merge_reviews(local, model)

    assert merged["approved"] is False
    assert merged["score"] == 0.7
    assert merged["missing"] == ["Missing approval"]


def test_review_requires_a_json_boolean_and_string_lists():
    review = _normalise_review({
        "approved": "false",
        "score": 0.99,
        "missing": [{"not": "a string"}],
        "strengths": ["Specific", 123],
    })

    assert review["approved"] is False
    assert review["missing"] == []
    assert review["strengths"] == ["Specific"]


def test_optional_model_advice_does_not_block_a_publishable_diagram():
    local = {"approved": True, "score": 0.92, "missing": [], "strengths": ["Safe boundary"]}
    model = _normalise_review({
        "approved": True,
        "score": 0.84,
        "blocking_failures": [],
        "advice": ["Consider a secondary on-call route."],
        "strengths": ["Domain specific"],
    })

    merged = _merge_reviews(local, model)

    assert merged["approved"] is True
    assert merged["missing"] == []
    assert merged["advice"] == ["Consider a secondary on-call route."]


def test_explicit_model_blocking_failure_still_rejects_the_diagram():
    review = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": ["The requested rollback path is absent."],
        "advice": [],
    })

    assert review["approved"] is False
    assert review["missing"] == ["The requested rollback path is absent."]


def test_render_gate_rejects_overlap_clipping_or_missing_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(graph, {
        "report": {
            "rendered_nodes": 2,
            "rendered_edges": 0,
            "overlap_count": 1,
            "clipped_nodes": 1,
            "clipped_edges": 1,
            "minimum_text_px": 8,
        },
    })

    assert review["approved"] is False
    assert review["terminal"] is True
    assert any("actual candidate" in item for item in review["missing"])
    assert any("overlapping" in item for item in review["missing"])


def test_render_gate_accepts_a_complete_readable_browser_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(graph, {
        "screenshot_base64": "valid-bounded-image",
        "report": {
            "rendered_nodes": 2,
            "rendered_edges": 0,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 7,
        },
    })

    assert review["approved"] is True
    assert review["terminal"] is False


def test_render_gate_rejects_missing_overview_and_group_labels_or_overlapping_zones():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}]}
    review = _deterministic_render_review(graph, {
        "screenshot_base64": "valid-bounded-image",
        "report": {
            "rendered_nodes": 2,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 7,
            "overview_required_edge_labels": 1,
            "visible_overview_required_edge_labels": 0,
            "grouped_nodes": 2,
            "group_labelled_nodes": 1,
            "visible_group_boundaries": 2,
            "group_boundary_overlap_count": 1,
        },
    })

    assert review["approved"] is False
    assert review["terminal"] is True
    assert any("overview-required edge label" in item for item in review["missing"])
    assert any("group label on every node" in item for item in review["missing"])
    assert any("responsibility-zone boundaries" in item for item in review["missing"])


def test_render_gate_accepts_legacy_reports_without_new_visual_metrics():
    graph = {"nodes": [{"id": "a"}], "edges": []}
    review = _deterministic_render_review(graph, {
        "screenshot_base64": "legacy-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 0,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 7,
        },
    })

    assert review["approved"] is True


def test_complete_browser_geometry_downgrades_a_contradicted_clipping_claim():
    graph = {"nodes": [{"id": "store"}], "edges": [{"source": "store", "target": "store"}]}
    model = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": [
            "Re-lay out the Document Store so all edges are fully visible within the canvas, with no clipped connections."
        ],
        "revision_instruction": "Move the clipped Document Store on-screen.",
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is True
    assert reconciled["missing"] == []
    assert reconciled["revision_instruction"] == ""
    assert "Unreproduced visual concern" in reconciled["advice"][0]


def test_complete_browser_geometry_owns_font_scale_and_zoom_claims():
    graph = {"nodes": [{"id": "store"}], "edges": [{"source": "store", "target": "store"}]}
    model = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": [
            "Re-render at a larger scale so node titles and edge labels are clearly legible without zooming."
        ],
        "revision_instruction": "Increase the font size and node dimensions.",
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is True
    assert reconciled["missing"] == []
    assert "Unreproduced visual concern" in reconciled["advice"][0]


def test_browser_geometry_does_not_override_a_real_clipped_edge():
    graph = {"nodes": [{"id": "store"}], "edges": [{"source": "store", "target": "store"}]}
    model = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": ["One edge is clipped outside the canvas."],
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 1,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is False
    assert reconciled["missing"] == ["One edge is clipped outside the canvas."]


def test_visual_revision_instruction_cannot_hide_a_remaining_semantic_failure():
    graph = {"nodes": [{"id": "executor"}], "edges": []}
    model = _normalise_review({
        "approved": False,
        "score": 0.6,
        "blocking_failures": [
            "Increase the font size for legibility.",
            "The executor has no rollback boundary.",
        ],
        "revision_instruction": "Zoom the canvas and use a larger font.",
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 0,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is False
    assert reconciled["missing"] == ["The executor has no rollback boundary."]
    assert reconciled["revision_instruction"] == "The executor has no rollback boundary."


@pytest.mark.asyncio
async def test_semantic_critic_never_receives_the_rendered_image(monkeypatch):
    captured = {}

    async def fake_stream_llm(**kwargs):
        captured.update(kwargs)
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["Domain responsibilities are explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        })

    async def send(_event):
        return None

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render-must-not-reach-the-semantic-model",
            "report": {
                "rendered_nodes": 6,
                "rendered_edges": 1,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    graph = _domain_graph()
    graph["design_origin"] = "applied"
    result = await graph_critic_node({
        "graph_data": graph,
        "graph_changed": True,
        "user_message": "Design a production growth marketing agent system",
        "evidence_bundle": {
            "checklist": [{"area": "evaluation", "question": "Measure outcomes"}],
            "book_evidence": [{"chapter": 1, "page_number": 8, "text": "Evaluate measured outcomes."}],
            "research_context": "- [Current source](https://example.com): current evidence",
        },
        "complexity": "production",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert isinstance(captured["messages"][0]["content"], str)
    assert "private-render-must-not-reach-the-semantic-model" not in captured["messages"][0]["content"]
    assert "Browser layout report" not in captured["messages"][0]["content"]
    assert "Supplied evidence allowlist" in captured["messages"][0]["content"]
    assert "https://example.com" in captured["messages"][0]["content"]
    assert "Do not assess or mention" in _GRAPH_CRITIC_SYSTEM


@pytest.mark.asyncio
async def test_terse_followup_still_reviews_every_changed_applied_graph(monkeypatch):
    calls = {"critic": 0, "render": 0}

    async def fake_stream_llm(**_kwargs):
        calls["critic"] += 1
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The requested approval path remains domain specific."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        })

    async def await_diagram(graph):
        calls["render"] += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "expand the approval path",
        "design_query": "growth marketing multi-agent system expand the approval path",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert calls == {"critic": 1, "render": 1}


@pytest.mark.asyncio
async def test_hard_render_failure_skips_the_paid_semantic_critic(monkeypatch):
    async def fail_stream_llm(**_kwargs):
        raise AssertionError("hard deterministic failures must not spend a critic call")

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": 5,
                "rendered_edges": 1,
                "overlap_count": 1,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fail_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is False
    assert any("overlapping" in item for item in result["graph_review"]["missing"])
