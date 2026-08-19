"""State-machine coverage for the staged applied-graph pipeline."""

from __future__ import annotations

import copy

import pytest

from agent import staged_graph_workflow as workflow
from agent.staged_graph_contract import (
    assign_server_ids,
    component_fingerprint,
    project_graph_data,
)


def _components_wire() -> dict:
    return {
        "title": "Payment processing",
        "assumptions": ["The caller is authenticated."],
        "root_index": 0,
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "components": [
            {
                "label": "Request gateway",
                "type": 104,
                "responsibility": "Accepts the payment request.",
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            },
            {
                "label": "Payment service",
                "type": 101,
                "responsibility": "Processes the payment request.",
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            },
        ],
    }


def _connections_wire() -> dict:
    return {
        "edges": [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "submits payment",
                "flow": 400,
                "sync": 500,
            }
        ]
    }


def _state(**overrides: object) -> dict:
    state = {
        "request_id": "request-1",
        "user_message": "Draw a payment system.",
        "design_query": "Draw a payment system.",
        "complexity": "prototype",
        "graph_intent": "create",
        "graph_operation": {
            "kind": "create",
            "status": "candidate",
            "failure_code": None,
        },
        "is_applied_design": True,
        "graph_mode": "auto",
        "evidence_bundle": {},
        "graph_stage_preview_count": 0,
    }
    state.update(overrides)
    return state


def _approved_graph(*, maturity: str = "prototype") -> dict:
    return {
        "graph_type": "architecture",
        "title": "Approved payment processing",
        "nodes": [
            {
                "id": "n1",
                "label": "Request gateway",
                "type": "gateway",
                "technology": "Gateway",
                "description": "Accepts the payment request.",
                "tier": None,
                "detail": None,
            },
            {
                "id": "n2",
                "label": "Payment service",
                "type": "service",
                "technology": "Service",
                "description": "Processes the payment request.",
                "tier": None,
                "detail": None,
            },
        ],
        "edges": [
            {
                "source": "n1",
                "target": "n2",
                "label": "submits payment",
                "technology": "HTTPS",
                "sync": "sync",
                "description": "submits payment",
                "flow": "runtime",
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["n1"], "description": "entry"},
            {"step": 2, "nodes": ["n2"], "description": "process"},
        ],
        "groups": [
            {
                "id": "group_runtime",
                "label": "Runtime",
                "kind": "runtime",
                "nodeIds": ["n1", "n2"],
            }
        ],
        "design_origin": "applied",
        "resolved_complexity": maturity,
        "assumptions": ["The caller is authenticated."],
        "version": "approved-v1",
    }


def _accepted_staged_graph(*, maturity: str = "prototype") -> dict:
    graph = project_graph_data(
        assign_server_ids(
            {
                "request_id": "approved-request",
                "title": "Payment processing",
                "assumptions": ["The caller is authenticated."],
                "root_index": 0,
                "capabilities": {
                    "external_effects": False,
                    "retrieval_or_reuse": False,
                    "learning_or_release": False,
                },
                "components": [
                    {
                        "model_index": 0,
                        "label": "Request gateway",
                        "type": "gateway",
                        "responsibility": "Accepts the payment request.",
                        "group_label": "Runtime",
                        "group_kind": "runtime",
                        "primary_flow_member": True,
                    },
                    {
                        "model_index": 1,
                        "label": "Payment service",
                        "type": "service",
                        "responsibility": "Processes the payment request.",
                        "group_label": "Runtime",
                        "group_kind": "runtime",
                        "primary_flow_member": True,
                    },
                ],
                "connections": [
                    {
                        "source_id": "0",
                        "target_id": "1",
                        "label": "submits payment",
                        "flow": "runtime",
                        "sync": "sync",
                    }
                ],
                "maturity": maturity,
                "source": "staged",
                "stage": "accepted",
            }
        )
    )
    graph["version"] = "approved-v1"
    return graph


async def _render_ok(state: dict, graph: dict, *, preview_count: int) -> dict:
    return {
        **state,
        "graph_data": copy.deepcopy(graph),
        "graph_render_admitted": True,
        "graph_stage_preview_count": preview_count + 1,
    }


def _approved_gate() -> dict:
    return {
        "approved": True,
        "terminal": False,
        "findings": [],
        "proofs": [],
        "diagnostics": [],
    }


def _rejected_gate(*, terminal: bool = False) -> dict:
    return {
        "approved": False,
        "terminal": terminal,
        "findings": [
            {"rule_code": "domain_specificity", "reason": "Missing domain ownership."}
        ],
        "proofs": [],
        "diagnostics": [],
    }


def _rejected_gate_with_findings(
    findings: list[dict[str, object]], *, terminal: bool = False
) -> dict:
    return {
        "approved": False,
        "terminal": terminal,
        "findings": findings,
        "proofs": [],
        "diagnostics": [],
    }


async def _approve_gate(**_kwargs) -> dict:
    return _approved_gate()


def _install_success_boundaries(monkeypatch, *, events: list[object] | None = None):
    async def components(**_kwargs):
        if events is not None:
            events.append("components")
        return {"wire": _components_wire(), "prompt_fingerprint": "component-prompt"}

    async def connections(**_kwargs):
        if events is not None:
            events.append("connections")
        return {"wire": _connections_wire(), "prompt_fingerprint": "connection-prompt"}

    async def render(state, graph, *, preview_count):
        if events is not None:
            events.append(("render", len(graph["edges"])))
        return await _render_ok(state, graph, preview_count=preview_count)

    async def component_gate(**_kwargs):
        if events is not None:
            events.append("component_gate")
        return _approved_gate()

    async def connection_gate(**_kwargs):
        if events is not None:
            events.append("connection_gate")
        return _approved_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)


