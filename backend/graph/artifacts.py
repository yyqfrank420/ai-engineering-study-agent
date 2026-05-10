from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import settings
from graph.schema import (
    RelationSpec,
    load_relation_registry,
    relation_allowed,
    validate_relation_registry,
)


@dataclass(frozen=True)
class CanonicalGraphArtifacts:
    concepts: dict[str, dict[str, Any]]
    architecture_nodes: dict[str, dict[str, Any]]
    edges: dict[str, dict[str, Any]]
    chunk_links: dict[str, dict[str, list[str]]]
    relations: dict[str, RelationSpec]
    build_report: dict[str, Any]

    @property
    def nodes(self) -> dict[str, dict[str, Any]]:
        return {**self.concepts, **self.architecture_nodes}


def load_canonical_graph(graph_dir: str | Path | None = None) -> CanonicalGraphArtifacts:
    directory = Path(graph_dir) if graph_dir is not None else settings.graph_dir
    concepts = _load_json(directory / "concepts.json")
    architecture_nodes = _load_json(directory / "architecture_nodes.json")
    edges = _load_json(directory / "edges.json")
    chunk_links = _load_json(directory / "chunk_links.json")
    build_report = _load_json(directory / "build_report.json")
    relations = load_relation_registry(directory / "relations.json")
    validate_relation_registry(relations)

    artifacts = CanonicalGraphArtifacts(
        concepts=_by_id(concepts, "canonical_id"),
        architecture_nodes=_by_id(architecture_nodes, "canonical_id"),
        edges=_by_id(edges, "edge_id"),
        chunk_links=_by_id(chunk_links, "parent_chunk_id"),
        relations=relations,
        build_report=build_report,
    )
    validate_graph_artifacts(artifacts)
    return artifacts


@lru_cache(maxsize=1)
def load_canonical_graph_cached() -> CanonicalGraphArtifacts:
    return load_canonical_graph(settings.graph_dir)


def validate_graph_artifacts(artifacts: CanonicalGraphArtifacts) -> None:
    nodes = artifacts.nodes

    for canonical_id, node in nodes.items():
        missing = [
            key
            for key in (
                "canonical_id",
                "layer",
                "label",
                "aliases",
                "kind",
                "description",
                "chapter_refs",
                "source_chunk_ids",
                "confidence",
            )
            if key not in node
        ]
        if missing:
            raise ValueError(f"Node {canonical_id} missing fields: {missing}")
        if node["canonical_id"] != canonical_id:
            raise ValueError(f"Node ID mismatch for {canonical_id}")
        if node["layer"] not in {"concept", "architecture"}:
            raise ValueError(f"Invalid node layer for {canonical_id}: {node['layer']}")
        if not node["source_chunk_ids"]:
            raise ValueError(f"Node {canonical_id} has no source chunks")

    for edge_id, edge in artifacts.edges.items():
        missing = [
            key
            for key in (
                "edge_id",
                "layer",
                "source_id",
                "target_id",
                "relation",
                "supporting_chunk_ids",
                "support_spans",
                "confidence",
            )
            if key not in edge
        ]
        if missing:
            raise ValueError(f"Edge {edge_id} missing fields: {missing}")
        if edge["edge_id"] != edge_id:
            raise ValueError(f"Edge ID mismatch for {edge_id}")
        source = nodes.get(edge["source_id"])
        target = nodes.get(edge["target_id"])
        if not source or not target:
            raise ValueError(f"Edge {edge_id} references unknown endpoint")
        if edge["relation"] not in artifacts.relations:
            raise ValueError(f"Edge {edge_id} uses unregistered relation {edge['relation']}")
        if not relation_allowed(
            artifacts.relations,
            edge["relation"],
            source["layer"],
            source["kind"],
            target["layer"],
            target["kind"],
        ):
            raise ValueError(f"Edge {edge_id} violates relation registry")
        if not edge["supporting_chunk_ids"] or not edge["support_spans"]:
            raise ValueError(f"Edge {edge_id} has no evidence")

    known_edge_ids = set(artifacts.edges)
    known_node_ids = set(nodes)
    for chunk_id, link in artifacts.chunk_links.items():
        for node_id in link.get("canonical_node_ids", []):
            if node_id not in known_node_ids:
                raise ValueError(f"Chunk {chunk_id} links unknown node {node_id}")
        for edge_id in link.get("canonical_edge_ids", []):
            if edge_id not in known_edge_ids:
                raise ValueError(f"Chunk {chunk_id} links unknown edge {edge_id}")


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing canonical graph artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {}
    for item in items:
        item_id = item.get(key)
        if not item_id:
            raise ValueError(f"Artifact item missing {key}: {item}")
        if item_id in result:
            raise ValueError(f"Duplicate canonical graph ID {item_id}")
        result[item_id] = item
    return result
