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


def _group(index: int) -> tuple[str, int]:
    if index < 5:
        return "Product runtime", 600
    if index < 9:
        return "Data and model services", 601
    if index < 12:
        return "Delivery controls", 603
    return "Operations", 602


def _draft(node_count: int = 14) -> dict:
    node_records = []
    for index in range(node_count):
        group, group_kind = _group(index)
        node_records.append(
            [
                f"Responsibility {index + 1}",
                108 if index == 3 else 101,
                f"Owns material responsibility {index + 1}.",
                group,
                group_kind,
            ]
        )
    components = [
        [
            index - 1,
            *node_records[index],
            f"passes validated action {index + 1}",
            400,
            500,
        ]
        for index in range(1, node_count)
    ]
    return {
        "root": node_records[0],
        "components": components,
        "connections": {"links": []},
        "composition": {
            "title": "Complete architecture",
            "steps": list(range(min(7, node_count))),
        },
    }


def _assert_rooted(draft: dict) -> None:
    parents = {
        edge["target"]: edge["source"]
        for edge in draft["edges"][: len(draft["nodes"]) - 1]
    }
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


def test_node_safety_capacity_cannot_overlap_wire_category_codes(monkeypatch):
    from agent import applied_graph_spec as module

    monkeypatch.setattr(module.settings, "graph_safety_max_nodes", 101)
    with pytest.raises(RuntimeError, match="wire category namespace"):
        applied_graph_spec("production")


def test_topology_schema_uses_compact_positional_records_with_resource_bounds():
    spec = applied_graph_spec("production")
    schema = applied_graph_topology_schema(spec)
    properties = schema["properties"]
    assert list(properties) == [
        "root",
        "components",
        "connections",
        "composition",
    ]
    root = properties["root"]
    components = properties["components"]
    connections = properties["connections"]
    composition = properties["composition"]
    assert "minItems" not in components
    assert components["maxItems"] == spec.safety_max_nodes - 1
    scalar_items = {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }
    assert root == {
        "type": "array",
        "maxItems": 5,
        "items": scalar_items,
    }
    assert components["items"] == {
        "type": "array",
        "maxItems": 9,
        "items": scalar_items,
    }
    assert connections["properties"]["links"]["maxItems"] == spec.safety_max_edges
    assert connections["properties"]["links"]["items"]["maxItems"] == 5
    assert connections["properties"]["links"]["items"]["items"] == scalar_items
    assert composition["required"] == ["title", "steps"]
    assert set(composition["properties"]) == {"title", "steps"}
    steps = composition["properties"]["steps"]
    assert steps["maxItems"] == spec.safety_max_nodes
    assert steps["items"] == {"type": "integer"}
    serialized = json.dumps(schema)
    for unsupported_or_shaping_keyword in (
        "$ref",
        "$defs",
        "minItems",
        "minLength",
        "maxLength",
        "allOf",
        "prefixItems",
    ):
        assert unsupported_or_shaping_keyword not in serialized


@pytest.mark.parametrize("node_count", [3, 14, 27])
def test_validator_accepts_variable_material_topologies(node_count):
    draft = validate_applied_graph_topology(
        _draft(node_count), applied_graph_spec("production")
    )
    assert len(draft["nodes"]) == node_count
    assert len(draft["edges"]) == node_count - 1
    _assert_rooted(draft)


def test_wire_references_are_zero_based_across_every_collection():
    payload = _draft(6)
    payload["connections"]["links"] = [[1, 4, "publishes feedback", 402, 501]]
    payload["composition"]["steps"] = [0, 1, 2, 3, 4, 5]

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert [node["group"] for node in draft["nodes"]] == [
        "Product runtime",
        "Product runtime",
        "Product runtime",
        "Product runtime",
        "Product runtime",
        "Data and model services",
    ]
    assert [(edge["source"], edge["target"]) for edge in draft["edges"][-1:]] == [
        ("n2", "n5")
    ]
    assert [node["sequence_step"] for node in draft["nodes"]] == [1, 2, 3, 4, 5, 6]
    _assert_rooted(draft)


