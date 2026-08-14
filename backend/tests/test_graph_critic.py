import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from adapters.llm_adapter import _anthropic_response_schema
from agent.architecture_rubric import (
    ADVISORY_RUBRIC_CODES,
    RUBRIC_CRITERIA,
    repair_requirements,
)
from agent.graph import _route_after_review
from agent.graph_repair_contract import (
    REPAIR_LAYER_PATCH_FIELDS,
    validate_local_repair_admission,
)
from agent.graph_review_budget import GraphReviewBudget
from agent.nodes.graph_critic import (
    _GRAPH_CRITIC_PROMPT_VERSION,
    _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA,
    _GRAPH_CRITIC_RESPONSE_SCHEMA,
    _GRAPH_CRITIC_SYSTEM,
    _MODEL_LAYER_FIELDS,
    _RUBRIC_CODE_OWNERS,
    _RUBRIC_CODES,
    _TOPOLOGY_PROOF_GUARANTEES,
    CriticProtocolError,
    _canonicalise_review_protocol,
    _critic_system,
    _deterministic_blocker_rule,
    _deterministic_render_review,
    _deterministic_review,
    _enforce_local_repair_admission,
    _hard_blockers,
    _locked_review_layers,
    _merge_locked_layer_verdicts,
    _model_connection_addition_obligations,
    _prior_open_obligations,
    _preflight_review_protocol,
    _prior_obligation_id,
    _review_packet,
    _request_critic_scorecard,
    _stop_repeated_repair_class,
    _semantic_graph_projection,
    _validate_repair_contract,
    _validate_corrected_group_move_authority,
    _validate_review_protocol,
    graph_critic_node,
    graph_render_gate_node,
)
from agent.nodes.graph_worker import _GRAPH_PATCH_KEYS, _apply_applied_graph_patch
from agent.stream_utils import StructuredLLMResponse
from config import GRAPH_MAX_CRITIC_CALLS, settings


def _structured_response(
    payload,
    *,
    finish_reason="end_turn",
):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return StructuredLLMResponse(
        text=text,
        finish_reason=finish_reason,
        input_tokens=1,
        output_tokens=1,
        provider="anthropic",
        model=settings.graph_qa_model,
    )


def _layer(status="pass", score=0.9, *, findings=None, **selectors):
    return {
        "status": status,
        "score": score,
        "blocking_findings": list(findings or []),
        "deterministic_finding_ids": list(
            selectors.get("deterministic_finding_ids") or []
        ),
        "node_ids": list(selectors.get("node_ids") or []),
        "edge_selectors": list(selectors.get("edge_selectors") or []),
        "group_ids": list(selectors.get("group_ids") or []),
        "composition_fields": list(selectors.get("composition_fields") or []),
        "sequence_indexes": list(selectors.get("sequence_indexes") or []),
        "assumption_indexes": list(selectors.get("assumption_indexes") or []),
        "context_node_ids": list(selectors.get("context_node_ids") or []),
        "addition_count": int(selectors.get("addition_count", 0)),
        "connection_addition_obligations": list(
            selectors.get("connection_addition_obligations") or []
        ),
        "composition_append_counts": dict(
            selectors.get("composition_append_counts") or {}
        ),
        "reason": "The artifact layer was assessed against the request.",
    }


def _repair_contract(
    *,
    scope="none",
    failed_layer=None,
    findings=None,
    score=0.9,
    layer_selectors=None,
):
    layers = {
        layer: _layer(score=score)
        for layer in (
            "components",
            "connections",
            "composition",
            "render",
        )
    }
    if failed_layer is not None:
        selectors = (layer_selectors or {}).get(failed_layer, {})
        layers[failed_layer] = _layer(
            "fail",
            min(score, 0.7),
            findings=findings or ["Repair this layer."],
            **selectors,
        )
    return {"repair_scope": scope, "layers": layers}


def _model_layer(layer):
    assessment = {
        "finding_codes": [],
        "deterministic_finding_indexes": [],
        "context_indexes": [],
        "context_node_indexes": [],
    }
    if layer == "components":
        assessment["node_indexes"] = []
        assessment["addition_count"] = 0
    elif layer == "connections":
        assessment["edge_indexes"] = []
        assessment["addition_obligations"] = []
    elif layer == "composition":
        assessment.update(
            {
                "group_indexes": [],
                "composition_fields": [],
                "sequence_indexes": [],
                "assumption_indexes": [],
                "group_addition_count": 0,
                "sequence_addition_count": 0,
                "assumption_addition_count": 0,
            }
        )
    return [assessment[field] for field in _MODEL_LAYER_FIELDS[layer]]


def _set_model_layer(payload, layer, **values):
    fields = _MODEL_LAYER_FIELDS[layer]
    row = payload["layers"][layer]
    for field, value in values.items():
        row[fields.index(field)] = value


def _passing_review_payload(*, strengths=None, advice=None, topology_proofs=None):
    _ = strengths, advice
    return {
        "layers": {
            layer: _model_layer(layer)
            for layer in (
                "components",
                "connections",
                "composition",
                "render",
            )
        },
        "topology_proofs": (
            topology_proofs
            if topology_proofs is not None
            else {
                guarantee: ["not_applicable", [], [], [], []]
                for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
            }
        ),
        "prior_obligation_dispositions": [],
    }


async def _accept_diagram(graph):
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


async def _ignore_event(_event):
    return None


@pytest.mark.asyncio
async def test_render_gate_emits_reversible_preview_and_binds_result_to_candidate():
    graph = _domain_graph()
    graph["design_origin"] = "applied"
    events = []

    async def send(event):
        events.append(event)

    result = await graph_render_gate_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "send": send,
            "await_diagram_evaluation": _accept_diagram,
        }
    )

    assert result["graph_render_admitted"] is True
    assert result["diagram_evaluation"]["result"]["screenshot_base64"] == (
        "private-render"
    )
    assert events[-1] == {"type": "graph_preview", "data": graph}


@pytest.mark.asyncio
async def test_render_gate_withholds_layout_failure_before_review_models_run():
    graph = _domain_graph()
    graph["design_origin"] = "applied"
    events = []

    async def send(event):
        events.append(event)

    async def clipped(_graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 1,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    result = await graph_render_gate_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "send": send,
            "await_diagram_evaluation": clipped,
        }
    )

    assert result["graph_render_admitted"] is False
    assert result["graph_review"]["failure_code"] == (
        "diagram_evaluation_layout_rejected"
    )
    assert not any(event.get("type") == "graph_preview" for event in events)


@pytest.mark.asyncio
async def test_render_gate_bounds_preview_transport_by_absolute_deadline():
    graph = _domain_graph()
    graph["design_origin"] = "applied"

    async def send(event):
        if event.get("type") == "graph_preview":
            await asyncio.Future()

    result = await graph_render_gate_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "send": send,
            "await_diagram_evaluation": _accept_diagram,
            "graph_preview_deadline_s": asyncio.get_running_loop().time() + 0.02,
        }
    )

    assert result["graph_render_admitted"] is False
    assert result["graph_review"]["failure_code"] == "graph_preview_timeout"
    assert "diagram_evaluation" not in result


def _critic_state(*, graph=None, complexity="prototype"):
    return {
        "graph_data": graph or _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": complexity,
        "send": _ignore_event,
        "await_diagram_evaluation": _accept_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    }


def test_semantic_critic_rejects_cache_replay_or_retry_gate_bypasses():
    assert _GRAPH_CRITIC_PROMPT_VERSION == "architecture_critic_v55"
    assert "gate-preserving reuse" in _GRAPH_CRITIC_SYSTEM
    assert "reuse stores accepted" in _GRAPH_CRITIC_SYSTEM
    assert "post-gate artifacts" in _GRAPH_CRITIC_SYSTEM
    assert "rejoins the gate" in _GRAPH_CRITIC_SYSTEM
    assert "inspect directed paths, not vocabulary" in _GRAPH_CRITIC_SYSTEM
    assert "Carrying a retry key is not durable" in _GRAPH_CRITIC_SYSTEM
    assert (
        "Rejection stops before execution and is not compensation"
        in _GRAPH_CRITIC_SYSTEM
    )
    assert "Sanitization does" in _GRAPH_CRITIC_SYSTEM
    assert "not make retrieved text trusted" in _GRAPH_CRITIC_SYSTEM
    assert "items 17-27 are blocking" in _GRAPH_CRITIC_SYSTEM
    assert "A passing proof cites the complete actual" in _critic_system(
        require_topology_proofs=True
    )
    assert "every blocking repair in one exhaustive scorecard" in _GRAPH_CRITIC_SYSTEM
    assert '[0,1,"returns the approved outcome"]' in _GRAPH_CRITIC_SYSTEM
    assert '[0,"$new_node_1","routes the rejected request"]' in _GRAPH_CRITIC_SYSTEM
    assert "Integer `2` never represents a proposed node" in _GRAPH_CRITIC_SYSTEM
    assert "event-stream systems define bounded" in _GRAPH_CRITIC_SYSTEM
    assert "backpressure and overload behavior" in _GRAPH_CRITIC_SYSTEM
    assert "partition/order or event-time semantics" in _GRAPH_CRITIC_SYSTEM
    assert "replay/checkpoint" in _GRAPH_CRITIC_SYSTEM
    assert "compatible schema evolution" in _GRAPH_CRITIC_SYSTEM
    assert (
        "grants only these exact source, target, and label triples"
        in _GRAPH_CRITIC_SYSTEM
    )
    assert "mandatory post-patch full-graph review" in _GRAPH_CRITIC_SYSTEM
    assert "is the normalized label for that added edge" in _GRAPH_CRITIC_SYSTEM
    assert "layers.composition.group_ids: unbounded_collection" in _GRAPH_CRITIC_SYSTEM
    assert "Never broaden one defective field" in _GRAPH_CRITIC_SYSTEM


def test_connection_addition_contract_label_is_bounded_by_graph_schema():
    with pytest.raises(CriticProtocolError) as raised:
        _model_connection_addition_obligations(
            [[0, 1, "x" * 101]],
            path="layers.connections.addition_obligations",
            nodes=[{"id": "source"}, {"id": "target"}],
            component_addition_count=0,
        )

    assert (
        raised.value.path
        == "layers.connections.addition_obligations[0].required_contract"
    )
    assert raised.value.rule == "invalid_range"


@pytest.mark.asyncio
async def test_request_scoped_critic_provider_call_ceiling_fails_closed(monkeypatch):
    calls = []

    async def unexpected_call(**kwargs):
        calls.append(kwargs)
        raise AssertionError(
            "critic provider must not be called past the request ceiling"
        )

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm", unexpected_call
    )
    state = _critic_state()
    state["graph_critic_call_count"] = GRAPH_MAX_CRITIC_CALLS

    result = await graph_critic_node(state)

    assert calls == []
    assert result["graph_critic_call_count"] == GRAPH_MAX_CRITIC_CALLS
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["failure_code"] == "semantic_review_unavailable"


@pytest.mark.asyncio
async def test_critic_adapter_retries_once_before_message_start(
    monkeypatch,
):
    import adapters.llm_adapter as llm_adapter

    attempts = 0

    async def critic_anthropic_stream(_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("critic provider failed before acceptance")
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=10,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                )
            ),
        )
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="{}"),
        )
        yield SimpleNamespace(
            type="message_delta",
            usage=SimpleNamespace(output_tokens=1),
            delta=SimpleNamespace(stop_reason="end_turn"),
        )

    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_delay_s", 0)
    monkeypatch.setattr(llm_adapter, "_anthropic_stream_once", critic_anthropic_stream)
    monkeypatch.setattr(
        "storage.telemetry_store.record_llm_telemetry", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "analytics.events.enqueue_analytics_event", lambda **_kwargs: None
    )
    monkeypatch.setattr("observability.current_trace_context", lambda: {})
    monkeypatch.setattr("observability.record_llm_metrics", lambda **_kwargs: None)

    result = await _request_critic_scorecard(
        _critic_state(),
        review_packet={"candidate": {}},
        render_result={},
        resolved_complexity="prototype",
        revision_count=0,
        require_topology_proofs=False,
    )

    assert settings.llm_max_retries == 2
    assert attempts == 2
    assert result.text == "{}"


def test_repair_contract_has_exactly_four_mece_layers_without_duplicate_selectors():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [{"id": "runtime"}],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {"source": "intake", "target": "gate", "label": "submit"}
                ]
            }
        },
    )

    _validate_repair_contract(contract, graph=graph)

    assert list(contract["layers"]) == [
        "components",
        "connections",
        "composition",
        "render",
    ]
    contract["layers"]["connections"]["edge_selectors"] *= 2
    with pytest.raises(ValueError, match="must not contain duplicates"):
        _validate_repair_contract(contract, graph=graph)


def test_component_additions_require_connection_additions():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={
            "components": {
                "addition_count": 1,
                "context_node_ids": ["intake"],
            }
        },
    )

    with pytest.raises(ValueError, match="connection"):
        _validate_repair_contract(contract, graph=graph)


def test_component_additions_in_a_grouped_graph_require_composition_groups():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Runtime",
                "kind": "runtime",
                "nodeIds": ["intake", "gate"],
            }
        ],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"addition_count": 1}},
    )
    contract["layers"]["connections"] = _layer(
        "fail",
        0.7,
        findings=["Connect the missing component."],
        addition_count=1,
        context_node_ids=["intake"],
        connection_addition_obligations=[
            {
                "source": "intake",
                "target": "$new_node_1",
                "required_contract": "attach the missing component",
            }
        ],
    )

    with pytest.raises(ValueError, match="groups"):
        _validate_repair_contract(contract, graph=graph)


def test_local_repair_admits_one_connected_cross_layer_region():
    edge = {"source": "intake", "target": "gate", "label": "submit"}
    graph = {
        "nodes": [{"id": node_id} for node_id in ("intake", "gate", "outcome")],
        "edges": [edge],
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": ["gate"]}},
    )
    contract["layers"]["connections"] = _layer(
        "fail",
        0.7,
        findings=["Repair the adjacent route."],
        edge_selectors=[edge],
    )

    validate_local_repair_admission(contract, graph=graph)


def test_local_repair_admits_a_contiguous_ungrouped_route():
    edges = [
        {"source": "a", "target": "b", "label": "first"},
        {"source": "b", "target": "c", "label": "second"},
        {"source": "c", "target": "d", "label": "third"},
    ]
    graph = {
        "nodes": [{"id": node_id} for node_id in ("a", "b", "c", "d")],
        "edges": edges,
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={"connections": {"edge_selectors": edges}},
    )

    validate_local_repair_admission(contract, graph=graph)


def test_local_repair_admits_disconnected_record_scoped_selectors():
    edges = [
        {"source": "a", "target": "b", "label": "first"},
        {"source": "c", "target": "d", "label": "second"},
    ]
    graph = {
        "design_origin": "applied",
        "nodes": [{"id": node_id} for node_id in ("a", "b", "c", "d")],
        "edges": edges,
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={"connections": {"edge_selectors": edges}},
    )

    validate_local_repair_admission(contract, graph=graph)

    review = _enforce_local_repair_admission(
        {
            "approved": False,
            "review_status": "completed",
            "repair_contract": contract,
        },
        graph,
    )
    assert review.get("terminal") is not True
    assert (
        _route_after_review(
            {
                "graph_changed": True,
                "graph_data": graph,
                "graph_revision_count": 0,
                "graph_review": review,
            }
        )
        == "revise"
    )


def test_local_repair_admits_an_existing_node_branch_addition():
    graph = {
        "nodes": [{"id": node_id} for node_id in ("gate", "approved", "rejected")],
        "edges": [],
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "addition_count": 2,
                "context_node_ids": ["gate", "approved", "rejected"],
                "connection_addition_obligations": [
                    {
                        "source": "gate",
                        "target": "approved",
                        "required_contract": "route approved decisions",
                    },
                    {
                        "source": "gate",
                        "target": "rejected",
                        "required_contract": "route rejected decisions",
                    },
                ],
            }
        },
    )

    validate_local_repair_admission(contract, graph=graph)


def test_local_component_additions_require_an_existing_graph_anchor():
    graph = {
        "nodes": [{"id": "existing"}],
        "edges": [],
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"addition_count": 2}},
    )
    contract["layers"]["connections"] = _layer(
        "fail",
        0.7,
        findings=["Connect the missing components."],
        addition_count=1,
        connection_addition_obligations=[
            {
                "source": "$new_node_1",
                "target": "$new_node_2",
                "required_contract": "connect the missing components",
            }
        ],
    )

    with pytest.raises(ValueError, match="existing graph anchor"):
        validate_local_repair_admission(contract, graph=graph)