def test_selector_only_enables_staged_applied_graph_turns(monkeypatch):
    monkeypatch.setattr(workflow.settings, "graph_pipeline_mode", "staged")
    assert workflow.should_use_staged_graph_pipeline(_state()) is True
    assert (
        workflow.should_use_staged_graph_pipeline(_state(is_applied_design=False))
        is False
    )
    assert (
        workflow.should_use_staged_graph_pipeline(_state(graph_intent="none")) is False
    )
    assert workflow.should_use_staged_graph_pipeline(_state(graph_mode="off")) is False
    monkeypatch.setattr(workflow.settings, "graph_pipeline_mode", "legacy")
    assert workflow.should_use_staged_graph_pipeline(_state()) is False


@pytest.mark.asyncio
async def test_component_gate_retries_at_most_twice_and_renders_each_candidate(
    monkeypatch,
):
    calls: list[object] = []
    component_inputs: list[dict] = []

    async def components(**kwargs):
        calls.append("components")
        component_inputs.append(copy.deepcopy(kwargs))
        wire = _components_wire()
        if calls.count("components") == 2:
            wire["components"][1]["responsibility"] = (
                "Processes and records the payment request."
            )
        return {
            "wire": wire,
            "prompt_fingerprint": f"component-{len(calls)}",
        }

    async def render(state, graph, *, preview_count):
        calls.append(("render", len(graph["edges"])))
        return await _render_ok(state, graph, preview_count=preview_count)

    async def component_gate(**_kwargs):
        calls.append("component_gate")
        return _rejected_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "review_components", component_gate)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert calls == [
        "components",
        ("render", 0),
        "component_gate",
        "components",
        ("render", 0),
        "component_gate",
    ]
    assert component_inputs[0]["rejected_candidate"] is None
    assert component_inputs[1]["rejected_candidate"] == _components_wire()
    assert component_inputs[1]["attempt"] == 1
    assert component_inputs[1]["prior_prompt_fingerprint"] == "component-1"
    assert component_inputs[0]["write_set"] == component_inputs[1]["write_set"]
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_component_attempts_exhausted"
    )


@pytest.mark.asyncio
async def test_identical_component_correction_is_not_reviewed_twice(monkeypatch):
    generation_calls = 0
    gate_calls = 0
    events: list[dict] = []
    analytics: list[dict] = []

    async def send(event):
        events.append(event)

    async def components(**_kwargs):
        nonlocal generation_calls
        generation_calls += 1
        return {"wire": _components_wire(), "prompt_fingerprint": "c" * 64}

    async def component_gate(**_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        return _rejected_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(
        workflow, "enqueue_analytics_event", lambda **event: analytics.append(event)
    )
    monkeypatch.setattr(
        workflow.settings, "internal_test_email_allowlist_raw", "eval@example.com"
    )

    result = await workflow.run_staged_graph_pipeline(
        _state(user_email="eval@example.com", send=send)
    )

    assert generation_calls == 2
    assert gate_calls == 1
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_component_attempts_exhausted"
    )
    diagnostic = result["graph_review"]["staged_failure"]
    assert result["graph_review_diagnostics"] == [
        events[0]["diagnostic"],
        diagnostic,
    ]
    assert events[-1]["diagnostic"] == diagnostic
    assert diagnostic["stage"] == "components"
    assert diagnostic["attempt"] == 2
    assert diagnostic["code"] == "candidate_repeated"
    assert diagnostic["path"] == "components"
    assert diagnostic["fingerprint_disposition"] == "matches_prior_candidate"
    assert len(diagnostic["candidate_fingerprint"]) == 64
    assert "Request gateway" not in repr(diagnostic)
    assert analytics[0]["event_name"] == "staged_graph_failure"
    assert "path" not in analytics[0]["properties"]


@pytest.mark.asyncio
async def test_final_component_gate_rejection_returns_review_and_safe_gate_diagnostic(
    monkeypatch,
):
    component_calls = 0
    analytics: list[dict] = []
    events: list[dict] = []

    gate_findings = [
        {
            "rule_code": "domain_specificity",
            "record_indexes": [0, 1, 0, -1, 9, True, "2"],
            "reason": "Missing domain ownership.",
        },
        {"rule_code": "brief_coverage", "record_indexes": "secret-raw-index"},
        {"rule_code": "invented_rule", "record_indexes": [0]},
    ]
    stage_gate = _rejected_gate_with_findings(gate_findings)

    async def components(**_kwargs):
        nonlocal component_calls
        component_calls += 1
        wire = _components_wire()
        if component_calls == 2:
            wire["components"][0]["responsibility"] = "secret-" + ("x" * 60)
        return {"wire": wire, "prompt_fingerprint": f"component-{component_calls}"}

    async def component_gate(**_kwargs):
        return stage_gate

    async def send(event):
        events.append(event)

    async def render(state, graph, *, preview_count):
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(
        workflow, "enqueue_analytics_event", lambda **event: analytics.append(event)
    )
    monkeypatch.setattr(
        workflow.settings, "internal_test_email_allowlist_raw", "internal@openai.com"
    )

    result = await workflow.run_staged_graph_pipeline(
        _state(user_email="internal@openai.com", send=send)
    )

    assert component_calls == 2
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_component_attempts_exhausted"
    )
    assert result["graph_review"]["staged_gate"] == stage_gate
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["schema_version"] == 1
    assert diagnostic["kind"] == "staged_gate"
    assert diagnostic["stage"] == "components"
    assert diagnostic["attempt"] == 2
    assert diagnostic["code"] == "gate_rejected"
    assert len(diagnostic["candidate_fingerprint"]) == 64
    assert diagnostic["findings"] == [
        {
            "rule_code": "domain_specificity",
            "record_paths": ["components.0", "components.1"],
        },
        {"rule_code": "brief_coverage", "record_paths": ["components"]},
    ]
    assert set(diagnostic["findings"][0].keys()) == {"rule_code", "record_paths"}
    assert "secret-" not in repr(diagnostic)
    diagnostics = result["graph_review_diagnostics"]
    assert len(diagnostics) == 2
    assert [item["attempt"] for item in diagnostics] == [1, 2]
    assert diagnostics[-1] == diagnostic
    assert [event.get("diagnostic") for event in events] == diagnostics
    assert [event["status"] for event in events] == ["retry", "rejected"]
    for event in events:
        assert event["type"] == "workflow_progress"
        assert event["phase"] == "review"
        assert "Missing domain ownership." not in repr(event)
        assert "secret-" not in repr(event)
        assert "record_indexes" not in repr(event)
    assert analytics[0]["properties"] == diagnostic
    assert "secret-" not in repr(analytics[0])


