import json
from dataclasses import replace

import pytest


def _relation(layer="concept", **overrides):
    from graph.schema import RelationSpec

    data = {
        "relation": "depends_on",
        "layer": layer,
        "definition": "source requires target",
        "allowed_source_kinds": ("method",),
        "allowed_target_kinds": ("component",),
        "positive_examples": ("RAG depends on retrieval",),
        "negative_examples": ("uses the same chapter",),
    }
    data.update(overrides)
    return RelationSpec(**data)


def _node(node_id="n1", *, layer="concept", kind="method"):
    return {
        "canonical_id": node_id,
        "layer": layer,
        "label": node_id.upper(),
        "aliases": [],
        "kind": kind,
        "description": "desc",
        "chapter_refs": [1],
        "source_chunk_ids": ["ai-eng:p1:pc1"],
        "confidence": 0.9,
    }


def _edge(edge_id="e1", source="n1", target="n2", relation="depends_on"):
    return {
        "edge_id": edge_id,
        "layer": "concept",
        "source_id": source,
        "target_id": target,
        "relation": relation,
        "supporting_chunk_ids": ["ai-eng:p1:pc1"],
        "support_spans": ["RAG depends on retrieval"],
        "confidence": 0.8,
    }


def _artifacts(**overrides):
    from graph.artifacts import CanonicalGraphArtifacts

    relation = _relation()
    data = {
        "concepts": {"n1": _node("n1", kind="method"), "n2": _node("n2", kind="component")},
        "architecture_nodes": {},
        "edges": {"e1": _edge()},
        "chunk_links": {
            "ai-eng:p1:pc1": {
                "parent_chunk_id": "ai-eng:p1:pc1",
                "canonical_node_ids": ["n1"],
                "canonical_edge_ids": ["e1"],
            }
        },
        "relations": {"depends_on": relation},
        "build_report": {},
    }
    data.update(overrides)
    return CanonicalGraphArtifacts(**data)


def test_graph_ids_raise_for_missing_metadata_and_fall_back_to_none():
    from graph.ids import child_chunk_id_from_metadata, parent_chunk_id_from_chunk, parent_chunk_id_from_metadata

    assert parent_chunk_id_from_metadata({"page_number": "2", "parent_chunk_index": "3"}) == "ai-eng:p2:pc3"
    assert child_chunk_id_from_metadata(
        {"page_number": 2, "parent_chunk_index": 3, "child_chunk_index": 4}
    ) == "ai-eng:p2:pc3:cc4"
    assert parent_chunk_id_from_chunk({"parent_chunk_id": 123}) == "123"
    assert parent_chunk_id_from_chunk({"page_number": 2}) is None
    with pytest.raises(ValueError, match="Missing chunk metadata"):
        parent_chunk_id_from_metadata({"page_number": 1})
    with pytest.raises(ValueError, match="Missing child_chunk_index"):
        child_chunk_id_from_metadata({"page_number": 1, "parent_chunk_index": 0})


