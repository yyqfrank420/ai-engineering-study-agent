from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Reviewer explanations must retain the repair context through generation.
MAX_REVIEW_REASON_CHARS = 2_000

RUBRIC_CRITERIA = {
    "domain_specificity": (
        "components",
        "Use component names and boundaries specific to the requested system.",
    ),
    "objective_fidelity": (
        "components",
        "Depict the requested subject system and make its runtime goal and constraints visible in component responsibilities. Establish the user's business domain, goal, and workflow from the request or accepted context. Retrieved examples cannot choose the user's domain or goal. Assumptions may fill implementation details but cannot invent a missing business goal or workflow. An explicit educational subject establishes the system to explain. For new designs, select the initiating primary runtime actor as the root; centrality of an AI service does not determine the root. Primary membership selects components for the main walkthrough. Every primary member must be naturally reachable outward from that root using directed runtime or control contracts, which may pass through non-primary supporting components. Keep independent ingress and supporting components in the design; mark them non-primary when they do not belong in the walkthrough. Feedback and deployment contracts cannot establish primary reachability. Do not invent reverse or control edges to repair an unsuitable root or primary membership. Determine initiation from declared behavior. A component that pulls or requests data may initiate an outward request with a return response; inbound responses and independent inputs do not disqualify that root. Require contracts consistent with the declared responsibilities, without inventing requests for push-only sources. At the component stage, assess whether declared responsibilities and assumptions support a feasible directed path; connections are authored in the next stage. Missing edges or absent peer names in responsibilities are not component defects. Identify a specific incompatible responsibility when rejecting root or primary membership; do not demand connection-stage evidence here. Scoped edits preserve the accepted root and primary membership outside the authorized write set. Instructions to explain, cite or ground the response in sources, or draw its flow govern the response; include those capabilities in the designed runtime only when explicitly requested as system features.",
    ),
    "runtime_completeness": (
        "connections",
        "Connect observations and accepted processing to measurable outcomes. Require decisions and actions only when accepted component responsibilities own them. For observation-only designs, a durable telemetry sink is a complete outcome.",
    ),
    "safe_action_boundary": (
        "connections",
        "Put policy, exact-action approval, audit, and recovery controls on external mutations.",
    ),
    "edge_semantics": (
        "connections",
        "Give each directed edge one distinct necessary contract, consolidate duplicate interactions, and keep reverse or parallel contracts compatible.",
    ),
    "assumption_hygiene": (
        "composition",
        "Record material unknowns as assumptions instead of facts.",
    ),
    "selected_depth": (
        "components",
        "Match component ownership and operational detail to the selected UI depth without importing deeper criteria.",
    ),
    "novice_clarity": (
        "composition",
        "Use authored groups and sequence to make the entry, main path, controls, and outcomes easy to locate in the screenshot.",
    ),
    "logical_flow": (
        "connections",
        "Start the primary operational path at its real trigger and follow directed contracts to an observable outcome.",
    ),
    "succinctness": (
        "components",
        "Keep node labels and responsibilities concise and distinct.",
    ),
    "mece_scope": (
        "components",
        "Give each material responsibility one clear owner, remove needless duplicates, and exclude mechanics used to author this response unless explicitly requested as runtime features of the subject system.",
    ),
    "authored_composition": (
        "composition",
        "Use title, groups, and one primary sequence to expose the operational spine while secondary paths remain subordinate.",
    ),
    "brief_coverage": (
        "components",
        "Give every requested responsibility of the subject system a component owner; response instructions do not create runtime responsibilities.",
    ),
    "branch_completion": (
        "connections",
        "Route normal, alternate, rejection, and fallback branches to a rejoin or observable outcome.",
    ),
    "independent_risk_coverage": (
        "components",
        "Give each material independently reviewed risk a named responsibility owner.",
    ),
    "gate_preserving_reuse": (
        "connections",
        "Store only accepted post-gate artifacts, or route cache, replay, retry, and shortcut paths back through the required gate with identity and version scope.",
    ),
    "topology_enforced_guarantees": (
        "connections",
        "Express each guarantee with directed components and edges. Labels and assumptions alone are not proof.",
    ),
    "controlled_external_effects": (
        "connections",
        "Trace each material mutation through authoritative observation, typed proposal, policy, exact-action approval, execution, authoritative target, reconciled outcome, and canonical audit state.",
    ),
    "race_and_ambiguity_safety": (
        "connections",
        "Converge alternative delivery paths before action, deduplicate atomically at the durable writer, reconcile timeout-after-commit by the same key, and send compensation through the normal controls.",
    ),
    "canonical_state_and_trust": (
        "connections",
        "Keep lifecycle authority out of caches and projections. Validate model actions deterministically and connect material claims to provenance and audit evidence.",
    ),
    "controlled_learning_and_release": (
        "connections",
        "Route feedback through versioned evidence, offline evaluation, reviewed immutable release, canary, separate promotion, and separate rollback before live changes.",
    ),
    "safe_factual_failure": (
        "connections",
        "End failed factual retrieval in clarification or abstention, bound validation retries, and scope caches by identity, version, provenance, invalidation, and revalidation.",
    ),
    "pre_effect_durability_and_freshness": (
        "connections",
        "Reserve a stable operation identity durably before a retryable effect, then revalidate authorization, policy, freshness, and fencing before execution.",
    ),
    "complete_reconciliation": (
        "connections",
        "Branch status read-back into COMMITTED, NOT_FOUND with same-key retry under valid authorization, and bounded STILL_UNKNOWN escalation. Route late anomalies to correlated, bounded compensation.",
    ),
    "complete_trust_and_release_scope": (
        "connections",
        "Keep retrieved bytes untrusted, verify material claim entailment, use access and release-complete cache keys, audit every terminal branch, curate hostile traces, and draw separate promotion and rollback edges.",
    ),
    "state_order_integrity": (
        "connections",
        "Represent required order with separate responsibilities and transitions. Split lookup/write, reserve/send, validate/deliver, and promote/rollback phases when order matters.",
    ),
    "streaming_integrity": (
        "connections",
        "For continuous streams, define bounded backpressure, ordering or event-time rules, replay and deduplication ownership, late-data handling, and compatible schema evolution.",
    ),
}