def test_index_base_is_rejected_as_an_unknown_field():
    payload = _draft(4)
    payload["index_base"] = 0

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.path == "$"
    assert caught.value.rule == "key_set"


@pytest.mark.parametrize(
    ("section", "row", "rule"),
    [
        ("root", ["label", 1], "tuple_arity"),
        ("components", [0, "label", 1], "tuple_arity"),
        ("links", [0, 1, "label", 0], "tuple_arity"),
    ],
)
def test_fixed_record_arity_fails_closed(section, row, rule):
    payload = _draft(4)
    if section == "root":
        payload["root"] = row
    elif section == "components":
        payload["components"][0] = row
    else:
        payload["connections"][section] = [row]
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == rule


@pytest.mark.parametrize(
    ("record", "row"),
    [
        ("root", ["label", 101, "responsibility", "group"]),
        (
            "component",
            [0, "label", 101, "responsibility", "group", "edge", 400, 500],
        ),
    ],
)
def test_group_identity_is_required_in_every_component_record(record, row):
    payload = _draft(4)
    if record == "root":
        payload["root"] = row
    else:
        payload["components"][0] = row

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.rule == "tuple_arity"


def test_component_enum_positions_are_validated_server_side():
    payload = _draft(4)
    payload["root"][1] = 999
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "invalid_enum"


def test_component_categorical_positions_reject_unknown_names():
    payload = _draft(4)
    payload["root"][1] = "model-serving-service"
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "invalid_enum"


def test_wire_codebooks_are_disjoint_and_decode_exhaustively():
    from agent import applied_graph_spec as module

    codebooks = (
        module._NODE_TYPE_CODES,
        module._FLOW_CODES,
        module._SYNC_CODES,
        module._GROUP_KIND_CODES,
    )
    all_codes = [code for codebook in codebooks for code in codebook]
    assert len(all_codes) == len(set(all_codes))
    for codebook in codebooks:
        for code, token in codebook.items():
            assert module._coded_token(code, codebook, path="$code") == token
            assert module._coded_token(str(code), codebook, path="$code") == token


@pytest.mark.parametrize(
    ("section", "field_index", "foreign_code"),
    [
        ("root", 1, 200),
        ("root", 4, 100),
        ("component", 5, 100),
        ("component", 7, 500),
        ("component", 8, 600),
        ("link", 3, 100),
        ("link", 4, 200),
    ],
)
def test_every_categorical_position_rejects_foreign_codes(
    section, field_index, foreign_code
):
    payload = _draft(4)
    if section == "root":
        payload["root"][field_index] = foreign_code
    elif section == "component":
        payload["components"][0][field_index] = foreign_code
    elif section == "link":
        payload["connections"]["links"] = [[0, 2, "material link", 400, 500]]
        payload["connections"]["links"][0][field_index] = foreign_code
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "invalid_enum"


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        (True, "value_type"),
        (1.0, "value_type"),
        ("109", "invalid_enum"),
        ("1" * 5000, "invalid_enum"),
        (-1, "invalid_enum"),
        (109, "invalid_enum"),
    ],
)
def test_wire_codes_reject_invalid_scalar_values(value, rule):
    payload = _draft(4)
    payload["root"][1] = value
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == rule


def test_compatibility_category_representations_are_normalized_in_every_tuple_layout():
    payload = _draft(4)
    payload["root"][1] = "101"
    payload["root"][4] = "runtime"
    payload["components"][0][2] = "decision"
    payload["components"][0][5] = "runtime"
    payload["components"][0][7] = "control"
    payload["components"][0][8] = "async"
    payload["connections"]["links"] = [[0, 2, "reports feedback", "feedback", "sync"]]

    graph = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert graph["nodes"][0]["type"] == "service"
    assert graph["nodes"][1]["type"] == "decision"
    assert graph["nodes"][0]["group_kind"] == "runtime"
    assert graph["edges"][0]["flow"] == "control"
    assert graph["edges"][0]["sync"] == "async"
    assert graph["edges"][-1]["flow"] == "feedback"
    assert graph["edges"][-1]["sync"] == "sync"