def test_relation_spec_and_registry_validation_errors(tmp_path):
    from graph.schema import RelationSpec, load_relation_registry, relation_allowed, validate_relation_registry

    with pytest.raises(ValueError, match="missing required"):
        RelationSpec.from_dict({"relation": "x"})

    empty_registry = tmp_path / "relations.json"
    empty_registry.write_text(json.dumps({"relations": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="No relations"):
        load_relation_registry(empty_registry)

    with pytest.raises(ValueError, match="Registry key mismatch"):
        validate_relation_registry({"wrong": _relation()})
    with pytest.raises(ValueError, match="Invalid relation layer"):
        validate_relation_registry({"depends_on": replace(_relation(), layer="bogus")})
    with pytest.raises(ValueError, match="invalid kinds"):
        validate_relation_registry({"depends_on": replace(_relation(), allowed_source_kinds=("bogus",))})

    cross = _relation(
        "cross_layer",
        relation="implements",
        allowed_source_kinds=("method",),
        allowed_target_kinds=("service",),
    )
    with pytest.raises(ValueError, match="must declare allowed layers"):
        validate_relation_registry({"implements": cross})

    cross = replace(cross, allowed_source_layers=("concept",), allowed_target_layers=("architecture",))
    assert relation_allowed({"implements": cross}, "implements", "concept", "method", "architecture", "service")
    assert not relation_allowed({"implements": cross}, "implements", "concept", "method", "concept", "method")
    assert not relation_allowed({"implements": cross}, "missing", "concept", "method", "architecture", "service")


def test_relation_allowed_layer_and_negative_example_branches():
    from graph.schema import relation_allowed, violates_negative_example

    concept = _relation()
    architecture = _relation(
        "architecture",
        relation="calls",
        allowed_source_kinds=("service",),
        allowed_target_kinds=("datastore",),
    )
    registry = {"depends_on": concept, "calls": architecture}

    assert relation_allowed(registry, "depends_on", "concept", "method", "concept", "component")
    assert not relation_allowed(registry, "depends_on", "architecture", "method", "concept", "component")
    assert relation_allowed(registry, "calls", "architecture", "service", "architecture", "datastore")
    assert not relation_allowed(registry, "calls", "concept", "service", "architecture", "datastore")
    assert violates_negative_example(concept, "This only uses the same   chapter as support")


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda artifacts: _artifacts(concepts={"n1": {**_node("other"), "canonical_id": "other"}}), "Node ID mismatch"),
        (lambda artifacts: _artifacts(concepts={"n1": {**_node("n1"), "layer": "bad"}}), "Invalid node layer"),
        (lambda artifacts: _artifacts(concepts={"n1": {**_node("n1"), "source_chunk_ids": []}}), "has no source chunks"),
        (lambda artifacts: _artifacts(edges={"e1": {**_edge(), "edge_id": "other"}}), "Edge ID mismatch"),
        (lambda artifacts: _artifacts(edges={"e1": {**_edge(), "source_id": "missing"}}), "unknown endpoint"),
        (lambda artifacts: _artifacts(edges={"e1": {**_edge(), "relation": "missing"}}), "unregistered relation"),
        (
            lambda artifacts: _artifacts(edges={"e1": {**_edge(), "supporting_chunk_ids": []}}),
            "has no evidence",
        ),
        (
            lambda artifacts: _artifacts(chunk_links={"c": {"canonical_node_ids": ["missing"], "canonical_edge_ids": []}}),
            "links unknown node",
        ),
        (
            lambda artifacts: _artifacts(chunk_links={"c": {"canonical_node_ids": [], "canonical_edge_ids": ["missing"]}}),
            "links unknown edge",
        ),
    ],
)
def test_validate_graph_artifacts_rejects_invalid_artifacts(mutation, match):
    from graph.artifacts import validate_graph_artifacts

    with pytest.raises(ValueError, match=match):
        validate_graph_artifacts(mutation(_artifacts()))


def test_load_canonical_graph_and_private_json_helpers(tmp_path):
    from graph.artifacts import _by_id, _load_json, load_canonical_graph

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "concepts.json").write_text(json.dumps([_node("n1", kind="method"), _node("n2", kind="component")]), encoding="utf-8")
    (graph_dir / "architecture_nodes.json").write_text("[]", encoding="utf-8")
    (graph_dir / "edges.json").write_text(json.dumps([_edge()]), encoding="utf-8")
    (graph_dir / "chunk_links.json").write_text(
        json.dumps([{"parent_chunk_id": "ai-eng:p1:pc1", "canonical_node_ids": ["n1"], "canonical_edge_ids": ["e1"]}]),
        encoding="utf-8",
    )
    (graph_dir / "build_report.json").write_text("{}", encoding="utf-8")
    (graph_dir / "relations.json").write_text(
        json.dumps(
            {
                "relations": [
                    {
                        "relation": "depends_on",
                        "definition": "source requires target",
                        "allowed_source_kinds": ["method"],
                        "allowed_target_kinds": ["component"],
                        "positive_examples": ["RAG depends on retrieval"],
                        "negative_examples": ["same chapter"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    artifacts = load_canonical_graph(graph_dir)

    assert set(artifacts.nodes) == {"n1", "n2"}
    with pytest.raises(FileNotFoundError, match="Missing canonical graph artifact"):
        _load_json(graph_dir / "missing.json")
    with pytest.raises(ValueError, match="missing canonical_id"):
        _by_id([{}], "canonical_id")
    with pytest.raises(ValueError, match="Duplicate canonical graph ID"):
        _by_id([{"canonical_id": "x"}, {"canonical_id": "x"}], "canonical_id")
