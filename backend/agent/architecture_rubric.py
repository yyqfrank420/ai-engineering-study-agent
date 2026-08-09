from __future__ import annotations

from typing import Any


RUBRIC_CRITERIA = {
    "domain_specificity": (
        "components",
        "Use component names and boundaries specific to the requested system.",
    ),
    "objective_fidelity": (
        "components",
        "Make the requested goal and constraints visible in component responsibilities.",
    ),
    "runtime_completeness": (
        "connections",
        "Connect observations, processing or decisions, applicable actions, and measurable outcomes.",
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
        "Name the production owners for applicable failure, observability, and rollout work.",
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
        "Give each material responsibility one clear owner, remove needless duplicates, and exclude diagram-authoring mechanics from the designed runtime.",
    ),
    "authored_composition": (
        "composition",
        "Use title, groups, and one primary sequence to expose the operational spine while secondary paths remain subordinate.",
    ),
    "brief_coverage": (
        "components",
        "Give every requested responsibility a component owner.",
    ),
    "branch_completion": (
        "connections",
        "Route normal, alternate, rejection, and fallback branches to a rejoin or observable outcome.",
    ),
    "independent_risk_coverage": (
        "components",
        "Give each material challenger risk a named responsibility owner.",
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


def repair_requirements(
    contract: dict[str, Any],
    topology_proofs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return compact acceptance criteria for only the failed review items."""
    findings = {
        str(finding)
        for layer in (contract.get("layers") or {}).values()
        if isinstance(layer, dict)
        for finding in (layer.get("blocking_findings") or [])
    }
    requirements = [
        {"criterion": code, "owner_layer": owner, "requirement": requirement}
        for code, (owner, requirement) in RUBRIC_CRITERIA.items()
        if f"Repair {code.replace('_', ' ')} in the {owner} layer." in findings
    ]
    requirements.extend(
        {
            "criterion": f"topology_proof:{guarantee}",
            "owner_layer": "connections",
            "requirement": TOPOLOGY_PROOF_REQUIREMENTS[guarantee],
        }
        for proof in topology_proofs
        if isinstance(proof, dict)
        and proof.get("status") == "fail"
        and isinstance(proof.get("guarantee"), str)
        and (guarantee := proof["guarantee"]) in TOPOLOGY_PROOF_REQUIREMENTS
    )
    return requirements
