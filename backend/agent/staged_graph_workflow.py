"""Request-scoped staged graph construction for applied architecture turns."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
import logging
import re
from typing import Any, Mapping

from analytics.events import enqueue_analytics_event
from agent.architecture_playbook import format_evidence_bundle
from agent.architecture_rubric import MAX_REVIEW_REASON_CHARS
from agent.complexity import resolve_complexity
from agent.deadlines import StageAdmissionDenied, staged_timeout_seconds
from agent.nodes.graph_critic import graph_render_gate_node
from agent.nodes.graph_worker import (
    _attach_graph_version,
    _patch_edge_id,
    admit_staged_graph_edit,
    sequence_after_node_removal,
    staged_edit_scope,
)
from agent.nodes.staged_graph_gate import (
    COMPONENT_RULE_CODES,
    CONNECTION_RULE_CODES,
    review_components,
    review_connections,
    review_identity,
)
from agent.nodes.staged_graph_generation import (
    FLOW_CODES,
    GROUP_KIND_CODES,
    NODE_TYPE_CODES,
    SYNC_CODES,
    StagedGenerationError,
    create_write_set,
    exact_edit_write_set,
    generate_component_candidate,
    generate_connection_candidate,
)
from agent.staged_graph_contract import (
    GraphContractError,
    assign_server_ids,
    component_fingerprint,
    connection_fingerprint,
    production_proofs_for_capabilities,
    project_graph_data,
    reconstruct_staged_graph_build,
    validate_component_write_set,
    validate_staged_graph_build,
)
from agent.state import AgentState, GraphData
from config import (
    STAGED_COMPONENT_GENERATION_CALLS,
    STAGED_CONNECTION_GENERATION_CALLS,
    settings,
)


_EXPLICIT_GRAPH_REBUILD = re.compile(
    r"\b(?:rebuild|redesign|replace|redraw)\s+(?:the\s+)?"
    r"(?:(?:entire|whole)\s+)?(?:architecture|diagram|graph|system)\b|"
    r"\b(?:start\s+over|from\s+scratch)\b",
    re.IGNORECASE,
)
_SAFE_FAILURE_TOKEN = re.compile(r"[a-zA-Z0-9_.:-]{1,96}")
logger = logging.getLogger(__name__)


def should_use_staged_graph_pipeline(state: Mapping[str, Any]) -> bool:
    return bool(
        settings.graph_pipeline_mode == "staged"
        and state.get("is_applied_design")
        and state.get("graph_intent") in {"create", "edit"}
        and state.get("graph_mode", "auto") != "off"
    )


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _maturity(state: AgentState) -> tuple[str, bool]:
    requested = str(state.get("complexity") or "auto")
    graph = state.get("approved_graph_data") or state.get("graph_data") or {}
    contract = state.get("approved_graph_contract") or state.get("graph_contract") or {}
    stored = contract.get("maturity") if isinstance(contract, Mapping) else None
    if stored not in {"prototype", "production"}:
        stored = graph.get("resolved_complexity")
    if stored not in {"prototype", "production"}:
        stored = "prototype"

    if state.get("graph_intent") == "edit" and requested == "auto":
        return str(stored), False
    resolved = resolve_complexity(
        requested,
        str(state.get("design_query") or state.get("user_message") or ""),
    ).resolved
    maturity = "production" if resolved == "production" else "prototype"
    return maturity, bool(
        state.get("graph_intent") == "edit"
        and requested != "auto"
        and maturity != stored
    )


def _safe_finding(exc: Exception, *, stage: str) -> dict[str, str]:
    path = getattr(exc, "path", None) or stage
    safe_path = _safe_path(path, fallback=stage)
    code = exc.code if isinstance(exc, StagedGenerationError) else "invalid_contract"
    reason = " ".join(str(exc).split())[:280]
    return {
        "code": code,
        "path": safe_path[:96],
        "rule": "contract_validation",
        **({"reason": reason} if reason else {}),
    }


def _safe_path(value: Any, *, fallback: str) -> str:
    path = re.sub(r"[^a-zA-Z0-9_.:-]+", ".", str(value))
    return re.sub(r"\.+", ".", path).strip(".") or fallback


def _failure_diagnostic(
    exc: Exception,
    *,
    stage: str,
    attempt: int,
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw_path = getattr(exc, "path", None) or stage
    path = _safe_path(raw_path, fallback=stage)
    if isinstance(exc, StagedGenerationError):
        code = (
            exc.code
            if _SAFE_FAILURE_TOKEN.fullmatch(exc.code)
            else "generation_rejected"
        )
    elif isinstance(exc, GraphContractError):
        code = (
            "candidate_repeated"
            if str(exc) == "correction repeated the prior candidate"
            else "contract_rejected"
        )
    else:
        code = "candidate_rejected"
    return {
        "schema_version": 1,
        "kind": "staged_generation",
        "stage": stage,
        "attempt": attempt,
        "code": code,
        "path": path[:96],
        "path_fingerprint": _fingerprint(path),
        "candidate_fingerprint": _fingerprint(candidate or {}),
        "fingerprint_disposition": (
            "matches_prior_candidate"
            if code == "candidate_repeated"
            else "rejected_before_render"
        ),
    }


def _gate_findings(
    findings: list[dict[str, Any]], *, stage: str
) -> list[dict[str, Any]]:
    return [
        {
            "code": str(finding.get("rule_code") or "semantic_rejection")[:96],
            "path": stage,
            "rule": "semantic_gate",
            **(
                {"reason": finding["reason"][:MAX_REVIEW_REASON_CHARS]}
                if isinstance(finding.get("reason"), str)
                else {}
            ),
            **(
                {"record_indexes": list(finding["record_indexes"])}
                if isinstance(finding.get("record_indexes"), list)
                else {}
            ),
        }
        for finding in findings
    ]


def _gate_failure_diagnostic(
    findings: list[dict[str, Any]],
    *,
    stage: str,
    attempt: int,
    code: str,
    candidate_records: list[dict[str, Any]],
) -> dict[str, Any]:
    rule_codes = (
        frozenset(COMPONENT_RULE_CODES)
        if stage == "components"
        else frozenset(CONNECTION_RULE_CODES)
    )
    record_count = len(candidate_records)
    gate_findings = []
    for finding in findings:
        if len(gate_findings) >= 24:
            break
        if not isinstance(finding, Mapping):
            continue
        rule_code = finding.get("rule_code")
        if not isinstance(rule_code, str) or rule_code not in rule_codes:
            continue
        paths = []
        seen_paths: set[str] = set()
        record_indexes = finding.get("record_indexes")
        if not isinstance(record_indexes, list):
            record_indexes = []
        for index in record_indexes:
            if (
                isinstance(index, int)
                and not isinstance(index, bool)
                and 0 <= index < record_count
            ):
                path = f"{stage}.{index}"
                if path not in seen_paths and len(paths) < 32:
                    paths.append(path)
                    seen_paths.add(path)
        if not paths:
            paths = [stage]
        gate_findings.append(
            {
                "rule_code": rule_code,
                "record_paths": paths,
            }
        )
    return {
        "schema_version": 1,
        "kind": "staged_gate",
        "stage": stage,
        "attempt": attempt,
        "code": code,
        "candidate_fingerprint": _fingerprint(candidate_records),
        "findings": gate_findings,
    }


def _decode_components(wire: Mapping[str, Any]) -> list[dict[str, Any]]:
    components = []
    for model_index, raw in enumerate(wire.get("components") or []):
        components.append(
            {
                "model_index": model_index,
                "label": raw["label"],
                "type": NODE_TYPE_CODES.get(raw["type"], ""),
                "responsibility": raw["responsibility"],
                "group_label": raw["group_label"],
                "group_kind": GROUP_KIND_CODES.get(raw["group_kind"], ""),
                "primary_flow_member": raw["primary_flow_member"],
            }
        )
    return components


def _decode_connections(wire: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": str(raw["source_index"]),
            "target_id": str(raw["target_index"]),
            "label": raw["label"],
            "flow": FLOW_CODES.get(raw["flow"], ""),
            "sync": SYNC_CODES.get(raw["sync"], ""),
        }
        for raw in wire.get("edges") or []
    ]


def _connection_prompt_base(build: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not build:
        return []
    index_by_id = {
        str(component["server_id"]): int(component["model_index"])
        for component in build.get("components") or []
        if component.get("server_id") is not None
    }
    flow_codes = {value: code for code, value in FLOW_CODES.items()}
    sync_codes = {value: code for code, value in SYNC_CODES.items()}
    prompt_edges = []
    for index, edge in enumerate(build.get("connections") or []):
        try:
            prompt_edges.append(
                {
                    "source_index": index_by_id[str(edge["source_id"])],
                    "target_index": index_by_id[str(edge["target_id"])],
                    "label": edge["label"],
                    "flow": flow_codes[edge["flow"]],
                    "sync": sync_codes[edge["sync"]],
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphContractError(
                "cannot project a prior connection into model indexes",
                path=f"connections[{index}]",
            ) from exc
    return prompt_edges


def _retain_component_ids(
    components: list[dict[str, Any]],
    base_build: Mapping[str, Any] | None,
    permissions: Mapping[str, Any] | None,
) -> None:
    if not base_build:
        return
    base_components = list(base_build.get("components") or [])
    removable = set((permissions or {}).get("removable_node_ids") or [])
    if permissions is not None:
        # Scoped generation assembles retained base rows before authorized additions.
        retained = [
            component
            for component in base_components
            if component["server_id"] not in removable
        ]
        for component, prior in zip(components, retained):
            component["server_id"] = prior["server_id"]
        named_ids = permissions.get("allowed_new_node_ids")
        if named_ids is not None:
            if not isinstance(named_ids, list) or any(
                not isinstance(node_id, str)
                or not node_id
                or node_id != node_id.strip()
                or len(node_id) > 80
                for node_id in named_ids
            ):
                raise GraphContractError(
                    "named additions require exact bounded IDs",
                    path="components.server_id",
                )
            additions = components[len(retained) :]
            count = permissions.get("allowed_new_node_count", 0)
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                or len(named_ids) != count
                or len(additions) != count
            ):
                raise GraphContractError(
                    "named addition count does not match authority",
                    path="components.server_id",
                )
            if len(named_ids) != len(set(named_ids)) or set(named_ids).intersection(
                component["server_id"] for component in base_components
            ):
                raise GraphContractError(
                    "named addition IDs must be unique and new",
                    path="components.server_id",
                )
            # The scope compiler authorizes one named addition. Multiple names
            # need an explicit row-to-ID contract before they can be assigned.
            if len(named_ids) > 1:
                raise GraphContractError(
                    "multiple named additions have no identity mapping",
                    path="components.server_id",
                )
            if named_ids:
                additions[0]["server_id"] = named_ids[0]
        return
    available = {
        str(component.get("server_id")): component
        for component in base_components
        if component.get("server_id") and component.get("server_id") not in removable
    }
    for component in components:
        exact = next(
            (
                node_id
                for node_id, prior in available.items()
                if prior.get("label") == component.get("label")
                and prior.get("type") == component.get("type")
            ),
            None,
        )
        if exact:
            component["server_id"] = exact
            available.pop(exact)


def _apply_scoped_addition_defaults(
    components: list[dict[str, Any]],
    base_build: Mapping[str, Any] | None,
    repair_contract: Mapping[str, Any] | None,
    permissions: Mapping[str, Any] | None,
) -> None:
    if not base_build or not permissions:
        return
    prior_ids = {
        str(component.get("server_id"))
        for component in base_build.get("components") or []
        if component.get("server_id")
    }
    additions = [
        component
        for component in components
        if str(component.get("server_id") or "") not in prior_ids
    ]
    if not additions:
        return
    for component in additions:
        component["primary_flow_member"] = False

    composition = ((repair_contract or {}).get("layers") or {}).get("composition") or {}
    group_ids = composition.get("group_ids") or []
    base_graph = base_build.get("base_graph") or {}
    groups = {
        str(group.get("id")): group
        for group in base_graph.get("groups") or []
        if isinstance(group, Mapping) and group.get("id")
    }
    if len(group_ids) != 1 or group_ids[0] not in groups:
        return
    group = groups[group_ids[0]]
    for component in additions:
        component["group_label"] = group["label"]
        component["group_kind"] = group.get("kind", "runtime")


def _component_preview(build: Mapping[str, Any]) -> GraphData:
    used_group_ids: set[str] = set()
    existing_groups = {
        (str(group.get("label")), str(group.get("kind") or "runtime")): str(
            group.get("id")
        )
        for group in ((build.get("base_graph") or {}).get("groups") or [])
        if isinstance(group, Mapping) and group.get("id") and group.get("label")
    }
    groups_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    nodes = []
    for component in build["components"]:
        node_id = component["server_id"]
        key = (component["group_label"], component["group_kind"])
        group = groups_by_key.get(key)
        if group is None:
            group_id = existing_groups.get(key) or re.sub(
                r"[^a-z0-9]+", "_", f"group_{key[0]}".lower()
            ).strip("_")
            base_id = group_id or "group"
            suffix = 2
            while group_id in used_group_ids:
                group_id = f"{base_id}_{suffix}"
                suffix += 1
            used_group_ids.add(group_id)
            group = {
                "id": group_id,
                "label": key[0],
                "kind": key[1],
                "nodeIds": [],
            }
            groups_by_key[key] = group
        group["nodeIds"].append(node_id)
        nodes.append(
            {
                "id": node_id,
                "label": component["label"],
                "type": component["type"],
                "technology": "Pending connection contract",
                "description": component["responsibility"],
                "tier": None,
                "lane": "bottom" if component["group_kind"] == "operations" else "main",
                "detail": None,
                "layer": "architecture",
                "design_origin": "applied",
            }
        )
    root_id = next(
        component["server_id"]
        for component in build["components"]
        if component["model_index"] == build["root_index"]
    )
    graph: GraphData = {
        "graph_type": "architecture",
        "title": build["title"],
        "nodes": nodes,
        "edges": [],
        "sequence": [{"step": 1, "nodes": [root_id], "description": "Primary entry"}],
        "groups": list(groups_by_key.values()),
        "design_origin": "applied",
        "resolved_complexity": build["maturity"],
        "assumptions": list(build["assumptions"]),
    }
    return _attach_graph_version(graph) or graph


def _contract(
    build: Mapping[str, Any],
    graph: Mapping[str, Any],
    *,
    component_gate: Mapping[str, Any],
    connection_gate: Mapping[str, Any],
    objective: str,
) -> dict[str, Any]:
    root = next(
        component["server_id"]
        for component in build["components"]
        if component["model_index"] == build["root_index"]
    )
    contract = {
        "schema_version": 1,
        "graph_version": graph["version"],
        "maturity": build["maturity"],
        "source": "staged",
        "stage": "accepted",
        "request_id": build["request_id"],
        "root_node_id": root,
        "capabilities": copy.deepcopy(build["capabilities"]),
        "component_fingerprint": component_fingerprint(build),
        "connection_fingerprint": connection_fingerprint(build),
        "groups": copy.deepcopy(graph.get("groups") or []),
        "component_gate": copy.deepcopy(dict(component_gate)),
        "connection_gate": copy.deepcopy(dict(connection_gate)),
        "objective": objective,
    }
    contract["reviewed_graph_fingerprint"] = _reviewed_graph_fingerprint(
        graph, contract
    )
    return contract


def _reviewed_graph_fingerprint(
    graph: Mapping[str, Any], contract: Mapping[str, Any]
) -> str:
    # View state is client-writable presentation. Every other stored graph field
    # and the semantic contract context must match the graph that was approved.
    return _fingerprint(
        {
            "graph": {
                key: value
                for key, value in graph.items()
                if key not in {"version", "view_state"}
            },
            "context": {
                key: contract.get(key)
                for key in ("maturity", "capabilities", "root_node_id", "objective")
            },
        }
    )


def _review_context(build: Mapping[str, Any]) -> dict[str, Any]:
    root_id = next(
        row["server_id"]
        for row in build["components"]
        if row["model_index"] == build["root_index"]
    )
    return {
        "title": build["title"],
        "assumptions": build["assumptions"],
        "capabilities": build["capabilities"],
        "maturity": build["maturity"],
        "root_node_id": root_id,
    }


def _has_current_approval(
    graph: Mapping[str, Any], contract: Mapping[str, Any], base: Mapping[str, Any]
) -> bool:
    if (
        contract.get("schema_version") != 1
        or contract.get("source") != "staged"
        or contract.get("stage") != "accepted"
        or not graph.get("version")
        or contract.get("graph_version") != graph["version"]
        or contract.get("reviewed_graph_fingerprint")
        != _reviewed_graph_fingerprint(graph, contract)
    ):
        return False
    guarantees = production_proofs_for_capabilities(
        base["capabilities"], maturity=base["maturity"]
    )
    for stage, key, required in (
        ("components", "component_gate", ()),
        ("connections", "connection_gate", guarantees),
    ):
        gate = contract.get(key)
        if (
            not isinstance(gate, Mapping)
            or gate.get("approved") is not True
            or gate.get("terminal") is not False
            or gate.get("findings") != []
            or gate.get("review_identity")
            != review_identity(stage, base["maturity"], required)
        ):
            return False
    return True


def _edit_review_scope(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    graph: Mapping[str, Any],
    contract: Mapping[str, Any],
    permissions: Mapping[str, Any],
) -> dict[str, Any]:
    before = {
        row["server_id"]: {
            key: value for key, value in row.items() if key != "model_index"
        }
        for row in base["components"]
    }
    after = {
        row["server_id"]: {
            key: value for key, value in row.items() if key != "model_index"
        }
        for row in candidate["components"]
    }
    changed_ids = {key for key, row in after.items() if before.get(key) != row}
    removed_ids = before.keys() - after.keys()
    prior_edges = {_fingerprint(row) for row in base["connections"]}
    current_edges = {_fingerprint(row) for row in candidate["connections"]}
    changed_indexes = [
        index
        for index, row in enumerate(candidate["connections"])
        if _fingerprint(row) not in prior_edges
    ]
    removed_edges = [
        row for row in base["connections"] if _fingerprint(row) not in current_edges
    ]
    changed_edges = [
        candidate["connections"][index] for index in changed_indexes
    ] + removed_edges
    affected_ids = (
        changed_ids
        | removed_ids
        | {row[key] for row in changed_edges for key in ("source_id", "target_id")}
    )
    neighbors = {
        row[key]
        for row in [*base["connections"], *candidate["connections"]]
        if affected_ids.intersection((row["source_id"], row["target_id"]))
        for key in ("source_id", "target_id")
    }
    baseline_context = _review_context(base)
    return {
        "kind": "scoped_edit",
        "trusted_baseline": (
            baseline_context == _review_context(candidate)
            and _has_current_approval(graph, contract, base)
        ),
        "baseline_objective": contract.get("objective") or base["title"],
        "baseline_context": baseline_context,
        "baseline_components": list(before.values()),
        "baseline_connections": base["connections"],
        "changed_component_ids": sorted(changed_ids),
        "removed_component_ids": sorted(removed_ids),
        "changed_connection_indexes": changed_indexes,
        "removed_connections": removed_edges,
        "affected_component_ids": sorted(affected_ids | neighbors),
        "edit_permissions": dict(permissions),
    }


def _preserve_existing_presentation(
    candidate: GraphData,
    existing: Mapping[str, Any] | None,
    *,
    edit_permissions: Mapping[str, Any] | None = None,
) -> GraphData:
    if not existing:
        return candidate
    preserved = copy.deepcopy(candidate)
    existing_nodes = {
        str(node.get("id")): node
        for node in existing.get("nodes") or []
        if isinstance(node, Mapping) and node.get("id")
    }
    for node in preserved.get("nodes") or []:
        prior = existing_nodes.get(str(node.get("id")))
        if prior is None:
            continue
        editable_fields = set(
            ((edit_permissions or {}).get("editable_node_fields") or {}).get(
                str(node.get("id")), []
            )
        )
        for field in ("technology", "tier", "detail", "layer"):
            if field in prior and field not in editable_fields:
                node[field] = copy.deepcopy(prior[field])
    semantic_fields = ("source", "target", "label", "sync", "flow")
    indexed_edges = [
        (_patch_edge_id(index), edge)
        for index, edge in enumerate(existing.get("edges") or [])
    ]
    prior_edges = {
        tuple(edge.get(field) for field in semantic_fields): (edge_id, edge)
        for edge_id, edge in indexed_edges
        if isinstance(edge, Mapping)
    }
    removable = set((edit_permissions or {}).get("removable_edge_ids") or [])
    retained_edges = [item for item in indexed_edges if item[0] not in removable]
    editable_edge_fields = (edit_permissions or {}).get("editable_edge_fields") or {}
    for index, edge in enumerate(preserved.get("edges") or []):
        matched = prior_edges.get(tuple(edge.get(field) for field in semantic_fields))
        if (
            matched is None
            and edit_permissions is not None
            and index < len(retained_edges)
        ):
            edge_id, prior = retained_edges[index]
            allowed = set(editable_edge_fields.get(edge_id, []))
            # Scoped delta assembly keeps retained base rows in order. Verify
            # that only authorized semantic fields changed before using the slot.
            if isinstance(prior, Mapping) and all(
                field in allowed or edge.get(field) == prior.get(field)
                for field in semantic_fields
            ):
                matched = (edge_id, prior)
        if matched is None:
            continue
        edge_id, prior = matched
        editable_fields = set(editable_edge_fields.get(edge_id, []))
        for field in ("technology", "description", "type", "edge_id", "relation"):
            if field in prior and field not in editable_fields:
                edge[field] = copy.deepcopy(prior[field])
    if edit_permissions is not None:
        removed_node_ids = set(edit_permissions.get("removable_node_ids") or [])
        if removed_node_ids:
            preserved["sequence"] = sequence_after_node_removal(
                existing.get("sequence") or [], removed_node_ids
            )
        elif "sequence" not in (
            edit_permissions.get("editable_composition_fields") or []
        ):
            preserved["sequence"] = copy.deepcopy(existing.get("sequence") or [])
    if "view_state" in existing:
        preserved["view_state"] = copy.deepcopy(existing["view_state"])
    return preserved


async def _render(
    state: AgentState,
    graph: GraphData,
    *,
    preview_count: int,
) -> AgentState:
    return await graph_render_gate_node(
        {
            **state,
            "graph_data": graph,
            "graph_changed": True,
            "graph_publication": "unreviewed",
            "graph_stage_preview_count": preview_count,
        }
    )


def _may_emit_staged_diagnostics(state: AgentState) -> bool:
    email = str(state.get("user_email") or "").strip().lower()
    return email in settings.internal_test_email_allowlist


async def _retain_staged_diagnostic(
    state: AgentState,
    diagnostic: Mapping[str, Any],
    *,
    emit_gate_progress: bool = False,
) -> AgentState:
    safe_diagnostic = copy.deepcopy(dict(diagnostic))
    diagnostics = [
        copy.deepcopy(item)
        for item in (state.get("graph_review_diagnostics") or [])
        if isinstance(item, dict)
    ]
    recorded = safe_diagnostic not in diagnostics
    if recorded:
        diagnostics.append(safe_diagnostic)
    retained_state: AgentState = {
        **state,
        "graph_review_diagnostics": diagnostics,
    }
    if (
        not emit_gate_progress
        or not recorded
        or not _may_emit_staged_diagnostics(state)
    ):
        return retained_state

    send = state.get("send")
    if callable(send):
        try:
            await send(
                {
                    "type": "workflow_progress",
                    "phase": "review",
                    "status": "retry",
                    "title": "Correcting staged graph candidate",
                    "detail": "The candidate failed one bounded admission check. One correction is running.",
                    "diagnostic": copy.deepcopy(safe_diagnostic),
                }
            )
        except Exception as exc:
            logger.info(
                "Staged gate progress event was not delivered: %s",
                type(exc).__name__,
            )
    return retained_state


async def _failed(
    state: AgentState,
    code: str,
    review: Mapping[str, Any] | None = None,
    *,
    diagnostic: Mapping[str, Any] | None = None,
    revision_instruction: str | None = None,
) -> AgentState:
    if diagnostic:
        state = await _retain_staged_diagnostic(state, diagnostic)
    approved_graph = copy.deepcopy(state.get("approved_graph_data"))
    approved_contract = copy.deepcopy(state.get("approved_graph_contract"))
    intent = state.get("graph_intent")
    operation = state.get("graph_operation") or {
        "kind": intent if intent in {"create", "edit"} else "create",
        "status": "candidate",
        "failure_code": None,
    }
    safe_diagnostic = copy.deepcopy(dict(diagnostic)) if diagnostic else None
    if safe_diagnostic is not None:
        enqueue_analytics_event(
            event_name="staged_graph_failure",
            event_category="graph",
            user_id=state.get("user_id"),
            session_id=state.get("session_id"),
            thread_id=state.get("thread_id") or state.get("session_id"),
            request_id=state.get("request_id"),
            client_request_id=state.get("client_request_id"),
            properties={
                key: value for key, value in safe_diagnostic.items() if key != "path"
            },
        )
        progress_event: dict[str, Any] = {
            "type": "workflow_progress",
            "phase": "review",
            "status": "rejected",
            "failure_code": code,
            "title": "Staged graph candidate rejected",
            "detail": "The candidate failed a bounded staged admission check and remains unpublished.",
        }
        if _may_emit_staged_diagnostics(state):
            progress_event["diagnostic"] = safe_diagnostic
        send = state.get("send")
        if callable(send):
            try:
                await send(progress_event)
            except Exception as exc:
                logger.info(
                    "Staged failure progress event was not delivered: %s",
                    type(exc).__name__,
                )
    result: AgentState = {
        **state,
        "graph_data": approved_graph,
        "approved_graph_data": copy.deepcopy(approved_graph),
        "graph_contract": approved_contract,
        "approved_graph_contract": copy.deepcopy(approved_contract),
        "graph_changed": False,
        "graph_publication": "preserved" if approved_graph else "withheld",
        "graph_operation": {**operation, "status": "failed", "failure_code": code},
        "graph_review": {
            "approved": False,
            "terminal": True,
            "failure_code": code,
            **({"staged_gate": copy.deepcopy(dict(review))} if review else {}),
            **({"staged_failure": safe_diagnostic} if safe_diagnostic else {}),
            **(
                {"revision_instruction": revision_instruction}
                if revision_instruction
                else {}
            ),
        },
    }
    return result


async def run_staged_graph_pipeline(state: AgentState) -> AgentState:
    """Build, render, and review one applied graph with one retry per layer."""
    state = {**state, "clarification_questions": []}
    send = state.get("send")
    if callable(send):
        try:
            await send(
                {
                    "type": "worker_status",
                    "worker": "graph",
                    "status": "Preparing the graph.",
                }
            )
        except Exception as exc:
            logger.info(
                "Staged graph worker status was not delivered: %s",
                type(exc).__name__,
            )
    maturity, maturity_changed = _maturity(state)
    request = str(state.get("design_query") or state.get("user_message") or "")
    raw_request = str(state.get("user_message") or "")
    approved_graph = state.get("approved_graph_data") or state.get("graph_data")
    approved_contract = state.get("approved_graph_contract") or state.get(
        "graph_contract"
    )
    base_build: dict[str, Any] | None = None
    repair_contract: dict[str, Any] | None = None
    permissions: dict[str, Any] | None = None
    if state.get("graph_intent") == "edit" and isinstance(approved_graph, Mapping):
        state = {
            **state,
            "approved_graph_data": copy.deepcopy(dict(approved_graph)),
            "approved_graph_contract": copy.deepcopy(approved_contract),
        }
        try:
            base_build = reconstruct_staged_graph_build(
                approved_graph,
                approved_contract if isinstance(approved_contract, Mapping) else None,
                request_id=str(state.get("request_id") or "staged"),
            )
        except GraphContractError:
            approved_contract = None
            state = {
                **state,
                "approved_graph_data": copy.deepcopy(dict(approved_graph)),
                "approved_graph_contract": None,
                "graph_contract": None,
            }
            maturity, maturity_changed = _maturity(state)
            try:
                base_build = reconstruct_staged_graph_build(
                    approved_graph,
                    None,
                    request_id=str(state.get("request_id") or "staged"),
                )
            except GraphContractError:
                return await _failed(state, "staged_base_graph_invalid")
        try:
            repair_contract, permissions = staged_edit_scope(
                raw_request,
                approved_graph,
                resolved_complexity=maturity,
            )
        except ValueError:
            if not _EXPLICIT_GRAPH_REBUILD.search(raw_request):
                return await _failed(
                    state,
                    "staged_edit_scope_ambiguous",
                    revision_instruction=(
                        "Identify the component or connection by its exact label or ID, "
                        "then repeat the edit."
                    ),
                )
        if permissions is not None and maturity_changed:
            return await _failed(
                state,
                "staged_edit_maturity_conflict",
                revision_instruction=(
                    "Keep this edit at the current maturity by selecting auto, "
                    f"or explicitly request a rebuild of the graph at {maturity} maturity."
                ),
            )

    component_capacity = settings.graph_safety_max_nodes
    edge_capacity = settings.graph_safety_max_edges
    if base_build is not None and permissions is not None:
        component_capacity = (
            len(base_build["components"])
            + int(permissions.get("allowed_new_node_count", 0))
            - len(permissions.get("removable_node_ids") or [])
        )
        edge_capacity = (
            len(base_build["connections"])
            + int(permissions.get("allowed_new_edge_count", 0))
            - len(permissions.get("removable_edge_ids") or [])
        )
        generation_write_set = exact_edit_write_set(
            component_ids=[f"component_{index}" for index in range(component_capacity)],
            edge_ids=[f"edge_{index}" for index in range(edge_capacity)],
        )
    else:
        generation_write_set = create_write_set(
            component_limit=component_capacity,
            edge_limit=edge_capacity,
        )

    architecture_context = format_evidence_bundle(state.get("evidence_bundle") or {})

    upstream_fingerprint = _fingerprint(
        {
            "request": request,
            "maturity": maturity,
            "architecture_context": architecture_context,
            "base_version": (approved_graph or {}).get("version")
            if isinstance(approved_graph, Mapping)
            else None,
        }
    )
    write_set_fingerprint = _fingerprint(generation_write_set)
    component_build: dict[str, Any] | None = None
    component_gate: dict[str, Any] = {}
    previous_prompt: str | None = None
    previous_component_candidate: str | None = None
    previous_component_wire: str | None = None
    rejected_component_candidate: dict[str, Any] | None = None
    reviewed_component_records: list[dict[str, Any]] = []
    correction_findings: list[dict[str, str]] = []
    preview_count = int(state.get("graph_stage_preview_count", 0))
    working_state = state

    for attempt in range(STAGED_COMPONENT_GENERATION_CALLS):
        try:
            generated = await generate_component_candidate(
                request=request,
                resolved_maturity=maturity,
                architecture_context=architecture_context,
                write_set=generation_write_set,
                upstream_fingerprint=upstream_fingerprint,
                attempt=attempt,
                prior_prompt_fingerprint=previous_prompt,
                prior_write_set_fingerprint=(
                    write_set_fingerprint if attempt else None
                ),
                structural_findings=correction_findings,
                base_components=base_build,
                edit_permissions=permissions,
                rejected_candidate=rejected_component_candidate,
                state=state,
                timeout_seconds=staged_timeout_seconds(
                    {**working_state, "graph_stage_preview_count": preview_count},
                    phase="components",
                    action="generate",
                    attempt=attempt,
                ),
            )
            if "clarification_questions" in generated:
                if permissions is not None:
                    raise StagedGenerationError("edit_clarification_not_allowed")
                return {
                    **state,
                    "graph_data": copy.deepcopy(approved_graph),
                    "approved_graph_data": copy.deepcopy(approved_graph),
                    "graph_contract": copy.deepcopy(approved_contract),
                    "approved_graph_contract": copy.deepcopy(approved_contract),
                    "graph_changed": False,
                    "graph_publication": "unchanged" if approved_graph else "none",
                    "graph_operation": {
                        "kind": "create",
                        "status": "needs_clarification",
                        "failure_code": None,
                    },
                    "clarification_questions": copy.deepcopy(
                        generated["clarification_questions"]
                    ),
                }
            wire = generated["wire"]
            rejected_component_candidate = copy.deepcopy(wire)
            wire_fingerprint = _fingerprint(wire)
            if wire_fingerprint == previous_component_wire:
                raise GraphContractError(
                    "correction repeated the prior candidate",
                    path="components",
                )
            previous_component_wire = wire_fingerprint
            components = _decode_components(wire)
            _retain_component_ids(components, base_build, permissions)
            _apply_scoped_addition_defaults(
                components,
                base_build,
                repair_contract,
                permissions,
            )
            editable_composition = set(
                (
                    ((repair_contract or {}).get("layers") or {}).get("composition")
                    or {}
                ).get("composition_fields")
                or []
            )
            scoped_edit = base_build is not None and permissions is not None
            root_index = wire["root_index"]
            removable_node_ids = set(
                (permissions or {}).get("removable_node_ids") or []
            )
            if scoped_edit:
                root_id = next(
                    component["server_id"]
                    for component in base_build["components"]
                    if component["model_index"] == base_build["root_index"]
                )
                root_index = next(
                    (
                        component["model_index"]
                        for component in components
                        if component.get("server_id") == root_id
                    ),
                    None,
                )
                if root_index is None:
                    raise GraphContractError(
                        "must retain the scoped root component", path="root_index"
                    )
            candidate = {
                "request_id": str(state.get("request_id") or "staged"),
                "title": (
                    wire["title"]
                    if not scoped_edit or "title" in editable_composition
                    else base_build["title"]
                ),
                "assumptions": (
                    wire["assumptions"]
                    if not scoped_edit or "assumptions" in editable_composition
                    else copy.deepcopy(base_build["assumptions"])
                ),
                "root_index": root_index,
                "capabilities": copy.deepcopy(wire["capabilities"]),
                "components": components,
                "connections": [
                    copy.deepcopy(edge)
                    for edge in (base_build or {}).get("connections") or []
                    if not removable_node_ids.intersection(
                        (edge["source_id"], edge["target_id"])
                    )
                ],
                "maturity": maturity,
                "source": "staged",
                "stage": "components",
                "base_graph": copy.deepcopy(approved_graph),
                "graph_contract": copy.deepcopy(approved_contract or {}),
            }
            assigned = assign_server_ids(candidate)
            candidate_fingerprint = component_fingerprint(assigned)
            if candidate_fingerprint == previous_component_candidate:
                raise GraphContractError(
                    "correction repeated the prior candidate",
                    path="components",
                )
            if base_build is not None and permissions is not None:
                validate_component_write_set(
                    base_build,
                    assigned,
                    {
                        "allowed_ids": sorted(
                            set(permissions.get("editable_node_ids") or [])
                            | set(permissions.get("removable_node_ids") or [])
                        ),
                        "addition_count": int(
                            permissions.get("allowed_new_node_count", 0)
                        ),
                        "removal_count": len(
                            permissions.get("removable_node_ids") or []
                        ),
                        "incident_edge_ids": [
                            f"{edge['source']}|{edge['target']}|{edge['label'].casefold()}"
                            for edge in permissions.get("editable_edges") or []
                            if edge["edge_id"]
                            in permissions.get("removable_edge_ids", [])
                            and removable_node_ids.intersection(
                                (edge["source"], edge["target"])
                            )
                        ],
                    },
                )
            preview = _component_preview(assigned)
            rendered = await _render(
                working_state, preview, preview_count=preview_count
            )
            if not rendered.get("graph_render_admitted"):
                return await _failed(rendered, "staged_component_render_rejected")
            preview_count += 1
            component_evidence = {
                "architecture_context": architecture_context,
                "candidate_context": {
                    "title": assigned["title"],
                    "assumptions": assigned["assumptions"],
                    "root_index": assigned["root_index"],
                    "capabilities": assigned["capabilities"],
                },
            }
            if scoped_edit:
                component_evidence["review_scope"] = _edit_review_scope(
                    base_build,
                    assigned,
                    approved_graph,
                    approved_contract or {},
                    permissions,
                )
            reviewed_component_records = copy.deepcopy(assigned["components"])
            component_gate = await review_components(
                user_request=request,
                evidence_bundle=component_evidence,
                resolved_maturity=maturity,
                candidate_records=reviewed_component_records,
                telemetry_context={**state, "staged_attempt": attempt + 1},
                timeout_seconds=staged_timeout_seconds(
                    rendered, phase="components", action="review", attempt=attempt
                ),
            )
            if component_gate["approved"]:
                component_build = assigned
                working_state = rendered
                break
            if component_gate["terminal"]:
                return await _failed(
                    rendered,
                    "staged_component_gate_unavailable",
                    component_gate,
                    diagnostic=_gate_failure_diagnostic(
                        findings=component_gate.get("findings", [])
                        if isinstance(component_gate.get("findings"), list)
                        else [],
                        stage="components",
                        attempt=attempt + 1,
                        code="gate_unavailable",
                        candidate_records=reviewed_component_records,
                    ),
                )
            correction_findings = _gate_findings(
                component_gate["findings"], stage="components"
            )
            previous_prompt = generated["prompt_fingerprint"]
            previous_component_candidate = candidate_fingerprint
            if attempt + 1 < STAGED_COMPONENT_GENERATION_CALLS:
                working_state = await _retain_staged_diagnostic(
                    rendered,
                    _gate_failure_diagnostic(
                        findings=component_gate.get("findings", [])
                        if isinstance(component_gate.get("findings"), list)
                        else [],
                        stage="components",
                        attempt=attempt + 1,
                        code="gate_rejected",
                        candidate_records=reviewed_component_records,
                    ),
                    emit_gate_progress=True,
                )
            else:
                working_state = rendered
        except StageAdmissionDenied:
            return await _failed(
                working_state, "staged_component_deadline_admission_denied"
            )
        except (GraphContractError, StagedGenerationError, ValueError) as exc:
            if attempt + 1 >= STAGED_COMPONENT_GENERATION_CALLS:
                return await _failed(
                    working_state,
                    "staged_component_attempts_exhausted",
                    diagnostic=_failure_diagnostic(
                        exc,
                        stage="components",
                        attempt=attempt + 1,
                        candidate=rejected_component_candidate,
                    ),
                )
            working_state = await _retain_staged_diagnostic(
                working_state,
                _failure_diagnostic(
                    exc,
                    stage="components",
                    attempt=attempt + 1,
                    candidate=rejected_component_candidate,
                ),
                emit_gate_progress=True,
            )
            correction_findings = [_safe_finding(exc, stage="components")]
            previous_prompt = (
                exc.prompt_fingerprint
                if isinstance(exc, StagedGenerationError)
                else locals().get("generated", {}).get("prompt_fingerprint")
            )
            if not previous_prompt:
                return await _failed(
                    working_state, "staged_component_generation_unavailable"
                )
    if component_build is None:
        return await _failed(
            working_state,
            "staged_component_attempts_exhausted",
            review=component_gate,
            diagnostic=_gate_failure_diagnostic(
                findings=component_gate.get("findings", [])
                if isinstance(component_gate.get("findings"), list)
                else [],
                stage="components",
                attempt=STAGED_COMPONENT_GENERATION_CALLS,
                code="gate_rejected",
                candidate_records=reviewed_component_records,
            ),
        )

    accepted_component_fingerprint = component_fingerprint(component_build)
    previous_prompt = None
    previous_connection_candidate: str | None = None
    previous_connection_wire: str | None = None
    rejected_connection_candidate: dict[str, Any] | None = None
    reviewed_connection_records: list[dict[str, Any]] = []
    correction_findings = []
    connection_gate: dict[str, Any] = {}
    for attempt in range(STAGED_CONNECTION_GENERATION_CALLS):
        try:
            generated = await generate_connection_candidate(
                request=request,
                resolved_maturity=maturity,
                write_set=generation_write_set,
                upstream_fingerprint=accepted_component_fingerprint,
                accepted_components=[
                    {
                        "index": component["model_index"],
                        "id": component["server_id"],
                        "label": component["label"],
                        "type": next(
                            code
                            for code, value in NODE_TYPE_CODES.items()
                            if value == component["type"]
                        ),
                        "responsibility": component["responsibility"],
                        "primary_flow_member": component["primary_flow_member"],
                        "is_root": component["model_index"]
                        == component_build["root_index"],
                    }
                    for component in component_build["components"]
                ],
                accepted_context={
                    "assumptions": copy.deepcopy(component_build["assumptions"]),
                    "capabilities": copy.deepcopy(component_build["capabilities"]),
                },
                attempt=attempt,
                prior_prompt_fingerprint=previous_prompt,
                prior_write_set_fingerprint=(
                    write_set_fingerprint if attempt else None
                ),
                structural_findings=correction_findings,
                base_connections=_connection_prompt_base(component_build),
                edit_permissions=permissions,
                rejected_candidate=rejected_connection_candidate,
                state=state,
                timeout_seconds=staged_timeout_seconds(
                    working_state,
                    phase="connections",
                    action="generate",
                    attempt=attempt,
                ),
            )
            rejected_connection_candidate = copy.deepcopy(generated["wire"])
            wire_fingerprint = _fingerprint(generated["wire"])
            if wire_fingerprint == previous_connection_wire:
                raise GraphContractError(
                    "correction repeated the prior candidate",
                    path="connections",
                )
            previous_connection_wire = wire_fingerprint
            candidate_build = assign_server_ids(
                {
                    **component_build,
                    "connections": _decode_connections(generated["wire"]),
                    "stage": "connections",
                }
            )
            candidate_fingerprint = connection_fingerprint(candidate_build)
            if candidate_fingerprint == previous_connection_candidate:
                raise GraphContractError(
                    "correction repeated the prior candidate",
                    path="connections",
                )
            candidate_build = validate_staged_graph_build(candidate_build)
            projected = _attach_graph_version(project_graph_data(candidate_build))
            if projected is None:
                raise GraphContractError(
                    "projection returned no graph", path="graph_data"
                )
            projected = _preserve_existing_presentation(
                projected,
                approved_graph if isinstance(approved_graph, Mapping) else None,
                edit_permissions=permissions,
            )
            if (
                base_build is not None
                and repair_contract is not None
                and permissions is not None
                and isinstance(approved_graph, dict)
            ):
                projected = _attach_graph_version(
                    admit_staged_graph_edit(
                        approved_graph,
                        projected,
                        resolved_complexity=maturity,
                        repair_contract=repair_contract,
                        mutation_permissions=permissions,
                    )
                )
                if projected is None:
                    raise GraphContractError(
                        "edit admission returned no graph", path="graph_data"
                    )
            rendered = await _render(
                working_state, projected, preview_count=preview_count
            )
            if not rendered.get("graph_render_admitted"):
                return await _failed(rendered, "staged_connection_render_rejected")
            preview_count += 1
            evidence = copy.deepcopy(state.get("evidence_bundle") or {})
            evidence["candidate_components"] = [
                {
                    "id": component["server_id"],
                    "label": component["label"],
                    "type": component["type"],
                    "responsibility": component["responsibility"],
                }
                for component in candidate_build["components"]
            ]
            evidence["candidate_context"] = {
                "title": candidate_build["title"],
                "assumptions": copy.deepcopy(candidate_build["assumptions"]),
                "root_index": candidate_build["root_index"],
                "capabilities": copy.deepcopy(candidate_build["capabilities"]),
            }
            if base_build is not None and permissions is not None:
                evidence["review_scope"] = _edit_review_scope(
                    base_build,
                    candidate_build,
                    approved_graph,
                    approved_contract or {},
                    permissions,
                )
            reviewed_connection_records = [
                {
                    "source": edge["source_id"],
                    "target": edge["target_id"],
                    "label": edge["label"],
                    "flow": edge["flow"],
                    "sync": edge["sync"],
                }
                for edge in candidate_build["connections"]
            ]
            connection_gate = await review_connections(
                user_request=request,
                evidence_bundle=evidence,
                resolved_maturity=maturity,
                candidate_records=reviewed_connection_records,
                required_production_guarantees=production_proofs_for_capabilities(
                    candidate_build["capabilities"], maturity=maturity
                ),
                telemetry_context={**state, "staged_attempt": attempt + 1},
                timeout_seconds=staged_timeout_seconds(
                    rendered, phase="connections", action="review", attempt=attempt
                ),
            )
            if connection_gate["approved"]:
                graph_contract = _contract(
                    candidate_build,
                    projected,
                    component_gate=component_gate,
                    connection_gate=connection_gate,
                    objective=(
                        str(
                            (approved_contract or {}).get("objective")
                            or base_build["title"]
                        )
                        if base_build is not None and permissions is not None
                        else request
                    ),
                )
                operation = state.get("graph_operation") or {
                    "kind": state.get("graph_intent") or "create",
                    "status": "candidate",
                    "failure_code": None,
                }
                return {
                    **rendered,
                    "graph_data": projected,
                    "graph_contract": graph_contract,
                    "graph_changed": True,
                    "graph_publication": "approved",
                    "graph_operation": {
                        **operation,
                        "status": "applied",
                        "failure_code": None,
                    },
                    "graph_review": {
                        "approved": True,
                        "terminal": False,
                        "component_gate": component_gate,
                        "connection_gate": connection_gate,
                    },
                    "reviewed_graph_data": copy.deepcopy(projected),
                    "graph_stage_preview_count": preview_count,
                    "staged_graph_build": candidate_build,
                }
            if connection_gate["terminal"]:
                return await _failed(
                    rendered,
                    "staged_connection_gate_unavailable",
                    connection_gate,
                    diagnostic=_gate_failure_diagnostic(
                        findings=connection_gate.get("findings", [])
                        if isinstance(connection_gate.get("findings"), list)
                        else [],
                        stage="connections",
                        attempt=attempt + 1,
                        code="gate_unavailable",
                        candidate_records=reviewed_connection_records,
                    ),
                )
            correction_findings = _gate_findings(
                connection_gate["findings"], stage="connections"
            )
            previous_prompt = generated["prompt_fingerprint"]
            previous_connection_candidate = candidate_fingerprint
            if attempt + 1 < STAGED_CONNECTION_GENERATION_CALLS:
                working_state = await _retain_staged_diagnostic(
                    rendered,
                    _gate_failure_diagnostic(
                        findings=connection_gate.get("findings", [])
                        if isinstance(connection_gate.get("findings"), list)
                        else [],
                        stage="connections",
                        attempt=attempt + 1,
                        code="gate_rejected",
                        candidate_records=reviewed_connection_records,
                    ),
                    emit_gate_progress=True,
                )
            else:
                working_state = rendered
        except StageAdmissionDenied:
            return await _failed(
                working_state, "staged_connection_deadline_admission_denied"
            )
        except (GraphContractError, StagedGenerationError, ValueError) as exc:
            if attempt + 1 >= STAGED_CONNECTION_GENERATION_CALLS:
                return await _failed(
                    working_state,
                    "staged_connection_attempts_exhausted",
                    diagnostic=_failure_diagnostic(
                        exc,
                        stage="connections",
                        attempt=attempt + 1,
                        candidate=rejected_connection_candidate,
                    ),
                )
            working_state = await _retain_staged_diagnostic(
                working_state,
                _failure_diagnostic(
                    exc,
                    stage="connections",
                    attempt=attempt + 1,
                    candidate=rejected_connection_candidate,
                ),
                emit_gate_progress=True,
            )
            correction_findings = [_safe_finding(exc, stage="connections")]
            previous_prompt = (
                exc.prompt_fingerprint
                if isinstance(exc, StagedGenerationError)
                else locals().get("generated", {}).get("prompt_fingerprint")
            )
            if not previous_prompt:
                return await _failed(
                    working_state, "staged_connection_generation_unavailable"
                )
    return await _failed(
        working_state,
        "staged_connection_attempts_exhausted",
        review=connection_gate,
        diagnostic=_gate_failure_diagnostic(
            findings=connection_gate.get("findings", [])
            if isinstance(connection_gate.get("findings"), list)
            else [],
            stage="connections",
            attempt=STAGED_CONNECTION_GENERATION_CALLS,
            code="gate_rejected",
            candidate_records=reviewed_connection_records,
        ),
    )