@pytest.mark.parametrize("field_index", [0, 2, 3])
def test_component_text_positions_reject_integer_codes(field_index):
    payload = _draft(4)
    payload["root"][field_index] = 100
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "value_type"


def test_each_non_root_component_carries_exactly_one_incoming_tree_edge():
    payload = _draft(4)
    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert len(draft["nodes"]) == 4
    assert len(draft["edges"]) == 3
    assert "tree" not in payload["connections"]


@pytest.mark.parametrize(
    ("record", "field_index", "value", "rule"),
    [
        ("root", 3, " ", "blank_required"),
        ("root", 3, 1, "value_type"),
        ("root", 4, 999, "invalid_enum"),
        ("component", 4, " ", "blank_required"),
        ("component", 4, 1, "value_type"),
        ("component", 5, 999, "invalid_enum"),
    ],
)
def test_inline_group_identity_is_validated(record, field_index, value, rule):
    payload = _draft(4)
    row = payload["root"] if record == "root" else payload["components"][0]
    row[field_index] = value

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.rule == rule


def test_legacy_group_definition_table_is_rejected():
    payload = _draft(4)
    payload["composition"]["groups"] = [["Product runtime", 600]]

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.path == "composition"
    assert caught.value.rule == "key_set"


def test_group_memberships_are_derived_from_inline_component_identity():
    draft = validate_applied_graph_topology(_draft(6), applied_graph_spec("production"))

    assert [node["group"] for node in draft["nodes"]] == [
        "Product runtime",
        "Product runtime",
        "Product runtime",
        "Product runtime",
        "Product runtime",
        "Data and model services",
    ]


def test_same_group_label_with_different_kinds_stays_distinct():
    payload = _draft(2)
    payload["components"][0][4] = payload["root"][3]
    payload["components"][0][5] = 601

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert [
        (node["group"], node["group_kind"]) for node in draft["nodes"]
    ] == [
        ("Product runtime", "runtime"),
        ("Product runtime", "data"),
    ]


def test_late_component_can_declare_a_new_group_without_a_definition_index():
    payload = _draft(7)
    payload["components"][5][4] = "New external boundary"
    payload["components"][5][5] = 604

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert draft["nodes"][6]["group"] == "New external boundary"
    assert draft["nodes"][6]["group_kind"] == "external"


@pytest.mark.parametrize("steps", [[0, 0], [99]])
def test_sequence_steps_are_unique_zero_based_node_indexes(steps):
    payload = _draft(4)
    payload["composition"]["steps"] = steps
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.code == "graph_design_topology_invalid"


def test_nested_sequence_batches_are_rejected():
    payload = _draft(4)
    payload["composition"]["steps"] = [[0], [1]]

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.code == "graph_design_schema_invalid"
    assert caught.value.path == "composition.steps[0]"
    assert caught.value.rule == "value_type"


def test_sequence_uses_component_indexes_without_row_offset():
    payload = _draft(6)
    payload["composition"]["steps"] = [0, 1, 2, 3, 4, 5]

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert draft["nodes"][0]["sequence_step"] == 1
    assert draft["nodes"][1]["sequence_step"] == 2
    assert draft["nodes"][5]["sequence_step"] == 6


def test_sequence_can_start_at_root_and_follows_primary_tree_edges():
    payload = _draft(4)
    payload["composition"]["steps"] = [0, 1, 2]

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert [node["sequence_step"] for node in draft["nodes"]] == [1, 2, 3, 0]


def test_production_requires_a_primary_sequence_but_prototype_can_omit_it():
    payload = _draft(4)
    payload["composition"]["steps"] = []

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.code == "graph_design_topology_invalid"
    validate_applied_graph_topology(payload, applied_graph_spec("prototype"))