RUBRIC_CODES = tuple(RUBRIC_CRITERIA)
RUBRIC_CODE_OWNERS = {
    code: owner for code, (owner, _requirement) in RUBRIC_CRITERIA.items()
}

# Screenshot readability is useful reviewer guidance, but it has no typed,
# server-checkable closure rule. Keep its wire code stable without allowing a
# subjective preference to withhold an otherwise valid graph.
ADVISORY_RUBRIC_CODES = frozenset({"novice_clarity"})
PROTOTYPE_ADVISORY_RUBRIC_CODES = frozenset(
    {
        "logical_flow",
        "authored_composition",
        "branch_completion",
    }
)


def advisory_rubric_codes(resolved_depth: str) -> frozenset[str]:
    """Return criteria that cannot withhold a graph at the selected UI depth."""
    if resolved_depth == "production":
        return ADVISORY_RUBRIC_CODES
    return ADVISORY_RUBRIC_CODES | PROTOTYPE_ADVISORY_RUBRIC_CODES


COMPOSITION_REPAIR_PROFILES = {
    "assumption_hygiene": ("assumptions",),
}


def required_composition_repair_fields(criteria: list[str]) -> list[str]:
    """Return server-owned composition authority required by hard criteria."""
    required = {
        field
        for criterion in criteria
        for field in COMPOSITION_REPAIR_PROFILES.get(criterion, ())
    }
    return [
        field
        for field in ("title", "groups", "sequence", "assumptions")
        if field in required
    ]


TOPOLOGY_PROOF_REQUIREMENTS = {
    "state_effect_reconciliation": (
        "Show a directed witness from durable operation reservation through execution and authoritative read-back to every reconciliation outcome."
    ),
    "authorization_and_compensation": (
        "Show exact-action authorization before execution and route compensation through policy, approval, execution, reconciliation, and audit."
    ),
    "retrieval_and_reuse_trust": (
        "Show untrusted retrieval, claim validation, access and release-scoped reuse, invalidation, and audited terminal outcomes."
    ),
    "audit_and_provenance": (
        "Show provenance and audit paths for material inputs, decisions, actions, and terminal outcomes."
    ),
    "learning_and_release": (
        "Show curated versioned evidence, offline evaluation, reviewed release, canary, promotion, rollback, and recorded outcomes."
    ),
}