@pytest.mark.asyncio
async def test_malformed_component_gate_is_terminal_without_retry(monkeypatch):
    calls = 0

    async def components(**_kwargs):
        nonlocal calls
        calls += 1
        return {"wire": _components_wire(), "prompt_fingerprint": "component-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", _render_ok)

    async def malformed_gate(**_kwargs):
        return _rejected_gate(terminal=True)

    monkeypatch.setattr(workflow, "review_components", malformed_gate)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert calls == 1
    assert (
        result["graph_operation"]["failure_code"] == "staged_component_gate_unavailable"
    )
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["code"] == "gate_unavailable"
    assert diagnostic["stage"] == "components"
    assert diagnostic["attempt"] == 1


@pytest.mark.asyncio
async def test_malformed_connection_gate_retains_safe_terminal_diagnostic(monkeypatch):
    _install_success_boundaries(monkeypatch)

    async def malformed_gate(**_kwargs):
        return _rejected_gate_with_findings(
            [{"rule_code": "edge_semantics", "record_indexes": [0]}],
            terminal=True,
        )

    monkeypatch.setattr(workflow, "review_connections", malformed_gate)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert (
        result["graph_operation"]["failure_code"]
        == "staged_connection_gate_unavailable"
    )
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["code"] == "gate_unavailable"
    assert diagnostic["stage"] == "connections"
    assert diagnostic["attempt"] == 1
    assert diagnostic["findings"] == [
        {"rule_code": "edge_semantics", "record_paths": ["connections.0"]}
    ]


@pytest.mark.asyncio
async def test_component_contract_correction_receives_rejected_wire(monkeypatch):
    component_inputs: list[dict] = []
    rendered_edge_counts: list[int] = []
    _install_success_boundaries(monkeypatch)

    async def components(**kwargs):
        component_inputs.append(copy.deepcopy(kwargs))
        wire = _components_wire()
        if len(component_inputs) == 1:
            wire["components"][0]["label"] = "x" * 61
        return {
            "wire": wire,
            "prompt_fingerprint": f"component-{len(component_inputs)}",
        }

    async def render(state, graph, *, preview_count):
        rendered_edge_counts.append(len(graph["edges"]))
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert result["graph_publication"] == "approved"
    assert (
        component_inputs[1]["rejected_candidate"]["components"][0]["label"] == "x" * 61
    )
    assert rendered_edge_counts == [0, 1]
    assert len(result["graph_review_diagnostics"]) == 1
    assert result["graph_review_diagnostics"][0]["kind"] == "staged_generation"
    assert result["graph_review_diagnostics"][0]["stage"] == "components"
    assert result["graph_review_diagnostics"][0]["attempt"] == 1
    assert result["graph_review_diagnostics"][0]["code"] == "contract_rejected"


@pytest.mark.asyncio
async def test_successful_connection_contract_correction_retains_first_diagnostic(
    monkeypatch,
):
    connection_calls = 0
    render_calls = 0
    _install_success_boundaries(monkeypatch)

    async def connections(**_kwargs):
        nonlocal connection_calls
        connection_calls += 1
        wire = _connections_wire()
        if connection_calls == 1:
            wire["edges"][0]["target_index"] = 0
        return {
            "wire": wire,
            "prompt_fingerprint": f"connection-{connection_calls}",
        }

    async def render(state, graph, *, preview_count):
        nonlocal render_calls
        render_calls += 1
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", render)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert result["graph_publication"] == "approved"
    assert connection_calls == 2
    assert render_calls == 2
    assert len(result["graph_review_diagnostics"]) == 1
    diagnostic = result["graph_review_diagnostics"][0]
    assert diagnostic["kind"] == "staged_generation"
    assert diagnostic["stage"] == "connections"
    assert diagnostic["attempt"] == 1
    assert diagnostic["code"] == "contract_rejected"
    assert diagnostic["path"] == "connections.0"


@pytest.mark.asyncio
async def test_repeated_invalid_component_wire_stops_before_render(monkeypatch):
    generation_calls = 0
    render_calls = 0

    async def components(**_kwargs):
        nonlocal generation_calls
        generation_calls += 1
        wire = _components_wire()
        wire["components"][0]["label"] = "x" * 61
        return {"wire": wire, "prompt_fingerprint": f"component-{generation_calls}"}

    async def render(state, graph, *, preview_count):
        nonlocal render_calls
        render_calls += 1
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **_event: True)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert generation_calls == 2
    assert render_calls == 0
    assert result["graph_review"]["staged_failure"]["code"] == "candidate_repeated"