@pytest.mark.parametrize(
    "steps",
    [
        [1, 2],
        [1, 3],
    ],
)
def test_sequence_requires_root_reachable_primary_runtime_membership(steps):
    payload = _draft(4)
    payload["composition"]["steps"] = steps

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.code == "graph_design_topology_invalid"
    assert caught.value.rule == "topology"


def test_sequence_list_order_is_derived_from_primary_topology():
    payload = _draft(5)
    payload["composition"]["steps"] = [4, 1, 3, 0, 2]

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert [node["sequence_step"] for node in draft["nodes"]] == [1, 2, 3, 4, 5]


def test_sequence_root_list_position_is_not_authoritative():
    payload = _draft(4)
    payload["composition"]["steps"] = [1, 0]

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert [node["sequence_step"] for node in draft["nodes"]] == [1, 2, 0, 0]


def test_sequence_accepts_a_runtime_link_from_an_earlier_stage():
    payload = _draft(4)
    payload["components"][1][0] = 0
    payload["connections"]["links"] = [[1, 2, "starts staged runtime", 400, 500]]
    payload["composition"]["steps"] = [0, 1, 2]

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert [node["sequence_step"] for node in draft["nodes"]] == [1, 2, 2, 0]


def test_sequence_rejects_a_runtime_link_in_the_reverse_direction():
    payload = _draft(4)
    payload["connections"]["links"] = [[3, 1, "reverses staged runtime", 400, 500]]
    payload["composition"]["steps"] = [0, 1, 3]

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.rule == "topology"


def test_presentation_metadata_is_derived_from_semantic_fields():
    payload = _draft(14)
    payload["components"][0][2] = 107

    draft = validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert all(node["tier"] is None for node in draft["nodes"])
    assert draft["nodes"][1]["lane"] == "main"
    assert draft["nodes"][12]["group_kind"] == "operations"
    assert draft["nodes"][12]["lane"] == "bottom"


def test_empty_topology_fails_closed():
    payload = _draft(1)
    payload["root"] = []
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(
            payload,
            applied_graph_spec("production"),
        )
    assert caught.value.code == "graph_design_schema_invalid"


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
    ("component_index", "parent_index"),
    [(0, -1), (0, 99), (1, 2)],
)
def test_invalid_parent_relationships_fail_closed(component_index, parent_index):
    payload = _draft(4)
    payload["components"][component_index][0] = parent_index
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.code == "graph_design_topology_invalid"


def test_late_component_parent_must_reference_an_earlier_node():
    payload = _draft(7)
    assert payload["components"][5][0] == 5
    validate_applied_graph_topology(payload, applied_graph_spec("production"))
    payload["components"][5][0] = 6

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.code == "graph_design_topology_invalid"
    assert caught.value.path == "components[5][0]"
    assert caught.value.rule == "topology"
    assert caught.value.observed_index == 6
    assert caught.value.maximum_index == 5


def test_deep_acyclic_parent_chain_is_preserved():
    draft = validate_applied_graph_topology(
        _draft(18), applied_graph_spec("production")
    )
    parents = {edge["target"]: edge["source"] for edge in draft["edges"][:17]}
    assert parents["n18"] == "n17"


def test_cross_links_use_indexes_and_preserve_every_material_link():
    payload = _draft(6)
    payload["connections"]["links"] = [
        [1, 4, "publishes measured feedback", 402, 501],
        [5, 2, "rolls back failed release", 403, 501],
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


def test_invalid_zero_based_link_endpoint_fails_at_exact_coordinate():
    payload = _draft(6)
    payload["connections"]["links"] = [
        [0, 5, "valid link", 402, 501],
        [1, 6, "out-of-range link", 403, 501],
    ]

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.code == "graph_design_topology_invalid"
    assert caught.value.path == "connections.links[1][1]"
    assert caught.value.rule == "topology"


@pytest.mark.parametrize(
    "cross_link",
    [
        [2, 2, "loop", 400, 500],
        [9, 2, "unknown", 400, 500],
    ],
)
def test_invalid_cross_link_fails_instead_of_disappearing(cross_link):
    payload = _draft(5)
    payload["connections"]["links"] = [cross_link]
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.code == "graph_design_topology_invalid"


def test_duplicate_cross_link_fails_instead_of_using_array_order():
    payload = _draft(5)
    duplicate = [1, 3, "material control", 401, 500]
    payload["connections"]["links"] = [duplicate, duplicate]
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "duplicate"


@pytest.mark.parametrize("field_index", [0, 2])
def test_blank_required_semantic_fields_are_rejected_instead_of_fabricated(field_index):
    payload = _draft(4)
    payload["root"][field_index] = " "
    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))
    assert caught.value.rule == "blank_required"