def test_local_component_addition_region_must_connect_to_existing_graph():
    graph = {
        "nodes": [{"id": "existing"}],
        "edges": [],
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={
            "components": {
                "addition_count": 2,
                "context_node_ids": ["existing"],
            }
        },
    )
    contract["layers"]["connections"] = _layer(
        "fail",
        0.7,
        findings=["Connect the missing components."],
        addition_count=2,
        context_node_ids=["existing"],
        connection_addition_obligations=[
            {
                "source": "existing",
                "target": "$new_node_1",
                "required_contract": "attach the new region",
            },
            {
                "source": "$new_node_1",
                "target": "$new_node_2",
                "required_contract": "connect the new responsibilities",
            },
        ],
    )

    validate_local_repair_admission(contract, graph=graph)


def test_appended_groups_can_organize_existing_components():
    graph = {
        "nodes": [{"id": "a"}],
        "edges": [],
        "groups": [{"id": "runtime", "nodeIds": ["a"]}],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="composition",
        layer_selectors={
            "composition": {
                "composition_fields": ["groups"],
                "composition_append_counts": {"groups": 1},
            }
        },
    )

    validate_local_repair_admission(contract, graph=graph)


def test_local_repair_rejects_whole_collection_composition_authority():
    graph = {
        "nodes": [{"id": "gate"}],
        "edges": [],
        "groups": [{"id": "runtime", "nodeIds": ["gate"]}],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="composition",
        layer_selectors={"composition": {"composition_fields": ["groups"]}},
    )

    with pytest.raises(ValueError, match="whole groups collection"):
        validate_local_repair_admission(contract, graph=graph)


def test_local_repair_admits_cross_layer_metadata_with_topology():
    graph = {
        "nodes": [{"id": "gate"}],
        "edges": [],
        "groups": [],
        "title": "Current title",
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": ["gate"]}},
    )
    contract["layers"]["composition"] = _layer(
        "fail",
        0.7,
        findings=["Repair the title."],
        composition_fields=["title"],
    )

    validate_local_repair_admission(contract, graph=graph)


@pytest.mark.parametrize(
    ("case", "expected_path", "expected_rule"),
    [
        ("groups", "layers.composition.group_ids", "unbounded_collection"),
        ("sequence", "layers.composition.sequence_indexes", "unbounded_collection"),
        (
            "assumptions",
            "layers.composition.assumption_indexes",
            "unbounded_collection",
        ),
        (
            "missing_anchor",
            "layers.components.context_node_ids",
            "missing_graph_anchor",
        ),
        (
            "disconnected_new_region",
            "layers.connections.connection_addition_obligations",
            "missing_graph_anchor",
        ),
        (
            "insufficient_edges",
            "layers.connections.addition_count",
            "insufficient_connection_additions",
        ),
    ],
)
def test_local_repair_admission_reports_safe_coordinates(
    case,
    expected_path,
    expected_rule,
):
    graph = {
        "nodes": [{"id": "existing"}],
        "edges": [],
        "groups": (
            [{"id": "runtime", "nodeIds": ["existing"]}]
            if case in {"groups", "sequence", "assumptions"}
            else []
        ),
        "sequence": [{"step": 1}],
        "assumptions": ["Current assumption."],
    }
    if case in {"groups", "sequence", "assumptions"}:
        contract = _repair_contract(
            scope="local",
            failed_layer="composition",
            layer_selectors={
                "composition": {"composition_fields": [case]},
            },
        )
    else:
        contract = _repair_contract(
            scope="local",
            failed_layer="components",
            layer_selectors={"components": {"addition_count": 2}},
        )
        contract["layers"]["connections"] = _layer(
            "fail",
            0.7,
            findings=["Attach the missing components."],
            addition_count=(
                2 if case in {"missing_anchor", "disconnected_new_region"} else 1
            ),
            context_node_ids=[] if case == "missing_anchor" else ["existing"],
            connection_addition_obligations=(
                [
                    {
                        "source": "$new_node_1",
                        "target": "$new_node_2",
                        "required_contract": "attach the first missing component",
                    },
                    {
                        "source": "$new_node_2",
                        "target": "$new_node_1",
                        "required_contract": "attach the second missing component",
                    },
                ]
                if case in {"missing_anchor", "disconnected_new_region"}
                else [
                    {
                        "source": "$new_node_1",
                        "target": "$new_node_2",
                        "required_contract": "attach both missing components",
                    }
                ]
            ),
        )

    review = _enforce_local_repair_admission(
        {
            "approved": False,
            "review_status": "completed",
            "repair_contract": contract,
        },
        graph,
    )

    assert review["failure_code"] == "graph_repair_nonlocal"
    assert review["admission_error"] == {
        "path": expected_path,
        "rule": expected_rule,
    }


def test_repair_layer_patch_fields_are_a_mece_partition():
    owners = [
        owner
        for layer_fields in REPAIR_LAYER_PATCH_FIELDS.values()
        for owner in layer_fields
    ]

    assert set(REPAIR_LAYER_PATCH_FIELDS) == set(_MODEL_LAYER_FIELDS)
    assert set(owners) == _GRAPH_PATCH_KEYS
    assert len(owners) == len(set(owners))


def test_internal_contract_requires_all_four_artifact_layers():
    contract = _repair_contract()
    for assessment in contract["layers"].values():
        assessment["status"] = "not_applicable"
        assessment["score"] = 0.0

    with pytest.raises(ValueError, match="status must be pass or fail"):
        _validate_repair_contract(contract, graph={})

    layer_schema = _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]["layers"]
    assert list(layer_schema["properties"]) == [
        "components",
        "connections",
        "composition",
        "render",
    ]
    assert layer_schema["properties"]["components"] == {"$ref": "#/$defs/layer_row"}
    assert "repair_scope" not in _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]
    assert all(
        "status" not in fields and "score" not in fields
        for fields in _MODEL_LAYER_FIELDS.values()
    )
    assert (
        set(
            _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]["topology_proofs"]["properties"]
        )
        == _TOPOLOGY_PROOF_GUARANTEES
    )


def test_model_indexes_are_expanded_to_exact_locked_selectors():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [{"id": "runtime"}],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "connections",
        finding_codes=[5],
        edge_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload, graph=graph, deterministic_findings=[], review_context=[]
    )

    assert list(normalized["repair_contract"]["layers"]) == [
        "components",
        "connections",
        "composition",
        "render",
    ]
    assert normalized["repair_contract"]["layers"]["connections"]["edge_selectors"] == [
        {"source": "intake", "target": "gate", "label": "submit"}
    ]
    assert normalized["repair_contract"]["layers"]["connections"][
        "blocking_findings"
    ] == ["Repair edge semantics in the connections layer."]
    _validate_repair_contract(normalized["repair_contract"], graph=graph)


def test_layer_status_score_and_scope_are_derived_from_blockers():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "connections",
        finding_codes=[5],
        edge_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    layers = normalized["repair_contract"]["layers"]

    assert layers["connections"]["status"] == "fail"
    assert layers["connections"]["score"] == 0.0
    assert layers["components"]["status"] == "pass"
    assert layers["components"]["score"] == 1.0
    assert normalized["repair_contract"]["repair_scope"] == "local"


def test_scorecard_preflight_reports_independent_row_defects_together():
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(payload, "components", node_indexes=[4])
    _set_model_layer(payload, "connections", edge_indexes=[7])

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
        )

    assert "layers.components.node_indexes:invalid_reference" in str(caught.value)
    assert "layers.connections.edge_indexes:invalid_reference" in str(caught.value)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_scorecard_preflight_reports_exact_root_shape_defect(mutation):
    payload = _passing_review_payload(topology_proofs={})
    if mutation == "missing":
        del payload["prior_obligation_dispositions"]
    else:
        payload["unexpected"] = []

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
        )

    assert caught.value.path == "critic_scorecard"
    assert caught.value.rule == "invalid_shape"


def test_scorecard_preflight_preserves_exact_nested_contract_defect():
    payload = _passing_review_payload(topology_proofs={})
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    _set_model_layer(
        payload,
        "connections",
        finding_codes=[connection_code],
        addition_obligations=[[0, 1, "x" * 101]],
    )

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={
                "nodes": [{"id": "source"}, {"id": "target"}],
                "edges": [],
            },
            deterministic_findings=[],
            review_context=[],
        )

    assert (
        caught.value.path
        == "layers.connections.addition_obligations[0].required_contract"
    )
    assert caught.value.rule == "invalid_range"


def test_scorecard_preflight_reports_independent_proof_defects_together():
    payload = _passing_review_payload()
    guarantees = sorted(_TOPOLOGY_PROOF_GUARANTEES)[:2]
    for guarantee in guarantees:
        payload["topology_proofs"][guarantee] = ["pass", [], [], [], []]

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=True,
        )

    for guarantee in guarantees:
        assert f"topology_proofs.{guarantee}:missing_evidence" in str(caught.value)


@pytest.mark.asyncio
async def test_protocol_correction_receives_all_repair_algebra_defects(monkeypatch):
    invalid = _passing_review_payload(topology_proofs={})
    _set_model_layer(invalid, "components", node_indexes=[0])
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    _set_model_layer(
        invalid,
        "connections",
        finding_codes=[connection_code],
        addition_obligations=[[0, 0, "invalid self connection"]],
    )
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = (
            invalid if len(calls) == 1 else _passing_review_payload(topology_proofs={})
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    graph["nodes"][0]["id"] = "selected"
    result = await graph_critic_node(_critic_state(graph=graph))

    assert result["graph_review"]["approved"] is True
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "layers.components:unexpected_context" in correction
    assert "layers.connections.addition_obligations:invalid_contract" in correction


@pytest.mark.asyncio
async def test_protocol_correction_receives_exact_root_shape_coordinate(monkeypatch):
    invalid = _passing_review_payload(topology_proofs={})
    invalid["unexpected"] = []
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = (
            invalid
            if len(calls) == 1
            else _passing_review_payload(topology_proofs={})
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )

    result = await graph_critic_node(_critic_state())

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 2
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "critic_scorecard:invalid_shape" in correction


def test_critic_schema_keeps_named_layers_without_repeating_rubric_names():
    layer_schemas = _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]["layers"]["properties"]
    for layer in ("components", "connections", "composition", "render"):
        assert layer_schemas[layer] == {"$ref": "#/$defs/layer_row"}
    schema_text = json.dumps(_GRAPH_CRITIC_RESPONSE_SCHEMA, separators=(",", ":"))
    assert len(schema_text) < 1_500
    assert "domain_specificity" not in schema_text


def test_anthropic_schema_transform_preserves_critic_definitions_and_refs():
    transformed = _anthropic_response_schema(_GRAPH_CRITIC_RESPONSE_SCHEMA)
    prototype = _anthropic_response_schema(_GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA)

    assert transformed["$defs"] == _GRAPH_CRITIC_RESPONSE_SCHEMA["$defs"]
    assert transformed["properties"]["layers"]["properties"]["components"] == {
        "$ref": "#/$defs/layer_row"
    }
    assert transformed["properties"]["topology_proofs"]["properties"][
        "state_effect_reconciliation"
    ] == {"$ref": "#/$defs/proof_row"}
    assert prototype["$defs"] == {
        "layer_row": _GRAPH_CRITIC_RESPONSE_SCHEMA["$defs"]["layer_row"]
    }
    assert prototype["properties"]["topology_proofs"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }


@pytest.mark.parametrize("layer", list(_MODEL_LAYER_FIELDS))
@pytest.mark.parametrize("length_change", [-1, 1])
def test_model_layer_rows_require_the_exact_layer_arity(layer, length_change):
    payload = _passing_review_payload()
    row = payload["layers"][layer]
    payload["layers"][layer] = row[:-1] if length_change < 0 else [*row, []]

    with pytest.raises(ValueError, match=f"{layer} scorecard row must contain"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )


@pytest.mark.parametrize("length", [1, 2, 3, 4, 6])
def test_model_proof_rows_require_exact_status_and_edge_indexes(length):
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["not_applicable"] * length

    with pytest.raises(ValueError, match=f"topology_proofs.{guarantee} is malformed"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )


def test_topology_proof_validation_follows_resolved_depth():
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["pass", [], [], [], []]

    prototype = _canonicalise_review_protocol(
        payload,
        graph={},
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )

    assert prototype["topology_proofs"] == []
    with pytest.raises(CriticProtocolError, match="pass requires evidence") as error:
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=True,
        )
    assert error.value.path == f"topology_proofs.{guarantee}"
    assert error.value.rule == "missing_evidence"


@pytest.mark.asyncio
async def test_prototype_depth_rejects_production_only_codes_despite_request_wording(
    monkeypatch,
):
    calls = []
    production_only_code = _RUBRIC_CODES.index("topology_enforced_guarantees") + 1
    invalid = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        invalid,
        "connections",
        finding_codes=[production_only_code],
        edge_indexes=[0],
    )
    valid = _passing_review_payload(topology_proofs={})

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid if len(calls) == 1 else valid)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(complexity="prototype")
    state["user_message"] = "Design a production-ready campaign workflow."

    result = await graph_critic_node(state)

    assert result["graph_review"]["approved"] is True
    assert [call["telemetry"]["operation"] for call in calls] == [
        "graph_critic",
        "graph_critic_protocol_correction",
    ]
    assert "selected UI depth is prototype and is authoritative" in calls[0]["system"]
    assert "out of scope" in calls[0]["system"]


def test_protocol_errors_expose_only_safe_coordinates():
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = [
        "PRIVATE_SENTINEL",
        [],
        [],
        [],
        [],
    ]

    with pytest.raises(CriticProtocolError) as error:
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )

    assert error.value.path == f"topology_proofs.{guarantee}.status"
    assert error.value.rule == "invalid_enum"
    assert "PRIVATE_SENTINEL" not in str(error.value)


@pytest.mark.parametrize(
    ("layer", "field", "value", "match"),
    [
        ("components", "finding_codes", 1, "unknown rubric code"),
        ("components", "node_indexes", ["0"], "valid zero-based indexes"),
        ("composition", "composition_fields", [0], "unknown token"),
    ],
)
def test_model_layer_rows_reject_position_type_swaps(layer, field, value, match):
    payload = _passing_review_payload()
    _set_model_layer(payload, layer, **{field: value})

    with pytest.raises(ValueError, match=match):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": [], "groups": []},
            deterministic_findings=[],
            review_context=[],
        )


@pytest.mark.parametrize(
    "codes",
    [[-1], [0], [28], [1.0], [True], ["domain_specificity"]],
)
def test_model_rubric_codes_reject_values_outside_the_numbered_codebook(codes):
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "components",
        finding_codes=codes,
    )

    with pytest.raises(ValueError, match="unknown rubric code"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": []},
            deterministic_findings=[],
            review_context=[],
        )


def test_model_rubric_codes_reject_duplicates():
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "components",
        finding_codes=[1, 1],
    )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": []},
            deterministic_findings=[],
            review_context=[],
        )


def test_every_numbered_rubric_code_expands_to_its_canonical_finding():
    payload = _passing_review_payload()
    for layer in _MODEL_LAYER_FIELDS:
        owned_codes = [
            index
            for index, code in enumerate(_RUBRIC_CODES, start=1)
            if _RUBRIC_CODE_OWNERS[code] == layer
        ]
        values = {"finding_codes": owned_codes}
        if layer == "composition":
            values["composition_fields"] = ["assumptions"]
        _set_model_layer(payload, layer, **values)

    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": []},
        deterministic_findings=[],
        review_context=[],
    )

    for layer in _MODEL_LAYER_FIELDS:
        assert normalized["repair_contract"]["layers"][layer]["blocking_findings"] == [
            f"Repair {code.replace('_', ' ')} in the {layer} layer."
            for code in _RUBRIC_CODES
            if _RUBRIC_CODE_OWNERS[code] == layer and code not in ADVISORY_RUBRIC_CODES
        ]
    assert normalized["advice"] == [RUBRIC_CRITERIA["novice_clarity"][1]]


def test_prototype_flow_and_branch_findings_are_advice_without_mutation_authority():
    payload = _passing_review_payload(topology_proofs={})
    codes = [
        _RUBRIC_CODES.index("logical_flow") + 1,
        _RUBRIC_CODES.index("branch_completion") + 1,
    ]
    _set_model_layer(payload, "connections", finding_codes=codes)

    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": [], "edges": []},
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
        resolved_depth="prototype",
    )

    connections = normalized["repair_contract"]["layers"]["connections"]
    assert connections["status"] == "pass"
    assert connections["blocking_findings"] == []
    assert connections["edge_selectors"] == []
    assert normalized["hard_blockers"] == []
    assert normalized["advice"] == [
        RUBRIC_CRITERIA["logical_flow"][1],
        RUBRIC_CRITERIA["branch_completion"][1],
    ]