@pytest.mark.asyncio
async def test_final_component_contract_failure_retains_safe_coordinate(monkeypatch):
    generation_calls = 0
    render_calls = 0
    gate_calls = 0
    analytics: list[dict] = []

    async def components(**_kwargs):
        nonlocal generation_calls
        generation_calls += 1
        wire = _components_wire()
        if generation_calls == 2:
            wire["components"][0]["label"] = "secret-" + "x" * 60
        return {"wire": wire, "prompt_fingerprint": f"component-{generation_calls}"}

    async def render(state, graph, *, preview_count):
        nonlocal render_calls
        render_calls += 1
        return await _render_ok(state, graph, preview_count=preview_count)

    async def component_gate(**_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        return _rejected_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(
        workflow, "enqueue_analytics_event", lambda **event: analytics.append(event)
    )

    result = await workflow.run_staged_graph_pipeline(_state())

    assert generation_calls == 2
    assert render_calls == 1
    assert gate_calls == 1
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["code"] == "contract_rejected"
    assert diagnostic["path"] == "components.0.label"
    assert diagnostic["attempt"] == 2
    assert "secret" not in repr(diagnostic)
    assert "path" not in analytics[0]["properties"]


@pytest.mark.asyncio
async def test_connection_retry_keeps_the_accepted_component_candidate_locked(
    monkeypatch,
):
    component_calls = 0
    connection_inputs: list[dict] = []
    connection_gates = [_rejected_gate(), _approved_gate()]

    async def components(**_kwargs):
        nonlocal component_calls
        component_calls += 1
        return {"wire": _components_wire(), "prompt_fingerprint": "component-prompt"}

    async def connections(**kwargs):
        connection_inputs.append(copy.deepcopy(kwargs))
        wire = _connections_wire()
        if len(connection_inputs) == 2:
            wire["edges"][0]["label"] = "submits approved payment"
        return {
            "wire": wire,
            "prompt_fingerprint": f"connection-{len(connection_inputs)}",
        }

    async def component_gate(**_kwargs):
        return _approved_gate()

    async def connection_gate(**_kwargs):
        return connection_gates.pop(0)

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert component_calls == 1
    assert len(connection_inputs) == 2
    assert (
        connection_inputs[0]["accepted_components"]
        == connection_inputs[1]["accepted_components"]
    )
    assert connection_inputs[0]["accepted_components"][0] == {
        "index": 0,
        "id": "n1",
        "label": "Request gateway",
        "type": 104,
        "responsibility": "Accepts the payment request.",
        "primary_flow_member": True,
        "is_root": True,
    }
    assert connection_inputs[0]["accepted_context"] == {
        "assumptions": ["The caller is authenticated."],
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
    }
    assert (
        connection_inputs[0]["upstream_fingerprint"]
        == connection_inputs[1]["upstream_fingerprint"]
    )
    assert connection_inputs[0]["rejected_candidate"] is None
    assert connection_inputs[1]["rejected_candidate"] == _connections_wire()
    assert connection_inputs[0]["upstream_fingerprint"] == component_fingerprint(
        result["staged_graph_build"]
    )


@pytest.mark.parametrize("full_restage", [False, True])
@pytest.mark.asyncio
async def test_create_connection_correction_cannot_invent_unowned_control_flow(
    monkeypatch,
    full_restage,
):
    connection_calls = 0
    connection_gate_calls = 0
    render_calls = 0
    _install_success_boundaries(monkeypatch)

    async def connections(**_kwargs):
        nonlocal connection_calls
        connection_calls += 1
        wire = _connections_wire()
        if connection_calls == 2:
            wire["edges"].append(
                {
                    "source_index": 1,
                    "target_index": 0,
                    "label": "feed monitoring findings back to gate",
                    "flow": 401,
                    "sync": 501,
                }
            )
        return {
            "wire": wire,
            "prompt_fingerprint": f"connection-{connection_calls}",
        }

    async def connection_gate(**_kwargs):
        nonlocal connection_gate_calls
        connection_gate_calls += 1
        return _rejected_gate_with_findings(
            [
                {
                    "rule_code": "runtime_completeness",
                    "reason": "Connect monitoring to an outcome.",
                }
            ]
        )

    async def render(state, graph, *, preview_count):
        nonlocal render_calls
        render_calls += 1
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **_event: True)

    state = _state()
    if full_restage:
        previous_graph = _accepted_staged_graph(maturity="prototype")

        def reject_scoped_edit(*_args, **_kwargs):
            raise ValueError("full restage required")

        monkeypatch.setattr(workflow, "staged_edit_scope", reject_scoped_edit)
        state = _state(
            graph_intent="edit",
            complexity="production",
            user_message="Redesign the entire graph at production depth.",
            design_query="Redesign the entire graph at production depth.",
            approved_graph_data=previous_graph,
            graph_data=previous_graph,
            approved_graph_contract={
                "maturity": "prototype",
                "capabilities": {
                    "external_effects": False,
                    "retrieval_or_reuse": False,
                    "learning_or_release": False,
                },
            },
        )

    result = await workflow.run_staged_graph_pipeline(state)

    assert connection_calls == 2
    assert connection_gate_calls == 1
    assert render_calls == 2
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_connection_attempts_exhausted"
    )
    assert [item["attempt"] for item in result["graph_review_diagnostics"]] == [1, 2]
    final = result["graph_review"]["staged_failure"]
    assert final["kind"] == "staged_generation"
    assert final["code"] == "contract_rejected"
    assert final["path"] == "connections"
    assert "monitoring" not in repr(final)


