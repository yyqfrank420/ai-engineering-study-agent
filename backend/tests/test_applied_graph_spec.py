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


def _group(index: int) -> tuple[str, str]:
    if index < 5:
        return "Product runtime", "runtime"
    if index < 9:
        return "Data and model services", "data"
    if index < 12:
        return "Delivery controls", "delivery"
    return "Operations", "operations"


def _draft(node_count: int = 14) -> dict:
    nodes = []
    for index in range(node_count):
        group, group_kind = _group(index)
        nodes.append({
            "label": f"Responsibility {index + 1}",
            "type": "decision" if index == 3 else "service",
            "tier": "private",
            "lane": "bottom" if group_kind == "operations" else "main",
            "responsibility": f"Owns material responsibility {index + 1}.",
            "group": group,
            "group_kind": group_kind,
            "parent_index": -1 if index == 0 else max(0, index - 1),
            "parent_label": "" if index == 0 else f"passes validated action {index + 1}",
            "parent_flow": "runtime",
            "parent_sync": "sync",
            "sequence_step": index if 0 < index < 8 else 0,
        })
    return {"title": "Complete architecture", "nodes": nodes, "cross_links": []}


def _assert_rooted(draft: dict) -> None:
    parents = {edge["target"]: edge["source"] for edge in draft["edges"][: len(draft["nodes"]) - 1]}
    assert set(parents) == {f"n{index}" for index in range(2, len(draft["nodes"]) + 1)}
    for node_id in parents:
        current = node_id
        seen = set()
        while current != "n1":
            assert current not in seen
            seen.add(current)
            current = parents[current]


def test_spec_uses_shared_resource_safety_settings(monkeypatch):
    from agent import applied_graph_spec as module

    monkeypatch.setattr(module.settings, "graph_safety_max_nodes", 44)
    monkeypatch.setattr(module.settings, "graph_safety_max_edges", 132)
    spec = applied_graph_spec("production")
    assert spec.depth == "production"
    assert spec.safety_max_nodes == 44
    assert spec.safety_max_edges == 132


def test_low_depth_stays_low():
    assert applied_graph_spec("low").depth == "low"


def test_topology_schema_uses_dynamic_closed_arrays_without_design_counts():
    schema = applied_graph_topology_schema(applied_graph_spec("production"))
    nodes = schema["properties"]["nodes"]
    links = schema["properties"]["cross_links"]
    node_record = nodes["items"]
    assert nodes["type"] == "array"
    assert node_record["additionalProperties"] is False
    assert node_record["required"] == [
        "label",
        "type",
        "tier",
        "lane",
        "responsibility",
        "group",
        "group_kind",
        "parent_index",
        "parent_label",
        "parent_flow",
        "parent_sync",
        "sequence_step",
    ]
    assert links["type"] == "array"
    assert links["items"]["required"] == [
        "source_index", "target_index", "label", "flow", "sync",
    ]
    serialized = json.dumps(schema)
    for unsupported_or_shaping_keyword in (
        "$ref", "$defs", "minItems", "maxItems", "minLength", "maxLength", "allOf"
    ):
        assert unsupported_or_shaping_keyword not in serialized


@pytest.mark.parametrize("node_count", [3, 14, 27])
def test_validator_accepts_variable_material_topologies(node_count):
    draft = validate_applied_graph_topology(_draft(node_count), applied_graph_spec("production"))
    assert len(draft["nodes"]) == node_count
    assert len(draft["edges"]) == node_count - 1
    _assert_rooted(draft)


def test_empty_topology_fails_closed():
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(
            {"title": "Empty", "nodes": [], "cross_links": []},
            applied_graph_spec("production"),
        )
    assert caught.value.code == "graph_design_topology_invalid"


def test_node_resource_safety_ceiling_is_enforced(monkeypatch):
    from agent import applied_graph_spec as module

    monkeypatch.setattr(module.settings, "graph_safety_max_nodes", 4)
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(_draft(5), applied_graph_spec("production"))
    assert caught.value.code == "graph_design_node_safety_limit"
    assert caught.value.node_count == 5