@pytest.mark.parametrize("resolved_depth", ["low", "prototype"])
def test_nonproduction_authored_composition_is_advice_without_mutation_authority(
    resolved_depth,
):
    graph = {
        "nodes": [{"id": "entry"}, {"id": "outcome"}],
        "edges": [{"source": "entry", "target": "outcome", "label": "returns"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Primary runtime",
                "kind": "runtime",
                "nodeIds": ["entry", "outcome"],
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["entry", "outcome"], "description": "returns"}
        ],
        "assumptions": [],
    }
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        payload,
        "composition",
        finding_codes=[_RUBRIC_CODES.index("authored_composition") + 1],
        group_indexes=[0],
        composition_fields=["groups", "sequence"],
        sequence_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
        resolved_depth=resolved_depth,
    )

    composition = normalized["repair_contract"]["layers"]["composition"]
    assert composition["status"] == "pass"
    assert composition["blocking_findings"] == []
    assert composition["group_ids"] == []
    assert composition["composition_fields"] == []
    assert composition["sequence_indexes"] == []
    assert normalized["hard_blockers"] == []
    assert normalized["advice"] == [RUBRIC_CRITERIA["authored_composition"][1]]


def test_production_flow_and_branch_findings_remain_blocking():
    payload = _passing_review_payload(topology_proofs={})
    codes = [
        _RUBRIC_CODES.index("logical_flow") + 1,
        _RUBRIC_CODES.index("branch_completion") + 1,
    ]
    _set_model_layer(payload, "connections", finding_codes=codes)

    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": [], "edges": []},
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
        resolved_depth="production",
    )

    connections = normalized["repair_contract"]["layers"]["connections"]
    assert connections["status"] == "fail"
    assert len(connections["blocking_findings"]) == 2
    assert len(normalized["hard_blockers"]) == 2


@pytest.mark.parametrize(
    ("layer", "code", "owner"),
    [
        ("components", 5, "connections"),
        ("connections", 6, "composition"),
        ("render", 8, "composition"),
        ("render", 1, "components"),
    ],
)
def test_rubric_codes_cannot_unlock_a_layer_they_do_not_own(layer, code, owner):
    payload = _passing_review_payload()
    values = {"finding_codes": [code]}
    if layer == "composition":
        values["composition_fields"] = ["assumptions"]
    _set_model_layer(payload, layer, **values)

    with pytest.raises(ValueError, match=f"belongs to the {owner} layer, not {layer}"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )


@pytest.mark.parametrize("finding_codes", [[17], [5]])
def test_failed_topology_proof_requires_connections_code_17(finding_codes):
    graph = {
        "nodes": [
            {"id": "source", "label": "Source"},
            {"id": "target", "label": "Target"},
        ],
        "edges": [],
    }
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["fail", [], [], [0], []]
    _set_model_layer(
        payload,
        "connections",
        finding_codes=finding_codes,
        context_node_indexes=[0, 1],
        addition_obligations=[[0, 1, "restore the required directed guarantee"]],
    )

    if finding_codes == [5]:
        with pytest.raises(ValueError, match="topology_enforced_guarantees"):
            _canonicalise_review_protocol(
                payload,
                graph=graph,
                deterministic_findings=[],
                review_context=[],
            )
        return

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
    )
    assert normalized["topology_proofs"][0]["reason"].startswith("Repair the failed ")
    assert (
        normalized["topology_proofs"][0]["reason"]
        in normalized["repair_contract"]["layers"]["connections"]["blocking_findings"]
    )
    topology_requirement = next(
        item
        for item in repair_requirements(
            normalized["repair_contract"], normalized["topology_proofs"]
        )
        if item["criterion"].startswith("topology_proof:")
    )
    assert (
        "Required additions: source -> target: restore the required directed guarantee"
        in topology_requirement["requirement"]
    )
    _validate_review_protocol(
        normalized,
        require_topology_proofs=True,
        graph=graph,
    )


def test_connection_addition_count_is_derived_from_exact_obligations():
    graph = {
        "nodes": [
            {"id": "gate", "label": "Gate"},
            {"id": "audit", "label": "Audit"},
            {"id": "metrics", "label": "Metrics"},
        ],
        "edges": [],
    }
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        payload,
        "connections",
        finding_codes=[5],
        addition_obligations=[
            [0, 1, "record the accepted action in the canonical audit log"]
        ],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    connections = normalized["repair_contract"]["layers"]["connections"]

    assert connections["addition_count"] == 1
    assert connections["connection_addition_obligations"] == [
        {
            "source": "gate",
            "target": "audit",
            "required_contract": (
                "record the accepted action in the canonical audit log"
            ),
        }
    ]
    assert connections["context_node_ids"] == ["gate", "audit"]
    _validate_repair_contract(normalized["repair_contract"], graph=graph)


def test_two_node_scorecard_authorizes_exact_attached_component_patch():
    graph = {
        "graph_type": "architecture",
        "design_origin": "applied",
        "title": "Two-node candidate",
        "nodes": [
            {
                "id": "entry",
                "label": "Request entry",
                "type": "gateway",
                "technology": "HTTPS",
                "description": "Receives a bounded request.",
            },
            {
                "id": "worker",
                "label": "Request worker",
                "type": "service",
                "technology": "Application service",
                "description": "Processes the bounded request.",
            },
        ],
        "edges": [
            {
                "source": "entry",
                "target": "worker",
                "label": "dispatches request",
                "technology": "HTTPS",
                "sync": "sync",
                "flow": "runtime",
                "description": "Dispatches the validated request.",
            }
        ],
        "sequence": [
            {
                "step": 1,
                "nodes": ["entry", "worker"],
                "description": "Processes the request.",
            }
        ],
        "assumptions": [],
    }
    payload = _passing_review_payload(topology_proofs={})
    component_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "components"
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    _set_model_layer(
        payload,
        "components",
        finding_codes=[component_code],
        context_node_indexes=[0],
        addition_count=1,
    )
    _set_model_layer(
        payload,
        "connections",
        finding_codes=[connection_code],
        addition_obligations=[
            [0, "$new_node_1", "route the request to an observable outcome"]
        ],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    contract = normalized["repair_contract"]
    validate_local_repair_admission(contract, graph=graph)
    patched = _apply_applied_graph_patch(
        graph,
        {
            "add_nodes": [
                {
                    "id": "outcome",
                    "label": "Observable outcome",
                    "type": "service",
                    "technology": "Application service",
                    "description": "Returns the completed request outcome.",
                }
            ],
            "add_edges": [
                {
                    "source": "entry",
                    "target": "outcome",
                    "label": "route the request to an observable outcome",
                    "technology": "HTTPS",
                    "sync": "sync",
                    "flow": "runtime",
                    "description": "Routes the request to its observable outcome.",
                }
            ],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert [node["id"] for node in patched["nodes"]] == [
        "entry",
        "worker",
        "outcome",
    ]
    assert (patched["edges"][-1]["source"], patched["edges"][-1]["target"]) == (
        "entry",
        "outcome",
    )


def test_failed_topology_proof_requires_an_exact_repair_obligation():
    graph = {
        "nodes": [
            {"id": "source", "label": "Source"},
            {"id": "target", "label": "Target"},
        ],
        "edges": [],
    }
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["fail", [], [], [], []]
    _set_model_layer(payload, "connections", finding_codes=[17])

    with pytest.raises(CriticProtocolError, match="exact repair path") as error:
        _canonicalise_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=[],
            review_context=[],
        )

    assert error.value.path == f"topology_proofs.{guarantee}"
    assert error.value.rule == "missing_evidence"


def test_failed_topology_proof_projects_an_existing_edge_repair_selector():
    graph = {
        "nodes": [
            {"id": "source", "label": "Source"},
            {"id": "target", "label": "Target"},
        ],
        "edges": [{"source": "source", "target": "target", "label": "ambiguous flow"}],
    }
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["fail", [], [], [], [0]]
    _set_model_layer(payload, "connections", finding_codes=[17])

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
    )

    selector = {"source": "source", "target": "target", "label": "ambiguous flow"}
    connections = normalized["repair_contract"]["layers"]["connections"]
    assert connections["edge_selectors"] == [selector]
    failed_proof = next(
        proof
        for proof in normalized["topology_proofs"]
        if proof["guarantee"] == guarantee
    )
    assert failed_proof["repair_obligations"] == []
    assert failed_proof["repair_edge_selectors"] == [selector]
    requirement = next(
        item
        for item in repair_requirements(
            normalized["repair_contract"], normalized["topology_proofs"]
        )
        if item["criterion"] == f"topology_proof:{guarantee}"
    )
    assert (
        "Required existing-edge repairs: source -> target: ambiguous flow"
        in requirement["requirement"]
    )
    _validate_review_protocol(
        normalized,
        require_topology_proofs=True,
        graph=graph,
    )


@pytest.mark.parametrize("status", ["pass", "not_applicable"])
def test_non_failed_topology_proofs_forbid_existing_edge_repair_references(status):
    graph = {
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [{"source": "source", "target": "target", "label": "flow"}],
    }
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    edge_indexes = [0] if status == "pass" else []
    route_pairs = [[0, 1]] if status == "pass" else []
    payload["topology_proofs"][guarantee] = [
        status,
        edge_indexes,
        route_pairs,
        [],
        [0],
    ]

    with pytest.raises(ValueError, match="cannot cite repair"):
        _canonicalise_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=[],
            review_context=[],
        )


def test_prior_open_obligations_require_explicit_consistent_dispositions():
    prior_finding = "Repair edge semantics in the connections layer."
    prior_id = _prior_obligation_id(layer="connections", finding=prior_finding)
    prior = [
        {
            "id": prior_id,
            "layer": "connections",
            "finding": prior_finding,
        }
    ]
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(payload, "connections", finding_codes=[5])

    with pytest.raises(ValueError, match="classify every prior open obligation"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=False,
            prior_open_obligations=prior,
        )

    payload["prior_obligation_dispositions"] = [[prior_id, "resolved"]]
    with pytest.raises(ValueError, match="server-derived typed blockers"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=False,
            prior_open_obligations=prior,
        )

    _set_model_layer(payload, "connections", finding_codes=[3])
    payload["prior_obligation_dispositions"] = [[prior_id, "resolved"]]
    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": [], "edges": []},
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
        prior_open_obligations=prior,
    )
    assert normalized["prior_obligation_dispositions"] == [
        {"prior_obligation_id": prior_id, "status": "resolved"}
    ]
    assert (
        prior_finding
        not in normalized["repair_contract"]["layers"]["connections"][
            "blocking_findings"
        ]
    )


def test_prior_obligation_dispositions_reject_unknown_server_ids():
    prior_finding = "Keep this blocker open."
    prior = [
        {
            "id": _prior_obligation_id(layer="connections", finding=prior_finding),
            "layer": "connections",
            "finding": prior_finding,
        }
    ]
    payload = _passing_review_payload(topology_proofs={})
    payload["prior_obligation_dispositions"] = [["prior_unknown", "resolved"]]

    with pytest.raises(ValueError, match="prior_obligation_id"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=False,
            prior_open_obligations=prior,
        )


def test_still_failing_prior_obligation_stops_an_identical_second_repair_class():
    finding = "Repair edge semantics in the connections layer."
    obligation_id = _prior_obligation_id(layer="connections", finding=finding)
    review = {
        "approved": False,
        "review_status": "completed",
        "missing": [finding],
        "prior_obligation_dispositions": [
            {"prior_obligation_id": obligation_id, "status": "still_fail"}
        ],
    }

    stopped = _stop_repeated_repair_class(
        review,
        prior_open_obligations=[
            {"id": obligation_id, "layer": "connections", "finding": finding}
        ],
        repair_round_count=1,
        contract_correction=None,
    )

    assert stopped["terminal"] is True
    assert stopped["failure_code"] == "graph_repair_no_new_counterexample"
    assert stopped["missing"] == [finding]


def test_resolved_prior_obligation_allows_a_distinct_second_repair():
    finding = "Repair edge semantics in the connections layer."
    obligation_id = _prior_obligation_id(layer="connections", finding=finding)
    review = {
        "approved": False,
        "review_status": "completed",
        "missing": ["Repair branch completion in the connections layer."],
        "prior_obligation_dispositions": [
            {"prior_obligation_id": obligation_id, "status": "resolved"}
        ],
    }

    continued = _stop_repeated_repair_class(
        review,
        prior_open_obligations=[
            {"id": obligation_id, "layer": "connections", "finding": finding}
        ],
        repair_round_count=1,
        contract_correction=None,
    )

    assert continued is review
    assert "terminal" not in continued


def _typed_blockers_for_test(*, edge_selectors=None, specs):
    layers = _repair_contract(
        scope="local",
        failed_layer="connections",
        findings=["Repair this layer."],
        layer_selectors={"connections": {"edge_selectors": list(edge_selectors or [])}},
    )["layers"]
    return _hard_blockers(canonical_layers=layers, specs=specs)


def test_hard_blocker_ids_ignore_display_wording_and_deterministic_order():
    rubric_a = _typed_blockers_for_test(
        specs=[
            {
                "kind": "rubric",
                "layer": "connections",
                "key": {"code": "branch_completion"},
                "message": "Repair every fallback branch.",
            }
        ]
    )
    rubric_b = _typed_blockers_for_test(
        specs=[
            {
                "kind": "rubric",
                "layer": "connections",
                "key": {"code": "branch_completion"},
                "message": "Different display wording.",
            }
        ]
    )
    deterministic_a = _typed_blockers_for_test(
        specs=[
            {
                "kind": "deterministic",
                "layer": "connections",
                "key": {"rule": "feedback_edge"},
                "message": "Add feedback.",
            },
            {
                "kind": "deterministic",
                "layer": "connections",
                "key": {"rule": "connected_graph"},
                "message": "Connect the graph.",
            },
        ]
    )
    deterministic_b = _typed_blockers_for_test(
        specs=list(
            reversed(
                [
                    {
                        "kind": "deterministic",
                        "layer": "connections",
                        "key": {"rule": "feedback_edge"},
                        "message": "New feedback wording.",
                    },
                    {
                        "kind": "deterministic",
                        "layer": "connections",
                        "key": {"rule": "connected_graph"},
                        "message": "New connectivity wording.",
                    },
                ]
            )
        )
    )
    context_a = _typed_blockers_for_test(
        specs=[
            {
                "kind": "context",
                "layer": "connections",
                "key": {
                    "commitments": ["Architect commitment: preserve the gate."],
                    "anchor_node_ids": ["approval", "executor"],
                },
                "message": "Repair the anchored context.",
            }
        ]
    )
    context_b = _typed_blockers_for_test(
        specs=[
            {
                "kind": "context",
                "layer": "connections",
                "key": {
                    "commitments": ["Architect commitment: preserve the gate."],
                    "anchor_node_ids": ["approval", "executor"],
                },
                "message": "Different context display wording.",
            }
        ]
    )

    assert rubric_a[0]["id"] == rubric_b[0]["id"]
    assert {blocker["id"] for blocker in deterministic_a} == {
        blocker["id"] for blocker in deterministic_b
    }
    assert context_a[0]["id"] == context_b[0]["id"]


def test_topology_hard_blocker_identity_uses_the_guarantee_not_its_reason():
    first = _typed_blockers_for_test(
        specs=[
            {
                "kind": "topology",
                "layer": "connections",
                "key": {"guarantee": "audit_and_provenance"},
                "message": "Repair the audit proof.",
            }
        ]
    )
    second = _typed_blockers_for_test(
        specs=[
            {
                "kind": "topology",
                "layer": "connections",
                "key": {"guarantee": "audit_and_provenance"},
                "message": "Different proof reason.",
            }
        ]
    )

    assert first[0]["id"] == second[0]["id"]
    assert first[0]["repair_fingerprint"] == second[0]["repair_fingerprint"]


def test_repair_fingerprint_ignores_set_like_selector_order():
    selectors = [
        {"source": "entry", "target": "worker", "label": "dispatch"},
        {"source": "worker", "target": "outcome", "label": "returns"},
    ]
    specs = [
        {
            "kind": "rubric",
            "layer": "connections",
            "key": {"code": "branch_completion"},
            "message": "Repair branch completion.",
        }
    ]

    first = _typed_blockers_for_test(edge_selectors=selectors, specs=specs)
    reordered = _typed_blockers_for_test(
        edge_selectors=list(reversed(selectors)),
        specs=specs,
    )

    assert first[0]["repair_fingerprint"] == reordered[0]["repair_fingerprint"]


