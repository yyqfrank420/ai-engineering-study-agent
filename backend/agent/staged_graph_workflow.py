"""Request-scoped staged graph construction for applied architecture turns."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
import logging
import re
from typing import Any, Mapping

from analytics.events import enqueue_analytics_event
from agent.complexity import resolve_complexity
from agent.nodes.graph_critic import graph_render_gate_node
from agent.nodes.graph_worker import (
    _attach_graph_version,
    admit_staged_graph_edit,
    staged_edit_scope,
)
from agent.nodes.staged_graph_gate import review_components, review_connections
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
from config import settings


_MAX_STAGE_ATTEMPTS = 2
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
                {"reason": str(finding["reason"])[:280]}
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
    available = {
        str(component.get("server_id")): component
        for component in base_components
        if component.get("server_id") and component.get("server_id") not in removable
    }
    editable = set((permissions or {}).get("editable_node_ids") or []) - removable
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
    base_by_index = {
        int(component["model_index"]): str(component["server_id"])
        for component in base_components
        if isinstance(component.get("model_index"), int)
        and component.get("server_id") in available
    }
    for component in components:
        if "server_id" in component:
            continue
        prior_id = base_by_index.get(component["model_index"])
        if prior_id in editable and prior_id in available:
            component["server_id"] = prior_id
            available.pop(prior_id)
    unmatched = [component for component in components if "server_id" not in component]
    editable_available = sorted(editable & available.keys())
    if len(unmatched) == len(editable_available):
        for component, node_id in zip(unmatched, editable_available):
            component["server_id"] = node_id


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
) -> dict[str, Any]:
    root = next(
        component["server_id"]
        for component in build["components"]
        if component["model_index"] == build["root_index"]
    )
    return {
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
    }


def _preserve_existing_presentation(
    candidate: GraphData,
    existing: Mapping[str, Any] | None,
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
        for field in ("technology", "tier", "detail", "layer"):
            if field in prior:
                node[field] = copy.deepcopy(prior[field])
    prior_edges = list(existing.get("edges") or [])
    for index, edge in enumerate(preserved.get("edges") or []):
        if index >= len(prior_edges) or not isinstance(prior_edges[index], Mapping):
            continue
        prior = prior_edges[index]
        semantic_fields = ("source", "target", "label", "sync", "flow")
        if any(edge.get(field) != prior.get(field) for field in semantic_fields):
            continue
        for field in ("technology", "description", "type", "edge_id", "relation"):
            if field in prior:
                edge[field] = copy.deepcopy(prior[field])
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


async def _failed(
    state: AgentState,
    code: str,
    review: Mapping[str, Any] | None = None,
    *,
    diagnostic: Mapping[str, Any] | None = None,
) -> AgentState:
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
        email = str(state.get("user_email") or "").strip().lower()
        if email in settings.internal_test_email_allowlist:
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
        },
    }
    return result


async def run_staged_graph_pipeline(state: AgentState) -> AgentState:
    """Build, render, and review one applied graph with one retry per layer."""
    maturity, full_restage = _maturity(state)
    request = str(state.get("design_query") or state.get("user_message") or "")
    approved_graph = state.get("approved_graph_data") or state.get("graph_data")
    approved_contract = state.get("approved_graph_contract") or state.get(
        "graph_contract"
    )
    base_build: dict[str, Any] | None = None
    repair_contract: dict[str, Any] | None = None
    permissions: dict[str, Any] | None = None
    if state.get("graph_intent") == "edit" and isinstance(approved_graph, Mapping):
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
            maturity, full_restage = _maturity(state)
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
                request,
                approved_graph,
                resolved_complexity=maturity,
            )
        except ValueError:
            if not full_restage and re.search(
                r"\b(?:rebuild|redesign|replace|redraw|start\s+over)\b",
                request,
                re.IGNORECASE,
            ):
                full_restage = True
            if not full_restage:
                return await _failed(state, "staged_edit_scope_ambiguous")

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

    upstream_fingerprint = _fingerprint(
        {
            "request": request,
            "maturity": maturity,
            "evidence": state.get("evidence_bundle") or {},
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
    correction_findings: list[dict[str, str]] = []
    preview_count = int(state.get("graph_stage_preview_count", 0))
    working_state = state

    for attempt in range(_MAX_STAGE_ATTEMPTS):
        try:
            generated = await generate_component_candidate(
                request=request,
                resolved_maturity=maturity,
                write_set=generation_write_set,
                upstream_fingerprint=upstream_fingerprint,
                attempt=attempt,
                prior_prompt_fingerprint=previous_prompt,
                prior_write_set_fingerprint=(
                    write_set_fingerprint if attempt else None
                ),
                structural_findings=correction_findings,
                base_components=base_build,
                rejected_candidate=rejected_component_candidate,
                state=state,
                timeout_seconds=settings.staged_component_timeout_s,
            )
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
                "root_index": (
                    base_build["root_index"] if scoped_edit else wire["root_index"]
                ),
                "capabilities": (
                    copy.deepcopy(base_build["capabilities"])
                    if scoped_edit
                    else wire["capabilities"]
                ),
                "components": components,
                "connections": copy.deepcopy(
                    (base_build or {}).get("connections") or []
                ),
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
                        "incident_edge_ids": [],
                    },
                )
            preview = _component_preview(assigned)
            rendered = await _render(
                working_state, preview, preview_count=preview_count
            )
            if not rendered.get("graph_render_admitted"):
                return await _failed(rendered, "staged_component_render_rejected")
            preview_count += 1
            component_evidence = copy.deepcopy(state.get("evidence_bundle") or {})
            component_evidence["candidate_context"] = {
                "title": assigned["title"],
                "assumptions": assigned["assumptions"],
                "root_index": assigned["root_index"],
                "capabilities": assigned["capabilities"],
            }
            component_gate = await review_components(
                user_request=request,
                evidence_bundle=component_evidence,
                resolved_maturity=maturity,
                candidate_records=assigned["components"],
                telemetry_context=state,
            )
            if component_gate["approved"]:
                component_build = assigned
                working_state = rendered
                break
            if component_gate["terminal"]:
                return await _failed(
                    rendered, "staged_component_gate_unavailable", component_gate
                )
            correction_findings = _gate_findings(
                component_gate["findings"], stage="components"
            )
            previous_prompt = generated["prompt_fingerprint"]
            previous_component_candidate = candidate_fingerprint
            working_state = rendered
        except (GraphContractError, StagedGenerationError, ValueError) as exc:
            if attempt + 1 >= _MAX_STAGE_ATTEMPTS:
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
        return await _failed(working_state, "staged_component_attempts_exhausted")

    accepted_component_fingerprint = component_fingerprint(component_build)
    previous_prompt = None
    previous_connection_candidate: str | None = None
    previous_connection_wire: str | None = None
    rejected_connection_candidate: dict[str, Any] | None = None
    correction_findings = []
    connection_gate: dict[str, Any] = {}
    for attempt in range(_MAX_STAGE_ATTEMPTS):
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
                        "primary_flow_member": component["primary_flow_member"],
                        "is_root": component["model_index"]
                        == component_build["root_index"],
                    }
                    for component in component_build["components"]
                ],
                attempt=attempt,
                prior_prompt_fingerprint=previous_prompt,
                prior_write_set_fingerprint=(
                    write_set_fingerprint if attempt else None
                ),
                structural_findings=correction_findings,
                base_connections=_connection_prompt_base(base_build),
                rejected_candidate=rejected_connection_candidate,
                state=state,
                timeout_seconds=settings.staged_connection_timeout_s,
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
            validate_staged_graph_build(candidate_build)
            projected = _attach_graph_version(project_graph_data(candidate_build))
            if projected is None:
                raise GraphContractError(
                    "projection returned no graph", path="graph_data"
                )
            projected = _preserve_existing_presentation(
                projected,
                approved_graph if isinstance(approved_graph, Mapping) else None,
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
            connection_gate = await review_connections(
                user_request=request,
                evidence_bundle=evidence,
                resolved_maturity=maturity,
                candidate_records=[
                    {
                        "source": edge["source_id"],
                        "target": edge["target_id"],
                        "label": edge["label"],
                        "flow": edge["flow"],
                        "sync": edge["sync"],
                    }
                    for edge in candidate_build["connections"]
                ],
                required_production_guarantees=production_proofs_for_capabilities(
                    candidate_build["capabilities"], maturity=maturity
                ),
                telemetry_context=state,
            )
            if connection_gate["approved"]:
                graph_contract = _contract(
                    candidate_build,
                    projected,
                    component_gate=component_gate,
                    connection_gate=connection_gate,
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
                    rendered, "staged_connection_gate_unavailable", connection_gate
                )
            correction_findings = _gate_findings(
                connection_gate["findings"], stage="connections"
            )
            previous_prompt = generated["prompt_fingerprint"]
            previous_connection_candidate = candidate_fingerprint
            working_state = rendered
        except (GraphContractError, StagedGenerationError, ValueError) as exc:
            if attempt + 1 >= _MAX_STAGE_ATTEMPTS:
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
    return await _failed(working_state, "staged_connection_attempts_exhausted")
