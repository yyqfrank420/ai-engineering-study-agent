from agent.nodes.graph_critic import (
    _deterministic_render_review,
    _deterministic_review,
    _merge_reviews,
    _normalise_review,
    _reconcile_objective_render_claims,
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


def test_production_review_recognises_measured_outcomes_as_observability():
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
    assert not any("observability" in item for item in review["missing"])


def test_deterministic_review_rejects_the_reported_generic_taxonomy():
    graph = {
        "nodes": [
            {"label": label, "description": "Generic book concept"}
            for label in (
                "Agent", "Tool Use", "Planning", "Evaluation", "Foundation Model", "Generation"
            )
        ],
        "edges": [{"source": "agent", "target": "planning", "label": "depends on"}],
    }

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("generic AI taxonomy" in item for item in review["missing"])
    assert any("feedback edge" in item for item in review["missing"])


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
