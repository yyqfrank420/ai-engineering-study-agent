from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import settings


CONCEPT_KINDS = {
    "method",
    "component",
    "control",
    "decision",
    "metric",
    "risk",
    "artifact",
    "objective",
}

ARCHITECTURE_KINDS = {
    "actor",
    "service",
    "datastore",
    "pipeline_stage",
    "control",
    "external",
}

CROSS_LAYER_RELATIONS = {"implements", "supports", "applies_to"}


@dataclass(frozen=True)
class RelationSpec:
    relation: str
    layer: str
    definition: str
    allowed_source_kinds: tuple[str, ...]
    allowed_target_kinds: tuple[str, ...]
    positive_examples: tuple[str, ...]
    negative_examples: tuple[str, ...]
    allowed_source_layers: tuple[str, ...] = ()
    allowed_target_layers: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationSpec":
        required = (
            "relation",
            "definition",
            "allowed_source_kinds",
            "allowed_target_kinds",
            "positive_examples",
            "negative_examples",
        )
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f"Relation spec missing required fields {missing}: {data}")
        layer = data.get("layer") or (
            "cross_layer" if data["relation"] in CROSS_LAYER_RELATIONS else "concept"
        )
        return cls(
            relation=data["relation"],
            layer=layer,
            definition=data["definition"],
            allowed_source_kinds=tuple(data["allowed_source_kinds"]),
            allowed_target_kinds=tuple(data["allowed_target_kinds"]),
            positive_examples=tuple(data["positive_examples"]),
            negative_examples=tuple(data["negative_examples"]),
            allowed_source_layers=tuple(data.get("allowed_source_layers", ())),
            allowed_target_layers=tuple(data.get("allowed_target_layers", ())),
        )


def relation_registry_path() -> Path:
    return settings.graph_schema_dir / "relations.json"


def load_relation_registry(path: Path | None = None) -> dict[str, RelationSpec]:
    registry_path = path or relation_registry_path()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    specs = [RelationSpec.from_dict(item) for item in payload.get("relations", [])]
    if not specs:
        raise ValueError(f"No relations found in {registry_path}")
    return {spec.relation: spec for spec in specs}


def validate_relation_registry(registry: dict[str, RelationSpec]) -> None:
    for relation, spec in registry.items():
        if relation != spec.relation:
            raise ValueError(f"Registry key mismatch for {relation}")
        if spec.layer not in {"concept", "architecture", "cross_layer"}:
            raise ValueError(f"Invalid relation layer for {relation}: {spec.layer}")
        if spec.layer == "concept":
            _validate_kinds(relation, spec.allowed_source_kinds, CONCEPT_KINDS)
            _validate_kinds(relation, spec.allowed_target_kinds, CONCEPT_KINDS)
        elif spec.layer == "architecture":
            _validate_kinds(relation, spec.allowed_source_kinds, ARCHITECTURE_KINDS)
            _validate_kinds(relation, spec.allowed_target_kinds, ARCHITECTURE_KINDS)
        else:
            if not spec.allowed_source_layers or not spec.allowed_target_layers:
                raise ValueError(f"Cross-layer relation {relation} must declare allowed layers")
            _validate_cross_kinds(relation, spec.allowed_source_kinds)
            _validate_cross_kinds(relation, spec.allowed_target_kinds)


def _validate_kinds(relation: str, kinds: tuple[str, ...], allowed: set[str]) -> None:
    invalid = set(kinds) - allowed
    if invalid:
        raise ValueError(f"{relation} declares invalid kinds: {sorted(invalid)}")


def _validate_cross_kinds(relation: str, kinds: tuple[str, ...]) -> None:
    invalid = set(kinds) - (CONCEPT_KINDS | ARCHITECTURE_KINDS)
    if invalid:
        raise ValueError(f"{relation} declares invalid cross-layer kinds: {sorted(invalid)}")


def relation_allowed(
    registry: dict[str, RelationSpec],
    relation: str,
    source_layer: str,
    source_kind: str,
    target_layer: str,
    target_kind: str,
) -> bool:
    spec = registry.get(relation)
    if spec is None:
        return False

    if spec.layer == "concept":
        if source_layer != "concept" or target_layer != "concept":
            return False
    elif spec.layer == "architecture":
        if source_layer != "architecture" or target_layer != "architecture":
            return False
    else:
        if source_layer == target_layer:
            return False
        if spec.allowed_source_layers and source_layer not in spec.allowed_source_layers:
            return False
        if spec.allowed_target_layers and target_layer not in spec.allowed_target_layers:
            return False

    return (
        source_kind in spec.allowed_source_kinds
        and target_kind in spec.allowed_target_kinds
    )


def violates_negative_example(spec: RelationSpec, text: str) -> bool:
    """Return True when a candidate's support directly matches a registry negative."""
    normalized_text = _normalize_example(text)
    return any(
        _normalize_example(example) in normalized_text
        for example in spec.negative_examples
    )


def _normalize_example(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