# Legacy review still uses the proof protocol above. Staged review checks each
# production obligation once, selected by the accepted system's capabilities.
STAGED_PRODUCTION_REQUIREMENTS = {
    "authorization_and_compensation": (
        "For external mutations, connect authoritative observation, a typed exact-action "
        "proposal, policy and approval, execution, and the authoritative target. Compensation must "
        "use the same policy, approval, execution, reconciliation, and audit controls."
    ),
    "state_effect_reconciliation": (
        "For retryable writes, including internal durable mutations, reserve a stable "
        "operation identity durably before the effect. Revalidate applicable authorization, "
        "policy, freshness, and fencing before execution. Converge "
        "alternative delivery paths and deduplicate atomically at the writer. Reconcile "
        "timeout-after-commit by authoritative read-back using that identity: COMMITTED "
        "records success, NOT_FOUND permits same-key retry under valid authorization, and "
        "STILL_UNKNOWN has a bounded escalation. Correlate late anomalies with bounded "
        "compensation. A response contract may describe these outcomes together."
    ),
    "retrieval_and_reuse_trust": (
        "Treat retrieved bytes as untrusted. Validate material claim entailment before "
        "delivery or reuse. Failed factual retrieval or rejected/stale artifacts must end "
        "in clarification, abstention, or a bounded validated retry. Scope reuse by access "
        "identity, version, and provenance, including model/prompt/index release when "
        "applicable; name invalidation and revalidation ownership. Shortcuts cannot bypass "
        "these controls."
    ),
    "learning_and_release": (
        "Route feedback through curated versioned evidence, including hostile traces, "
        "offline evaluation, reviewed immutable release, and canary. Keep promotion and "
        "rollback as distinct controlled operations and record their outcomes."
    ),
    "audit_and_provenance": (
        "Give lifecycle state one authoritative owner; caches and projections cannot own "
        "it. Validate model-proposed actions deterministically. Retain provenance and "
        "correlated audit evidence for material inputs, decisions, actions, and terminal "
        "outcomes."
    ),
    "streaming_integrity": (
        "For continuous streams, name ownership of bounded backpressure, ordering or "
        "event-time rules, replay and deduplication, late-data handling, and schema "
        "compatibility. Component responsibilities or channel contracts may specify "
        "these properties; each property does not need a separate edge."
    ),
}


def staged_review_requirements(
    stage: str,
    maturity: str,
    required_production_guarantees: Sequence[str] = (),
) -> dict[str, str]:
    """Give staged generation and review the same applicable acceptance criteria."""
    if stage not in {"components", "connections"}:
        raise ValueError("stage must be components or connections")
    if maturity not in {"prototype", "production"}:
        raise ValueError("maturity must be prototype or production")
    # Wire rule order is versioned; the production extension begins at index 16.
    excluded = set(advisory_rubric_codes(maturity))
    # The staged production rules below replace overlapping legacy checks.
    excluded.update(RUBRIC_CODES[16:])
    # Staged construction has no independently reviewed upstream risk artifact.
    excluded.add("independent_risk_coverage")
    requirements = {
        code: requirement
        for code, (owner, requirement) in RUBRIC_CRITERIA.items()
        if owner == stage and code not in excluded
    }
    if stage == "components":
        requirements["capability_classification"] = (
            "Classify capabilities from the candidate responsibilities and assumptions: "
            "external_effects means it can mutate an external system; retrieval_or_reuse "
            "means it retrieves or reuses stored artifacts; learning_or_release means "
            "feedback can change a model, prompt, ranking, or live configuration. "
            "Check each flag independently against named component responsibilities "
            "and assumptions, and report every unsupported flag in the same review. "
            "Internal dataset curation or publication and a passive downstream consumer "
            "alone do not imply external_effects or learning_or_release. Require an "
            "owner in this system for the external write or the feedback-driven change "
            "to a model, prompt, ranking, or live configuration, respectively."
        )
        if maturity == "production":
            requirements["selected_depth"] += (
                " Before freezing the component set, require named executable ownership "
                "for production obligations applicable to declared responsibilities and "
                "capabilities: external_effects requires controlled execution, reconciliation, "
                "and compensation; retrieval_or_reuse requires validation, reuse lifecycle "
                "management, and invalidation; learning_or_release requires curated evidence, "
                "offline evaluation, reviewed release, canary, promotion, and rollback. "
                "Existing components may own compatible operations; do not require a separate "
                "component for every checklist step. A datastore, registry, or audit label, "
                "or an assumption alone, cannot execute evaluation, release, or control."
                " Retryable internal writes also need reservation, atomic deduplication, "
                "and reconciliation ownership. State required internal ordering, such as "
                "reserve before send and validate before deliver, in the owning component's "
                "responsibility; connection generation cannot change that responsibility."
            )
    elif maturity == "production":
        requirements["topology_enforced_guarantees"] = (
            "Show necessary directed contracts between components, including controls "
            "that must precede cross-boundary actions. Compatible internal operations "
            "may stay with one executable owner whose responsibility states the behavior. "
            "A typed response may contain success and rejection outcomes. A title or "
            "assumption cannot substitute for an owner or a required interaction."
        )
        requirements.update(
            (code, STAGED_PRODUCTION_REQUIREMENTS[code])
            for code in (
                "streaming_integrity",
                "state_effect_reconciliation",
            )
        )
        for guarantee in required_production_guarantees:
            if guarantee not in TOPOLOGY_PROOF_REQUIREMENTS:
                raise ValueError(f"unknown production guarantee: {guarantee!r}")
            requirements[guarantee] = STAGED_PRODUCTION_REQUIREMENTS[guarantee]
    return requirements