def test_second_repair_requires_a_new_typed_counterexample():
    selector = {"source": "entry", "target": "worker", "label": "dispatch"}
    prior = _typed_blockers_for_test(
        edge_selectors=[selector],
        specs=[
            {
                "kind": "rubric",
                "layer": "connections",
                "key": {"code": "branch_completion"},
                "message": "Repair branch completion.",
            }
        ],
    )[0]
    changed = _typed_blockers_for_test(
        edge_selectors=[{"source": "worker", "target": "outcome", "label": "returns"}],
        specs=[
            {
                "kind": "rubric",
                "layer": "connections",
                "key": {"code": "branch_completion"},
                "message": "Repair branch completion again.",
            }
        ],
    )[0]
    review = {
        "approved": False,
        "review_status": "completed",
        "hard_blockers": [changed],
        "prior_obligation_dispositions": [
            {"prior_obligation_id": prior["id"], "status": "still_fail"}
        ],
    }

    assert (
        _stop_repeated_repair_class(
            review,
            prior_open_obligations=[prior],
            repair_round_count=1,
            contract_correction=None,
        )
        is review
    )

    repeated_review = {**review, "hard_blockers": [prior]}
    stopped = _stop_repeated_repair_class(
        repeated_review,
        prior_open_obligations=[prior],
        repair_round_count=1,
        contract_correction=None,
    )
    assert stopped["failure_code"] == "graph_repair_no_new_counterexample"


def test_locked_layer_merge_preserves_hard_blockers():
    component_blocker = {
        "id": "blocker_v1:rubric:components:test",
        "kind": "rubric",
        "layer": "components",
        "key": {"code": "domain_specificity"},
        "message": "Repair domain specificity.",
        "repair_fingerprint": "fingerprint",
    }
    contract = _repair_contract()
    merged = _merge_locked_layer_verdicts(
        {
            "repair_contract": contract,
            "strengths": [],
            "advice": [],
            "topology_proofs": [],
            "hard_blockers": [],
            "prior_obligation_dispositions": [],
        },
        previous_review={
            "repair_contract": contract,
            "topology_proofs": [],
            "hard_blockers": [component_blocker],
        },
        locked_layers={"components"},
    )

    assert merged["hard_blockers"] == [component_blocker]


def test_review_packet_carries_open_findings_and_prototype_filters_production_only():
    state = _critic_state()
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        findings=[
            "Repair edge semantics in the connections layer.",
            "Repair topology enforced guarantees in the connections layer.",
        ],
        layer_selectors={"connections": {"edge_selectors": []}},
    )
    state["graph_review"] = {"repair_contract": contract}

    packet = _review_packet(
        state,
        graph=state["graph_data"],
        query=state["user_message"],
        resolved_depth="prototype",
        render_result={},
    )

    assert packet["prior_open_obligations"] == [
        {
            "id": _prior_obligation_id(
                layer="connections",
                finding="Repair edge semantics in the connections layer.",
            ),
            "layer": "connections",
            "kind": "legacy",
            "finding": "Repair edge semantics in the connections layer.",
            "message": "Repair edge semantics in the connections layer.",
            "repair_fingerprint": "legacy",
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "deterministic_findings", "review_context", "match"),
    [
        (
            "finding_codes",
            [1],
            [],
            [],
            "failed components layer must cite a node or declare additions",
        ),
        (
            "deterministic_finding_indexes",
            [0],
            [
                {
                    "id": "deterministic_1",
                    "finding": "Missing required control.",
                    "owner_layer": "components",
                }
            ],
            [],
            "failed components layer must cite a node or declare additions",
        ),
        ("node_indexes", [0], [], [], "cannot expose editable selectors"),
        (
            "context_indexes",
            [0],
            [],
            ["Architect commitment: preserve trust."],
            "cannot cite repair context",
        ),
    ],
)
def test_passing_component_layer_is_locked_at_the_model_boundary(
    field,
    value,
    deterministic_findings,
    review_context,
    match,
):
    payload = _passing_review_payload()
    _set_model_layer(payload, "components", **{field: value})

    if field == "context_indexes":
        with pytest.raises(ValueError, match=match):
            _canonicalise_review_protocol(
                payload,
                graph={"nodes": [{"id": "intake"}]},
                deterministic_findings=deterministic_findings,
                review_context=review_context,
            )
        return

    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": [{"id": "intake"}]},
        deterministic_findings=deterministic_findings,
        review_context=review_context,
    )
    with pytest.raises(ValueError, match=match):
        _validate_review_protocol(
            normalized,
            require_topology_proofs=False,
            graph={"nodes": [{"id": "intake"}]},
            deterministic_findings=deterministic_findings,
        )


def test_missing_record_context_is_actionable_without_unlocking_node_anchors():
    graph = {
        "nodes": [
            {"id": "approval", "label": "Exact action approval"},
            {"id": "executor", "label": "Bounded executor"},
        ],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "connections",
        finding_codes=[4],
        context_indexes=[0],
        context_node_indexes=[0, 1],
        addition_obligations=[[0, 1, "bind approval to the exact authorized action"]],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=["Architect commitment: bind approval to the exact action."],
    )
    layer = normalized["repair_contract"]["layers"]["connections"]

    assert layer["node_ids"] == []
    assert layer["edge_selectors"] == []
    assert layer["context_node_ids"] == ["approval", "executor"]
    assert layer["addition_count"] == 1
    assert layer["blocking_findings"] == [
        "Repair safe action boundary in the connections layer.",
        "Repair context for the connections layer. Node anchors: approval "
        "(Exact action approval), executor (Bounded executor). Obligations: "
        "Architect commitment: bind approval to the exact action.",
    ]
    _validate_repair_contract(normalized["repair_contract"], graph=graph)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("context_indexes", [1], "valid zero-based indexes"),
        ("context_node_indexes", [2], "valid zero-based indexes"),
    ],
)
def test_repair_context_rejects_out_of_range_indexes(field, value, match):
    graph = {
        "nodes": [{"id": "approval", "label": "Approval"}],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "components",
        finding_codes=[1],
        **{field: value},
    )

    with pytest.raises(ValueError, match=match):
        _canonicalise_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=[],
            review_context=["Architect commitment: use domain names."],
        )


def test_passing_layer_cannot_expose_repair_context():
    payload = _passing_review_payload()
    _set_model_layer(payload, "components", context_node_indexes=[0])

    with pytest.raises(ValueError, match="passing components layer"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": [{"id": "intake", "label": "Intake"}]},
            deterministic_findings=[],
            review_context=[],
        )


def test_model_index_arrays_reject_duplicates_before_locking():
    graph = {
        "nodes": [{"id": "intake"}],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "components",
        finding_codes=[1],
        node_indexes=[0, 0],
    )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _canonicalise_review_protocol(
            payload, graph=graph, deterministic_findings=[], review_context=[]
        )


def test_model_scorecard_rejects_a_missing_mandatory_layer():
    payload = _passing_review_payload()
    payload["layers"].pop("render")

    with pytest.raises(ValueError, match="every artifact layer exactly once"):
        _canonicalise_review_protocol(
            payload, graph={}, deterministic_findings=[], review_context=[]
        )


def test_feedback_edge_finding_cannot_fail_components_while_connections_passes():
    graph = {
        "nodes": [
            {"id": "decision", "label": "Campaign Decision"},
            {"id": "outcome", "label": "Measured Outcome"},
        ],
        "edges": [
            {
                "source": "decision",
                "target": "outcome",
                "label": "records campaign outcome",
                "flow": "runtime",
            }
        ],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    deterministic_review = _deterministic_review(
        "Design a closed-loop campaign optimiser",
        graph,
        "prototype",
    )
    deterministic_findings = [
        {"id": "deterministic_1", **deterministic_review["deterministic_findings"][0]}
    ]
    assert deterministic_findings[0]["owner_layer"] == "connections"

    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "components",
        deterministic_finding_indexes=[0],
    )

    with pytest.raises(
        ValueError, match="belongs to the connections layer, not components"
    ):
        _canonicalise_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=[],
        )


def test_scorecard_admits_disconnected_selectors_when_every_finding_is_classified():
    graph = {
        "nodes": [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
            {"id": "c", "label": "C"},
            {"id": "d", "label": "D"},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "first"},
            {"source": "c", "target": "d", "label": "second"},
        ],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    deterministic_findings = [
        {
            "id": "deterministic_1",
            "owner_layer": "connections",
            "finding": "Repair the first route.",
        },
        {
            "id": "deterministic_2",
            "owner_layer": "connections",
            "finding": "Repair the disconnected second route.",
        },
    ]
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "connections",
        deterministic_finding_indexes=[0, 1],
        edge_indexes=[0, 1],
    )

    _preflight_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=deterministic_findings,
        review_context=[],
    )
    canonical = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=deterministic_findings,
        review_context=[],
        require_topology_proofs=False,
    )
    _validate_review_protocol(
        canonical,
        require_topology_proofs=False,
        graph=graph,
        deterministic_findings=deterministic_findings,
    )

    validate_local_repair_admission(canonical["repair_contract"], graph=graph)
    assert canonical["repair_contract"]["layers"]["connections"][
        "deterministic_finding_ids"
    ] == ["deterministic_1", "deterministic_2"]
    assert (
        canonical["repair_contract"]["layers"]["connections"]["edge_selectors"]
        == graph["edges"]
    )


def test_scorecard_rejects_unclassified_deterministic_findings():
    graph = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
        "edges": [
            {"source": "a", "target": "b", "label": "first"},
            {"source": "c", "target": "d", "label": "second"},
        ],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    deterministic_findings = [
        {
            "id": "deterministic_1",
            "owner_layer": "connections",
            "finding": "Repair the first route.",
        },
        {
            "id": "deterministic_2",
            "owner_layer": "connections",
            "finding": "Repair the second route.",
        },
    ]
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "connections",
        deterministic_finding_indexes=[0],
        edge_indexes=[0],
    )

    with pytest.raises(CriticProtocolError, match="incomplete_classification"):
        _preflight_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=[],
        )


def test_repair_contract_validation_enforces_deterministic_finding_owner():
    finding_id = "deterministic_1"
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        findings=["Add the required feedback edge."],
        layer_selectors={
            "components": {"deterministic_finding_ids": [finding_id]},
        },
    )

    with pytest.raises(
        ValueError, match="belongs to the connections layer, not components"
    ):
        _validate_repair_contract(
            contract,
            graph={},
            deterministic_finding_owners={finding_id: "connections"},
        )


def test_repair_contract_rejects_unknown_exact_selectors():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [{"id": "runtime"}],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {"source": "intake", "target": "gate", "label": "invented"}
                ]
            }
        },
    )

    with pytest.raises(ValueError, match="edge absent from the graph"):
        _validate_repair_contract(contract, graph=graph)


def test_failed_layer_score_must_stay_below_publishable_threshold():
    contract = _repair_contract(scope="local", failed_layer="components")
    contract["layers"]["components"]["score"] = 0.9

    with pytest.raises(ValueError, match="fail score must be below 0.78"):
        _validate_repair_contract(contract, graph={})


def test_graph_caused_render_failure_can_use_one_local_repair():
    contract = _repair_contract(scope="local", failed_layer="composition")
    contract["layers"]["composition"]["composition_fields"] = ["groups"]
    contract["layers"]["render"] = _layer(
        "fail",
        0.7,
        findings=["The screenshot has no clear reading order."],
    )

    _validate_repair_contract(contract, graph={"groups": []})


def test_render_only_failure_cannot_enter_local_patch_lane():
    contract = _repair_contract(scope="local", failed_layer="render")

    with pytest.raises(
        ValueError, match="must be global for the failed layer ownership"
    ):
        _validate_repair_contract(contract, graph={})


def test_model_payload_rejects_server_owned_repair_fields():
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"

    with pytest.raises(ValueError, match="exactly the required fields"):
        _canonicalise_review_protocol(
            payload, graph={}, deterministic_findings=[], review_context=[]
        )


@pytest.mark.parametrize(
    ("failed_layer", "expected_scope", "expected_route"),
    [
        ("connections", "local", "revise"),
        (None, "none", "accept"),
    ],
)
def test_repair_scope_is_derived_from_failed_layer_ownership(
    failed_layer,
    expected_scope,
    expected_route,
):
    graph = _domain_graph()
    payload = _passing_review_payload()
    if failed_layer is not None:
        finding_code = next(
            index
            for index, code in enumerate(_RUBRIC_CODES, start=1)
            if _RUBRIC_CODE_OWNERS[code] == failed_layer
        )
        values = {"finding_codes": [finding_code]}
        if failed_layer == "connections":
            values["edge_indexes"] = [0]
        _set_model_layer(
            payload,
            failed_layer,
            **values,
        )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    _validate_review_protocol(
        normalized,
        require_topology_proofs=False,
        graph=graph,
        deterministic_findings=[],
    )

    assert normalized["repair_contract"]["repair_scope"] == expected_scope
    assert (
        _route_after_review(
            {
                "graph_changed": True,
                "graph_data": {**graph, "design_origin": "applied"},
                "graph_revision_count": 0,
                "graph_review": {
                    "approved": expected_scope == "none",
                    **normalized,
                },
            }
        )
        == expected_route
    )


def test_failed_topology_proof_cannot_hide_behind_passing_layers():
    proofs = _valid_protocol_topology_proofs()
    proofs[0] = {
        **proofs[0],
        "status": "fail",
        "edge_evidence": [],
        "reason": "The reconciliation path is incomplete.",
    }

    _validate_review_protocol(
        _protocol_review(proofs),
        require_topology_proofs=False,
    )
    with pytest.raises(ValueError, match="failed connections layer"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
        )


@pytest.mark.parametrize(
    ("scope", "approved", "expected"),
    [
        ("none", True, "accept"),
        ("local", False, "revise"),
        ("global", False, "reject"),
    ],
)
def test_repair_scope_controls_review_routing(scope, approved, expected):
    failed_layer = (
        None if scope == "none" else ("render" if scope == "global" else "components")
    )
    state = {
        "graph_changed": True,
        "graph_data": {
            "design_origin": "applied",
            "nodes": [{"id": "target"}],
            "edges": [],
            "groups": [],
        },
        "graph_revision_count": 0,
        "graph_review": {
            "approved": approved,
            "repair_contract": _repair_contract(
                scope=scope,
                failed_layer=failed_layer,
                layer_selectors=(
                    {"components": {"node_ids": ["target"]}}
                    if failed_layer == "components"
                    else None
                ),
            ),
        },
    }

    assert _route_after_review(state) == expected


@pytest.mark.asyncio
async def test_revision_node_reviews_unchanged_graphs_until_graph_changes(
    monkeypatch,
):
    calls = []
    graph = _domain_graph()

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(_passing_review_payload())

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )

    result = await graph_critic_node(
        {
            **_critic_state(graph=graph),
            "graph_changed": False,
            "graph_revision_count": 1,
            "graph_data": {**graph, "design_origin": "applied"},
        }
    )

    assert calls
    assert isinstance(result["graph_review"], dict)