@pytest.mark.parametrize("full_restage", [False, True])
@pytest.mark.asyncio
async def test_connection_correction_after_generation_error_cannot_invent_control_flow(
    monkeypatch,
    full_restage,
):
    connection_calls = 0
    connection_gate_calls = 0
    render_calls = 0
    _install_success_boundaries(monkeypatch)

    async def connections(**_kwargs):
        nonlocal connection_calls
        connection_calls += 1
        if connection_calls == 1:
            raise workflow.StagedGenerationError(
                "connection_wire_invalid",
                prompt_fingerprint="c" * 64,
            )
        wire = _connections_wire()
        wire["edges"].append(
            {
                "source_index": 1,
                "target_index": 0,
                "label": "feed monitoring findings back to gate",
                "flow": 401,
                "sync": 501,
            }
        )
        return {"wire": wire, "prompt_fingerprint": "connection-2"}

    async def connection_gate(**_kwargs):
        nonlocal connection_gate_calls
        connection_gate_calls += 1
        return _approved_gate()

    async def render(state, graph, *, preview_count):
        nonlocal render_calls
        render_calls += 1
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **_event: True)

    state = _state()
    if full_restage:
        previous_graph = _accepted_staged_graph(maturity="prototype")
        previous_graph["edges"][0] = {
            **previous_graph["edges"][0],
            "flow": "control",
        }

        def reject_scoped_edit(*_args, **_kwargs):
            raise ValueError("full restage required")

        monkeypatch.setattr(workflow, "staged_edit_scope", reject_scoped_edit)
        state = _state(
            graph_intent="edit",
            complexity="production",
            user_message="Redesign the entire graph at production depth.",
            design_query="Redesign the entire graph at production depth.",
            approved_graph_data=previous_graph,
            graph_data=previous_graph,
            approved_graph_contract={
                "maturity": "prototype",
                "capabilities": {
                    "external_effects": False,
                    "retrieval_or_reuse": False,
                    "learning_or_release": False,
                },
            },
        )

    result = await workflow.run_staged_graph_pipeline(state)

    assert connection_calls == 2
    assert connection_gate_calls == 0
    assert render_calls == 1
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_connection_attempts_exhausted"
    )
    assert [item["attempt"] for item in result["graph_review_diagnostics"]] == [1, 2]
    assert result["graph_review"]["staged_failure"]["code"] == "contract_rejected"
    assert result["graph_review"]["staged_failure"]["path"] == "connections"


@pytest.mark.asyncio
async def test_identical_connection_correction_retains_safe_coordinate(monkeypatch):
    connection_calls = 0
    connection_gate_calls = 0
    analytics: list[dict] = []
    _install_success_boundaries(monkeypatch)

    async def connections(**_kwargs):
        nonlocal connection_calls
        connection_calls += 1
        return {"wire": _connections_wire(), "prompt_fingerprint": "c" * 64}

    async def connection_gate(**_kwargs):
        nonlocal connection_gate_calls
        connection_gate_calls += 1
        return _rejected_gate()

    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    monkeypatch.setattr(
        workflow, "enqueue_analytics_event", lambda **event: analytics.append(event)
    )

    result = await workflow.run_staged_graph_pipeline(_state())

    assert connection_calls == 2
    assert connection_gate_calls == 1
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["stage"] == "connections"
    assert diagnostic["attempt"] == 2
    assert diagnostic["code"] == "candidate_repeated"
    assert diagnostic["path"] == "connections"
    assert diagnostic["fingerprint_disposition"] == "matches_prior_candidate"
    assert "path" not in analytics[0]["properties"]


@pytest.mark.asyncio
async def test_final_connection_gate_rejection_returns_review_and_safe_gate_diagnostic(
    monkeypatch,
):
    connection_calls = 0
    connection_gate_calls = 0
    events: list[dict] = []

    gate_findings = [
        {
            "rule_code": "edge_semantics",
            "record_indexes": [0],
            "reason": "Duplicate flow edge.",
        }
    ]
    stage_gate = _rejected_gate_with_findings(gate_findings)

    async def connections(**_kwargs):
        nonlocal connection_calls
        connection_calls += 1
        wire = _connections_wire()
        if connection_calls == 2:
            wire["edges"][0]["label"] = "submits corrected payment"
        return {
            "wire": wire,
            "prompt_fingerprint": f"connection-{connection_calls}",
        }

    async def component_gate(**_kwargs):
        return _approved_gate()

    async def connection_gate(**_kwargs):
        nonlocal connection_gate_calls
        connection_gate_calls += 1
        return stage_gate

    async def send(event):
        events.append(event)

    async def components(**_kwargs):
        return {"wire": _components_wire(), "prompt_fingerprint": "component-1"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **event: True)
    monkeypatch.setattr(
        workflow.settings, "internal_test_email_allowlist_raw", "internal@openai.com"
    )
    result = await workflow.run_staged_graph_pipeline(
        _state(user_email="normal@example.com", send=send)
    )

    assert connection_calls == 2
    assert connection_gate_calls == 2
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_connection_attempts_exhausted"
    )
    assert result["graph_review"]["staged_gate"] == stage_gate
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["schema_version"] == 1
    assert diagnostic["kind"] == "staged_gate"
    assert diagnostic["stage"] == "connections"
    assert diagnostic["attempt"] == 2
    assert diagnostic["code"] == "gate_rejected"
    assert diagnostic["findings"] == [
        {"rule_code": "edge_semantics", "record_paths": ["connections.0"]}
    ]
    assert set(diagnostic["findings"][0].keys()) == {"rule_code", "record_paths"}
    assert "reason" not in diagnostic["findings"][0]
    assert [item["attempt"] for item in result["graph_review_diagnostics"]] == [1, 2]
    assert result["graph_review_diagnostics"][-1] == diagnostic
    assert len(events) == 1
    assert "diagnostic" not in events[0]