def test_edge_resource_safety_ceiling_is_enforced(monkeypatch):
    from agent import applied_graph_spec as module

    monkeypatch.setattr(module.settings, "graph_safety_max_edges", 3)
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(_draft(5), applied_graph_spec("production"))
    assert caught.value.code == "graph_design_edge_safety_limit"
    assert caught.value.edge_count == 4


@pytest.mark.parametrize(
    ("node_index", "parent_index"),
    [(0, 0), (1, -1), (1, 1), (1, 99)],
)
def test_invalid_parent_relationships_fail_closed(node_index, parent_index):
    payload = _draft(4)
    payload["nodes"][node_index]["parent_index"] = parent_index
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.code == "graph_design_topology_invalid"


def test_parent_cycle_fails_instead_of_reparenting_with_stale_label():
    payload = _draft(4)
    payload["nodes"][1]["parent_index"] = 2
    payload["nodes"][2]["parent_index"] = 1
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.code == "graph_design_topology_invalid"


def test_deep_acyclic_parent_chain_is_preserved():
    draft = validate_applied_graph_topology(_draft(18), applied_graph_spec("production"))
    parents = {edge["target"]: edge["source"] for edge in draft["edges"][:17]}
    assert parents["n18"] == "n17"


def test_cross_links_use_indexes_and_preserve_every_material_link():
    payload = _draft(6)
    payload["cross_links"] = [
        {
            "source_index": 1,
            "target_index": 4,
            "label": "publishes measured feedback",
            "flow": "feedback",
            "sync": "async",
        },
        {
            "source_index": 5,
            "target_index": 2,
            "label": "rolls back failed release",
            "flow": "deployment",
            "sync": "async",
        },
    ]
    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert draft["edges"][-2:] == [
        {
            "source": "n2",
            "target": "n5",
            "label": "publishes measured feedback",
            "flow": "feedback",
            "sync": "async",
        },
        {
            "source": "n6",
            "target": "n3",
            "label": "rolls back failed release",
            "flow": "deployment",
            "sync": "async",
        },
    ]


@pytest.mark.parametrize(
    "cross_link",
    [
        {"source_index": 2, "target_index": 2, "label": "loop", "flow": "runtime", "sync": "sync"},
        {"source_index": 9, "target_index": 2, "label": "unknown", "flow": "runtime", "sync": "sync"},
    ],
)
def test_invalid_cross_link_fails_instead_of_disappearing(cross_link):
    payload = _draft(5)
    payload["cross_links"] = [cross_link]
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.code == "graph_design_topology_invalid"


def test_duplicate_cross_link_fails_instead_of_using_array_order():
    payload = _draft(5)
    duplicate = {
        "source_index": 1,
        "target_index": 3,
        "label": "material control",
        "flow": "control",
        "sync": "sync",
    }
    payload["cross_links"] = [duplicate, duplicate]
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "duplicate"


@pytest.mark.parametrize(
    ("field", "value", "rule"),
    [("label", " ", "blank_required"), ("responsibility", "x" * 221, "safety_limit")],
)
def test_required_semantic_fields_are_rejected_instead_of_fabricated(field, value, rule):
    payload = _draft(4)
    payload["nodes"][1][field] = value
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == rule


def test_enrichment_preserves_authored_groups_and_runtime_sequence():
    spec = applied_graph_spec("production")
    payload = _draft(14)
    payload["nodes"][2]["sequence_step"] = 2
    payload["nodes"][3]["sequence_step"] = 2
    graph = enrich_applied_graph_topology(
        validate_applied_graph_topology(payload, spec),
        spec=spec,
        architect_plan={"assumptions": ["The source API supports version reads."]},
    )
    assert [group["label"] for group in graph["groups"]] == [
        "Product runtime", "Data and model services", "Delivery controls", "Operations",
    ]
    assert {node_id for group in graph["groups"] for node_id in group["nodeIds"]} == {
        f"n{index}" for index in range(1, 15)
    }
    parallel_step = graph["sequence"][1]
    assert {"n3", "n4"} <= set(parallel_step["nodes"])
    assert graph["assumptions"] == ["The source API supports version reads."]


def test_worst_case_topology_serialization_is_bounded_by_resource_ceiling():
    assert worst_case_topology_chars(applied_graph_spec("production")) < 200_000