def test_presentation_text_is_bounded_without_rejecting_valid_topology(caplog):
    payload = _draft(4)
    payload["composition"]["title"] = "t" * 101
    payload["components"][0][1] = "l" * 61
    payload["components"][0][3] = "r" * 221
    payload["components"][0][4] = "g" * 81
    payload["components"][0][6] = "p" * 101
    payload["connections"]["links"] = [[0, 2, "e" * 101, 401, 501]]

    with caplog.at_level("INFO"):
        draft = validate_applied_graph_topology(
            payload,
            applied_graph_spec("production"),
        )

    assert draft["title"] == "t" * 100
    assert draft["nodes"][1]["label"] == "l" * 60
    assert draft["nodes"][1]["responsibility"] == "r" * 220
    assert draft["nodes"][1]["group"] == "g" * 80
    assert draft["edges"][0]["label"] == "p" * 100
    assert draft["edges"][-1]["label"] == "e" * 100
    assert "original_chars=221 limit=220" in caplog.text
    assert "r" * 221 not in caplog.text


def test_bounded_group_labels_cannot_merge_distinct_ownership_boundaries():
    payload = _draft(6)
    prefix = "g" * 80
    payload["root"][3] = prefix + " first"
    payload["root"][4] = 600
    payload["components"][0][4] = prefix + " second"
    payload["components"][0][5] = 600

    with pytest.raises(AppliedGraphSpecError) as caught:
        validate_applied_graph_topology(payload, applied_graph_spec("production"))

    assert caught.value.path == "components[0][4]"
    assert caught.value.rule == "bounded_identity_collision"


def test_bounded_presentation_text_prefers_a_word_boundary():
    payload = _draft(4)
    payload["components"][0][3] = "word " * 60

    draft = validate_applied_graph_topology(
        payload,
        applied_graph_spec("production"),
    )

    assert len(draft["nodes"][1]["responsibility"]) <= 220
    assert draft["nodes"][1]["responsibility"].endswith("word")


def test_enrichment_preserves_authored_groups_and_runtime_sequence():
    spec = applied_graph_spec("production")
    payload = _draft(14)
    payload["components"][1][0] = 0
    payload["composition"]["steps"] = [0, 1, 2, 3, 4, 5, 6, 7]
    graph = enrich_applied_graph_topology(
        validate_applied_graph_topology(payload, spec),
        spec=spec,
        architect_plan={"assumptions": ["The source API supports version reads."]},
    )
    assert [group["label"] for group in graph["groups"]] == [
        "Product runtime",
        "Data and model services",
        "Delivery controls",
        "Operations",
    ]
    assert {node_id for group in graph["groups"] for node_id in group["nodeIds"]} == {
        f"n{index}" for index in range(1, 15)
    }
    parallel_step = graph["sequence"][1]
    assert parallel_step["nodes"] == ["n2", "n3"]
    assert [node_id for step in graph["sequence"] for node_id in step["nodes"]] == [
        "n1",
        "n2",
        "n3",
        "n4",
        "n5",
        "n6",
        "n7",
        "n8",
    ]
    assert graph["assumptions"] == ["The source API supports version reads."]