@pytest.mark.asyncio
async def test_gate_diagnostic_caps_findings_and_redacts_from_non_internal_users(
    monkeypatch,
):
    component_calls = 0

    def _too_many_findings() -> list[dict]:
        return [
            {"rule_code": "domain_specificity", "record_indexes": [index % 2]}
            for index in range(25)
        ]

    stage_gate = _rejected_gate_with_findings(_too_many_findings())
    events: list[dict] = []

    async def components(**_kwargs):
        nonlocal component_calls
        component_calls += 1
        wire = _components_wire()
        if component_calls == 2:
            wire["components"][0]["responsibility"] = "Accepts validated requests."
        return {
            "wire": wire,
            "prompt_fingerprint": f"component-{component_calls}",
        }

    async def component_gate(**_kwargs):
        return stage_gate

    async def send(event):
        events.append(event)

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **event: True)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(
        workflow.settings, "internal_test_email_allowlist_raw", "internal@openai.com"
    )

    result = await workflow.run_staged_graph_pipeline(
        _state(user_email="normal@example.com", send=send)
    )

    assert component_calls == 2
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_component_attempts_exhausted"
    )
    diagnostic = result["graph_review"]["staged_failure"]
    assert len(diagnostic["findings"]) == 24
    assert "record_indexes" not in diagnostic["findings"][0]
    assert "reason" not in diagnostic["findings"][0]
    assert "diagnostic" not in events[0]


@pytest.mark.asyncio
async def test_final_connection_contract_failure_skips_second_render(monkeypatch):
    connection_calls = 0
    connection_gate_calls = 0
    render_calls = 0
    _install_success_boundaries(monkeypatch)

    async def connections(**_kwargs):
        nonlocal connection_calls
        connection_calls += 1
        wire = _connections_wire()
        if connection_calls == 2:
            wire["edges"][0]["target_index"] = 0
        return {"wire": wire, "prompt_fingerprint": f"connection-{connection_calls}"}

    async def connection_gate(**_kwargs):
        nonlocal connection_gate_calls
        connection_gate_calls += 1
        return _rejected_gate()

    async def render(state, graph, *, preview_count):
        nonlocal render_calls
        render_calls += 1
        return await _render_ok(state, graph, preview_count=preview_count)

    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **_event: True)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert connection_calls == 2
    assert connection_gate_calls == 1
    assert render_calls == 2
    diagnostic = result["graph_review"]["staged_failure"]
    assert diagnostic["stage"] == "connections"
    assert diagnostic["attempt"] == 2
    assert diagnostic["code"] == "contract_rejected"
    assert diagnostic["path"] == "connections.0"


@pytest.mark.asyncio
async def test_every_candidate_is_rendered_before_its_gate(monkeypatch):
    events: list[object] = []
    _install_success_boundaries(monkeypatch, events=events)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert events == [
        "components",
        ("render", 0),
        "component_gate",
        "connections",
        ("render", 1),
        "connection_gate",
    ]


@pytest.mark.asyncio
async def test_explicit_prototype_wins_over_production_wording(monkeypatch):
    maturities: list[str] = []
    _install_success_boundaries(monkeypatch)

    async def component_gate(**kwargs):
        maturities.append(kwargs["resolved_maturity"])
        return _approved_gate()

    async def connection_gate(**kwargs):
        maturities.append(kwargs["resolved_maturity"])
        assert kwargs["required_production_guarantees"] == []
        return _approved_gate()

    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            user_message="Create a production-grade payment system.",
            design_query="Create a production-grade payment system.",
            complexity="prototype",
        )
    )

    assert maturities == ["prototype", "prototype"]
    assert result["graph_contract"]["maturity"] == "prototype"


def test_auto_edit_inherits_stored_maturity_and_explicit_change_restages():
    graph = _approved_graph(maturity="prototype")
    contract = {"maturity": "production"}
    inherited, inherited_restage = workflow._maturity(
        _state(
            graph_intent="edit",
            complexity="auto",
            approved_graph_data=graph,
            approved_graph_contract=contract,
        )
    )
    changed, changed_restage = workflow._maturity(
        _state(
            graph_intent="edit",
            complexity="production",
            approved_graph_data=graph,
            approved_graph_contract={"maturity": "prototype"},
        )
    )

    assert (inherited, inherited_restage) == ("production", False)
    assert (changed, changed_restage) == ("production", True)


@pytest.mark.asyncio
async def test_explicit_depth_change_compiles_narrow_edit_scope(monkeypatch):
    calls: list[tuple[dict, dict]] = []
    _install_success_boundaries(monkeypatch)
    component_wire = _components_wire()
    component_wire["components"][0]["label"] = "Public gateway"

    async def components(**_kwargs):
        return {"wire": component_wire, "prompt_fingerprint": "component-prompt"}

    original_scope = workflow.staged_edit_scope

    def capture_scope(*args, **kwargs):
        contract, permissions = original_scope(*args, **kwargs)
        calls.append((contract, permissions))
        return contract, permissions

    monkeypatch.setattr(workflow, "staged_edit_scope", capture_scope)
    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="production",
            user_message="Rename Request gateway to Public gateway.",
            design_query="Rename Request gateway to Public gateway.",
            approved_graph_data=_accepted_staged_graph(maturity="prototype"),
            approved_graph_contract={"maturity": "prototype", "capabilities": {}},
        )
    )

    assert len(calls) == 1
    assert calls[0][0]["repair_scope"] == "local"
    assert calls[0][1]["editable_node_ids"] == ["n1"]
    assert result["graph_contract"]["maturity"] == "production"