@pytest.mark.asyncio
async def test_initial_local_rejection_gets_one_local_repair_pass(monkeypatch):
    calls = []
    graph = _domain_graph()
    graph["edges"].append(
        {
            "source": "objective",
            "target": "approval",
            "label": "requires approval",
        }
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload()
        _set_model_layer(
            payload,
            "connections",
            finding_codes=[connection_code],
            edge_indexes=[0] if len(calls) == 1 else [0, 1],
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(_critic_state(graph=graph))

    assert len(calls) == 1
    assert calls[0]["telemetry"]["operation"] == "graph_critic"
    assert (
        len(
            result["graph_review"]["repair_contract"]["layers"]["connections"][
                "edge_selectors"
            ]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_disconnected_scorecard_selectors_are_admitted_without_correction(
    monkeypatch,
):
    calls = []
    graph = _domain_graph()
    graph["edges"].append(
        {
            "source": "approval",
            "target": "executor",
            "label": "executes approved action",
        }
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload()
        _set_model_layer(
            payload,
            "connections",
            finding_codes=[connection_code],
            edge_indexes=[0, 1],
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )

    review = (await graph_critic_node(_critic_state(graph=graph)))["graph_review"]

    assert len(calls) == 1
    assert review.get("terminal") is not True
    assert review["repair_contract"]["repair_scope"] == "local"
    assert review["repair_contract"]["layers"]["connections"]["edge_selectors"] == [
        {
            "source": edge["source"],
            "target": edge["target"],
            "label": edge["label"],
        }
        for edge in graph["edges"][:2]
    ]


@pytest.mark.asyncio
async def test_protocol_correction_requires_a_complete_scorecard(monkeypatch):
    calls = []
    invalid = _passing_review_payload()
    _set_model_layer(invalid, "components", finding_codes="invalid")
    local = _passing_review_payload()
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    _set_model_layer(
        local,
        "connections",
        finding_codes=[connection_code],
        edge_indexes=[0],
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid if len(calls) == 1 else local)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(_critic_state())

    assert result["graph_review"]["repair_contract"]["repair_scope"] == "local"
    assert [call["telemetry"]["operation"] for call in calls] == [
        "graph_critic",
        "graph_critic_protocol_correction",
    ]
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "complete scorecard" in correction
    assert "every blocking defect" in correction


@pytest.mark.asyncio
async def test_completed_scorecard_admission_failure_gets_one_contract_correction(
    monkeypatch,
):
    graph = {
        "design_origin": "applied",
        "nodes": [{"id": "existing", "label": "Existing component"}],
        "edges": [],
        "groups": [],
    }
    component_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "components"
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload(topology_proofs={})
        if len(calls) == 1:
            _set_model_layer(
                payload,
                "components",
                finding_codes=[component_code],
                addition_count=2,
            )
            _set_model_layer(
                payload,
                "connections",
                finding_codes=[connection_code],
                addition_obligations=[
                    ["$new_node_1", "$new_node_2", "connect new responsibilities"],
                    ["$new_node_2", "$new_node_1", "return connection state"],
                ],
            )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=graph)
    state["user_message"] = "Do not include this raw request in correction diagnostics."

    result = await graph_critic_node(state)

    assert [call["telemetry"]["operation"] for call in calls] == [
        "graph_critic",
        "graph_critic_contract_correction",
    ]
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "previous repair permission contract" in correction
    assert "previous patch attempt" not in correction
    assert "Validation path: layers.components.context_node_ids" in correction
    assert "Validation rule: missing_graph_anchor" in correction
    assert state["user_message"] not in correction
    assert result["graph_review"].get("terminal") is not True
    assert result["graph_review"]["admission_correction"] == {
        "path": "layers.components.context_node_ids",
        "rule": "missing_graph_anchor",
    }
    assert result["graph_contract_correction_count"] == 1


@pytest.mark.asyncio
async def test_completed_scorecard_does_not_retry_after_contract_correction_is_consumed(
    monkeypatch,
):
    graph = {
        "design_origin": "applied",
        "nodes": [{"id": "existing", "label": "Existing component"}],
        "edges": [],
        "groups": [],
    }
    component_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "components"
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload(topology_proofs={})
        _set_model_layer(
            payload,
            "components",
            finding_codes=[component_code],
            addition_count=2,
        )
        _set_model_layer(
            payload,
            "connections",
            finding_codes=[connection_code],
            addition_obligations=[
                ["$new_node_1", "$new_node_2", "connect new responsibilities"],
                ["$new_node_2", "$new_node_1", "return connection state"],
            ],
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=graph)
    state["graph_contract_correction_count"] = 1

    result = await graph_critic_node(state)

    assert len(calls) == 1
    assert result["graph_review"]["failure_code"] == "graph_repair_nonlocal"
    assert result["graph_contract_correction_count"] == 1


@pytest.mark.asyncio
async def test_patch_validation_error_informs_one_contract_correction(monkeypatch):
    graph = _domain_graph()
    graph["groups"] = [
        {"id": "group_1", "nodeIds": []},
        {"id": "group_2", "nodeIds": []},
    ]
    edge = graph["edges"][0]
    prior_contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "label": edge["label"],
                    }
                ]
            }
        },
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    composition_code = _RUBRIC_CODES.index("authored_composition") + 1
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload()
        payload["prior_obligation_dispositions"] = [
            [
                _prior_obligation_id(
                    layer="connections",
                    finding="Repair this layer.",
                ),
                "resolved",
            ]
        ]
        _set_model_layer(
            payload,
            "connections",
            finding_codes=[connection_code],
            edge_indexes=[0],
        )
        _set_model_layer(
            payload,
            "composition",
            finding_codes=[composition_code],
            group_indexes=[0, 1],
            composition_fields=["groups"],
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=graph, complexity="production")
    state.update(
        {
            "reviewed_graph_data": deepcopy(graph),
            "graph_review": {
                "repair_contract": prior_contract,
                "topology_proofs": [],
            },
            "graph_contract_correction_pending": True,
            "graph_patch_validation_error": {
                "path": "groups.group_1.group_2",
                "rule": "locked_record_changed",
            },
            "graph_operation": {
                "kind": "create",
                "status": "failed",
                "failure_code": "graph_patch_invalid_preserved_existing_graph",
            },
        }
    )

    result = await graph_critic_node(state)

    assert len(calls) == 1
    assert calls[0]["telemetry"]["operation"] == "graph_critic_contract_correction"
    assert calls[0]["provider_attempt_limit"] == 2
    correction = calls[0]["messages"][0]["content"][-1]["text"]
    assert "previous repair permission contract" in correction
    assert "Validation path: groups.group_1.group_2" in correction
    assert "Validation rule: locked_record_changed" in correction
    assert result["graph_review"]["contract_correction"] == {
        "path": "groups.group_1.group_2",
        "rule": "locked_record_changed",
    }
    assert result["graph_operation"]["status"] == "candidate"


def test_corrected_group_move_rejects_destination_only_authority():
    review = {
        "repair_contract": _repair_contract(
            scope="local",
            failed_layer="composition",
            layer_selectors={
                "composition": {
                    "group_ids": ["group_2"],
                    "composition_fields": ["groups"],
                }
            },
        )
    }
    correction = {
        "path": "groups.group_1.group_2",
        "rule": "locked_record_changed",
    }

    with pytest.raises(CriticProtocolError) as raised:
        _validate_corrected_group_move_authority(review, correction)

    assert raised.value.path == "layers.composition.group_indexes"
    assert raised.value.rule == "invalid_contract"

    review["repair_contract"]["layers"]["composition"]["group_ids"] = [
        "group_1",
        "group_2",
    ]
    _validate_corrected_group_move_authority(review, correction)

    review["repair_contract"]["layers"]["composition"]["group_ids"] = [
        "group_2",
        "group_3",
    ]
    with pytest.raises(CriticProtocolError):
        _validate_corrected_group_move_authority(review, correction)


@pytest.mark.parametrize(
    ("changed_layer", "expected_locked_layers"),
    [
        ("unchanged", {"components", "connections", "composition"}),
        ("components", set()),
        ("connections", {"components"}),
        ("composition", {"components", "connections"}),
    ],
)
def test_dependency_aware_locks_reopen_downstream_review_layers(
    changed_layer,
    expected_locked_layers,
):
    reviewed_graph = _domain_graph()
    candidate = deepcopy(reviewed_graph)
    if changed_layer == "components":
        candidate["nodes"][0]["description"] = "Changed component responsibility."
    elif changed_layer == "connections":
        candidate["edges"][0]["description"] = "Changed edge contract."
    elif changed_layer == "composition":
        candidate["assumptions"] = [
            *candidate.get("assumptions", []),
            "Changed retained assumption.",
        ]

    locked_layers = _locked_review_layers(
        {
            "reviewed_graph_data": reviewed_graph,
            "graph_review": {
                "repair_contract": _repair_contract(),
                "resolved_complexity": "prototype",
            },
        },
        candidate,
        resolved_depth="prototype",
    )

    assert locked_layers == expected_locked_layers


@pytest.mark.asyncio
async def test_unchanged_passed_layers_retain_their_prior_verdict(monkeypatch):
    reviewed_graph = _domain_graph()
    for node, node_id in zip(
        reviewed_graph["nodes"],
        ("objective", "quality", "optimizer", "approval", "executor", "outcome"),
        strict=True,
    ):
        node["id"] = node_id
    reviewed_graph["edges"] = [
        {"source": source, "target": target, "label": "passes bounded work"}
        for source, target in zip(
            ("objective", "quality", "optimizer", "approval", "executor"),
            ("quality", "optimizer", "approval", "executor", "outcome"),
            strict=True,
        )
    ]
    candidate = deepcopy(reviewed_graph)
    candidate["assumptions"] = ["The composition changed after its prior review."]
    component_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "components"
    )

    async def fake_stream_llm(**_kwargs):
        payload = _passing_review_payload(topology_proofs={})
        _set_model_layer(
            payload,
            "components",
            finding_codes=[component_code],
            node_indexes=[0],
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=candidate)
    state.update(
        {
            "reviewed_graph_data": reviewed_graph,
            "graph_review": {
                "repair_contract": _repair_contract(),
                "topology_proofs": [],
            },
        }
    )

    review = (await graph_critic_node(state))["graph_review"]

    assert review["approved"] is True
    assert review["locked_layers"] == ["components", "connections"]
    assert review["repair_contract"]["layers"]["components"]["status"] == "pass"


@pytest.mark.asyncio
async def test_unchanged_connections_retain_valid_production_topology_proofs(
    monkeypatch,
):
    reviewed_graph = _domain_graph()
    node_ids = ("objective", "quality", "optimizer", "approval", "executor", "outcome")
    for node, node_id in zip(reviewed_graph["nodes"], node_ids, strict=True):
        node["id"] = node_id
    reviewed_graph["edges"] = [
        {"source": source, "target": target, "label": "passes bounded work"}
        for source, target in zip(node_ids[:-1], node_ids[1:], strict=True)
    ]
    candidate = deepcopy(reviewed_graph)
    candidate["assumptions"] = ["The composition changed after its prior review."]
    prior_proofs = _valid_protocol_topology_proofs(reviewed_graph["edges"][0])
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(_passing_review_payload(topology_proofs={}))

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=candidate, complexity="production")
    state.update(
        {
            "reviewed_graph_data": reviewed_graph,
            "graph_review": {
                "repair_contract": _repair_contract(),
                "topology_proofs": prior_proofs,
                "resolved_complexity": "production",
            },
        }
    )

    review = (await graph_critic_node(state))["graph_review"]

    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert review["approved"] is True
    assert review["topology_proofs"] == prior_proofs


@pytest.mark.asyncio
async def test_production_depth_reopens_prototype_connections_and_topology_proofs(
    monkeypatch,
):
    reviewed_graph = _domain_graph()
    node_ids = ("objective", "quality", "optimizer", "approval", "executor", "outcome")
    for node, node_id in zip(reviewed_graph["nodes"], node_ids, strict=True):
        node["id"] = node_id
    reviewed_graph["edges"] = [
        {"source": source, "target": target, "label": "passes bounded work"}
        for source, target in zip(node_ids[:-1], node_ids[1:], strict=True)
    ]
    candidate = deepcopy(reviewed_graph)
    candidate["assumptions"] = ["The production composition changed."]
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                topology_proofs=_valid_model_topology_proofs(),
            )
        )

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=candidate, complexity="production")
    state.update(
        {
            "reviewed_graph_data": reviewed_graph,
            "graph_review": {
                "repair_contract": _repair_contract(),
                "topology_proofs": [],
                "resolved_complexity": "prototype",
            },
        }
    )

    review = (await graph_critic_node(state))["graph_review"]

    assert calls[0]["response_schema"] == _GRAPH_CRITIC_RESPONSE_SCHEMA
    assert review["approved"] is True
    assert review["locked_layers"] == ["components"]
    assert len(review["topology_proofs"]) == len(_TOPOLOGY_PROOF_GUARANTEES)
    assert review["resolved_complexity"] == "production"


@pytest.mark.asyncio
async def test_production_rerun_with_proofless_prior_review_reopens_connections_and_rechecks_topology(
    monkeypatch,
):
    reviewed_graph = _domain_graph()
    node_ids = ("objective", "quality", "optimizer", "approval", "executor", "outcome")
    for node, node_id in zip(reviewed_graph["nodes"], node_ids, strict=True):
        node["id"] = node_id
    reviewed_graph["edges"] = [
        {"source": source, "target": target, "label": "passes bounded work"}
        for source, target in zip(node_ids[:-1], node_ids[1:], strict=True)
    ]
    candidate = deepcopy(reviewed_graph)
    candidate["assumptions"] = ["The production composition changed."]
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                topology_proofs=_valid_model_topology_proofs(),
            )
        )

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state(graph=candidate, complexity="production")
    state.update(
        {
            "reviewed_graph_data": reviewed_graph,
            "graph_review": {
                "repair_contract": _repair_contract(),
                "topology_proofs": [],
                "resolved_complexity": "production",
            },
        }
    )

    review = (await graph_critic_node(state))["graph_review"]

    assert calls[0]["response_schema"] == _GRAPH_CRITIC_RESPONSE_SCHEMA
    assert review["approved"] is True
    assert review["locked_layers"] == ["components"]
    assert len(review["topology_proofs"]) == len(_TOPOLOGY_PROOF_GUARANTEES)


@pytest.mark.asyncio
async def test_reviewed_graph_data_matches_the_scorecard_candidate(monkeypatch):
    graph = _domain_graph()
    graph["nodes"][0]["technology"] = "Candidate-specific implementation detail"
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(_passing_review_payload(topology_proofs={}))

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )

    result = await graph_critic_node(_critic_state(graph=graph))
    packet = json.loads(calls[0]["messages"][0]["content"][0]["text"].split("\n", 1)[1])

    assert packet["candidate"] == _semantic_graph_projection(graph)
    assert result["reviewed_graph_data"] == graph