def test_worst_case_topology_serialization_is_bounded_by_resource_ceiling():
    spec = applied_graph_spec("production")
    legacy_nodes = [
        {
            "label": "l" * spec.node_label_chars,
            "type": "datastore",
            "tier": "private",
            "lane": "bottom",
            "responsibility": "r" * spec.responsibility_chars,
            "group": f"{index:02d}" + "g" * (spec.group_label_chars - 2),
            "group_kind": "operations",
            "parent_index": -1 if index == 0 else index - 1,
            "parent_label": "" if index == 0 else "e" * spec.edge_label_chars,
            "parent_flow": "deployment",
            "parent_sync": "async",
            "sequence_step": index,
        }
        for index in range(spec.safety_max_nodes)
    ]
    tree_edge_count = max(0, len(legacy_nodes) - 1)
    link_endpoints = [
        (source, target)
        for source in reversed(range(len(legacy_nodes)))
        for target in reversed(range(len(legacy_nodes)))
        if source != target and target != source + 1
    ][: max(0, spec.safety_max_edges - tree_edge_count)]
    legacy_links = [
        {
            "source_index": source,
            "target_index": target,
            "label": "e" * spec.edge_label_chars,
            "flow": "deployment",
            "sync": "async",
        }
        for source, target in link_endpoints
    ]
    legacy_payload = {
        "title": "t" * spec.title_chars,
        "nodes": legacy_nodes,
        "cross_links": legacy_links,
    }
    legacy_chars = len(
        json.dumps(legacy_payload, ensure_ascii=False, separators=(",", ":"))
    )
    topology_chars = worst_case_topology_chars(spec)
    assert topology_chars < 200_000
    assert topology_chars <= legacy_chars * 0.82


def test_provider_schema_stays_below_compact_byte_budget():
    schema = applied_graph_topology_schema(applied_graph_spec("production"))
    assert len(json.dumps(schema, separators=(",", ":"))) < 1_500