@pytest.mark.asyncio
async def test_accepted_result_has_a_version_matched_server_contract(monkeypatch):
    _install_success_boundaries(monkeypatch)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert result["graph_contract"]["graph_version"] == result["graph_data"]["version"]
    assert result["graph_contract"]["component_fingerprint"]
    assert result["graph_contract"]["connection_fingerprint"]


@pytest.mark.asyncio
async def test_failure_restores_approved_graph_and_contract(monkeypatch):
    approved_graph = _approved_graph()
    approved_contract = {"maturity": "prototype", "graph_version": "approved-v1"}
    _install_success_boundaries(monkeypatch)

    async def terminal_component_gate(**_kwargs):
        return _rejected_gate(terminal=True)

    monkeypatch.setattr(workflow, "review_components", terminal_component_gate)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            approved_graph_data=approved_graph,
            approved_graph_contract=approved_contract,
            graph_data=approved_graph,
            graph_contract=approved_contract,
        )
    )

    assert result["graph_data"] == approved_graph
    assert result["graph_data"] is not approved_graph
    assert result["graph_contract"] == approved_contract
    assert result["graph_contract"] is not approved_contract
    assert result["graph_publication"] == "preserved"


@pytest.mark.asyncio
async def test_failure_progress_transport_does_not_block_state_restoration(monkeypatch):
    approved_graph = _approved_graph()

    async def closed_transport(_event):
        raise RuntimeError("closed")

    monkeypatch.setattr(workflow, "enqueue_analytics_event", lambda **_event: True)
    diagnostic = workflow._failure_diagnostic(
        workflow.GraphContractError("rejected", path="components[0].label"),
        stage="components",
        attempt=2,
        candidate=_components_wire(),
    )

    result = await workflow._failed(
        _state(
            approved_graph_data=approved_graph,
            graph_data=approved_graph,
            send=closed_transport,
        ),
        "staged_component_attempts_exhausted",
        diagnostic=diagnostic,
    )

    assert result["graph_data"] == approved_graph
    assert result["graph_publication"] == "preserved"


@pytest.mark.asyncio
async def test_scoped_component_expansion_preserves_existing_records(monkeypatch):
    """A one-node expansion must pass through the existing exact-record authority."""
    component_wire = _components_wire()
    component_wire["components"].append(
        {
            "label": "Fraud check",
            "type": 108,
            "responsibility": "Approves or rejects the payment request.",
            "group_label": "Runtime",
            "group_kind": 600,
            "primary_flow_member": False,
        }
    )
    connection_wire = _connections_wire()
    connection_wire["edges"].append(
        {
            "source_index": 0,
            "target_index": 2,
            "label": "requests fraud check",
            "flow": 400,
            "sync": 500,
        }
    )

    async def components(**_kwargs):
        return {"wire": component_wire, "prompt_fingerprint": "component-prompt"}

    async def connections(**_kwargs):
        return {"wire": connection_wire, "prompt_fingerprint": "connection-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", _render_ok)

    async def component_gate(**_kwargs):
        return _approved_gate()

    async def connection_gate(**_kwargs):
        return _approved_gate()

    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    previous_graph = _accepted_staged_graph()
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            user_message="Expand Request gateway.",
            design_query="Expand Request gateway.",
            approved_graph_data=previous_graph,
            approved_graph_contract={"maturity": "prototype", "capabilities": {}},
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert [node["id"] for node in result["graph_data"]["nodes"][:2]] == ["n1", "n2"]
    assert len(result["graph_data"]["nodes"]) == 3
    assert len(result["graph_data"]["edges"]) == 2


@pytest.mark.asyncio
async def test_scoped_component_rename_retains_the_existing_server_id(monkeypatch):
    component_wire = _components_wire()
    component_wire["components"][0]["label"] = "Public gateway"

    async def components(**_kwargs):
        return {"wire": component_wire, "prompt_fingerprint": "component-prompt"}

    async def connections(**_kwargs):
        return {"wire": _connections_wire(), "prompt_fingerprint": "connection-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", _render_ok)

    async def component_gate(**_kwargs):
        return _approved_gate()

    async def connection_gate(**_kwargs):
        return _approved_gate()

    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    previous_graph = _accepted_staged_graph()
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            user_message="Rename Request gateway to Public gateway.",
            design_query="Rename Request gateway to Public gateway.",
            approved_graph_data=previous_graph,
            approved_graph_contract={"maturity": "prototype", "capabilities": {}},
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert result["graph_data"]["nodes"][0]["id"] == "n1"
    assert result["graph_data"]["nodes"][0]["label"] == "Public gateway"
    assert result["graph_data"]["edges"] == previous_graph["edges"]


