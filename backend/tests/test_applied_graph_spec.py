import json
from types import SimpleNamespace

import pytest

from agent.applied_graph_spec import (
    AppliedGraphSpecError,
    applied_graph_spec,
    applied_graph_topology_prompt,
    applied_graph_topology_schema,
    enrich_applied_graph_topology,
    validate_applied_graph_topology,
    worst_case_topology_chars,
)
from agent.stream_utils import StructuredLLMResponse


def _draft() -> dict:
    nodes = {}
    for index in range(1, 10):
        nodes[f"n{index}"] = {
            "label": f"Responsibility {index}",
            "type": "decision" if index == 3 else "service",
            "tier": "private",
            "lane": "bottom" if index >= 8 else "main",
            "responsibility": f"Owns bounded responsibility {index}.",
            "parent": "ROOT" if index == 1 else "n1",
            "parent_label": "starts the runtime" if index == 1 else f"passes validated action {index}",
            "parent_flow": "runtime",
            "parent_sync": "sync",
        }
    return {
        "title": "Bounded architecture",
        "nodes": nodes,
        "cross_links": [],
    }


def _assert_rooted_connected(draft: dict) -> dict[str, str]:
    parents = {edge["target"]: edge["source"] for edge in draft["edges"]}
    assert set(parents) == {f"n{index}" for index in range(2, 10)}
    for node_id in parents:
        current = node_id
        seen = set()
        while current != "n1":
            assert current not in seen
            seen.add(current)
            current = parents[current]
    return parents


def test_specs_keep_existing_depth_and_edge_budgets():
    prototype = applied_graph_spec("prototype")
    production = applied_graph_spec("production")
    assert (prototype.min_nodes, prototype.target_nodes, prototype.max_nodes) == (7, 9, 12)
    assert prototype.max_edges == 27
    assert (production.min_nodes, production.target_nodes, production.max_nodes) == (9, 9, 13)
    assert production.max_edges == 30
    assert prototype.max_output_tokens == 5200
    assert production.max_output_tokens == 5200


def test_topology_schema_has_exact_closed_slots_without_unsupported_bounds():
    schema = applied_graph_topology_schema(applied_graph_spec("prototype"))
    nodes = schema["properties"]["nodes"]
    links = schema["properties"]["cross_links"]
    node_record = schema["$defs"]["node_record"]
    cross_link_record = schema["$defs"]["cross_link_record"]
    assert nodes["additionalProperties"] is False
    assert nodes["required"] == [f"n{index}" for index in range(1, 10)]
    assert all(
        value == {"$ref": "#/$defs/node_record"}
        for value in nodes["properties"].values()
    )
    assert node_record["additionalProperties"] is False
    assert node_record["required"] == [
        "label", "type", "tier", "lane", "responsibility",
        "parent", "parent_label", "parent_flow", "parent_sync",
    ]
    assert node_record["properties"]["parent"]["enum"] == [
        "ROOT", *(f"n{index}" for index in range(1, 10))
    ]
    assert links == {
        "type": "array",
        "items": {"$ref": "#/$defs/cross_link_record"},
    }
    assert cross_link_record["additionalProperties"] is False
    assert cross_link_record["required"] == [
        "source", "target", "label", "flow", "sync",
    ]
    assert schema["required"] == ["title", "nodes", "cross_links"]
    assert set(schema["properties"]) == set(schema["required"])
    serialized = json.dumps(schema)
    assert "minItems" not in serialized
    assert "maxItems" not in serialized
    assert "minLength" not in serialized
    assert "maxLength" not in serialized
    assert "allOf" not in serialized


def test_parent_slots_materialize_exact_connected_tree():
    draft = validate_applied_graph_topology(_draft(), applied_graph_spec("prototype"))
    assert len(draft["nodes"]) == 9
    assert len(draft["edges"]) == 8
    assert {edge["target"] for edge in draft["edges"]} == {
        f"n{index}" for index in range(2, 10)
    }


def test_missing_node_slot_fails_closed():
    payload = _draft()
    del payload["nodes"]["n9"]
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    assert caught.value.code == "graph_design_node_budget_invalid"


def test_forward_parent_is_preserved_and_connected():
    payload = _draft()
    payload["nodes"]["n2"]["parent"] = "n9"
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    parents = _assert_rooted_connected(draft)
    assert parents["n2"] == "n9"


def test_self_unknown_and_extra_root_parents_repair_to_n1():
    payload = _draft()
    payload["nodes"]["n2"]["parent"] = "ROOT"
    payload["nodes"]["n3"]["parent"] = "n3"
    payload["nodes"]["n4"]["parent"] = "not-a-slot"
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    parents = _assert_rooted_connected(draft)
    assert parents["n2"] == "n1"
    assert parents["n3"] == "n1"
    assert parents["n4"] == "n1"