def test_prompt_delegates_graph_size_and_preserves_material_boundaries():
    from agent import applied_graph_spec as module

    prompt = applied_graph_topology_prompt(
        query="Build a RAG runtime",
        spec=applied_graph_spec("production"),
    )
    assert len(prompt) < 6_000
    assert "Choose the number of components and links from the design" in prompt
    spec = applied_graph_spec("production")
    assert f"at most {spec.safety_max_nodes} nodes including root" in prompt
    assert f"and {spec.safety_max_edges} total edges" in prompt
    assert f"components has at most {spec.safety_max_nodes - 1} rows" in prompt
    assert "components plus links must not exceed" in prompt
    assert "Preserve every material owner" in prompt
    assert "root: [label:string,type:integer" in prompt
    assert "components[i]: [parent_index:integer" in prompt
    assert "connections.links[i]: [source_index:integer" in prompt
    assert "group_label:string,group_kind:integer" in prompt
    assert "composition.groups" not in prompt
    assert "incoming_edge_label:string" in prompt
    assert "parent_index:integer,label:string,type:integer" in prompt
    assert "source_index:integer,target_index:integer" in prompt
    assert "flat array of integer node indexes" in prompt
    assert "Do not use null, booleans, objects, omitted tuple values" in prompt
    assert "Type: 100=client,101=service" in prompt
    assert "Group kind: 600=runtime,601=data" in prompt
    assert "The server owns stable IDs" in prompt
    assert "Every root and component row must carry its exact group label and kind" in prompt
    assert "At production depth, include every applicable control" in prompt
    assert "At prototype depth, use concrete buildable boundaries" in prompt
    assert "Do not add production hardening at low or prototype depth" in prompt
    assert "include a no-effect rejection outcome" in prompt
    assert (
        "distinct retry exhaustion, success, COMMITTED, NOT_FOUND, and STILL_UNKNOWN outcomes"
        in prompt
    )
    assert "distinct canary, promotion, and rollback paths" in prompt
    assert "Use integer codes for type, group_kind, flow, and sync" in prompt
    assert "The request owns the objective" in prompt
    assert "independent architecture review follows" in prompt
    assert "evidence_ref" not in prompt
    assert "Do not emit server-owned fields" in prompt
    assert "The server derives each lane from its authored group kind" in prompt
    for codebook in (
        module._NODE_TYPE_CODES,
        module._FLOW_CODES,
        module._SYNC_CODES,
        module._GROUP_KIND_CODES,
    ):
        for code, token in codebook.items():
            assert f"{code}={token}" in prompt
    assert "Every index is zero-based" in prompt
    assert "Root is index 0" in prompt
    assert "components[i] defines node index i+1" in prompt
    assert "an existing earlier node index from 0 through i" in prompt
    assert "components[5][0] may be 0 through 5; value 6 is self-reference" in prompt
    assert "composition.steps is one flat array" in prompt
    assert "Reuse the same label and kind for nodes in the same group" in prompt
    assert "Link endpoints and composition steps address nodes" in prompt
    assert "Never emit server node IDs" in prompt
    assert "$new_node_N placeholders" in prompt
    assert "declares primary runtime-sequence membership" in prompt
    assert (
        "server derives stage order from directed primary/runtime edges"
        in prompt
    )
    assert "inner batch" not in prompt
    assert "Nested batches" not in prompt
    assert "index_base" not in prompt
    assert "one-based" not in prompt
    assert "all material non-tree links" in prompt
    assert "Make the root the primary runtime entry or trigger" in prompt
    assert "Tree-edge direction and its incoming label must agree" in prompt
    assert "Production depth requires a primary sequence" in prompt
    assert "diagram authoring, rendering" in prompt
    assert "Multiple edges between the same pair" in prompt
    assert "A component earns a row" in prompt
    assert "An edge earns a record" in prompt
    assert "Return only compact schema-constrained JSON" in prompt
    assert (
        '"root":["Client",100,"Submits one request.","Product runtime",600]'
        in prompt
    )
    assert '"connections":{"links":[]}' in prompt
    assert '"steps":[0,1,2]' in prompt
    assert "diagram_commitments" not in prompt
    assert "diagram_requirements" not in prompt
    assert '"reviewed_plan"' not in prompt
    assert '"architect_plan"' not in prompt
    assert '"challenger_review"' not in prompt
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

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
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
    assert calls[0]["effort"] == "high"
    assert calls[0]["provider_attempt_limit"] == 1
    response_schema = calls[0]["response_schema"]
    spec = applied_graph_spec("production")
    assert (
        response_schema["properties"]["components"]["maxItems"]
        == spec.safety_max_nodes - 1
    )
    assert (
        response_schema["properties"]["connections"]["properties"]["links"]["maxItems"]
        == spec.safety_max_edges
    )


@pytest.mark.asyncio
async def test_dynamic_generator_logs_safe_parent_bounds(monkeypatch, caplog):
    import agent.nodes.graph_worker as graph_worker

    payload = _draft(7)
    payload["components"][5][0] = 6
    payload["components"][5][1] = "PRIVATE_SENTINEL"

    async def fake_stream_structured_llm(**_kwargs):
        return StructuredLLMResponse(
            text=json.dumps(payload),
            finish_reason="end_turn",
            input_tokens=100,
            output_tokens=500,
            provider="moonshot",
            model="kimi-k3",
        )

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )

    with caplog.at_level("WARNING", logger="agent.nodes.graph_worker"):
        with pytest.raises(AppliedGraphSpecError) as caught:
            await graph_worker._generate_applied_architecture(
                {
                    "graph_data": None,
                    "approved_graph_data": None,
                    "architecture_ready": True,
                },
                "Build a runtime",
                SimpleNamespace(resolved="prototype"),
            )

    assert caught.value.path == "components[5][0]"
    assert caught.value.observed_index == 6
    assert caught.value.maximum_index == 5
    assert "path=components[5][0] rule=topology" in caplog.text
    assert "observed_index=6 maximum_index=5" in caplog.text
    assert "PRIVATE_SENTINEL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "finish_reason", "code"),
    [
        ('{"title":', "max_tokens", "graph_design_output_truncated"),
        ('{"title":', "end_turn", "graph_design_schema_invalid"),
    ],
)
async def test_dynamic_generator_classifies_provider_truncation(
    monkeypatch, text, finish_reason, code
):
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

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
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