def repair_requirements(
    contract: dict[str, Any],
    topology_proofs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return compact acceptance criteria for only the failed review items."""
    component_layer = (contract.get("layers") or {}).get("components")
    component_operations = (
        component_layer.get("existing_node_operations")
        if isinstance(component_layer, dict)
        else None
    )
    findings = {
        str(finding)
        for layer in (contract.get("layers") or {}).values()
        if isinstance(layer, dict)
        for finding in (layer.get("blocking_findings") or [])
    }
    requirements = [
        {
            "criterion": code,
            "owner_layer": owner,
            "requirement": " ".join(
                part
                for part in (
                    requirement,
                    _format_repair_node_operations(component_operations)
                    if owner == "components"
                    else "",
                )
                if part
            ),
        }
        for code, (owner, requirement) in RUBRIC_CRITERIA.items()
        if f"Repair {code.replace('_', ' ')} in the {owner} layer." in findings
    ]
    requirements.extend(
        {
            "criterion": f"topology_proof:{guarantee}",
            "owner_layer": "connections",
            "requirement": " ".join(
                part
                for part in (
                    TOPOLOGY_PROOF_REQUIREMENTS[guarantee],
                    _format_repair_obligations(proof.get("repair_obligations")),
                    _format_repair_edge_operations(proof.get("repair_edge_operations")),
                )
                if part
            ),
        }
        for proof in topology_proofs
        if isinstance(proof, dict)
        and proof.get("status") == "fail"
        and isinstance(proof.get("guarantee"), str)
        and (guarantee := proof["guarantee"]) in TOPOLOGY_PROOF_REQUIREMENTS
    )
    return requirements


def _format_repair_obligations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    obligations = [
        obligation
        for obligation in value
        if isinstance(obligation, dict)
        and all(
            isinstance(obligation.get(field), str) and obligation[field].strip()
            for field in ("source", "target", "required_contract")
        )
    ]
    if not obligations:
        return ""
    return "Required additions: " + "; ".join(
        f"{obligation['source']} -> {obligation['target']}: "
        f"{obligation['required_contract']}"
        for obligation in obligations
    )


def _format_repair_node_operations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    operations = [operation for operation in value if isinstance(operation, dict)]
    if not operations:
        return ""
    return "Required existing-node updates: " + "; ".join(
        f"update {operation.get('node_id', '?')}: "
        + ", ".join(
            f"{field}={item!s}"
            for field, item in sorted((operation.get("set") or {}).items())
        )
        for operation in operations
    )


def _format_repair_edge_operations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    operations = [operation for operation in value if isinstance(operation, dict)]
    if not operations:
        return ""
    return "Required existing-edge operations: " + "; ".join(
        _format_repair_edge_operation(operation) for operation in operations
    )


def _format_repair_edge_operation(operation: dict[str, Any]) -> str:
    selector = operation.get("edge_selector") or {}
    identity = (
        f"{selector.get('source', '?')} -> {selector.get('target', '?')}: "
        f"{selector.get('label', '?')}"
    )
    kind = operation.get("kind")
    if kind == "update":
        return f"update {identity} to {str((operation.get('set') or {}).get('label') or '')}"
    if kind == "replace":
        replacements = _format_repair_obligations(
            operation.get("replacement_obligations")
        ).removeprefix("Required additions: ")
        return f"replace {identity} with {replacements}"
    return f"remove {identity}"