def test_cycle_repairs_first_slot_order_participant_to_n1():
    payload = _draft()
    payload["nodes"]["n2"]["parent"] = "n3"
    payload["nodes"]["n3"]["parent"] = "n2"
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    parents = _assert_rooted_connected(draft)
    assert parents["n2"] == "n1"
    assert parents["n3"] == "n2"


def test_depth_over_five_repairs_current_node_to_n1():
    payload = _draft()
    payload["nodes"]["n2"]["parent"] = "n3"
    payload["nodes"]["n3"]["parent"] = "n4"
    payload["nodes"]["n4"]["parent"] = "n5"
    payload["nodes"]["n5"]["parent"] = "n6"
    payload["nodes"]["n6"]["parent"] = "n7"
    payload["nodes"]["n7"]["parent"] = "n1"
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    parents = _assert_rooted_connected(draft)
    assert parents["n2"] == "n1"
    assert parents["n3"] == "n4"


def test_cross_link_self_loop_and_duplicate_are_discarded_deterministically():
    payload = _draft()
    payload["cross_links"] = [
        {"source": "n2", "target": "n2", "label": "retry", "flow": "runtime", "sync": "sync"},
        {"source": "n1", "target": "n2", "label": "passes validated action 2", "flow": "runtime", "sync": "sync"},
    ]
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    assert len(draft["edges"]) == 8


def test_blank_authored_fields_and_root_metadata_normalize_deterministically():
    payload = _draft()
    payload["title"] = "   "
    payload["nodes"]["n1"]["parent_label"] = ""
    payload["nodes"]["n2"].update({
        "label": " ",
        "type": " SERVICE ",
        "tier": " PRIVATE ",
        "lane": " MAIN ",
        "responsibility": "",
        "parent": " N1 ",
        "parent_label": " ",
        "parent_flow": " RUNTIME ",
        "parent_sync": " SYNC ",
    })
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    node = next(item for item in draft["nodes"] if item["id"] == "n2")
    edge = next(item for item in draft["edges"] if item["target"] == "n2")
    assert draft["title"] == "Applied Agent Architecture"
    assert node["label"] == "Service n2"
    assert node["responsibility"] == "Handles the assigned service responsibility."
    assert edge == {
        "source": "n1",
        "target": "n2",
        "label": "Routes validated work to Service n2",
        "flow": "runtime",
        "sync": "sync",
    }


def test_optional_cross_links_canonicalize_endpoints_and_drop_invalid_or_blank():
    payload = _draft()
    payload["cross_links"] = [
        {"source": " N2 ", "target": "N3", "label": "Material route", "flow": "CONTROL", "sync": "ASYNC"},
        {"source": "missing", "target": "n3", "label": "Invalid endpoint", "flow": "control", "sync": "async"},
        {"source": "n3", "target": "n4", "label": " ", "flow": "control", "sync": "async"},
    ]
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    assert draft["edges"][8:] == [{
        "source": "n2",
        "target": "n3",
        "label": "Material route",
        "flow": "control",
        "sync": "async",
    }]


def test_structural_string_failure_exposes_safe_path_and_rule_only():
    payload = _draft()
    payload["nodes"]["n2"]["label"] = None
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    assert caught.value.code == "graph_design_schema_invalid"
    assert caught.value.path == "nodes.n2.label"
    assert caught.value.rule == "value_type"


def test_more_than_ten_cross_links_after_dedupe_keep_first_ten():
    payload = _draft()
    unique_links = [
        {
            "source": "n2",
            "target": "n3",
            "label": f"material cross route {index}",
            "flow": "control",
            "sync": "async",
        }
        for index in range(1, 12)
    ]
    payload["cross_links"] = [unique_links[0], *unique_links]
    draft = validate_applied_graph_topology(payload, applied_graph_spec("prototype"))
    assert [edge["label"] for edge in draft["edges"][8:]] == [
        f"material cross route {index}" for index in range(1, 11)
    ]


def test_enrichment_builds_three_groups_without_inventing_edges():
    spec = applied_graph_spec("prototype")
    payload = _draft()
    draft = validate_applied_graph_topology(payload, spec)
    graph = enrich_applied_graph_topology(draft, spec=spec, architect_plan={})
    assert len(graph["edges"]) == 8
    assert len(graph["groups"]) == 3
    assert len(graph["sequence"]) == 5
    assert {node_id for group in graph["groups"] for node_id in group["nodeIds"]} == {
        f"n{index}" for index in range(1, 10)
    }