def test_required_topology_proofs_reject_missing_or_invented_edges():
    graph = {
        "edges": [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
    }
    value = [
        {
            "guarantee": guarantee,
            "status": "not_applicable",
            "edge_evidence": [],
            "route_claims": [],
            "reason": "This flow class is absent.",
        }
        for guarantee in (
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        )
    ]
    value.append(
        {
            "guarantee": "state_effect_reconciliation",
            "status": "pass",
            "edge_evidence": [
                {"source": "gate", "target": "writer", "label": "release action"}
            ],
            "route_claims": [{"source": "gate", "target": "writer"}],
            "reason": "The action is supposedly reserved before execution.",
        }
    )

    with pytest.raises(ValueError, match="edge absent from the graph"):
        _validate_review_protocol(
            {
                "repair_contract": _repair_contract(),
                "strengths": [],
                "advice": [],
                "topology_proofs": value,
            },
            require_topology_proofs=True,
            graph=graph,
        )


def test_required_topology_proofs_accept_exact_citations_from_semantic_reviewer():
    graph = {
        "edges": [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
    }
    value = [
        {
            "guarantee": guarantee,
            "status": "pass"
            if guarantee == "authorization_and_compensation"
            else "not_applicable",
            "edge_evidence": (
                [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "route_claims": (
                [{"source": "proposal", "target": "gate"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "reason": "The cited path is present."
            if guarantee == "authorization_and_compensation"
            else "This flow class is absent.",
        }
        for guarantee in sorted(
            {
                "state_effect_reconciliation",
                "authorization_and_compensation",
                "retrieval_and_reuse_trust",
                "audit_and_provenance",
                "learning_and_release",
            }
        )
    ]

    _validate_review_protocol(
        {
            "repair_contract": _repair_contract(),
            "strengths": [],
            "advice": [],
            "topology_proofs": value,
        },
        require_topology_proofs=True,
        graph=graph,
    )


@pytest.mark.parametrize(
    ("route_claims", "match"),
    [
        ([{"source": "gate", "target": "proposal"}], "is not directed"),
        ([{"source": "proposal", "target": "proposal"}], "is not directed"),
    ],
)
def test_topology_witness_rejects_unproved_direction_or_cycle(route_claims, match):
    graph = {
        "edges": [
            {"source": "proposal", "target": "gate", "label": "submit proposal"},
        ]
    }
    proofs = [
        {
            "guarantee": guarantee,
            "status": "pass"
            if guarantee == "authorization_and_compensation"
            else "not_applicable",
            "edge_evidence": (
                [graph["edges"][0]]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "route_claims": (
                route_claims if guarantee == "authorization_and_compensation" else []
            ),
            "reason": "The witness is reviewed semantically.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]

    with pytest.raises(ValueError, match=match):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
            graph=graph,
        )


def test_topology_witness_rejects_disconnected_padding():
    graph = {
        "edges": [
            {"source": "proposal", "target": "gate", "label": "submit proposal"},
            {"source": "cache", "target": "metrics", "label": "emit metric"},
        ]
    }
    proofs = [
        {
            "guarantee": guarantee,
            "status": "pass"
            if guarantee == "authorization_and_compensation"
            else "not_applicable",
            "edge_evidence": (
                graph["edges"] if guarantee == "authorization_and_compensation" else []
            ),
            "route_claims": (
                [{"source": "proposal", "target": "gate"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "reason": "The witness is reviewed semantically.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]

    with pytest.raises(ValueError, match="outside every claimed route"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
            graph=graph,
        )


@pytest.mark.parametrize(
    ("guarantee", "label"),
    [
        ("state_effect_reconciliation", "Action Executor"),
        ("authorization_and_compensation", "Supervisor Approval"),
        ("retrieval_and_reuse_trust", "Scoped Answer Cache"),
        ("audit_and_provenance", "Lifecycle Audit Ledger"),
        ("learning_and_release", "Canary Release Gate"),
    ],
)
def test_topology_applicability_is_owned_by_semantic_review_not_label_regex(
    guarantee, label
):
    graph = {
        "nodes": [{"id": "visible", "label": label}],
        "edges": [
            {"source": "visible", "target": "outcome", "label": "returns result"}
        ],
    }
    value = [
        {
            "guarantee": item,
            "status": "not_applicable",
            "edge_evidence": [],
            "route_claims": [],
            "reason": "This flow class is absent.",
        }
        for item in (
            "state_effect_reconciliation",
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        )
    ]

    _validate_review_protocol(
        {
            "repair_contract": _repair_contract(),
            "strengths": [],
            "advice": [],
            "topology_proofs": value,
        },
        require_topology_proofs=True,
        graph=graph,
    )


def test_production_gate_accepts_cache_write_owned_by_acceptance_gate():
    graph = {
        "nodes": [
            {"id": "generator", "label": "Answer Generator"},
            {"id": "validator", "label": "Grounding Validator"},
            {"id": "fallback", "label": "No-Evidence Fallback"},
            {"id": "delivery", "label": "Response Delivery"},
            {"id": "cache", "label": "Answer Cache"},
        ],
        "edges": [
            {"source": "generator", "target": "validator", "label": "submit candidate"},
            {
                "source": "validator",
                "target": "cache",
                "label": "write accepted answer",
            },
            {
                "source": "validator",
                "target": "fallback",
                "label": "reject ungrounded answer",
            },
            {"source": "fallback", "target": "delivery", "label": "deliver abstention"},
            {"source": "cache", "target": "delivery", "label": "serve scoped answer"},
            {
                "source": "delivery",
                "target": "generator",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design a production RAG workflow", graph, "production"
    )

    assert review["approved"] is True
    assert not any("cache writes" in item for item in review["missing"])


def test_production_gate_does_not_treat_approval_audit_store_as_a_decision():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Permit Request", "type": "client"},
            # Even if the model classifies an audit projection as a control,
            # its ownership noun must keep it from becoming an approval gate.
            {"id": "ledger", "label": "Approval Audit Ledger", "type": "control"},
            {"id": "outcome", "label": "Permit Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "ledger", "label": "records reviewed permit"},
            {
                "source": "ledger",
                "target": "outcome",
                "label": "publishes audit projection",
            },
            {
                "source": "outcome",
                "target": "entry",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design an audited permit workflow", graph, "production"
    )

    assert not any("rejection/cancellation" in item for item in review["missing"])


def test_production_gate_does_not_treat_approved_registry_as_a_decision():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Definition Proposal", "type": "service"},
            {
                "id": "registry",
                "label": "Event Definition Registry",
                "type": "control",
                "description": "Stores approved versioned definitions for canary release.",
            },
            {"id": "outcome", "label": "Definition Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "entry",
                "target": "registry",
                "label": "register approved version",
            },
            {
                "source": "registry",
                "target": "outcome",
                "label": "publish immutable version",
            },
            {
                "source": "outcome",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design controlled event-definition releases",
        graph,
        "production",
    )

    assert not any("approval decision registry" in item for item in review["missing"])


def test_approval_owner_accepts_separate_approval_and_rejection_routes():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {"id": "owner", "label": "Clinical Sign-off", "type": "control"},
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "terminal", "label": "Audited Rejection", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {"source": "owner", "target": "lifecycle", "label": "approve exact action"},
            {"source": "owner", "target": "terminal", "label": "reject exact action"},
            {
                "source": "lifecycle",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
            {
                "source": "terminal",
                "target": "entry",
                "label": "return rejection outcome",
            },
        ],
    }

    review = _deterministic_review(
        "Design a controlled external action", graph, "production"
    )

    assert review["approved"] is True


def test_approval_owner_may_persist_both_outcomes_in_complete_durable_envelope():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {"id": "owner", "label": "Clinical Sign-off", "type": "control"},
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "terminal", "label": "Decision Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {
                "source": "owner",
                "target": "lifecycle",
                "label": "record approve or reject decision",
                "technology": "Signed payload and target envelope",
                "description": (
                    "Persists policy version, expiry, and idempotency key before any lease."
                ),
            },
            {
                "source": "lifecycle",
                "target": "terminal",
                "label": "publish decision outcome",
            },
        ],
    }

    review = _deterministic_review(
        "Design a controlled clinical action", graph, "production"
    )

    assert review["approved"] is True
    assert not any("approval decision" in item for item in review["missing"])
    assert not any("approval edge" in item for item in review["missing"])


def test_release_controller_may_own_promotion_and_rollback_for_registry_canary():
    graph = {
        "nodes": [
            {"id": "registry", "label": "Model Registry", "type": "datastore"},
            {"id": "controller", "label": "Rollout Controller", "type": "control"},
            {"id": "runtime", "label": "Decision Runtime", "type": "service"},
            {"id": "outcome", "label": "Canary Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "registry",
                "target": "controller",
                "label": "supplies immutable release",
            },
            {"source": "controller", "target": "runtime", "label": "deploy canary"},
            {
                "source": "controller",
                "target": "runtime",
                "label": "promote full production",
            },
            {
                "source": "controller",
                "target": "registry",
                "label": "rollback to prior release",
            },
            {"source": "runtime", "target": "outcome", "label": "measure canary"},
            {
                "source": "outcome",
                "target": "controller",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design a controlled model release", graph, "production"
    )

    assert review["approved"] is True
    assert not any("canary" in item.lower() for item in review["missing"])


def test_reservation_store_description_does_not_make_it_an_executor():
    graph = {
        "nodes": [
            {"id": "policy", "label": "Risk Policy", "type": "decision"},
            {
                "id": "reservation",
                "label": "Operation Reservation",
                "type": "datastore",
                "description": "Owns durable execution lifecycle state and leases.",
            },
            {"id": "executor", "label": "Channel Executor", "type": "gateway"},
            {"id": "outcome", "label": "Campaign Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "policy",
                "target": "reservation",
                "label": "forward auto-authorized payload",
                "technology": "Signed target envelope",
                "description": "Binds policy version, expiry, and idempotency key.",
            },
            {
                "source": "reservation",
                "target": "executor",
                "label": "lease reserved operation",
            },
            {
                "source": "executor",
                "target": "outcome",
                "label": "execute campaign change",
            },
            {
                "source": "outcome",
                "target": "policy",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design an automatic campaign workflow", graph, "production"
    )

    assert review["approved"] is True
    assert not any("durable reservation state" in item for item in review["missing"])


def test_read_only_external_adapter_is_not_treated_as_effect_executor():
    graph = {
        "nodes": [
            {"id": "reservation", "label": "Query Lifecycle", "type": "datastore"},
            {"id": "adapter", "label": "Ad Platform Adapter", "type": "gateway"},
            {"id": "target", "label": "Ad Platform", "type": "external"},
            {"id": "reconciler", "label": "Query Reconciler", "type": "service"},
        ],
        "edges": [
            {
                "source": "reservation",
                "target": "adapter",
                "label": "lease reserved query",
            },
            {"source": "adapter", "target": "target", "label": "query campaign status"},
            {
                "source": "target",
                "target": "reconciler",
                "label": "return campaign status",
            },
            {
                "source": "reconciler",
                "target": "adapter",
                "label": "NOT_FOUND retry read",
            },
            {
                "source": "reconciler",
                "target": "reservation",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design a read-only campaign status lookup", graph, "production"
    )

    assert review["approved"] is True
    assert not any("durable reservation" in item for item in review["missing"])


def test_distinct_reconciliation_branch_may_contrast_other_outcomes_and_share_audit():
    graph = {
        "nodes": [
            {"id": "ledger", "label": "Lifecycle Ledger", "type": "datastore"},
            {"id": "adapter", "label": "Fulfilment Adapter", "type": "gateway"},
            {"id": "target", "label": "External Fulfilment", "type": "external"},
            {"id": "reconciler", "label": "Outcome Reconciler", "type": "control"},
            {"id": "audit", "label": "Audit Log", "type": "datastore"},
        ],
        "edges": [
            {
                "source": "ledger",
                "target": "adapter",
                "label": "lease reserved operation",
            },
            {
                "source": "adapter",
                "target": "target",
                "label": "apply fulfilment mutation",
            },
            {"source": "target", "target": "reconciler", "label": "return status"},
            {
                "source": "reconciler",
                "target": "ledger",
                "label": "NOT_FOUND retry reservation",
                "description": "Retries only NOT_FOUND; STILL_UNKNOWN escalates on its own branch.",
            },
            {
                "source": "reconciler",
                "target": "audit",
                "label": "log reconciliation outcomes",
                "description": "Audits COMMITTED, NOT_FOUND, and STILL_UNKNOWN branch results.",
            },
        ],
    }

    review = _deterministic_review(
        "Design a fulfilment integration", graph, "production"
    )

    assert not any(
        "distinct reconciliation branches" in item for item in review["missing"]
    )


def test_domain_specific_connected_topology_passes_local_structural_checks():
    graph = {
        "nodes": [
            {"id": "report", "label": "Missing Bag Report"},
            {"id": "router", "label": "Recovery Route Decision"},
            {"id": "resolution", "label": "Passenger Resolution"},
        ],
        "edges": [
            {
                "source": "report",
                "target": "router",
                "label": "submits verified bag record",
            },
            {
                "source": "router",
                "target": "resolution",
                "label": "returns recovery outcome",
            },
        ],
    }

    review = _deterministic_review(
        "Design an airport baggage recovery workflow",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []


def _domain_graph():
    return {
        "design_origin": "applied",
        "nodes": [
            {
                "label": "Campaign Objective",
                "description": "Defines ROAS objective and spend constraints",
            },
            {
                "label": "Event Quality Gate",
                "description": "Validates conversion and attribution events",
            },
            {
                "label": "Creative Optimizer",
                "description": "Chooses copy variants for an audience",
            },
            {
                "label": "Approval Policy",
                "description": "Approves risky actions and writes an audit record",
            },
            {
                "label": "Channel Executor",
                "description": "Applies idempotent targeting and bid changes",
            },
            {
                "label": "Outcome Attribution",
                "description": "Observes attributed revenue and campaign outcomes",
            },
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


@pytest.mark.parametrize(
    ("query", "labels"),
    [
        (
            "Design a municipal water-leak triage system",
            ("Leak Report", "Dispatch Decision", "Repair Outcome"),
        ),
        (
            "Design a telescope transient-alert pipeline",
            ("Sky Event", "Candidate Classifier", "Observer Outcome"),
        ),
        (
            "Design a music-royalty reconciliation service",
            ("Usage Evidence", "Royalty Reconciler", "Dispute Outcome"),
        ),
        (
            "Design an airport baggage recovery workflow",
            ("Missing Bag", "Recovery Router", "Passenger Outcome"),
        ),
    ],
)
def test_feedback_flow_is_a_loop_without_renderer_specific_metadata(query, labels):
    graph = {
        "design_origin": "applied",
        "nodes": [
            {
                "id": "entry",
                "label": labels[0],
                "description": "Captures a verified request.",
            },
            {
                "id": "decision",
                "label": labels[1],
                "description": "Owns the bounded decision.",
            },
            {
                "id": "outcome",
                "label": labels[2],
                "description": "Records the measured outcome.",
            },
        ],
        "edges": [
            {"source": "entry", "target": "decision", "label": "sends verified input"},
            {
                "source": "decision",
                "target": "outcome",
                "label": "records bounded result",
            },
            {
                "source": "outcome",
                "target": "decision",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(query, graph, "prototype")

    assert review["approved"] is True
    assert review["missing"] == []


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
                "Agent",
                "Tool Use",
                "Planning",
                "Evaluation",
                "Foundation Model",
                "Generation",
            )
        ],
        "edges": [
            {
                "source": "agent",
                "target": "planning",
                "label": "returns measured outcome",
                "type": "loop",
            }
        ],
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
        {**node, "id": f"node_{index}"} for index, node in enumerate(graph["nodes"])
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
            {
                "id": "request",
                "label": "Research Request",
                "description": "Captures the research question",
            },
            {
                "id": "retriever",
                "label": "Evidence Retriever",
                "description": "Retrieves cited source passages",
            },
            {
                "id": "composer",
                "label": "Answer Composer",
                "description": "Builds a grounded answer",
            },
        ],
        "edges": [
            {
                "source": "request",
                "target": "retriever",
                "label": "submits ACL-scoped query",
            },
            {
                "source": "retriever",
                "target": "composer",
                "label": "returns cited passages",
            },
        ],
    }

    review = _deterministic_review(
        "Design a research assistant system",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert not any("approval" in item for item in review["missing"])
    assert not any("feedback" in item for item in review["missing"])


def test_explicit_optimisation_request_requires_a_measured_feedback_edge():
    graph = {
        "nodes": [
            {"id": "input", "label": "Observed Outcome"},
            {"id": "decision", "label": "Allocation Decision"},
            {"id": "result", "label": "Allocation Result"},
        ],
        "edges": [
            {
                "source": "input",
                "target": "decision",
                "label": "supplies measured evidence",
            },
            {
                "source": "decision",
                "target": "result",
                "label": "returns bounded allocation",
            },
        ],
    }

    review = _deterministic_review(
        "Design a system that continuously optimizes allocations from measured outcomes",
        graph,
        "prototype",
    )

    assert review["approved"] is False
    assert any("feedback edge" in item for item in review["missing"])


def test_render_gate_rejects_overlap_clipping_or_missing_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(
        graph,
        {
            "report": {
                "rendered_nodes": 2,
                "rendered_edges": 0,
                "overlap_count": 1,
                "clipped_nodes": 1,
                "clipped_edges": 1,
                "minimum_text_px": 12,
            },
        },
    )

    assert review["approved"] is False
    assert review["terminal"] is True
    assert review["failure_code"] == "diagram_evaluation_layout_rejected"
    assert any("actual candidate" in item for item in review["missing"])
    assert any("overlapping" in item for item in review["missing"])


def test_render_gate_accepts_a_complete_readable_browser_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(
        graph,
        {
            "screenshot_base64": "valid-bounded-image",
            "report": {
                "rendered_nodes": 2,
                "rendered_edges": 0,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 11,
            },
        },
    )

    assert review["approved"] is True
    assert review["terminal"] is False


def test_render_gate_rejects_missing_overview_and_group_labels_or_overlapping_zones():
    graph = {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"source": "a", "target": "b"}],
    }
    review = _deterministic_render_review(
        graph,
        {
            "screenshot_base64": "valid-bounded-image",
            "report": {
                "rendered_nodes": 2,
                "rendered_edges": 1,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 11,
                "overview_required_edge_labels": 1,
                "visible_overview_required_edge_labels": 0,
                "grouped_nodes": 2,
                "group_labelled_nodes": 1,
                "visible_group_boundaries": 2,
                "group_boundary_overlap_count": 1,
            },
        },
    )

    assert review["approved"] is False
    assert review["terminal"] is True
    assert any("overview-required edge label" in item for item in review["missing"])
    assert any("group label on every node" in item for item in review["missing"])
    assert any("responsibility-zone boundaries" in item for item in review["missing"])


def test_render_gate_accepts_legacy_reports_without_new_visual_metrics():
    graph = {"nodes": [{"id": "a"}], "edges": []}
    review = _deterministic_render_review(
        graph,
        {
            "screenshot_base64": "legacy-image",
            "report": {
                "rendered_nodes": 1,
                "rendered_edges": 0,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 11,
            },
        },
    )

    assert review["approved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision_count", "expected_effort"),
    [(0, "medium"), (1, "medium")],
)
async def test_semantic_critic_reviews_the_private_rendered_image(
    monkeypatch,
    revision_count,
    expected_effort,
):
    captured = {}
    timeline = []
    events = []
    architect_tail = "a" * 10_100 + " architect-tail"
    challenger_tail = "c" * 6_100 + " challenger-tail"

    async def fake_stream_llm(**kwargs):
        timeline.append("critic_call")
        captured.update(kwargs)
        return _structured_response(_passing_review_payload())

    async def send(event):
        events.append(event)
        if event["type"] == "workflow_progress":
            timeline.append(f"{event['phase']}_{event['status']}")
        else:
            timeline.append(event["type"])

    async def await_diagram(_graph):
        timeline.append("private_render")
        return {
            "screenshot_base64": "private-render-image",
            "media_type": "image/png",
            "report": {
                "rendered_nodes": 6,
                "rendered_edges": 1,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    graph["design_origin"] = "applied"
    result = await graph_critic_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "user_message": "Design a production growth marketing agent system",
            "evidence_bundle": {
                "checklist": [{"area": "evaluation", "question": "Measure outcomes"}],
                "book_evidence": [
                    {
                        "chapter": 1,
                        "page_number": 8,
                        "text": "Evaluate measured outcomes.",
                    }
                ],
                "research_context": "- [Current source](https://example.com): current evidence",
            },
            "architect_plan": {
                "diagram_requirements": [architect_tail],
                "runtime_flow": ["full-plan-duplicate-must-not-ship"],
            },
            "challenger_review": {
                "risks": [
                    {
                        "area": "safety",
                        "risk": "Unapproved writes",
                        "mitigation": "Approval gate",
                    },
                    {
                        "area": "completeness",
                        "risk": challenger_tail,
                        "mitigation": "Keep it visible",
                    },
                ],
                "status_update": "challenger-status-must-not-ship",
            },
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
            "graph_revision_count": revision_count,
        }
    )

    assert result["graph_review"]["approved"] is True
    assert timeline.index("render_active") < timeline.index("private_render")
    assert timeline.index("private_render") < timeline.index("graph_preview")
    assert timeline.index("private_render") < timeline.index("render_complete")
    assert timeline.index("render_complete") < timeline.index("graph_preview")
    assert timeline.index("graph_preview") < timeline.index("critic_call")
    assert {
        "type": "workflow_progress",
        "phase": "render",
        "status": "complete",
        "title": "Private browser rendering passed",
        "detail": "The browser layout checks passed. The candidate is ready for semantic review.",
    } in events
    assert captured["effort"] == expected_effort
    assert captured["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    content = captured["messages"][0]["content"]
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "private-render-image",
        },
    }
    packet = json.loads(content[0]["text"].split("\n", 1)[1])
    assert packet["render_report"]["rendered_nodes"] == 6
    assert "https://example.com" in packet["evidence_allowlist"]
    assert packet["review_context"] == [
        f"Architect commitment: {architect_tail}",
    ]
    assert challenger_tail not in content[0]["text"]
    assert "full-plan-duplicate-must-not-ship" not in content[0]["text"]
    assert "challenger-status-must-not-ship" not in content[0]["text"]
    assert "Use it to verify that the authored entry" in _GRAPH_CRITIC_SYSTEM


def test_review_packet_keeps_semantics_and_omits_duplicate_internal_metadata():
    graph = _domain_graph()
    for index, node in enumerate(graph["nodes"], start=1):
        node["id"] = f"node-{index}"
    graph.update(
        {
            "version": "private-version",
            "resolved_complexity": "production",
            "groups": [
                {
                    "id": "runtime",
                    "label": "Runtime",
                    "kind": "runtime",
                    "nodeIds": [node["id"] for node in graph["nodes"]],
                }
            ],
            "sequence": [
                {
                    "step": 1,
                    "nodes": [graph["nodes"][0]["id"]],
                    "description": "Enter the runtime path",
                }
            ],
            "assumptions": ["The campaign API supports exact-action approval."],
        }
    )
    graph["nodes"][0].update(
        {
            "technology": "Internal presentation subtitle",
            "detail": "Deferred detail",
            "layer": "architecture",
            "design_origin": "applied",
        }
    )
    graph["edges"][0].update(
        {
            "technology": "Internal edge subtitle",
            "description": graph["edges"][0]["label"],
            "edge_id": "private-edge-id",
            "relation": "private-relation",
        }
    )
    packet = _review_packet(
        {
            "architect_plan": {
                "diagram_requirements": ["Bind approval to the exact action."],
                "runtime_flow": ["Duplicate planning prose"],
            },
            "challenger_review": {
                "risks": [
                    {
                        "area": "safety",
                        "risk": "Approval can go stale.",
                        "mitigation": "Revalidate immediately before execution.",
                    }
                ],
                "missing_requirements": ["Confirm the source of truth."],
                "tradeoffs": ["Freshness adds one read."],
                "status_update": "Duplicate progress prose",
            },
        },
        graph=graph,
        query="Design the system.",
        resolved_depth="production",
        render_result={
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "unknown_browser_field": "omit",
            },
        },
    )

    assert packet["review_context"] == [
        "Architect commitment: Bind approval to the exact action.",
    ]
    candidate = packet["candidate"]
    assert len(candidate["nodes"]) == len(graph["nodes"])
    assert len(candidate["edges"]) == len(graph["edges"])
    assert candidate["nodes"][0]["description"] == graph["nodes"][0]["description"]
    assert set(candidate["nodes"][0]) <= {
        "id",
        "label",
        "type",
        "description",
    }
    assert set(candidate["edges"][0]) <= {
        "source",
        "target",
        "label",
        "flow",
        "sync",
    }
    assert candidate["groups"] == graph["groups"]
    assert candidate["sequence"] == graph["sequence"]
    assert candidate["assumptions"] == graph["assumptions"]
    assert packet["render_report"] == {
        "rendered_nodes": len(graph["nodes"]),
        "rendered_edges": len(graph["edges"]),
    }
    packet_text = json.dumps(packet)
    assert "private-version" not in packet_text
    assert "private-edge-id" not in packet_text
    assert "Duplicate planning prose" not in packet_text
    assert "Duplicate progress prose" not in packet_text


@pytest.mark.asyncio
async def test_terse_followup_still_reviews_every_changed_applied_graph(monkeypatch):
    calls = {"critic": 0, "render": 0}

    async def fake_stream_llm(**_kwargs):
        calls["critic"] += 1
        return _structured_response(
            _passing_review_payload(
                strengths=["The requested approval path remains domain specific."],
            )
        )

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
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "expand the approval path",
            "design_query": "growth marketing multi-agent system expand the approval path",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is True
    assert calls == {"critic": 1, "render": 1}


@pytest.mark.asyncio
async def test_hard_render_failure_is_included_in_exhaustive_semantic_review(
    monkeypatch,
):
    calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload(topology_proofs={})
        _set_model_layer(
            payload,
            "render",
            deterministic_finding_indexes=[0, 1],
        )
        return _structured_response(payload)

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": 5,
                "rendered_edges": 1,
                "overlap_count": 1,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert any("overlapping" in item for item in result["graph_review"]["missing"])
    assert result["graph_review"]["terminal"] is True
    assert "diagram_evaluation" not in result
    assert result["graph_review"]["review_status"] == "completed"
    assert result["graph_review"]["repair_contract"]["repair_scope"] == "global"
    assert (
        result["graph_review"]["repair_contract"]["layers"]["render"]["status"]
        == "fail"
    )
    blocker_ids = [blocker["id"] for blocker in result["graph_review"]["hard_blockers"]]
    assert len(blocker_ids) == 2
    assert len(set(blocker_ids)) == 2
    assert len(calls) == 1
    assert not any(event["type"] == "graph_preview" for event in events)
    assert not any(
        event.get("phase") == "render" and event.get("status") == "complete"
        for event in events
    )


def test_every_render_gate_failure_has_a_distinct_stable_blocker_rule():
    review = _deterministic_render_review(
        _domain_graph(),
        {
            "capture_error": "capture failed",
            "report": {
                "rendered_nodes": 0,
                "rendered_edges": 0,
                "overlap_count": 1,
                "clipped_nodes": 1,
                "clipped_edges": 1,
                "minimum_text_px": 10,
                "overview_required_edge_labels": 2,
                "visible_overview_required_edge_labels": 1,
                "grouped_nodes": 2,
                "group_labelled_nodes": 1,
                "group_boundary_overlap_count": 1,
            },
        },
    )

    rules = [
        _deterministic_blocker_rule({"finding": finding})
        for finding in review["missing"]
    ]

    assert len(rules) == 10
    assert len(set(rules)) == len(rules)
    assert all(not rule.startswith("legacy") for rule in rules)


@pytest.mark.asyncio
async def test_cancelled_critic_keeps_the_claimed_provider_call(monkeypatch):
    provider_started = asyncio.Event()

    async def blocking_stream_llm(**_kwargs):
        provider_started.set()
        await asyncio.Future()

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        blocking_stream_llm,
    )
    budget = GraphReviewBudget()
    task = asyncio.create_task(graph_critic_node(_critic_state(), review_budget=budget))
    await provider_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert budget.critic_calls == 1
    assert budget.contract_corrections == 0


@pytest.mark.asyncio
async def test_missing_browser_evaluation_fails_closed_before_paid_semantic_review(
    monkeypatch,
):
    calls = 0

    async def fake_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            )
        )

    async def await_diagram(_graph):
        raise TimeoutError("browser did not respond")

    events = []

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    result = await graph_critic_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert calls == 0
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "diagram_evaluation_timeout"
    assert not any(
        event.get("phase") == "render" and event.get("status") == "complete"
        for event in events
    )


@pytest.mark.asyncio
async def test_deterministic_domain_findings_reach_semantic_localization(monkeypatch):
    calls = []
    finding = (
        "Replace generic book concepts with domain-owned component responsibilities."
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload()
        _set_model_layer(
            payload,
            "components",
            finding_codes=[1],
            deterministic_finding_indexes=[0],
            node_indexes=[0],
        )
        return _structured_response(payload)

    async def await_diagram(candidate):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(candidate["nodes"]),
                "rendered_edges": len(candidate["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    for index, node in enumerate(graph["nodes"]):
        node["id"] = f"growth_stage_{index}"
    graph["edges"] = [
        {
            "source": f"growth_stage_{index}",
            "target": f"growth_stage_{index + 1}",
            "label": f"passes campaign state {index}",
        }
        for index in range(len(graph["nodes"]) - 1)
    ]
    graph["nodes"][0]["label"] = "Agent"
    result = await graph_critic_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["repair_contract"]["repair_scope"] == "local"
    packet = json.loads(calls[0]["messages"][0]["content"][0]["text"].split("\n", 1)[1])
    assert packet["deterministic_pre_review_findings"] == [
        {
            "id": "deterministic_1",
            "rule": "generic_component",
            "finding": finding,
            "owner_layer": "components",
        }
    ]


@pytest.mark.asyncio
async def test_malformed_structured_review_fails_closed_without_retry(monkeypatch):
    calls = []
    render_calls = 0

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response('{"approved": tru')

    async def await_diagram(graph):
        nonlocal render_calls
        render_calls += 1
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

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_output_truncated"
    assert len(calls) == 1
    assert calls[0]["model"] == settings.graph_qa_model
    assert calls[0]["timeout_seconds"] <= settings.graph_critic_max_timeout_s
    assert calls[0]["max_output_tokens"] == settings.graph_qa_max_completion_tokens
    assert calls[0]["effort"] == "medium"
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert render_calls == 1


@pytest.mark.asyncio
async def test_browser_render_time_is_deducted_from_one_absolute_critic_deadline(
    monkeypatch,
):
    clock = {"now": 100.0}
    calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            )
        )

    async def await_diagram(graph):
        clock["now"] += 7.0
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

    async def send(event):
        events.append(event)

    monkeypatch.setattr("agent.nodes.graph_critic.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
            "_graph_stage_deadline_s": 145.0,
        }
    )

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 1
    assert calls[0]["timeout_seconds"] == pytest.approx(37.0)
    assert any(
        event.get("phase") == "review" and event.get("status") == "complete"
        for event in events
    )


@pytest.mark.asyncio
async def test_prototype_critic_uses_depth_specific_wire_contract(monkeypatch):
    calls = []
    payload = _passing_review_payload(topology_proofs={})

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(_critic_state())

    assert result["graph_review"]["approved"] is True
    assert result["graph_review"]["topology_proofs"] == []
    assert len(calls) == 1
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert calls[0]["response_schema"]["properties"]["topology_proofs"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }
    assert '"topology_proofs": {}' in calls[0]["system"]
    assert "state_effect_reconciliation" not in calls[0]["system"]
    assert "topology guarantee" not in calls[0]["system"]
    assert "topology-proof contracts" not in calls[0]["system"]
    assert "Preserve every required layer and proof" not in calls[0]["system"]


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_protocol_correction_logs_safe_coordinates(
    monkeypatch,
    caplog,
    recovers,
):
    invalid = _passing_review_payload()
    _set_model_layer(invalid, "components", finding_codes="PRIVATE_SENTINEL")
    valid = _passing_review_payload()
    calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        response = valid if recovers and len(calls) == 2 else invalid
        return _structured_response(response)

    async def send(event):
        events.append(event)

    caplog.set_level("WARNING", logger="agent.nodes.graph_critic")
    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state()
    state["send"] = send
    result = await graph_critic_node(state)

    assert result["graph_review"]["approved"] is recovers
    assert len(calls) == 2
    assert "path=layers.components.finding_codes" in caplog.text
    assert "rule=invalid_reference" in caplog.text
    assert "PRIVATE_SENTINEL" not in caplog.text
    if not recovers:
        assert result["graph_review"]["terminal"] is True
        terminal_logs = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Model review unavailable")
        ]
        assert len(terminal_logs) == 1
        assert (
            "path=layers.components.finding_codes rule=invalid_reference"
            in terminal_logs[0]
        )
        assert (
            result["graph_review"]["failure_code"] == "semantic_review_protocol_invalid"
        )
        review_event = events[-1]
        assert review_event["validation_stage"] == "correction"
        assert review_event["validation_path"] == "layers.components.finding_codes"
        assert review_event["validation_rule"] == "invalid_reference"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("layer", "rubric_code", "selector_field", "selector"),
    [
        ("components", "domain_specificity", "node_indexes", [0]),
        ("connections", "edge_semantics", "edge_indexes", [0]),
    ],
)
async def test_model_derived_repair_contract_failure_gets_one_protocol_correction(
    monkeypatch,
    layer,
    rubric_code,
    selector_field,
    selector,
):
    calls = []
    invalid = _passing_review_payload(topology_proofs={})
    finding_code = _RUBRIC_CODES.index(rubric_code) + 1
    _set_model_layer(invalid, layer, finding_codes=[finding_code])
    corrected = deepcopy(invalid)
    _set_model_layer(corrected, layer, **{selector_field: selector})

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid if len(calls) == 1 else corrected)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    monkeypatch.setattr(
        "agent.nodes.graph_critic._deterministic_review",
        lambda *_args, **_kwargs: {
            "approved": True,
            "deterministic_findings": [],
        },
    )
    graph = _domain_graph()
    for index, node in enumerate(graph["nodes"], start=1):
        node["id"] = f"n{index}"
    state = _critic_state()
    state["graph_data"] = graph

    result = await graph_critic_node(state)

    assert [call["telemetry"]["operation"] for call in calls] == [
        "graph_critic",
        "graph_critic_protocol_correction",
    ]
    assert calls[0]["messages"] != calls[1]["messages"]
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert f"failed {layer} layer must cite" in correction
    assert result["graph_review"]["review_status"] == "completed"
    assert result["graph_review"]["repair_contract"]["layers"][layer][
        "status"
    ] == "fail"
    assert result["graph_review"]["repair_contract"]["layers"][layer][
        "node_ids" if layer == "components" else "edge_selectors"
    ]
    assert result["graph_review"].get("terminal") is not True


@pytest.mark.asyncio
async def test_cross_layer_addition_contract_failure_gets_one_protocol_correction(
    monkeypatch,
):
    component_code = _RUBRIC_CODES.index("brief_coverage") + 1
    connection_code = _RUBRIC_CODES.index("runtime_completeness") + 1
    invalid = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        invalid,
        "components",
        finding_codes=[component_code],
        context_node_indexes=[0],
        addition_count=1,
    )
    corrected = deepcopy(invalid)
    _set_model_layer(
        corrected,
        "connections",
        finding_codes=[connection_code],
        addition_obligations=[[0, "$new_node_1", "routes to added responsibility"]],
    )
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid if len(calls) == 1 else corrected)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    monkeypatch.setattr(
        "agent.nodes.graph_critic._deterministic_review",
        lambda *_args, **_kwargs: {
            "approved": True,
            "deterministic_findings": [],
        },
    )
    graph = {
        "design_origin": "applied",
        "nodes": [{"id": "existing", "label": "Existing responsibility"}],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }

    result = await graph_critic_node(_critic_state(graph=graph))

    assert [call["telemetry"]["operation"] for call in calls] == [
        "graph_critic",
        "graph_critic_protocol_correction",
    ]
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "component additions require connection addition permission" in correction
    contract = result["graph_review"]["repair_contract"]
    assert contract["layers"]["components"]["addition_count"] == 1
    assert contract["layers"]["connections"]["addition_count"] == 1
    assert result["graph_review"].get("terminal") is not True


@pytest.mark.asyncio
async def test_post_merge_review_failure_is_typed_and_not_retried(monkeypatch):
    calls = []
    validation_calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(_passing_review_payload(topology_proofs={}))

    def reject_post_merge_review(*args, **kwargs):
        validation_calls.append((args, kwargs))
        if len(validation_calls) == 2:
            raise ValueError("PRIVATE_POST_MERGE_INVARIANT")
        return _validate_review_protocol(*args, **kwargs)

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    monkeypatch.setattr(
        "agent.nodes.graph_critic._validate_review_protocol",
        reject_post_merge_review,
    )
    state = _critic_state()
    state["send"] = send

    result = await graph_critic_node(state)

    assert len(calls) == 1
    assert len(validation_calls) == 2
    assert result["graph_review"]["failure_code"] == "semantic_review_protocol_invalid"
    review_event = events[-1]
    assert review_event["validation_stage"] == "initial"
    assert review_event["validation_path"] == "canonical_review"
    assert review_event["validation_rule"] == "invalid_server_state"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "repair_contract": {"repair_scope": "none", "layers": {}},
            "strengths": ["The runtime path is explicit."],
            "advice": [],
            "topology_proofs": [],
        },
        {
            "strengths": ["The runtime path is explicit."],
            "advice": [],
            "topology_proofs": [],
        },
    ],
)
async def test_invalid_structured_review_contract_fails_closed(
    monkeypatch,
    invalid_payload,
):
    calls = []
    render_calls = 0

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid_payload)

    async def await_diagram(graph):
        nonlocal render_calls
        render_calls += 1
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

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_protocol_invalid"
    assert result["graph_review"]["review_status"] == "unavailable"
    assert "repair_contract" not in result["graph_review"]
    assert len(calls) == 2
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert "state_effect_reconciliation" not in calls[0]["system"]
    assert calls[1]["effort"] == "medium"
    assert "topology guarantee" not in calls[1]["system"]
    correction_text = calls[1]["messages"][0]["content"][-1]["text"]
    assert "topology-proof contracts" not in correction_text
    assert calls[1]["telemetry"]["operation"] == "graph_critic_protocol_correction"
    assert render_calls == 1


def _valid_protocol_topology_proofs(edge=None):
    edge = edge or {
        "source": "source_node",
        "target": "target_node",
        "label": "carries typed payload",
    }
    return [
        {
            "guarantee": guarantee,
            "status": "pass",
            "edge_evidence": [edge],
            "route_claims": [{"source": edge["source"], "target": edge["target"]}],
            "repair_obligations": [],
            "repair_edge_selectors": [],
            "reason": "The cited witness subgraph supports this guarantee.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]


def _valid_model_topology_proofs():
    return {
        guarantee: ["pass", [0], [[0, 1]], [], []]
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    }


def _protocol_review(topology_proofs):
    return {
        "repair_contract": _repair_contract(),
        "strengths": ["The runtime path is explicit."],
        "advice": [],
        "topology_proofs": topology_proofs,
    }


@pytest.mark.parametrize(
    "defect",
    [
        "missing_proof",
        "duplicate_guarantee",
        "invalid_status",
        "invalid_evidence",
        "empty_pass_evidence",
        "invalid_reason",
    ],
)
def test_production_critic_protocol_rejects_malformed_topology_proofs(defect):
    proofs = _valid_protocol_topology_proofs()
    if defect == "missing_proof":
        proofs.pop()
    elif defect == "duplicate_guarantee":
        proofs[-1]["guarantee"] = proofs[0]["guarantee"]
    elif defect == "invalid_status":
        proofs[0]["status"] = "approved"
    elif defect == "invalid_evidence":
        proofs[0]["edge_evidence"] = [{"source": "source_node"}]
    elif defect == "empty_pass_evidence":
        proofs[0]["edge_evidence"] = []
    else:
        proofs[0]["reason"] = ["not", "a", "string"]

    with pytest.raises(ValueError, match="critic response protocol invalid"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
        )


def test_production_critic_protocol_accepts_complete_topology_proofs():
    _validate_review_protocol(
        _protocol_review(_valid_protocol_topology_proofs()),
        require_topology_proofs=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_malformed_topology_proofs_get_one_bounded_correction(
    monkeypatch,
    caplog,
    recovers,
):
    graph = {
        "design_origin": "applied",
        "nodes": [
            {"id": "source_node", "label": "Source"},
            {"id": "target_node", "label": "Target"},
        ],
        "edges": [
            {
                "source": "source_node",
                "target": "target_node",
                "label": "carries typed payload",
            }
        ],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    valid = _passing_review_payload(topology_proofs=_valid_model_topology_proofs())
    malformed = deepcopy(valid)
    malformed_guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    malformed["topology_proofs"][malformed_guarantee] = [
        "pass",
        [],
        [],
        [],
        [],
    ]
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        response = valid if recovers and len(calls) == 2 else malformed
        return _structured_response(response)

    caplog.set_level("WARNING", logger="agent.nodes.graph_critic")
    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    monkeypatch.setattr(
        "agent.nodes.graph_critic._deterministic_review",
        lambda *_args, **_kwargs: {
            "approved": True,
            "score": 1.0,
            "strengths": [],
            "missing": [],
            "advice": [],
            "revision_instruction": "",
        },
    )
    result = await graph_critic_node(
        _critic_state(graph=graph, complexity="production")
    )

    assert result["graph_review"]["approved"] is recovers
    assert result["graph_review"]["review_status"] == (
        "completed" if recovers else "unavailable"
    )
    if recovers:
        assert len(result["graph_review"]["topology_proofs"]) == len(
            _TOPOLOGY_PROOF_GUARANTEES
        )
    else:
        assert result["graph_review"]["terminal"] is True
        assert (
            result["graph_review"]["failure_code"] == "semantic_review_protocol_invalid"
        )
    assert len(calls) == 2
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_RESPONSE_SCHEMA
    assert "state_effect_reconciliation" in calls[0]["system"]
    assert "Preserve every required proof" in calls[0]["system"]
    assert calls[1]["effort"] == "medium"
    correction_text = calls[1]["messages"][0]["content"][-1]["text"]
    assert "topology-proof contracts" in correction_text
    assert f"path=topology_proofs.{malformed_guarantee}" in caplog.text
    assert "rule=missing_evidence" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_reason", "failure_code", "call_count"),
    [
        ("max_tokens", "semantic_review_output_truncated", 1),
        (None, "semantic_review_protocol_invalid", 2),
    ],
)
async def test_incomplete_structured_review_fails_closed_without_retry(
    monkeypatch,
    finish_reason,
    failure_code,
    call_count,
):
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            ),
            finish_reason=finish_reason,
        )

    async def await_diagram(graph):
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

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert len(calls) == call_count
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == failure_code
    assert result["graph_review"]["review_status"] == "unavailable"
    assert "missing" not in result["graph_review"]


@pytest.mark.asyncio
async def test_valid_first_semantic_review_uses_one_call(monkeypatch):
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            )
        )

    async def await_diagram(graph):
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

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 1
    assert "semantic_attempt" not in calls[0]["telemetry"]["metadata"]


def test_semantic_review_wire_has_only_fixed_scorecard_fields():
    assert set(_GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]) == {
        "layers",
        "topology_proofs",
        "prior_obligation_dispositions",
    }
    schema_text = json.dumps(_GRAPH_CRITIC_RESPONSE_SCHEMA)
    assert "blocking_findings" not in schema_text
    assert '"reason"' not in schema_text
    assert '"strengths"' not in schema_text
    assert '"advice"' not in schema_text
    row_item_types = {
        option["type"]
        for option in _GRAPH_CRITIC_RESPONSE_SCHEMA["$defs"]["layer_row"]["items"][
            "anyOf"
        ]
    }
    assert row_item_types == {"integer", "array"}


def test_semantic_review_failure_classifies_truncated_protocol_output():
    from agent.nodes.graph_critic import _semantic_review_failure_code

    assert (
        _semantic_review_failure_code(
            ValueError("invalid JSON"),
            '{"approved":false',
        )
        == "semantic_review_output_truncated"
    )
    assert (
        _semantic_review_failure_code(
            TimeoutError("provider unavailable"),
            "",
        )
        == "semantic_review_timeout"
    )


@pytest.mark.asyncio
async def test_semantic_critic_outage_fails_closed(monkeypatch):
    calls = 0
    events = []

    async def fail_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider unavailable")

    async def await_diagram(graph):
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

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fail_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert calls == 1
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_timeout"
    assert any(
        event.get("failure_code") == "semantic_review_timeout" for event in events
    )
    assert result["graph_review"]["review_status"] == "unavailable"
    assert "missing" not in result["graph_review"]


def test_every_semantic_blocker_has_an_editable_owner():
    assert (
        "render` records the deterministic browser assessment" in _GRAPH_CRITIC_SYSTEM
    )
    assert "subjective visual\npreference is advice" in _GRAPH_CRITIC_SYSTEM
    assert "Parallel edges between one component pair" in _GRAPH_CRITIC_SYSTEM
    assert "one primary sequence expose" in _GRAPH_CRITIC_SYSTEM
    assert all(
        REPAIR_LAYER_PATCH_FIELDS[_RUBRIC_CODE_OWNERS[code]] for code in _RUBRIC_CODES
    )


def test_novice_clarity_is_advisory_without_mutation_authority():
    graph = {
        "nodes": [{"id": "entry"}, {"id": "outcome"}],
        "edges": [{"source": "entry", "target": "outcome", "label": "returns"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Primary runtime",
                "kind": "runtime",
                "nodeIds": ["entry", "outcome"],
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["entry", "outcome"], "description": "returns"}
        ],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    novice_clarity_code = _RUBRIC_CODES.index("novice_clarity") + 1
    _set_model_layer(
        payload,
        "composition",
        finding_codes=[novice_clarity_code],
        context_indexes=[0],
        context_node_indexes=[0],
        group_indexes=[0],
        composition_fields=["groups", "sequence"],
        sequence_indexes=[0],
        group_addition_count=1,
        sequence_addition_count=1,
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=["Architect commitment: keep the main path visible."],
        require_topology_proofs=False,
    )

    contract = normalized["repair_contract"]
    composition = contract["layers"]["composition"]

    assert _RUBRIC_CODE_OWNERS["novice_clarity"] == "composition"
    assert contract["repair_scope"] == "none"
    assert composition["status"] == "pass"
    assert composition["blocking_findings"] == []
    assert composition["group_ids"] == []
    assert composition["composition_fields"] == []
    assert composition["sequence_indexes"] == []
    assert composition["composition_append_counts"] == {}
    assert normalized["advice"]
    assert normalized["hard_blockers"] == []
    assert RUBRIC_CRITERIA["novice_clarity"][1] in normalized["advice"]


def test_production_authored_composition_remains_blocking():
    graph = {
        "nodes": [{"id": "entry"}, {"id": "outcome"}],
        "edges": [{"source": "entry", "target": "outcome", "label": "returns"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Primary runtime",
                "kind": "runtime",
                "nodeIds": ["entry", "outcome"],
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["entry", "outcome"], "description": "returns"}
        ],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "composition",
        finding_codes=[
            _RUBRIC_CODES.index("novice_clarity") + 1,
            _RUBRIC_CODES.index("authored_composition") + 1,
        ],
        group_indexes=[0],
        composition_fields=["groups", "sequence"],
        sequence_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
        resolved_depth="production",
    )
    composition = normalized["repair_contract"]["layers"]["composition"]

    assert composition["status"] == "fail"
    assert composition["blocking_findings"] == [
        "Repair authored composition in the composition layer."
    ]
    assert composition["composition_fields"] == ["groups", "sequence"]
    assert composition["group_ids"] == ["runtime"]
    assert composition["sequence_indexes"] == [0]
    assert composition["composition_append_counts"] == {}
    assert RUBRIC_CRITERIA["novice_clarity"][1] in normalized["advice"]


def test_prior_open_obligations_filter_legacy_novice_clarity_blockers():
    state = _critic_state()
    state["graph_review"] = {
        "repair_contract": _repair_contract(
            scope="local",
            failed_layer="composition",
            findings=["Repair novice clarity in the composition layer."],
            layer_selectors={"composition": {"composition_fields": ["groups"]}},
        )
    }

    assert _prior_open_obligations(state, resolved_depth="production") == []


@pytest.mark.parametrize(
    "code",
    ["logical_flow", "authored_composition", "branch_completion"],
)
@pytest.mark.parametrize("resolved_depth", ["low", "prototype"])
def test_prior_open_obligations_filter_stale_nonproduction_advisory_blockers(
    code, resolved_depth
):
    prior = _typed_blockers_for_test(
        specs=[
            {
                "kind": "rubric",
                "layer": _RUBRIC_CODE_OWNERS[code],
                "key": {"code": code},
                "message": f"Repair {code.replace('_', ' ')}.",
            }
        ]
    )[0]
    state = _critic_state()
    state["graph_review"] = {"hard_blockers": [prior]}

    assert _prior_open_obligations(state, resolved_depth=resolved_depth) == []


@pytest.mark.parametrize("resolved_depth", ["low", "prototype"])
def test_prior_open_obligations_filter_legacy_nonproduction_authored_composition(
    resolved_depth,
):
    finding = "Repair authored composition in the composition layer."
    state = _critic_state()
    state["graph_review"] = {
        "repair_contract": _repair_contract(
            scope="local",
            failed_layer="composition",
            findings=[finding],
            layer_selectors={"composition": {"composition_fields": ["groups"]}},
        )
    }

    assert _prior_open_obligations(state, resolved_depth=resolved_depth) == []
    assert _prior_open_obligations(state, resolved_depth="production") == [
        {
            "id": _prior_obligation_id(layer="composition", finding=finding),
            "layer": "composition",
            "kind": "legacy",
            "finding": finding,
            "message": finding,
            "repair_fingerprint": "legacy",
        }
    ]


def test_authored_composition_preserves_exact_fields_and_requires_record_selectors():
    graph = {
        "nodes": [{"id": "entry"}, {"id": "outcome"}],
        "edges": [{"source": "entry", "target": "outcome", "label": "returns"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Primary runtime",
                "kind": "runtime",
                "nodeIds": ["entry", "outcome"],
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["entry", "outcome"], "description": "returns"}
        ],
        "assumptions": [],
    }
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        payload,
        "composition",
        finding_codes=[_RUBRIC_CODES.index("authored_composition") + 1],
        composition_fields=["groups"],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    contract = normalized["repair_contract"]

    assert contract["layers"]["composition"]["composition_fields"] == ["groups"]
    with pytest.raises(ValueError, match="whole groups collection"):
        validate_local_repair_admission(contract, graph=graph)


def test_authored_composition_sequence_repair_does_not_open_groups():
    graph = {
        "nodes": [{"id": "entry"}, {"id": "outcome"}],
        "edges": [{"source": "entry", "target": "outcome", "label": "returns"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Primary runtime",
                "kind": "runtime",
                "nodeIds": ["entry", "outcome"],
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["entry", "outcome"], "description": "returns"}
        ],
        "assumptions": [],
    }
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        payload,
        "composition",
        finding_codes=[_RUBRIC_CODES.index("authored_composition") + 1],
        composition_fields=["sequence"],
        sequence_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    contract = normalized["repair_contract"]

    assert contract["layers"]["composition"]["composition_fields"] == ["sequence"]
    assert contract["layers"]["composition"]["group_ids"] == []
    validate_local_repair_admission(contract, graph=graph)


def test_blocking_composition_profile_discards_advisory_field_permissions():
    graph = {
        "nodes": [{"id": "entry"}, {"id": "outcome"}],
        "edges": [{"source": "entry", "target": "outcome", "label": "returns"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Primary runtime",
                "kind": "runtime",
                "nodeIds": ["entry", "outcome"],
            }
        ],
        "sequence": [
            {"step": 1, "nodes": ["entry", "outcome"], "description": "returns"}
        ],
        "assumptions": ["The caller is authenticated."],
    }
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(
        payload,
        "composition",
        finding_codes=[
            _RUBRIC_CODES.index("authored_composition") + 1,
            _RUBRIC_CODES.index("assumption_hygiene") + 1,
        ],
        group_indexes=[0],
        composition_fields=["groups", "sequence", "assumptions"],
        sequence_indexes=[0],
        assumption_indexes=[0],
        group_addition_count=1,
        sequence_addition_count=1,
        assumption_addition_count=1,
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
        resolved_depth="prototype",
    )

    contract = normalized["repair_contract"]
    composition = contract["layers"]["composition"]
    assert contract["repair_scope"] == "local"
    assert composition["status"] == "fail"
    assert composition["composition_fields"] == ["assumptions"]
    assert composition["group_ids"] == []
    assert composition["sequence_indexes"] == []
    assert composition["assumption_indexes"] == [0]
    assert composition["composition_append_counts"] == {"assumptions": 1}
    assert normalized["advice"] == [RUBRIC_CRITERIA["authored_composition"][1]]
    validate_local_repair_admission(contract, graph=graph)