@pytest.mark.asyncio
async def test_production_scoped_expansion_keeps_prior_records_and_uses_exact_authority(
    monkeypatch,
):
    component_wire = _components_wire()
    component_wire["components"].append(
        {
            "label": "Fraud check",
            "type": 108,
            "responsibility": "Approves or rejects a payment before processing.",
            "group_label": "Runtime",
            "group_kind": 600,
            "primary_flow_member": False,
        }
    )
    connection_wire = _connections_wire()
    connection_wire["edges"].append(
        {
            "source_index": 0,
            "target_index": 2,
            "label": "requests fraud check",
            "flow": 400,
            "sync": 500,
        }
    )
    component_inputs: list[dict] = []
    scope_calls: list[tuple[dict, dict]] = []
    original_scope = workflow.staged_edit_scope

    async def components(**kwargs):
        component_inputs.append(copy.deepcopy(kwargs))
        return {"wire": component_wire, "prompt_fingerprint": "component-prompt"}

    async def connections(**_kwargs):
        return {"wire": connection_wire, "prompt_fingerprint": "connection-prompt"}

    def capture_scope(*args, **kwargs):
        contract, permissions = original_scope(*args, **kwargs)
        scope_calls.append((contract, permissions))
        return contract, permissions

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "staged_edit_scope", capture_scope)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)

    previous_graph = _accepted_staged_graph(maturity="prototype")
    previous_nodes = copy.deepcopy(previous_graph["nodes"])
    previous_edges = copy.deepcopy(previous_graph["edges"])
    previous_groups = copy.deepcopy(previous_graph["groups"])
    previous_sequence = copy.deepcopy(previous_graph["sequence"])
    previous_title = previous_graph["title"]
    previous_assumptions = copy.deepcopy(previous_graph["assumptions"])
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="production",
            user_message="Expand Request gateway.",
            design_query="Expand Request gateway.",
            approved_graph_data=previous_graph,
            approved_graph_contract={
                "maturity": "prototype",
                "capabilities": {
                    "external_effects": False,
                    "retrieval_or_reuse": False,
                    "learning_or_release": False,
                },
            },
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert component_inputs[0]["write_set"]["mode"] == "edit"
    assert len(component_inputs[0]["write_set"]["component_ids"]) == 3
    assert len(component_inputs[0]["write_set"]["edge_ids"]) == 2
    assert len(scope_calls) == 1
    assert scope_calls[0][0]["repair_scope"] == "local"
    assert [
        node for node in result["graph_data"]["nodes"] if node["id"] in {"n1", "n2"}
    ] == previous_nodes
    assert result["graph_data"]["edges"][:1] == previous_edges
    assert result["graph_data"]["sequence"] == previous_sequence
    assert result["graph_data"]["title"] == previous_title
    assert result["graph_data"]["assumptions"] == previous_assumptions
    assert result["graph_data"]["groups"][0] == {
        **previous_groups[0],
        "nodeIds": [*previous_groups[0]["nodeIds"], "n3"],
    }
    added_nodes = [
        node for node in result["graph_data"]["nodes"] if node["id"] not in {"n1", "n2"}
    ]
    added_edges = result["graph_data"]["edges"][1:]
    assert len(added_nodes) == 1
    assert len(added_edges) == 1
    assert added_edges[0]["source"] == "n1"
    assert added_edges[0]["target"] == added_nodes[0]["id"]


@pytest.mark.asyncio
async def test_matching_version_malformed_contract_falls_back_to_graph_defaults(
    monkeypatch,
):
    component_wire = _components_wire()
    component_wire["components"][0]["label"] = "Public gateway"
    component_inputs: list[dict] = []

    async def components(**kwargs):
        component_inputs.append(copy.deepcopy(kwargs))
        return {"wire": component_wire, "prompt_fingerprint": "component-prompt"}

    async def connections(**_kwargs):
        return {"wire": _connections_wire(), "prompt_fingerprint": "connection-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)

    previous_graph = _accepted_staged_graph()
    malformed_contract = {
        "graph_version": previous_graph["version"],
        "maturity": "production",
        "capabilities": {"unexpected": True},
    }
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="auto",
            user_message="Rename Request gateway to Public gateway.",
            design_query="Rename Request gateway to Public gateway.",
            approved_graph_data=previous_graph,
            approved_graph_contract=malformed_contract,
            graph_data=previous_graph,
            graph_contract=malformed_contract,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert component_inputs[0]["resolved_maturity"] == "prototype"
    assert component_inputs[0]["base_components"]["maturity"] == "prototype"
    assert component_inputs[0]["base_components"]["capabilities"] == {
        "external_effects": False,
        "retrieval_or_reuse": False,
        "learning_or_release": False,
    }
    assert result["graph_data"]["nodes"][0]["label"] == "Public gateway"
    assert result["graph_contract"]["maturity"] == "prototype"
    assert result["graph_contract"]["graph_version"] == result["graph_data"]["version"]


@pytest.mark.asyncio
async def test_connection_generation_receives_indexed_coded_base_connections(
    monkeypatch,
):
    component_wire = _components_wire()
    component_wire["components"][0]["label"] = "Public gateway"
    connection_inputs: list[dict] = []

    async def components(**_kwargs):
        return {"wire": component_wire, "prompt_fingerprint": "component-prompt"}

    async def connections(**kwargs):
        connection_inputs.append(copy.deepcopy(kwargs))
        return {"wire": _connections_wire(), "prompt_fingerprint": "connection-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)

    previous_graph = _accepted_staged_graph()
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            user_message="Rename Request gateway to Public gateway.",
            design_query="Rename Request gateway to Public gateway.",
            approved_graph_data=previous_graph,
            approved_graph_contract={"maturity": "prototype", "capabilities": {}},
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert connection_inputs[0]["base_connections"] == [
        {
            "source_index": 0,
            "target_index": 1,
            "label": "submits payment",
            "flow": 400,
            "sync": 500,
        }
    ]