def test_enrichment_preserves_only_authored_compensation_edges():
    spec = applied_graph_spec("prototype")
    payload = _draft()
    payload["cross_links"] = [{
        "source": "n2",
        "target": "n1",
        "label": "Compensation proposal returns for validation",
        "flow": "control",
        "sync": "async",
    }]
    graph = enrich_applied_graph_topology(
        validate_applied_graph_topology(payload, spec), spec=spec, architect_plan={}
    )
    compensation_edges = [
        edge for edge in graph["edges"]
        if "compensat" in edge["label"].lower() and edge["target"] == "n1"
    ]
    assert {edge["source"] for edge in compensation_edges} == {"n2"}


def test_ten_cross_links_remain_inside_nine_node_render_budget():
    spec = applied_graph_spec("production")
    payload = _draft()
    payload["cross_links"] = [
        {
            "source": f"n{((index - 1) % 8) + 1}",
            "target": f"n{(index % 8) + 2}",
            "label": f"material cross route {index}",
            "flow": "control",
            "sync": "async",
        }
        for index in range(1, 11)
    ]
    graph = enrich_applied_graph_topology(
        validate_applied_graph_topology(payload, spec), spec=spec, architect_plan={}
    )
    assert len(graph["edges"]) == 18


def test_worst_case_topology_serialization_fits_generation_budget():
    assert worst_case_topology_chars(applied_graph_spec("production")) < 16_000


def test_prompt_names_fixed_slots_parent_depth_and_semantic_identity():
    prompt = applied_graph_topology_prompt(
        query="Build a RAG runtime",
        architect_plan={"components": ["retriever"], "assumptions": ["book corpus"]},
        challenger_review={"blockers": ["show trust boundary"]},
        commitments="show cache acceptance once",
        spec=applied_graph_spec("prototype"),
    )
    assert "n1 through n9 exactly once" in prompt
    assert "parent ROOT" in prompt
    assert "depth at or below five" in prompt
    assert "rooted, acyclic n1 tree" in prompt
    assert "earlier parent" not in prompt
    assert "cross_links as an array" in prompt
    assert "at most ten distinct" in prompt
    assert "semantic identity" in prompt
    assert '"authoring_limits"' in prompt
    assert "title at most 100 characters" in prompt
    assert "node label at most 60 characters" in prompt
    assert "one sentence of at most 140 characters" in prompt
    assert "parent or cross-link label at most 100 characters" in prompt
    assert "material cross-links only" in prompt
    assert "no prose outside the schema fields" in prompt
    assert "visible topology must identify distinct validation" in prompt


@pytest.mark.asyncio
async def test_bounded_generator_uses_schema_once(monkeypatch):
    import agent.nodes.graph_worker as graph_worker
    calls = []

    async def fake_stream_structured_llm(**kwargs):
        calls.append(kwargs)
        payload = _draft()
        payload["cross_links"].append({
            "source": "n2", "target": "n2", "label": "retry", "flow": "runtime", "sync": "sync",
        })
        return StructuredLLMResponse(
            text=json.dumps(payload), finish_reason="end_turn", input_tokens=100,
            output_tokens=500, provider="anthropic", model="claude-sonnet-5",
        )

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
    monkeypatch.setattr(graph_worker, "_normalise_applied_graph", lambda graph, **_kwargs: graph)

    def reject_if_called(*_args):
        raise AssertionError("the canonical workflow owns semantic review")

    monkeypatch.setattr(
        graph_worker,
        "_validate_applied_architecture_patch",
        reject_if_called,
    )
    result = await graph_worker._generate_bounded_applied_architecture(
        {"graph_data": None, "architect_plan": {}, "challenger_review": {}, "complexity": "prototype"},
        "Build a bounded runtime", SimpleNamespace(resolved="prototype"),
    )
    assert len(result["nodes"]) == 9
    assert len(result["edges"]) == 8
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "finish_reason", "code"),
    [('{"title":', "max_tokens", "graph_design_output_truncated"), ('{"title":', "end_turn", "graph_design_schema_invalid")],
)
async def test_bounded_generator_classifies_max_tokens_before_parse(monkeypatch, text, finish_reason, code):
    import agent.nodes.graph_worker as graph_worker

    async def fake_stream_structured_llm(**_kwargs):
        return StructuredLLMResponse(
            text=text, finish_reason=finish_reason, input_tokens=10,
            output_tokens=3600, provider="anthropic", model="claude-sonnet-5",
        )

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
    with pytest.raises(AppliedGraphSpecError) as caught:
        await graph_worker._generate_bounded_applied_architecture(
            {"graph_data": None, "architect_plan": {}, "challenger_review": {}},
            "Build a bounded runtime", SimpleNamespace(resolved="prototype"),
        )
    assert caught.value.code == code