def test_prompt_delegates_graph_size_and_preserves_material_boundaries():
    prompt = applied_graph_topology_prompt(
        query="Build a RAG runtime",
        architect_plan={"required_capabilities": ["retriever"]},
        challenger_review={"risks": ["show trust boundary"]},
        commitments="show accepted cache writes",
        spec=applied_graph_spec("production"),
    )
    assert "Choose the number of nodes, groups, and cross-links from the design" in prompt
    assert "Never merge distinct owners" in prompt
    assert "zero-based index" in prompt
    assert "sequence_step" in prompt
    assert "all material non-tree connections" in prompt
    assert "at most ten" not in prompt
    assert "n1 through n9" not in prompt
    assert "node_budget" not in prompt


@pytest.mark.asyncio
async def test_dynamic_generator_uses_schema_once(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    calls = []

    async def fake_stream_structured_llm(**kwargs):
        calls.append(kwargs)
        return StructuredLLMResponse(
            text=json.dumps(_draft(14)),
            finish_reason="end_turn",
            input_tokens=100,
            output_tokens=500,
            provider="moonshot",
            model="kimi-k3",
        )

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
    result = await graph_worker._generate_applied_architecture(
        {
            "graph_data": None,
            "approved_graph_data": None,
            "architect_plan": {"required_capabilities": ["complete runtime"]},
            "challenger_review": {"risks": ["complete failures"]},
            "architecture_ready": True,
            "complexity": "production",
        },
        "Build a complete runtime",
        SimpleNamespace(resolved="production"),
    )
    assert len(result["nodes"]) == 14
    assert len(result["groups"]) == 4
    assert len(calls) == 1
    serialized_schema = json.dumps(calls[0]["response_schema"])
    assert "maxItems" not in serialized_schema


@pytest.mark.asyncio
async def test_unpublished_rejection_gets_complete_redraw_with_all_blockers(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    calls = []
    blockers = [
        "The approval rejection route has no durable terminal state.",
        "The timeout path retries without same-key outcome reconciliation.",
        "The release path has no rollback edge.",
    ]

    async def fake_stream_structured_llm(**kwargs):
        calls.append(kwargs)
        return StructuredLLMResponse(
            text=json.dumps(_draft(14)),
            finish_reason="end_turn",
            input_tokens=100,
            output_tokens=500,
            provider="moonshot",
            model="kimi-k3",
        )

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
    await graph_worker._generate_applied_architecture(
        {
            "graph_data": {
                "title": "Rejected candidate",
                "nodes": [{"id": "old-node", "label": "Old node"}],
                "edges": [],
            },
            "approved_graph_data": None,
            "architect_plan": {"required_capabilities": ["complete runtime"]},
            "challenger_review": {"risks": ["complete failures"]},
            "graph_review": {
                "approved": False,
                "missing": blockers,
                "revision_instruction": "Resolve the complete review.",
            },
            "graph_revision_count": 1,
            "architecture_ready": True,
            "complexity": "production",
        },
        "Build a complete runtime",
        SimpleNamespace(resolved="production"),
    )

    prompt = calls[0]["messages"][0]["content"]
    assert all(blocker in prompt for blocker in blockers)
    assert "Rejected candidate" in prompt
    assert "no identity-retention requirement" in prompt
    assert "Keep at least 60%" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "finish_reason", "code"),
    [
        ('{"title":', "max_tokens", "graph_design_output_truncated"),
        ('{"title":', "end_turn", "graph_design_schema_invalid"),
    ],
)
async def test_dynamic_generator_classifies_provider_truncation(monkeypatch, text, finish_reason, code):
    import agent.nodes.graph_worker as graph_worker

    async def fake_stream_structured_llm(**_kwargs):
        return StructuredLLMResponse(
            text=text,
            finish_reason=finish_reason,
            input_tokens=10,
            output_tokens=3600,
            provider="moonshot",
            model="kimi-k3",
        )

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
    with pytest.raises(AppliedGraphSpecError) as caught:
        await graph_worker._generate_applied_architecture(
            {
                "graph_data": None,
                "approved_graph_data": None,
                "architect_plan": {"required_capabilities": ["runtime"]},
                "challenger_review": {"risks": ["failure"]},
                "architecture_ready": True,
            },
            "Build a runtime",
            SimpleNamespace(resolved="prototype"),
        )
    assert caught.value.code == code
