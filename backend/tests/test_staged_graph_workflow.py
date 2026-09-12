"""State-machine coverage for the staged applied-graph pipeline."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from agent import staged_graph_workflow as workflow
from agent.graph_identity import applied_edge_metadata
from agent.nodes import staged_graph_generation as generation
from agent.staged_graph_contract import (
    assign_server_ids,
    component_fingerprint,
    project_graph_data,
)


def test_captured_gate_reason_reaches_correction_without_losing_route_context():
    capture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_gate_34649724600.json"
        ).read_text()
    )
    original = capture["response"]["findings"][0]
    correction = generation._sanitize_findings(
        workflow._gate_findings([original], stage="components")
    )

    assert len(original["reason"]) == 538
    assert correction[0]["reason"] == original["reason"]
    assert correction[0]["record_indexes"] == [8]


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


@pytest.mark.parametrize("first_type", [101, 104])
def test_scoped_renames_keep_server_identity_when_labels_match_prior_nodes(first_type):
    wire = _components_wire()
    wire["components"][0]["type"] = first_type
    base_components = [
        {**component, "server_id": f"n{index + 1}"}
        for index, component in enumerate(workflow._decode_components(wire))
    ]
    wire["components"][0]["label"], wire["components"][1]["label"] = (
        wire["components"][1]["label"],
        wire["components"][0]["label"],
    )
    renamed = workflow._decode_components(wire)

    workflow._retain_component_ids(
        renamed,
        {"components": base_components},
        {"editable_node_ids": ["n1", "n2"], "removable_node_ids": []},
    )

    assert [(component["server_id"], component["label"]) for component in renamed] == [
        ("n1", "Payment service"),
        ("n2", "Request gateway"),
    ]


@pytest.mark.asyncio
async def test_component_gate_retries_at_most_twice_and_renders_each_candidate(
    monkeypatch,
):
    calls: list[object] = []
    component_inputs: list[dict] = []
    gate_inputs: list[dict] = []
    evidence_bundle = {
        "book_evidence": [
            {
                "chapter": 10,
                "page_number": 473,
                "section": "Serving",
                "text": "Add routing and monitoring when the serving flow needs them.",
            }
        ]
    }

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

    async def component_gate(**kwargs):
        calls.append("component_gate")
        gate_inputs.append(copy.deepcopy(kwargs))
        return _rejected_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "review_components", component_gate)

    result = await workflow.run_staged_graph_pipeline(
        _state(evidence_bundle=evidence_bundle)
    )

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
    architecture_context = workflow.format_evidence_bundle(evidence_bundle)
    assert component_inputs[0]["architecture_context"] == architecture_context
    assert component_inputs[1]["architecture_context"] == architecture_context
    assert gate_inputs[0]["evidence_bundle"]["architecture_context"] == (
        architecture_context
    )
    assert gate_inputs[1]["evidence_bundle"]["architecture_context"] == (
        architecture_context
    )
    assert "Add routing and monitoring" in architecture_context
    assert "book:" not in architecture_context
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
        next(
            event["diagnostic"]
            for event in events
            if event["type"] == "workflow_progress"
        ),
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
    progress_events = [
        event for event in events if event["type"] == "workflow_progress"
    ]
    assert [event.get("diagnostic") for event in progress_events] == diagnostics
    assert [event["status"] for event in progress_events] == ["retry", "rejected"]
    assert all(event["phase"] == "review" for event in progress_events)
    for event in events:
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


@pytest.mark.asyncio
async def test_staged_provider_calls_receive_admitted_timeouts(monkeypatch):
    from agent import deadlines

    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100.0)
    _install_success_boundaries(monkeypatch)
    timeouts = {}

    async def components(**kwargs):
        timeouts["components"] = kwargs["timeout_seconds"]
        return {"wire": _components_wire(), "prompt_fingerprint": "component-prompt"}

    async def connections(**kwargs):
        timeouts["connections"] = kwargs["timeout_seconds"]
        return {"wire": _connections_wire(), "prompt_fingerprint": "connection-prompt"}

    async def component_gate(**kwargs):
        timeouts["component_review"] = kwargs["timeout_seconds"]
        return _approved_gate()

    async def connection_gate(**kwargs):
        timeouts["connection_review"] = kwargs["timeout_seconds"]
        return _approved_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)

    result = await workflow.run_staged_graph_pipeline(
        _state(terminal_deadline_s=1_000.0)
    )

    assert result["graph_publication"] == "approved"
    assert timeouts == {
        "components": 137.0,
        "connections": workflow.settings.graph_builder_max_timeout_s,
        "component_review": workflow.settings.graph_critic_max_timeout_s,
        "connection_review": workflow.settings.graph_critic_max_timeout_s,
    }
    assert timeouts["connections"] > workflow.settings.staged_connection_timeout_s


@pytest.mark.asyncio
async def test_real_staged_gates_forward_workflow_timeout_to_provider(monkeypatch):
    from agent import deadlines
    from agent.nodes import staged_graph_gate as gate
    from agent.stream_utils import StructuredLLMResponse

    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100.0)
    _install_success_boundaries(monkeypatch)
    provider_timeouts = []

    async def provider(**kwargs):
        provider_timeouts.append(kwargs["timeout_seconds"])
        schema = kwargs["response_schema"]["properties"]
        payload = {
            "approved": True,
            "checked_rules": schema["checked_rules"]["items"]["enum"],
            "findings": [],
        }
        if "proofs" in schema:
            payload["proofs"] = []
        return StructuredLLMResponse(
            text=json.dumps(payload),
            finish_reason="end_turn",
            input_tokens=1,
            output_tokens=1,
            provider="test",
            model="test",
        )

    monkeypatch.setattr(workflow, "review_components", gate.review_components)
    monkeypatch.setattr(workflow, "review_connections", gate.review_connections)
    monkeypatch.setattr(gate, "stream_structured_llm", provider)
    result = await workflow.run_staged_graph_pipeline(
        _state(terminal_deadline_s=2_000.0)
    )
    assert result["graph_publication"] == "approved"
    assert provider_timeouts == [workflow.settings.graph_critic_max_timeout_s] * 2


@pytest.mark.asyncio
async def test_component_correction_uses_local_count_after_first_preview(monkeypatch):
    from agent import deadlines

    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100.0)
    _install_success_boundaries(monkeypatch)
    generation_timeouts = []
    reviews = []

    async def components(**kwargs):
        generation_timeouts.append(kwargs["timeout_seconds"])
        wire = _components_wire()
        wire["components"][1]["responsibility"] += f" Revision {kwargs['attempt']}."
        return {"wire": wire, "prompt_fingerprint": f"component-{kwargs['attempt']}"}

    async def render(state, graph, *, preview_count):
        rendered = await _render_ok(state, graph, preview_count=preview_count)
        return {
            **rendered,
            "graph_preview_deadline_s": 100.0,
            "graph_stage_preview_count": preview_count,
        }

    async def component_gate(**kwargs):
        reviews.append(kwargs)
        return _rejected_gate() if len(reviews) == 1 else _approved_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "_render", render)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            terminal_deadline_s=2_000.0,
            graph_preview_deadline_s=1_000.0,
        )
    )
    assert result["graph_publication"] == "approved"
    assert generation_timeouts == [workflow.settings.graph_builder_max_timeout_s] * 2


@pytest.mark.parametrize("phase", ["components", "connections"])
@pytest.mark.parametrize("action", ["generate", "review"])
@pytest.mark.parametrize("denied_attempt", [0, 1])
@pytest.mark.parametrize("has_approved_graph", [False, True])
@pytest.mark.asyncio
async def test_staged_deadline_denial_skips_provider_and_restores_approved_graph(
    monkeypatch, phase, action, denied_attempt, has_approved_graph
):
    from agent import deadlines

    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100.0)
    _install_success_boundaries(monkeypatch)
    approved_graph = _approved_graph() if has_approved_graph else None
    approved_contract = (
        {"maturity": "prototype", "graph_version": "approved-v1"}
        if has_approved_graph
        else None
    )
    calls = []
    original_timeout = workflow.staged_timeout_seconds
    denied_position = (phase, action, denied_attempt)

    def timeout(state, **position):
        if (
            position["phase"],
            position["action"],
            position["attempt"],
        ) == denied_position:
            state = {**state, "terminal_deadline_s": 100.0}
        return original_timeout(state, **position)

    async def components(**kwargs):
        attempt = kwargs["attempt"]
        calls.append(("components", "generate", attempt))
        wire = _components_wire()
        wire["components"][1]["responsibility"] += f" Revision {attempt}."
        return {"wire": wire, "prompt_fingerprint": f"component-{attempt}"}

    async def connections(**kwargs):
        attempt = kwargs["attempt"]
        calls.append(("connections", "generate", attempt))
        wire = _connections_wire()
        wire["edges"][0]["label"] += f" revision {attempt}"
        return {"wire": wire, "prompt_fingerprint": f"connection-{attempt}"}

    async def component_gate(**kwargs):
        attempt = kwargs["telemetry_context"]["staged_attempt"] - 1
        calls.append(("components", "review", attempt))
        return _rejected_gate() if phase == "components" else _approved_gate()

    async def connection_gate(**kwargs):
        attempt = kwargs["telemetry_context"]["staged_attempt"] - 1
        calls.append(("connections", "review", attempt))
        return _rejected_gate()

    monkeypatch.setattr(workflow, "staged_timeout_seconds", timeout)
    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "review_connections", connection_gate)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            terminal_deadline_s=2_000.0,
            approved_graph_data=approved_graph,
            approved_graph_contract=approved_contract,
            graph_data=approved_graph,
            graph_contract=approved_contract,
        )
    )

    assert denied_position not in calls
    assert not any(call[0] == phase and call[2] > denied_attempt for call in calls)
    if phase == "components":
        assert not any(call[0] == "connections" for call in calls)
    if denied_attempt:
        assert (phase, "review", 0) in calls
    singular = "component" if phase == "components" else "connection"
    assert (
        result["graph_operation"]["failure_code"]
        == f"staged_{singular}_deadline_admission_denied"
    )
    assert result["graph_review"]["terminal"] is True
    assert result["graph_changed"] is False
    assert result["graph_data"] == approved_graph
    assert result["graph_contract"] == approved_contract
    assert result["graph_publication"] == (
        "preserved" if has_approved_graph else "withheld"
    )
    if has_approved_graph:
        assert result["graph_data"] is not approved_graph
        assert result["graph_contract"] is not approved_contract


@pytest.mark.parametrize("full_restage", [False, True])
@pytest.mark.asyncio
async def test_semantic_gate_rejects_unowned_control_flow_on_correction(
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
    assert connection_gate_calls == 2
    assert render_calls == 3
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_connection_attempts_exhausted"
    )
    assert [item["attempt"] for item in result["graph_review_diagnostics"]] == [1, 2]
    final = result["graph_review"]["staged_failure"]
    assert final["kind"] == "staged_gate"
    assert final["code"] == "gate_rejected"
    assert "monitoring" not in repr(final)


@pytest.mark.parametrize("full_restage", [False, True])
@pytest.mark.asyncio
async def test_connection_correction_after_generation_error_requires_semantic_approval(
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
        return _rejected_gate_with_findings(
            [
                {
                    "rule_code": "edge_semantics",
                    "reason": "The accepted components do not own this control action.",
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
    assert connection_gate_calls == 1
    assert render_calls == 2
    assert (
        result["graph_operation"]["failure_code"]
        == "staged_connection_attempts_exhausted"
    )
    assert [item["attempt"] for item in result["graph_review_diagnostics"]] == [1, 2]
    assert result["graph_review"]["staged_failure"]["code"] == "gate_rejected"


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
    progress_events = [
        event for event in events if event["type"] == "workflow_progress"
    ]
    assert len(progress_events) == 1
    assert "diagnostic" not in progress_events[0]


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
    assert all("diagnostic" not in event for event in events)


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


@pytest.mark.parametrize("correct_capability", [False, True])
@pytest.mark.asyncio
async def test_component_correction_tracks_capability_context(
    monkeypatch, correct_capability
):
    _install_success_boundaries(monkeypatch)
    component_inputs = []
    component_reviews = []
    connection_inputs = []

    async def components(**kwargs):
        component_inputs.append(copy.deepcopy(kwargs))
        wire = _components_wire()
        if correct_capability and len(component_inputs) == 2:
            wire["capabilities"]["retrieval_or_reuse"] = True
        return {
            "wire": wire,
            "prompt_fingerprint": f"component-{len(component_inputs)}",
        }

    async def component_gate(**kwargs):
        component_reviews.append(copy.deepcopy(kwargs))
        return _rejected_gate() if len(component_reviews) == 1 else _approved_gate()

    async def connections(**kwargs):
        connection_inputs.append(copy.deepcopy(kwargs))
        return {"wire": _connections_wire(), "prompt_fingerprint": "connection-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "review_components", component_gate)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)

    result = await workflow.run_staged_graph_pipeline(_state(complexity="production"))

    assert len(component_inputs) == 2
    if not correct_capability:
        assert len(component_reviews) == 1
        assert connection_inputs == []
        assert (
            result["graph_operation"]["failure_code"]
            == "staged_component_attempts_exhausted"
        )
        assert result["graph_review"]["staged_failure"]["code"] == "candidate_repeated"
        return

    assert result["graph_publication"] == "approved"
    assert len(component_reviews) == 2
    assert (
        component_reviews[0]["candidate_records"]
        == component_reviews[1]["candidate_records"]
    )
    assert (
        component_reviews[0]["evidence_bundle"]["candidate_context"]["capabilities"][
            "retrieval_or_reuse"
        ]
        is False
    )
    assert (
        component_reviews[1]["evidence_bundle"]["candidate_context"]["capabilities"][
            "retrieval_or_reuse"
        ]
        is True
    )
    assert (
        connection_inputs[0]["accepted_context"]["capabilities"]["retrieval_or_reuse"]
        is True
    )
    assert connection_inputs[0]["upstream_fingerprint"] == component_fingerprint(
        result["staged_graph_build"]
    )
    assert result["graph_contract"]["capabilities"]["retrieval_or_reuse"] is True


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


def test_auto_edit_inherits_stored_maturity_and_explicit_change_is_detected():
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


@pytest.mark.parametrize(
    ("stored", "requested"), [("prototype", "production"), ("production", "prototype")]
)
@pytest.mark.parametrize("with_approved_snapshot", [False, True])
@pytest.mark.asyncio
async def test_scoped_maturity_change_is_rejected_before_generation(
    monkeypatch,
    stored,
    requested,
    with_approved_snapshot,
):
    calls: list[tuple[dict, dict]] = []
    events: list[object] = []
    scope_queries: list[str] = []
    _install_success_boundaries(monkeypatch, events=events)

    original_scope = workflow.staged_edit_scope

    def capture_scope(*args, **kwargs):
        scope_queries.append(args[0])
        contract, permissions = original_scope(*args, **kwargs)
        calls.append((contract, permissions))
        return contract, permissions

    monkeypatch.setattr(workflow, "staged_edit_scope", capture_scope)
    previous_graph = _accepted_staged_graph(maturity=stored)
    previous_contract = {"maturity": stored, "capabilities": {}}
    snapshot = (
        {
            "approved_graph_data": previous_graph,
            "approved_graph_contract": previous_contract,
        }
        if with_approved_snapshot
        else {}
    )
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity=requested,
            user_message="Rename Request gateway to Public gateway.",
            design_query=(
                "Existing graph context: Payment processing.\n"
                "Latest user request: Rename Request gateway to Public gateway."
            ),
            graph_data=previous_graph,
            graph_contract=previous_contract,
            **snapshot,
        )
    )

    assert len(calls) == 1
    assert scope_queries == ["Rename Request gateway to Public gateway."]
    assert calls[0][0]["repair_scope"] == "local"
    assert calls[0][1]["editable_node_ids"] == ["n1"]
    assert events == []
    assert result["graph_operation"]["failure_code"] == "staged_edit_maturity_conflict"
    assert "auto" in result["graph_review"]["revision_instruction"]
    assert "rebuild" in result["graph_review"]["revision_instruction"]
    assert requested in result["graph_review"]["revision_instruction"]
    assert result["graph_publication"] == "preserved"
    assert result["graph_data"] == previous_graph
    assert result["graph_contract"] == previous_contract


@pytest.mark.parametrize(
    "user_request",
    [
        "Make it production ready.",
        "Replace Request gateway.",
        "Review the entire graph.",
    ],
)
@pytest.mark.asyncio
async def test_selected_maturity_does_not_authorize_graph_replacement(
    monkeypatch, user_request
):
    events = []
    _install_success_boundaries(monkeypatch, events=events)
    previous_graph = _accepted_staged_graph()
    previous_contract = {"maturity": "prototype", "capabilities": {}}

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="production",
            user_message=user_request,
            design_query=user_request,
            approved_graph_data=previous_graph,
            approved_graph_contract=previous_contract,
        )
    )

    assert events == []
    assert result["graph_operation"]["failure_code"] == "staged_edit_scope_ambiguous"
    assert result["graph_publication"] == "preserved"
    assert result["graph_data"] == previous_graph
    assert result["graph_contract"] == previous_contract


@pytest.mark.asyncio
async def test_ambiguous_monitoring_expansion_preserves_graph_and_requests_exact_target(
    monkeypatch,
):
    graph = _accepted_staged_graph()
    graph["nodes"][0]["label"] = "Monitoring Collector"
    graph["nodes"][1]["label"] = "Monitoring Dashboard"
    query = (
        "Expand the monitoring component while preserving the original graph topic "
        "and existing components. Add exactly one directly connected responsibility."
    )

    async def unexpected_generation(**_kwargs):
        pytest.fail("Ambiguous edit must fail before provider generation")

    monkeypatch.setattr(workflow, "generate_component_candidate", unexpected_generation)
    monkeypatch.setattr(
        workflow, "generate_connection_candidate", unexpected_generation
    )
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            user_message=query,
            design_query=query,
            graph_data=graph,
            approved_graph_data=graph,
        )
    )

    assert result["graph_operation"]["failure_code"] == "staged_edit_scope_ambiguous"
    assert result["graph_publication"] == "preserved"
    assert result["graph_data"] == graph
    assert result["graph_review"]["revision_instruction"] == (
        "Identify the component or connection by its exact label or ID, then repeat the edit."
    )


@pytest.mark.parametrize(
    "target,expected_id",
    [
        ("Monitoring Collector", "n1"),
        ("Monitoring Dashboard", "n2"),
        ("n1", "n1"),
        ("n2", "n2"),
    ],
)
def test_monitoring_expansion_exact_label_or_id_selects_one_authorized_anchor(
    target, expected_id
):
    graph = _accepted_staged_graph()
    graph["nodes"][0]["label"] = "Monitoring Collector"
    graph["nodes"][1]["label"] = "Monitoring Dashboard"

    _, permissions = workflow.staged_edit_scope(
        f"Expand {target}.", graph, resolved_complexity="prototype"
    )

    assert permissions["added_edge_anchor_node_ids"] == [expected_id]
    assert permissions["allowed_new_node_count"] == 1
    assert permissions["minimum_new_edge_count"] == 1
    assert permissions["allowed_new_edge_count"] == 2


@pytest.mark.parametrize(
    "user_request", ["Redesign the entire graph.", "Rebuild the graph.", "Start over."]
)
@pytest.mark.asyncio
async def test_explicit_graph_rebuild_can_change_maturity(monkeypatch, user_request):
    events = []
    _install_success_boundaries(monkeypatch, events=events)
    previous_graph = _accepted_staged_graph()
    previous_contract = {"maturity": "prototype", "capabilities": {}}

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="production",
            user_message=user_request,
            design_query=user_request,
            approved_graph_data=previous_graph,
            approved_graph_contract=previous_contract,
        )
    )

    assert events.count("components") == events.count("connections") == 1
    assert result["graph_publication"] == "approved"
    assert result["graph_contract"]["maturity"] == "production"
    assert previous_contract["maturity"] == "prototype"
    assert previous_graph["resolved_complexity"] == "prototype"


@pytest.mark.asyncio
async def test_accepted_result_has_a_version_matched_server_contract(monkeypatch):
    _install_success_boundaries(monkeypatch)

    result = await workflow.run_staged_graph_pipeline(_state())

    assert result["graph_contract"]["graph_version"] == result["graph_data"]["version"]
    assert result["graph_contract"]["component_fingerprint"]
    assert result["graph_contract"]["connection_fingerprint"]
    assert result["graph_contract"]["reviewed_graph_fingerprint"]
    assert result["graph_contract"]["objective"] == _state()["design_query"]


def _current_review_contract(graph: dict) -> tuple[dict, dict]:
    build = workflow.reconstruct_staged_graph_build(graph)
    gates = {
        stage: {
            **_approved_gate(),
            "review_identity": workflow.review_identity(stage, build["maturity"]),
        }
        for stage in ("components", "connections")
    }
    contract = workflow._contract(
        build,
        graph,
        component_gate=gates["components"],
        connection_gate=gates["connections"],
        objective="Draw a payment system.",
    )
    return build, contract


@pytest.mark.parametrize(
    "corruption",
    [
        None,
        "version",
        "graph",
        "capabilities",
        "old_release",
        "rejected",
        "missing_fingerprint",
    ],
)
def test_review_scope_reuses_only_matching_current_server_approval(corruption):
    graph = _accepted_staged_graph()
    base, contract = _current_review_contract(graph)
    if corruption == "version":
        contract["graph_version"] = "another-version"
    elif corruption == "graph":
        graph["nodes"][0]["description"] = "Owns an unreviewed external action."
    elif corruption == "capabilities":
        contract["capabilities"]["external_effects"] = True
    elif corruption == "old_release":
        contract["connection_gate"]["review_identity"] = "obsolete-reviewer"
    elif corruption == "rejected":
        contract["component_gate"]["approved"] = False
    elif corruption == "missing_fingerprint":
        contract.pop("reviewed_graph_fingerprint")
    graph["view_state"] = {"positions": {"n1": {"x": 100, "y": 40}}}
    candidate = copy.deepcopy(base)
    candidate["components"][0]["label"] = "Public gateway"

    scope = workflow._edit_review_scope(base, candidate, graph, contract, {})

    assert scope["trusted_baseline"] is (corruption is None)
    assert scope["changed_component_ids"] == ["n1"]
    assert scope["affected_component_ids"] == ["n1", "n2"]
    assert scope["changed_connection_indexes"] == []
    assert scope["baseline_objective"] == "Draw a payment system."


@pytest.mark.parametrize(
    "changed_context",
    ["title", "assumptions", "capabilities", "maturity", "root_index"],
)
def test_changed_global_obligations_require_full_review(changed_context):
    graph = _accepted_staged_graph()
    base, contract = _current_review_contract(graph)
    candidate = copy.deepcopy(base)
    changed = {
        "title": "Payment release system",
        "assumptions": ["Payment processing can release funds."],
        "capabilities": {**base["capabilities"], "external_effects": True},
        "maturity": "production",
        "root_index": 1,
    }
    candidate[changed_context] = changed[changed_context]

    scope = workflow._edit_review_scope(base, candidate, graph, contract, {})

    assert scope["trusted_baseline"] is False


@pytest.mark.asyncio
async def test_scoped_edit_passes_verified_baseline_and_dependency_changes_to_both_gates(
    monkeypatch,
):
    _install_success_boundaries(monkeypatch)
    graph = _accepted_staged_graph()
    _, contract = _current_review_contract(graph)
    reviews = []

    async def components(**_kwargs):
        wire = _components_wire()
        wire["components"][0]["label"] = "Public gateway"
        return {"wire": wire, "prompt_fingerprint": "component-prompt"}

    async def review(**kwargs):
        reviews.append(copy.deepcopy(kwargs))
        return _approved_gate()

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "review_components", review)
    monkeypatch.setattr(workflow, "review_connections", review)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="auto",
            user_message="Rename Request gateway to Public gateway.",
            design_query="Rename Request gateway to Public gateway.",
            approved_graph_data=graph,
            approved_graph_contract=contract,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert len(reviews) == 2
    for review in reviews:
        scope = review["evidence_bundle"]["review_scope"]
        assert scope["trusted_baseline"] is True
        assert scope["changed_component_ids"] == ["n1"]
        assert scope["affected_component_ids"] == ["n1", "n2"]
        assert scope["edit_permissions"]["editable_node_ids"] == ["n1"]
        assert scope["baseline_components"][0]["label"] == "Request gateway"
    assert result["graph_contract"]["objective"] == contract["objective"]


@pytest.mark.parametrize("first_generation_fails", [False, True])
@pytest.mark.asyncio
async def test_same_control_candidate_receives_same_review_after_generation_failure(
    monkeypatch, first_generation_fails
):
    _install_success_boundaries(monkeypatch)
    calls = 0
    reviews = []
    wire = _connections_wire()
    wire["edges"].append(
        {
            "source_index": 1,
            "target_index": 0,
            "label": "return authorization decision",
            "flow": 401,
            "sync": 500,
        }
    )

    async def connections(**_kwargs):
        nonlocal calls
        calls += 1
        if first_generation_fails and calls == 1:
            raise workflow.StagedGenerationError(
                "connection_wire_invalid", prompt_fingerprint="first"
            )
        return {"wire": wire, "prompt_fingerprint": "corrected"}

    async def review(**kwargs):
        reviews.append(copy.deepcopy(kwargs))
        return _approved_gate()

    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(workflow, "review_connections", review)
    result = await workflow.run_staged_graph_pipeline(_state())

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert calls == 1 + first_generation_fails
    assert len(reviews) == 1
    assert reviews[0]["candidate_records"][-1] == {
        "source": "n2",
        "target": "n1",
        "label": "return authorization decision",
        "flow": "control",
        "sync": "sync",
    }


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


@pytest.mark.parametrize("retrieval_enabled", [False, True])
@pytest.mark.asyncio
async def test_production_scoped_expansion_keeps_prior_records_and_uses_exact_authority(
    monkeypatch,
    retrieval_enabled,
):
    component_wire = _components_wire()
    component_wire["capabilities"]["retrieval_or_reuse"] = retrieval_enabled
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
    if retrieval_enabled:
        component_wire["components"][-1].update(
            label="Risk reference retrieval",
            type=101,
            responsibility="Retrieves versioned payment risk references.",
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
    connection_inputs: list[dict] = []
    component_reviews: list[dict] = []
    connection_reviews: list[dict] = []
    scope_calls: list[tuple[dict, dict]] = []
    scope_queries: list[str] = []
    original_scope = workflow.staged_edit_scope

    async def components(**kwargs):
        component_inputs.append(copy.deepcopy(kwargs))
        return await generation.generate_component_candidate(**kwargs)

    async def connections(**kwargs):
        connection_inputs.append(copy.deepcopy(kwargs))
        return await generation.generate_connection_candidate(**kwargs)

    async def generate_delta(**kwargs):
        assert kwargs["schema"]["properties"]["updates"]["properties"] == {}
        if kwargs["stage"] == "components":
            return json.dumps(
                {
                    "additions": component_wire["components"][-1:],
                    "updates": {},
                    "capabilities": component_wire["capabilities"],
                }
            )
        return json.dumps({"additions": connection_wire["edges"][-1:], "updates": {}})

    async def review_components(**kwargs):
        component_reviews.append(copy.deepcopy(kwargs))
        return _approved_gate()

    async def review_connections(**kwargs):
        connection_reviews.append(copy.deepcopy(kwargs))
        return _approved_gate()

    def capture_scope(*args, **kwargs):
        scope_queries.append(args[0])
        contract, permissions = original_scope(*args, **kwargs)
        scope_calls.append((contract, permissions))
        return contract, permissions

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(generation, "_run_generation", generate_delta)
    monkeypatch.setattr(workflow, "staged_edit_scope", capture_scope)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", review_components)
    monkeypatch.setattr(workflow, "review_connections", review_connections)

    previous_graph = _accepted_staged_graph(maturity="production")
    previous_nodes = copy.deepcopy(previous_graph["nodes"])
    previous_edges = copy.deepcopy(previous_graph["edges"])
    previous_groups = copy.deepcopy(previous_graph["groups"])
    previous_sequence = copy.deepcopy(previous_graph["sequence"])
    previous_title = previous_graph["title"]
    previous_assumptions = copy.deepcopy(previous_graph["assumptions"])
    previous_contract = {
        "maturity": "production",
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
    }
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="production",
            user_message="Expand Request gateway.",
            design_query=(
                "Existing graph context: Payment processing.\n"
                "Latest user request: Expand Request gateway."
            ),
            approved_graph_data=previous_graph,
            approved_graph_contract=previous_contract,
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result["graph_operation"]
    assert component_inputs[0]["write_set"]["mode"] == "edit"
    assert len(component_inputs[0]["write_set"]["component_ids"]) == 3
    assert len(component_inputs[0]["write_set"]["edge_ids"]) == 3
    assert len(scope_calls) == 1
    assert scope_queries == ["Expand Request gateway."]
    assert scope_calls[0][0]["repair_scope"] == "local"
    assert component_inputs[0]["edit_permissions"] == scope_calls[0][1]
    assert connection_inputs[0]["edit_permissions"] == scope_calls[0][1]
    assert (
        component_inputs[0]["base_components"]["capabilities"]["retrieval_or_reuse"]
        is False
    )
    expected_capabilities = component_wire["capabilities"]
    assert len(component_reviews) == len(connection_reviews) == 1
    assert len(component_reviews[0]["candidate_records"]) == 3
    assert len(connection_reviews[0]["candidate_records"]) == 2
    assert (
        component_reviews[0]["evidence_bundle"]["candidate_context"]["capabilities"]
        == expected_capabilities
    )
    assert (
        connection_inputs[0]["accepted_context"]["capabilities"]
        == expected_capabilities
    )
    assert (
        connection_reviews[0]["evidence_bundle"]["candidate_context"]["capabilities"]
        == expected_capabilities
    )
    assert connection_reviews[0]["required_production_guarantees"] == (
        ["audit_and_provenance", "retrieval_and_reuse_trust"]
        if retrieval_enabled
        else ["audit_and_provenance"]
    )
    assert result["graph_contract"]["capabilities"] == expected_capabilities
    assert previous_contract["capabilities"]["retrieval_or_reuse"] is False
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
@pytest.mark.parametrize("run_id", ["32300653373", "34653111423"])
async def test_retained_model_serving_graph_expands_monitoring_without_prior_record_drift(
    monkeypatch,
    run_id,
):
    from eval.browser_runner import _graph_expansion_failure

    # Captured scheduled-eval browser-results.json, graph-expansion case, first
    # graph_data event, eval_turn=1. Fixtures retain only the published graph.
    fixture = (
        Path(__file__).with_name("fixtures") / f"staged_model_serving_{run_id}.json"
    )
    previous_graph = json.loads(fixture.read_text())
    original = copy.deepcopy(previous_graph)
    node_count = len(original["nodes"])
    edge_count = len(original["edges"])
    anchor = original["nodes"][-1]
    group = next(
        group for group in original["groups"] if anchor["id"] in group["nodeIds"]
    )
    request = (
        "Expand the monitoring component while preserving the original graph topic "
        "and existing components. Add exactly one directly connected responsibility."
    )
    provider_stages = []
    component_reviews = []
    connection_reviews = []

    async def generate_delta(**kwargs):
        provider_stages.append(kwargs["stage"])
        properties = kwargs["schema"]["properties"]
        assert properties["updates"]["properties"] == {}
        assert properties["additions"]["minItems"] == 1
        assert properties["additions"]["maxItems"] == (
            1 if kwargs["stage"] == "components" else 2
        )
        if kwargs["stage"] == "components":
            return json.dumps(
                {
                    "additions": [
                        {
                            "label": "Alert Triage Service",
                            "type": 101,
                            "responsibility": "Evaluates monitoring alerts and prioritizes issues for operator review.",
                            "group_label": group["label"],
                            "group_kind": 602,
                            "primary_flow_member": False,
                        }
                    ],
                    "updates": {},
                    "capabilities": {
                        "external_effects": False,
                        "retrieval_or_reuse": run_id == "34653111423",
                        "learning_or_release": False,
                    },
                }
            )
        return json.dumps(
            {
                "additions": [
                    {
                        "source_index": node_count - 1,
                        "target_index": node_count,
                        "label": "dispatch monitoring alerts for triage",
                        "flow": 402,
                        "sync": 501,
                    }
                ],
                "updates": {},
            }
        )

    async def review_components(**kwargs):
        component_reviews.append(copy.deepcopy(kwargs))
        return _approved_gate()

    async def review_connections(**kwargs):
        connection_reviews.append(copy.deepcopy(kwargs))
        return _approved_gate()

    monkeypatch.setattr(generation, "_run_generation", generate_delta)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", review_components)
    monkeypatch.setattr(workflow, "review_connections", review_connections)

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            graph_operation={
                "kind": "edit",
                "status": "candidate",
                "failure_code": None,
            },
            complexity="auto",
            user_message=request,
            design_query=request,
            approved_graph_data=previous_graph,
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result.get(
        "graph_review_diagnostics"
    )
    assert provider_stages == ["components", "connections"]
    assert len(component_reviews) == len(connection_reviews) == 1
    assert len(component_reviews[0]["candidate_records"]) == node_count + 1
    assert len(connection_reviews[0]["candidate_records"]) == edge_count + 1
    assert component_reviews[0]["resolved_maturity"] == "prototype"
    assert connection_reviews[0]["resolved_maturity"] == "prototype"
    current_graph = result["graph_data"]
    assert (
        _graph_expansion_failure(
            original, current_graph, anchor_label_contains="Monitoring"
        )
        is None
    )
    assert current_graph["nodes"][:node_count] == original["nodes"]
    assert current_graph["edges"][:edge_count] == original["edges"]
    assert current_graph["nodes"][-1]["label"] == "Alert Triage Service"
    assert current_graph["edges"][-1]["source"] == anchor["id"]
    assert current_graph["edges"][-1]["target"] == current_graph["nodes"][-1]["id"]
    assert current_graph["edges"][-1]["sync"] == "async"
    for field in ("title", "assumptions", "sequence", "resolved_complexity"):
        assert current_graph[field] == original[field]
    assert current_graph["groups"] == [
        {
            **group,
            "nodeIds": group["nodeIds"]
            + (
                [current_graph["nodes"][-1]["id"]]
                if anchor["id"] in group["nodeIds"]
                else []
            ),
        }
        for group in original["groups"]
    ]
    assert previous_graph == original


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


@pytest.mark.asyncio
async def test_scoped_root_deletion_requires_replacement_authority(monkeypatch):
    _install_success_boundaries(monkeypatch)
    wire = _components_wire()
    wire["components"].pop(0)

    async def components(**_kwargs):
        return {"wire": wire, "prompt_fingerprint": "component-prompt"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    previous_graph = _accepted_staged_graph()
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            user_message="Delete Request gateway.",
            design_query="Delete Request gateway.",
            approved_graph_data=previous_graph,
            approved_graph_contract={"maturity": "prototype", "capabilities": {}},
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "preserved"
    assert result["graph_data"] == previous_graph
    assert result["graph_review_diagnostics"][0]["path"] == "root_index"


@pytest.mark.parametrize("removed_index", [0, 1])
@pytest.mark.parametrize("mutation", [None, "component", "edge", "group"])
@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.asyncio
async def test_scoped_deletion_preserves_surviving_ids_root_and_directed_edges(
    monkeypatch,
    removed_index,
    mutation,
    maturity,
):
    wire = _components_wire()
    wire["components"][1]["group_label"] = "Settlement"
    wire["components"][:0] = [
        {
            "label": label,
            "type": 101,
            "responsibility": responsibility,
            "group_label": "Runtime",
            "group_kind": 600,
            "primary_flow_member": False,
        }
        for label, responsibility in [
            ("Metrics sink", "Collects request metrics."),
            ("Audit mirror", "Receives audit copies."),
        ]
    ]
    prior_build = assign_server_ids(
        {
            **wire,
            "request_id": "prior-request",
            "root_index": 2,
            "components": workflow._decode_components(wire),
            "connections": [
                {
                    "source_id": str(source),
                    "target_id": str(target),
                    "label": label,
                    "flow": flow,
                    "sync": "sync",
                }
                for source, target, label, flow in [
                    (2, 0, "reports metrics", "feedback"),
                    (2, 1, "copies audit", "feedback"),
                    (2, 3, "submits payment", "runtime"),
                    (3, 2, "returns payment status", "feedback"),
                ]
            ],
            "maturity": maturity,
        }
    )
    previous_graph = project_graph_data(prior_build)
    for index, edge in enumerate(previous_graph["edges"]):
        edge["technology"] = f"Transport {index}"
        edge["description"] = f"Stored edge description {index}"
    previous_graph["version"] = "prior-version"
    untouched_graph = copy.deepcopy(previous_graph)
    removed = wire["components"].pop(removed_index)
    removed_id = prior_build["components"][removed_index]["server_id"]
    remaining_build = {
        **prior_build,
        "components": [
            {**component, "model_index": index}
            for index, component in enumerate(
                component
                for component in prior_build["components"]
                if component["server_id"] != removed_id
            )
        ],
        "connections": [
            edge
            for edge in prior_build["connections"]
            if removed_id not in (edge["source_id"], edge["target_id"])
        ],
    }
    expected_connections = workflow._connection_prompt_base(remaining_build)
    returned_connections = copy.deepcopy(expected_connections)
    if mutation == "component":
        wire["components"][-1]["responsibility"] = "Owns unrelated payment records."
    elif mutation == "group":
        wire["components"][-1]["group_label"] = "Unrelated group"
    elif mutation == "edge":
        edge = returned_connections[-1]
        edge["source_index"], edge["target_index"] = (
            edge["target_index"],
            edge["source_index"],
        )
    connection_inputs = []

    async def components(**kwargs):
        if mutation is None:
            return await generation.generate_component_candidate(**kwargs)
        return {"wire": wire, "prompt_fingerprint": "component-prompt"}

    async def connections(**kwargs):
        connection_inputs.append(copy.deepcopy(kwargs))
        if mutation is None:
            return await generation.generate_connection_candidate(**kwargs)
        return {
            "wire": {"edges": returned_connections},
            "prompt_fingerprint": "connection-prompt",
        }

    async def generate_delta(**kwargs):
        assert kwargs["schema"]["properties"]["updates"]["properties"] == {}
        assert kwargs["schema"]["properties"]["additions"]["maxItems"] == 0
        return json.dumps(
            {
                "additions": [],
                "updates": {},
                **(
                    {"capabilities": wire["capabilities"]}
                    if kwargs["stage"] == "components"
                    else {}
                ),
            }
        )

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", connections)
    monkeypatch.setattr(generation, "_run_generation", generate_delta)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)
    request = f"Delete {removed['label']}."

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity=maturity,
            user_message=request,
            design_query=request,
            approved_graph_data=previous_graph,
            approved_graph_contract={"maturity": maturity, "capabilities": {}},
            graph_data=previous_graph,
        )
    )

    if mutation is not None:
        assert result["graph_publication"] == "preserved"
        assert result["graph_data"] == untouched_graph
        assert previous_graph == untouched_graph
        return

    assert result["graph_publication"] == "approved", result.get(
        "graph_review_diagnostics"
    )
    assert len(connection_inputs) == 1
    assert connection_inputs[0]["base_connections"] == expected_connections
    assert [
        component["id"]
        for component in connection_inputs[0]["accepted_components"]
        if component["is_root"]
    ] == ["n3"]
    assert result["staged_graph_build"]["root_index"] == 1
    assert result["graph_data"]["nodes"] == [
        node for node in previous_graph["nodes"] if node["id"] != removed_id
    ]
    assert result["graph_data"]["edges"] == [
        edge
        for edge in previous_graph["edges"]
        if removed_id not in (edge["source"], edge["target"])
    ]
    assert result["graph_data"]["sequence"] == previous_graph["sequence"]
    assert result["graph_data"]["groups"] == [
        {
            **group,
            "nodeIds": [
                node_id for node_id in group["nodeIds"] if node_id != removed_id
            ],
        }
        for group in previous_graph["groups"]
    ]
    assert previous_graph == untouched_graph


@pytest.mark.parametrize(
    ("user_request", "field", "wire_value", "stored_value"),
    [
        (
            "Rename edge_1 label to payment submission.",
            "label",
            "payment submission",
            "payment submission",
        ),
        ("Make edge_1 asynchronous.", "sync", 501, "async"),
        ("Set edge_1 flow to control.", "flow", 401, "control"),
    ],
)
@pytest.mark.asyncio
async def test_scoped_edge_scalar_edit_preserves_locked_presentation(
    monkeypatch,
    user_request,
    field,
    wire_value,
    stored_value,
):
    previous_graph = _accepted_staged_graph()
    previous_graph["edges"][0].update(
        technology="Signed HTTP contract",
        description="Authoritative payment request payload.",
    )
    original = copy.deepcopy(previous_graph)
    provider_stages = []

    async def generate_delta(**kwargs):
        provider_stages.append(kwargs["stage"])
        if kwargs["stage"] == "components":
            return json.dumps(
                {
                    "additions": [],
                    "updates": {},
                    "capabilities": _components_wire()["capabilities"],
                }
            )
        assert set(
            kwargs["schema"]["properties"]["updates"]["properties"]["slot_0"][
                "properties"
            ]
        ) == {field}
        return json.dumps({"additions": [], "updates": {"slot_0": {field: wire_value}}})

    monkeypatch.setattr(generation, "_run_generation", generate_delta)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            user_message=user_request,
            design_query=user_request,
            approved_graph_data=previous_graph,
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result.get(
        "graph_review_diagnostics"
    )
    assert provider_stages == ["components", "connections"]
    expected_edge = {**original["edges"][0], field: stored_value}
    if field == "label":
        expected_edge.update(applied_edge_metadata("n1", "n2", "payment submission"))
    assert result["graph_data"]["edges"] == [expected_edge]
    for key in ("nodes", "groups", "sequence", "title", "assumptions"):
        assert result["graph_data"][key] == original[key]
    assert previous_graph == original


@pytest.mark.parametrize(
    ("unauthorized_field", "value"), [("source", "n2"), ("label", "unrequested label")]
)
def test_scoped_presentation_slot_rejects_unauthorized_semantic_changes(
    unauthorized_field,
    value,
):
    previous_graph = _accepted_staged_graph()
    candidate = copy.deepcopy(previous_graph)
    candidate["edges"][0].update(
        technology="Unrelated transport",
        description="Unrelated edge description.",
        **{unauthorized_field: value},
    )
    repair_contract, permissions = workflow.staged_edit_scope(
        "Make edge_1 asynchronous.", previous_graph, resolved_complexity="prototype"
    )

    preserved = workflow._preserve_existing_presentation(
        candidate,
        previous_graph,
        edit_permissions=permissions,
    )

    assert preserved["edges"][0] == candidate["edges"][0]
    with pytest.raises(ValueError, match="locked edge fields"):
        workflow.admit_staged_graph_edit(
            previous_graph,
            preserved,
            resolved_complexity="prototype",
            repair_contract=repair_contract,
            mutation_permissions=permissions,
        )


def test_presentation_preservation_honors_explicit_presentation_field_authority():
    previous_graph = _accepted_staged_graph()
    candidate = copy.deepcopy(previous_graph)
    candidate["nodes"][0]["technology"] = "Authorized gateway transport"
    candidate["edges"][0]["description"] = "Authorized edge description."

    preserved = workflow._preserve_existing_presentation(
        candidate,
        previous_graph,
        edit_permissions={
            "editable_node_fields": {"n1": ["technology"]},
            "editable_edge_fields": {"edge_1": ["description"]},
        },
    )

    assert preserved["nodes"][0]["technology"] == "Authorized gateway transport"
    assert preserved["edges"][0]["description"] == "Authorized edge description."


@pytest.mark.parametrize("operation", ["rename", "remove"])
@pytest.mark.asyncio
async def test_scoped_primary_node_edit_preserves_authored_sequence(
    monkeypatch, operation
):
    previous_graph = _accepted_staged_graph()
    previous_graph["sequence"][0]["description"] = "Receive the authenticated payment."
    previous_graph["sequence"][1]["description"] = "Process the payment instruction."
    original = copy.deepcopy(previous_graph)
    provider_stages = []

    async def generate_delta(**kwargs):
        provider_stages.append(kwargs["stage"])
        if kwargs["stage"] == "components":
            return json.dumps(
                {
                    "additions": [],
                    "updates": {"slot_1": {"label": "Settlement service"}}
                    if operation == "rename"
                    else {},
                    "capabilities": _components_wire()["capabilities"],
                }
            )
        return json.dumps({"additions": [], "updates": {}})

    monkeypatch.setattr(generation, "_run_generation", generate_delta)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)
    user_request = (
        "Rename Payment service to Settlement service."
        if operation == "rename"
        else "Delete Payment service."
    )

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="auto",
            user_message=user_request,
            design_query=user_request,
            approved_graph_data=previous_graph,
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result.get(
        "graph_review_diagnostics"
    )
    assert provider_stages == ["components", "connections"]
    if operation == "rename":
        assert result["graph_data"]["sequence"] == original["sequence"]
        assert result["graph_data"]["nodes"] == [
            original["nodes"][0],
            {**original["nodes"][1], "label": "Settlement service"},
        ]
        assert result["graph_data"]["edges"] == original["edges"]
        assert result["graph_data"]["groups"] == original["groups"]
    else:
        assert result["graph_data"]["sequence"] == original["sequence"][:1]
        assert result["graph_data"]["nodes"] == original["nodes"][:1]
        assert result["graph_data"]["edges"] == []
        assert result["graph_data"]["groups"] == [
            {**original["groups"][0], "nodeIds": ["n1"]}
        ]
    assert previous_graph == original


@pytest.mark.parametrize("outcome", ["approved", "base_rejected", "gate_rejected"])
@pytest.mark.asyncio
async def test_staged_pipeline_reports_graph_worker_once_for_actual_execution(
    monkeypatch, outcome
):
    from eval.staging_runner import extract_workers

    events = []

    async def send(event):
        events.append(event)

    _install_success_boundaries(monkeypatch)
    state = _state(send=send)
    if outcome == "base_rejected":
        state.update(graph_intent="edit", approved_graph_data={"nodes": []})
    elif outcome == "gate_rejected":

        async def reject(**kwargs):
            return _rejected_gate()

        monkeypatch.setattr(workflow, "review_components", reject)

    result = await workflow.run_staged_graph_pipeline(state)

    worker_events = [event for event in events if event["type"] == "worker_status"]
    assert worker_events == [
        {"type": "worker_status", "worker": "graph", "status": "Preparing the graph."}
    ]
    assert events[0] == worker_events[0]
    assert extract_workers(events) == {"graph"}
    if outcome == "approved":
        assert result["graph_publication"] == "approved"
    else:
        assert result["graph_operation"]["status"] == "failed"
        assert result["graph_operation"]["failure_code"] == (
            "staged_base_graph_invalid"
            if outcome == "base_rejected"
            else "staged_component_attempts_exhausted"
        )


@pytest.mark.parametrize(
    "sender", ["missing", None, "not callable", "closed transport"]
)
@pytest.mark.asyncio
async def test_staged_worker_reporting_preserves_optional_transport_behavior(
    monkeypatch, sender
):
    async def closed_transport(event):
        raise RuntimeError("closed")

    _install_success_boundaries(monkeypatch)
    state = _state()
    if sender != "missing":
        state["send"] = closed_transport if sender == "closed transport" else sender
    result = await workflow.run_staged_graph_pipeline(state)
    assert result["graph_publication"] == "approved"


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize(
    ("user_request", "expected_id"),
    [("Add Cache to Payment service.", "cache"), ("Expand Payment service.", "n3")],
)
@pytest.mark.asyncio
async def test_scoped_additions_use_server_authorized_node_identity(
    monkeypatch,
    maturity,
    user_request,
    expected_id,
):
    previous_graph = _accepted_staged_graph(maturity=maturity)
    original = copy.deepcopy(previous_graph)
    provider_stages = []

    async def generate_delta(**kwargs):
        provider_stages.append(kwargs["stage"])
        if kwargs["stage"] == "components":
            fields = kwargs["schema"]["properties"]["additions"]["items"]["properties"]
            assert "id" not in fields and "server_id" not in fields
            return json.dumps(
                {
                    "additions": [
                        {
                            "label": "Cache",
                            "type": 102,
                            "responsibility": "Stores reusable payment status lookups.",
                            "group_label": "Runtime",
                            "group_kind": 600,
                            "primary_flow_member": False,
                        }
                    ],
                    "updates": {},
                    "capabilities": {
                        "external_effects": False,
                        "retrieval_or_reuse": True,
                        "learning_or_release": False,
                    },
                }
            )
        return json.dumps(
            {
                "additions": [
                    {
                        "source_index": 1,
                        "target_index": 2,
                        "label": "looks up payment status",
                        "flow": 400,
                        "sync": 500,
                    }
                ],
                "updates": {},
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate_delta)
    monkeypatch.setattr(workflow, "_render", _render_ok)
    monkeypatch.setattr(workflow, "review_components", _approve_gate)
    monkeypatch.setattr(workflow, "review_connections", _approve_gate)

    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            complexity="auto",
            user_message=user_request,
            design_query=user_request,
            approved_graph_data=previous_graph,
            graph_data=previous_graph,
        )
    )

    assert result["graph_publication"] == "approved", result.get(
        "graph_review_diagnostics"
    )
    assert provider_stages == ["components", "connections"]
    assert result["graph_data"]["nodes"][:2] == original["nodes"]
    assert result["graph_data"]["edges"][:1] == original["edges"]
    assert result["graph_data"]["nodes"][-1]["id"] == expected_id
    assert result["graph_data"]["edges"][-1]["source"] == "n2"
    assert result["graph_data"]["edges"][-1]["target"] == expected_id
    assert result["graph_data"]["groups"][0]["nodeIds"] == ["n1", "n2", expected_id]
    assert result["graph_data"]["sequence"] == original["sequence"]
    assert previous_graph == original


@pytest.mark.parametrize(
    ("named_ids", "count", "actual_count", "removed", "error"),
    [
        ([], 1, 1, [], "count does not match"),
        (["cache"], 1, 0, [], "count does not match"),
        (["cache"], 2, 2, [], "count does not match"),
        (["cache"], True, 1, [], "count does not match"),
        (["cache", "cache"], 2, 2, [], "must be unique and new"),
        (["n1"], 1, 1, [], "must be unique and new"),
        (["n2"], 1, 1, ["n2"], "must be unique and new"),
        (["cache", "queue"], 2, 2, [], "no identity mapping"),
        ([" cache "], 1, 1, [], "exact bounded IDs"),
        ("cache", 1, 1, [], "exact bounded IDs"),
    ],
)
def test_scoped_named_additions_reject_invalid_identity_authority(
    named_ids,
    count,
    actual_count,
    removed,
    error,
):
    base_components = [
        {**component, "server_id": f"n{index + 1}"}
        for index, component in enumerate(
            workflow._decode_components(_components_wire())
        )
    ]
    original = copy.deepcopy(base_components)
    retained = [
        component
        for component in base_components
        if component["server_id"] not in removed
    ]
    candidate = [
        {key: value for key, value in component.items() if key != "server_id"}
        for component in retained
    ] + [
        {**base_components[-1], "label": f"Addition {index}"}
        for index in range(actual_count)
    ]

    with pytest.raises(workflow.GraphContractError, match=error):
        workflow._retain_component_ids(
            candidate,
            {"components": base_components},
            {
                "removable_node_ids": removed,
                "allowed_new_node_ids": named_ids,
                "allowed_new_node_count": count,
            },
        )

    assert base_components == original


@pytest.mark.asyncio
@pytest.mark.parametrize("render_passes", [True, False])
async def test_timed_out_components_retry_after_preview_target_still_requires_private_render(
    monkeypatch, render_passes
):
    from agent import deadlines
    from agent.stream_utils import StructuredLLMResponse

    clock = {"now": 100.0}
    monkeypatch.setattr(deadlines.time, "monotonic", lambda: clock["now"])
    actual_render = workflow._render
    downstream = []
    _install_success_boundaries(monkeypatch, events=downstream)
    provider_timeouts = []
    events = []
    rendered_at = []

    async def component_provider(**kwargs):
        provider_timeouts.append(kwargs["timeout_seconds"])
        if len(provider_timeouts) == 1:
            clock["now"] += 129.955
            raise TimeoutError("first component stream timed out")
        clock["now"] += 100.0
        return StructuredLLMResponse(
            text=json.dumps(
                {"candidate": _components_wire(), "clarification_questions": []}
            ),
            finish_reason="end_turn",
            input_tokens=1,
            output_tokens=1,
            provider="test",
            model="test",
        )

    async def send(event):
        events.append(event)

    async def private_render(graph):
        rendered_at.append(clock["now"])
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0 if render_passes else 1,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    monkeypatch.setattr(
        workflow,
        "generate_component_candidate",
        generation.generate_component_candidate,
    )
    monkeypatch.setattr(generation, "stream_structured_llm", component_provider)
    monkeypatch.setattr(workflow, "_render", actual_render)
    approved = _approved_graph()
    result = await workflow.run_staged_graph_pipeline(
        _state(
            terminal_deadline_s=1_010.0,
            graph_preview_deadline_s=270.0,
            approved_graph_data=approved,
            graph_data=approved,
            send=send,
            await_diagram_evaluation=private_render,
        )
    )

    assert provider_timeouts == pytest.approx([147.0, 217.045])
    assert rendered_at and min(rendered_at) > 270.0
    previews = [event for event in events if event.get("type") == "graph_preview"]
    if render_passes:
        assert result["graph_publication"] == "approved"
        assert downstream == ["component_gate", "connections", "connection_gate"]
        assert len(rendered_at) == len(previews) == 2
    else:
        assert result["graph_publication"] == "preserved"
        assert result["graph_data"] == approved
        assert (
            result["graph_operation"]["failure_code"]
            == "staged_component_render_rejected"
        )
        assert downstream == []
        assert len(rendered_at) == 1
        assert previews == []
