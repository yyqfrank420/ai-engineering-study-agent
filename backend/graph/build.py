from __future__ import annotations

import argparse
import json
# This build step reads only the repository's generated, checksum-pinned artifact.
import pickle  # nosec B403
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from config import settings
from graph.ids import parent_chunk_id_from_metadata
from graph.schema import (
    ARCHITECTURE_KINDS,
    CONCEPT_KINDS,
    RelationSpec,
    load_relation_registry,
    relation_allowed,
    validate_relation_registry,
    violates_negative_example,
)


@dataclass(frozen=True)
class TermRule:
    label: str
    layer: str
    kind: str
    aliases: tuple[str, ...] = ()

    @property
    def canonical_id(self) -> str:
        return f"{self.layer}:{_slug(self.label)}"

    @property
    def match_terms(self) -> tuple[str, ...]:
        return (self.label, *self.aliases)


def _slug(label: str) -> str:
    value = label.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


@dataclass(frozen=True)
class NodeCandidate:
    rule: TermRule
    parent_chunk_id: str
    support_span: str
    chapter_ref: dict[str, Any]
    normalization_certainty: float = 1.0


@dataclass(frozen=True)
class EdgeCandidate:
    source_id: str
    target_id: str
    relation: str
    parent_chunk_id: str
    support_span: str
    requires_trigger_order: bool = True


CONCEPT_RULES: tuple[TermRule, ...] = (
    TermRule("Foundation Model", "concept", "component", ("foundation models",)),
    TermRule("Language Model", "concept", "component", ("large language model", "LLM", "LLMs")),
    TermRule("Context Window", "concept", "component", ("context length",)),
    TermRule("Tokenization", "concept", "method", ("tokenizer", "tokens")),
    TermRule("Embeddings", "concept", "artifact", ("embedding", "text embedding")),
    TermRule("Embedding Model", "concept", "component", ("embedding models",)),
    TermRule("Prompt Engineering", "concept", "method", ("prompting",)),
    TermRule("Prompt Template", "concept", "artifact", ("prompt templates",)),
    TermRule("System Prompt", "concept", "artifact", ("system prompts",)),
    TermRule("Retrieval-Augmented Generation", "concept", "method", ("RAG", "retrieval augmented generation")),
    TermRule("Retrieval", "concept", "method", ("retriever", "retrievers")),
    TermRule("Reranking", "concept", "method", ("reranker", "rerankers")),
    TermRule("Chunking", "concept", "method", ("chunks", "chunk")),
    TermRule("Vector Database", "concept", "component", ("vector store", "vector stores", "vector database")),
    TermRule("Generation", "concept", "method", ("generate", "generating")),
    TermRule("Fine-Tuning", "concept", "method", ("finetuning", "fine tuning")),
    TermRule("Supervised Fine-Tuning", "concept", "method", ("SFT",)),
    TermRule("Parameter-Efficient Fine-Tuning", "concept", "method", ("PEFT",)),
    TermRule("Low-Rank Adaptation", "concept", "method", ("LoRA", "low rank adaptation")),
    TermRule("Quantization", "concept", "method", ("quantized",)),
    TermRule("Distillation", "concept", "method", ("model distillation",)),
    TermRule("Sampling", "concept", "method", ("decoding", "temperature")),
    TermRule("Batching", "concept", "method", ("batch inference", "batching")),
    TermRule("Caching", "concept", "method", ("cache", "caches")),
    TermRule("Model Serving", "concept", "method", ("serving", "inference serving")),
    TermRule("Latency", "concept", "metric", ("latencies",)),
    TermRule("Cost", "concept", "metric", ("costs",)),
    TermRule("Quality", "concept", "objective", ("response quality", "model quality")),
    TermRule("Accuracy", "concept", "metric", ("accurate",)),
    TermRule("Precision", "concept", "metric", ("precise",)),
    TermRule("Recall", "concept", "metric", ("coverage",)),
    TermRule("Evaluation", "concept", "method", ("evals", "evaluating")),
    TermRule("Benchmark", "concept", "artifact", ("benchmarks",)),
    TermRule("Human Evaluation", "concept", "method", ("human evaluators",)),
    TermRule("Offline Evaluation", "concept", "method", ("offline eval",)),
    TermRule("Online Evaluation", "concept", "method", ("online eval",)),
    TermRule("A/B Testing", "concept", "method", ("AB testing", "A/B tests")),
    TermRule("Model Selection", "concept", "decision", ("choose a model", "model choice")),
    TermRule("Model Routing", "concept", "decision", ("model router", "routing")),
    TermRule("Guardrails", "concept", "control", ("guardrail", "guardrails")),
    TermRule("Moderation", "concept", "control", ("moderate", "moderating")),
    TermRule("Access Control", "concept", "control", ("authorization", "permissions")),
    TermRule("Prompt Injection", "concept", "risk", ("prompt injections", "jailbreak")),
    TermRule("Hallucination", "concept", "risk", ("hallucinations",)),
    TermRule("Data Privacy", "concept", "risk", ("privacy", "private data")),
    TermRule("Safety", "concept", "objective", ("safe",)),
    TermRule("Reliability", "concept", "objective", ("reliable",)),
    TermRule("Agent", "concept", "component", ("agents",)),
    TermRule("Tool Use", "concept", "method", ("tools", "tool calling")),
    TermRule("Planning", "concept", "method", ("planner", "plans")),
    TermRule("Memory", "concept", "component", ("memories",)),
    TermRule("Feedback Loop", "concept", "method", ("feedback loops", "feedback")),
    TermRule("Data Flywheel", "concept", "method", ("data flywheels",)),
)

ARCHITECTURE_RULES: tuple[TermRule, ...] = (
    TermRule("User", "architecture", "actor", ("users", "human", "humans")),
    TermRule("Application", "architecture", "service", ("AI application", "applications")),
    TermRule("API Gateway", "architecture", "service", ("gateway",)),
    TermRule("Orchestrator", "architecture", "service", ("orchestration",)),
    TermRule("Model Server", "architecture", "service", ("model service", "inference server")),
    TermRule("LLM Provider", "architecture", "external", ("model API", "model APIs", "foundation model API")),
    TermRule("Embedding Service", "architecture", "service", ("embedding endpoint",)),
    TermRule("Retriever Service", "architecture", "service", ("retriever",)),
    TermRule("Reranker Service", "architecture", "service", ("reranker",)),
    TermRule("Vector Store", "architecture", "datastore", ("vector database", "vector index")),
    TermRule("Document Store", "architecture", "datastore", ("documents", "document database")),
    TermRule("Prompt Store", "architecture", "datastore", ("prompt registry",)),
    TermRule("Cache", "architecture", "datastore", ("caches", "cached")),
    TermRule("Tool Service", "architecture", "external", ("external tool", "tools")),
    TermRule("Guardrail Service", "architecture", "control", ("guardrail", "moderation service")),
    TermRule("Evaluation Pipeline", "architecture", "pipeline_stage", ("evaluation pipeline", "eval pipeline")),
    TermRule("Data Pipeline", "architecture", "pipeline_stage", ("ingestion pipeline", "data pipeline")),
    TermRule("Monitoring Service", "architecture", "control", ("monitoring", "observability")),
    TermRule("Log Store", "architecture", "datastore", ("logs", "traces")),
)

TERM_RULES: tuple[TermRule, ...] = CONCEPT_RULES + ARCHITECTURE_RULES
TERM_BY_ID = {rule.canonical_id: rule for rule in TERM_RULES}
EVALUATOR_SOURCE_IDS = {
    "concept:a_b_testing",
    "concept:accuracy",
    "concept:benchmark",
    "concept:cost",
    "concept:evaluation",
    "concept:human_evaluation",
    "concept:latency",
    "concept:offline_evaluation",
    "concept:online_evaluation",
    "concept:precision",
    "concept:quality",
    "concept:recall",
    "concept:reliability",
    "concept:safety",
}

RELATION_TRIGGERS: dict[str, tuple[str, ...]] = {
    "part_of": ("part of", "component of"),
    "depends_on": ("depends on", "requires", "relies on", "prerequisite"),
    "feeds_into": ("feeds into", "passed to", "sent to", "input to", "becomes input", "then goes to"),
    "compares_with": ("compared with", "compared to", "versus", "vs.", "trade-off", "tradeoff"),
    "constrains": ("constrains", "limits", "limited by", "governs", "restricts"),
    "improves": (
        "improves",
        "improve",
        "reduces",
        "reduction",
        "increase",
        "increases",
        "boosts",
        "helps",
        "savings",
        "save",
        "saves",
        "lower",
        "lowers",
    ),
    "risks": ("risk", "risks", "threat", "attack", "harm", "failure"),
    "evaluates": ("evaluates", "evaluating", "measure", "measures", "score", "validate"),
    "calls": ("calls", "invokes", "request to", "queries"),
    "routes_to": ("routes to", "dispatches", "forwards", "route requests"),
    "reads_from": ("reads from", "retrieves from", "looks up in", "searches"),
    "writes_to": ("writes to", "write to", "indexes", "persists"),
    "stores_in": ("stores in", "stored in", "save to", "saved in"),
    "uses": ("uses", "using", "use a", "use the"),
    "monitors": ("monitors", "observes", "logs", "traces"),
    "sends_to": ("sends to", "sent to", "passes to", "passes", "streams to"),
    "implements": ("implements", "realizes", "builds"),
    "supports": ("supports", "enables", "helps"),
    "applies_to": ("applies to", "governs", "protects"),
}

POSITIVE_METRIC_LABELS = {
    "accuracy",
    "precision",
    "quality",
    "recall",
    "reliability",
    "safety",
}

NEGATIVE_METRIC_LABELS = {
    "cost",
    "latency",
}

UPWARD_CHANGE_TERMS = (
    "add",
    "adds",
    "added",
    "increase",
    "increases",
    "increased",
    "increasing",
    "overhead",
    "slowdown",
    "slower",
)
DOWNWARD_CHANGE_TERMS = (
    "decrease",
    "decreases",
    "decreased",
    "decreasing",
    "lower",
    "lowers",
    "lowered",
    "lowering",
    "reduce",
    "reduction",
    "reductions",
    "reduces",
    "reduced",
    "reducing",
    "save",
    "saves",
    "saved",
    "saving",
    "savings",
)
IMPROVEMENT_TERMS = (
    "benefit",
    "benefits",
    "boost",
    "boosts",
    "boosted",
    "help",
    "helps",
    "helped",
    "improve",
    "improves",
    "improved",
    "improving",
)
OPTIMIZATION_TERMS = (
    "optimize",
    "optimizes",
    "optimized",
    "optimizing",
    "optimization",
)
PROTECTION_TERMS = (
    "keep",
    "keeps",
    "kept",
    "protect",
    "protects",
    "protected",
    "protecting",
)
NEGATIVE_METRIC_IMPROVEMENT_BLOCKERS = (
    "adhering",
    "budget",
    "budgets",
    "constraint",
    "constraints",
    "requirement",
    "requirements",
    "request",
    "requests",
    "sla",
    "slo",
    "throughput",
    "volume",
)
IMPROVEMENT_TARGET_PROXIMITY = 96

DIRECTIONAL_TRIGGER_RELATIONS = {
    "applies_to",
    "calls",
    "constrains",
    "depends_on",
    "evaluates",
    "feeds_into",
    "implements",
    "improves",
    "monitors",
    "part_of",
    "reads_from",
    "risks",
    "routes_to",
    "sends_to",
    "stores_in",
    "supports",
    "uses",
    "writes_to",
}

SEEDED_ONLY_RELATIONS = {
    "applies_to",
    "calls",
    "implements",
    "monitors",
    "reads_from",
    "routes_to",
    "sends_to",
    "stores_in",
    "supports",
    "uses",
    "writes_to",
}

SEEDED_EDGES: tuple[tuple[str, str, str], ...] = (
    ("concept:retrieval_augmented_generation", "concept:retrieval", "depends_on"),
    ("concept:retrieval", "concept:embeddings", "depends_on"),
    ("concept:chunking", "concept:retrieval", "feeds_into"),
    ("concept:embedding_model", "concept:embeddings", "feeds_into"),
    ("concept:retrieval", "concept:generation", "feeds_into"),
    ("concept:reranking", "concept:quality", "improves"),
    ("concept:caching", "concept:latency", "improves"),
    ("concept:batching", "concept:cost", "improves"),
    ("concept:quantization", "concept:cost", "improves"),
    ("concept:low_rank_adaptation", "concept:parameter_efficient_fine_tuning", "part_of"),
    ("concept:parameter_efficient_fine_tuning", "concept:fine_tuning", "part_of"),
    ("concept:evaluation", "concept:model_selection", "feeds_into"),
    ("concept:benchmark", "concept:quality", "evaluates"),
    ("concept:human_evaluation", "concept:quality", "evaluates"),
    ("concept:offline_evaluation", "concept:evaluation", "part_of"),
    ("concept:online_evaluation", "concept:evaluation", "part_of"),
    ("concept:latency", "concept:model_selection", "constrains"),
    ("concept:cost", "concept:model_selection", "constrains"),
    ("concept:prompt_injection", "concept:safety", "risks"),
    ("concept:hallucination", "concept:quality", "risks"),
    ("concept:guardrails", "concept:generation", "constrains"),
    ("concept:moderation", "concept:safety", "improves"),
    ("concept:agent", "concept:tool_use", "depends_on"),
    ("concept:planning", "concept:agent", "part_of"),
    ("architecture:user", "architecture:application", "sends_to"),
    ("architecture:application", "architecture:orchestrator", "calls"),
    ("architecture:orchestrator", "architecture:model_server", "calls"),
    ("architecture:orchestrator", "architecture:tool_service", "calls"),
    ("architecture:orchestrator", "architecture:retriever_service", "routes_to"),
    ("architecture:retriever_service", "architecture:vector_store", "reads_from"),
    ("architecture:data_pipeline", "architecture:document_store", "writes_to"),
    ("architecture:data_pipeline", "architecture:vector_store", "writes_to"),
    ("architecture:embedding_service", "architecture:vector_store", "writes_to"),
    ("architecture:reranker_service", "architecture:retriever_service", "uses"),
    ("architecture:guardrail_service", "architecture:model_server", "monitors"),
    ("architecture:evaluation_pipeline", "architecture:log_store", "reads_from"),
    ("architecture:monitoring_service", "architecture:log_store", "writes_to"),
    ("architecture:model_server", "concept:generation", "implements"),
    ("architecture:retriever_service", "concept:retrieval", "implements"),
    ("architecture:vector_store", "concept:vector_database", "supports"),
    ("architecture:guardrail_service", "concept:guardrails", "implements"),
    ("concept:latency", "architecture:model_server", "applies_to"),
    ("concept:cost", "architecture:model_server", "applies_to"),
)


def build_canonical_graph(
    parent_docs_path: Path | None = None,
    output_dir: Path | None = None,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    parent_docs_path = parent_docs_path or (settings.faiss_dir / "parent_docs.pkl")
    output_dir = output_dir or settings.graph_dir
    schema_dir = schema_dir or settings.graph_schema_dir

    registry_path = schema_dir / "relations.json"
    registry = load_relation_registry(registry_path)
    validate_relation_registry(registry)

    with parent_docs_path.open("rb") as handle:
        parent_docs = pickle.load(handle)  # nosec B301

    chunks = _prepare_chunks(parent_docs)
    node_candidates, terms_by_chunk = _extract_node_candidates(chunks)
    verified_nodes = [
        candidate
        for candidate in node_candidates
        if _verify_node_candidate(candidate, chunks[candidate.parent_chunk_id])
    ]

    canonical_nodes = _merge_nodes(verified_nodes)

    edge_candidates = _extract_edge_candidates(chunks, terms_by_chunk, canonical_nodes, registry)
    verified_edges = [
        edge
        for edge in edge_candidates
        if _verify_edge_candidate(edge, chunks[edge.parent_chunk_id], canonical_nodes, registry)
    ]
    canonical_edges = _merge_edges(verified_edges, canonical_nodes, registry)
    chunk_links = _build_chunk_links(chunks.keys(), canonical_nodes, canonical_edges)

    concept_nodes = [node for node in canonical_nodes.values() if node["layer"] == "concept"]
    architecture_nodes = [
        node for node in canonical_nodes.values() if node["layer"] == "architecture"
    ]

    build_report = {
        "built_at": datetime.now(UTC).isoformat(),
        "source_parent_docs": str(parent_docs_path),
        "parent_chunk_count": len(chunks),
        "node_candidate_count": len(node_candidates),
        "verified_node_candidate_count": len(verified_nodes),
        "canonical_concept_count": len(concept_nodes),
        "canonical_architecture_count": len(architecture_nodes),
        "edge_candidate_count": len(edge_candidates),
        "verified_edge_candidate_count": len(verified_edges),
        "canonical_edge_count": len(canonical_edges),
        "relation_count": len(registry),
        "verifier": "deterministic-source-span-and-registry",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "concepts.json", concept_nodes)
    _write_json(output_dir / "architecture_nodes.json", architecture_nodes)
    _write_json(output_dir / "edges.json", canonical_edges)
    _write_json(output_dir / "chunk_links.json", chunk_links)
    _write_json(output_dir / "build_report.json", build_report)
    shutil.copyfile(registry_path, output_dir / "relations.json")

    return build_report


def _prepare_chunks(parent_docs: list[Any]) -> dict[str, dict[str, Any]]:
    chunks: dict[str, dict[str, Any]] = {}
    for doc in parent_docs:
        chunk_id = parent_chunk_id_from_metadata(doc.metadata)
        chunks[chunk_id] = {
            "id": chunk_id,
            "text": _clean_text(doc.page_content),
            "metadata": dict(doc.metadata),
        }
    return chunks


def _extract_node_candidates(
    chunks: dict[str, dict[str, Any]],
) -> tuple[list[NodeCandidate], dict[str, set[str]]]:
    candidates: list[NodeCandidate] = []
    terms_by_chunk: dict[str, set[str]] = defaultdict(set)
    for chunk_id, chunk in chunks.items():
        text = chunk["text"]
        for rule in TERM_RULES:
            support = _find_support_sentence(text, rule.match_terms)
            if not support:
                continue
            candidates.append(
                NodeCandidate(
                    rule=rule,
                    parent_chunk_id=chunk_id,
                    support_span=support,
                    chapter_ref=_chapter_ref(chunk["metadata"]),
                )
            )
            terms_by_chunk[chunk_id].add(rule.canonical_id)
    return candidates, terms_by_chunk


def _verify_node_candidate(candidate: NodeCandidate, chunk: dict[str, Any]) -> bool:
    if candidate.rule.layer == "concept" and candidate.rule.kind not in CONCEPT_KINDS:
        return False
    if candidate.rule.layer == "architecture" and candidate.rule.kind not in ARCHITECTURE_KINDS:
        return False
    text = chunk["text"]
    return (
        candidate.support_span in text
        and _contains_any(text, candidate.rule.match_terms)
    )


def _merge_nodes(candidates: list[NodeCandidate]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[NodeCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.rule.canonical_id].append(candidate)

    nodes: dict[str, dict[str, Any]] = {}
    for canonical_id, group in sorted(grouped.items()):
        rule = group[0].rule
        chunk_ids = sorted({candidate.parent_chunk_id for candidate in group}, key=_chunk_sort_key)
        chapter_refs = _dedupe_dicts(candidate.chapter_ref for candidate in group)
        support_spans = _dedupe_strings(candidate.support_span for candidate in group)[:6]
        evidence_count = len(chunk_ids)
        confidence = _confidence(evidence_count, len({ref.get("chapter") for ref in chapter_refs}))
        nodes[canonical_id] = {
            "canonical_id": canonical_id,
            "layer": rule.layer,
            "label": rule.label,
            "aliases": sorted({alias for candidate in group for alias in candidate.rule.aliases}),
            "kind": rule.kind,
            "description": _node_description(rule, support_spans),
            "chapter_refs": chapter_refs,
            "source_chunk_ids": chunk_ids,
            "support_spans": support_spans,
            "confidence": confidence,
        }
    return nodes


def _extract_edge_candidates(
    chunks: dict[str, dict[str, Any]],
    terms_by_chunk: dict[str, set[str]],
    nodes: dict[str, dict[str, Any]],
    registry: dict[str, RelationSpec],
) -> list[EdgeCandidate]:
    candidates: list[EdgeCandidate] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for chunk_id, chunk in chunks.items():
        chunk_terms = [term for term in terms_by_chunk.get(chunk_id, set()) if term in nodes]
        if len(chunk_terms) < 2:
            continue
        for sentence in _sentences(chunk["text"]):
            sentence_terms = [
                term_id
                for term_id in chunk_terms
                if _contains_any(sentence, TERM_BY_ID[term_id].match_terms)
            ]
            if len(sentence_terms) < 2:
                continue
            for relation, triggers in RELATION_TRIGGERS.items():
                if relation in SEEDED_ONLY_RELATIONS:
                    continue
                if not _contains_any(sentence, triggers):
                    continue
                for source_id, target_id in _ordered_pairs(sentence_terms, sentence):
                    if _candidate_relation_allowed(
                        source_id, target_id, relation, nodes, registry
                    ) and _candidate_support_allowed(
                        source_id,
                        target_id,
                        relation,
                        sentence,
                    ) and _relation_order_allowed(source_id, target_id, relation, sentence):
                        key = (source_id, target_id, relation, chunk_id, sentence)
                        if key not in seen:
                            seen.add(key)
                            candidates.append(
                                EdgeCandidate(source_id, target_id, relation, chunk_id, sentence)
                            )

        for source_id, target_id, relation in SEEDED_EDGES:
            if source_id not in chunk_terms or target_id not in chunk_terms:
                continue
            support = _find_joint_support_sentence(
                chunk["text"],
                TERM_BY_ID[source_id].match_terms,
                TERM_BY_ID[target_id].match_terms,
            )
            if not support:
                continue
            if not _candidate_relation_allowed(source_id, target_id, relation, nodes, registry):
                continue
            key = (source_id, target_id, relation, chunk_id, support)
            if key not in seen:
                seen.add(key)
                candidates.append(
                    EdgeCandidate(
                        source_id,
                        target_id,
                        relation,
                        chunk_id,
                        support,
                        requires_trigger_order=False,
                    )
                )

    return candidates


def _candidate_relation_allowed(
    source_id: str,
    target_id: str,
    relation: str,
    nodes: dict[str, dict[str, Any]],
    registry: dict[str, RelationSpec],
) -> bool:
    if source_id == target_id:
        return False
    if relation == "evaluates" and source_id not in EVALUATOR_SOURCE_IDS:
        return False
    if relation == "evaluates" and target_id in EVALUATOR_SOURCE_IDS:
        return False
    source = nodes[source_id]
    target = nodes[target_id]
    return relation_allowed(
        registry,
        relation,
        source["layer"],
        source["kind"],
        target["layer"],
        target["kind"],
    )


def _relation_order_allowed(
    source_id: str,
    target_id: str,
    relation: str,
    support_span: str,
) -> bool:
    if relation not in DIRECTIONAL_TRIGGER_RELATIONS:
        return True

    normalized = _normalize_relation_text(support_span)
    source_spans = _term_spans(normalized, TERM_BY_ID[source_id].match_terms)
    target_spans = _term_spans(normalized, TERM_BY_ID[target_id].match_terms)
    trigger_spans = _term_spans(normalized, RELATION_TRIGGERS.get(relation, ()))
    return any(
        source_start <= trigger_start <= target_start
        and trigger_start - source_end <= 160
        and target_start - trigger_end <= 160
        and not _has_intervening_canonical_source(
            normalized,
            source_id,
            (source_start, source_end),
            trigger_start,
        )
        and not _relation_trigger_target_blocked(
            normalized,
            relation,
            (trigger_start, trigger_end),
            target_start,
        )
        for source_start, source_end in source_spans
        for trigger_start, trigger_end in trigger_spans
        for target_start, _ in target_spans
    )


def _candidate_support_allowed(
    source_id: str,
    target_id: str,
    relation: str,
    support_span: str,
) -> bool:
    if not _relation_support_usable(support_span):
        return False

    if relation == "compares_with":
        return _compare_support_allowed(source_id, target_id, support_span)

    if relation != "improves":
        return True

    target_rule = TERM_BY_ID[target_id]
    if target_rule.kind not in {"metric", "objective"}:
        return False

    target_label = target_rule.label.lower()
    normalized = _normalize_relation_text(support_span)
    target_terms = target_rule.match_terms

    if target_label in NEGATIVE_METRIC_LABELS:
        if _has_negated_downward_target(normalized, target_terms):
            return False
        if _has_requirement_target_context(normalized, target_terms):
            return False
        if _has_nearby_terms(normalized, UPWARD_CHANGE_TERMS, target_terms):
            return False
        return _has_negative_metric_improvement(normalized, target_terms)

    if target_label in POSITIVE_METRIC_LABELS:
        if _has_nearby_terms(normalized, DOWNWARD_CHANGE_TERMS, target_terms):
            return False
        return _has_positive_metric_improvement(normalized, target_terms)

    return _has_nearby_terms(normalized, IMPROVEMENT_TERMS + OPTIMIZATION_TERMS, target_terms)


def _verify_edge_candidate(
    candidate: EdgeCandidate,
    chunk: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    registry: dict[str, RelationSpec],
) -> bool:
    source = nodes.get(candidate.source_id)
    target = nodes.get(candidate.target_id)
    spec = registry.get(candidate.relation)
    if not source or not target or not spec:
        return False
    text = chunk["text"]
    source_rule = TERM_BY_ID[candidate.source_id]
    target_rule = TERM_BY_ID[candidate.target_id]
    return (
        candidate.support_span in text
        and _contains_any(text, source_rule.match_terms)
        and _contains_any(text, target_rule.match_terms)
        and _candidate_relation_allowed(candidate.source_id, candidate.target_id, candidate.relation, nodes, registry)
        and _candidate_support_allowed(candidate.source_id, candidate.target_id, candidate.relation, candidate.support_span)
        and (
            not candidate.requires_trigger_order
            or _relation_order_allowed(
                candidate.source_id,
                candidate.target_id,
                candidate.relation,
                candidate.support_span,
            )
        )
        and not violates_negative_example(spec, candidate.support_span)
    )


def _merge_edges(
    candidates: list[EdgeCandidate],
    nodes: dict[str, dict[str, Any]],
    registry: dict[str, RelationSpec],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[EdgeCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate.source_id, candidate.target_id, candidate.relation)].append(candidate)

    edges: list[dict[str, Any]] = []
    for (source_id, target_id, relation), group in sorted(grouped.items()):
        source = nodes[source_id]
        target = nodes[target_id]
        spec = registry[relation]
        if not relation_allowed(
            registry,
            relation,
            source["layer"],
            source["kind"],
            target["layer"],
            target["kind"],
        ):
            continue
        chunk_ids = sorted({candidate.parent_chunk_id for candidate in group}, key=_chunk_sort_key)
        support_spans = _dedupe_strings(candidate.support_span for candidate in group)[:6]
        confidence = _confidence(len(chunk_ids), len({source_id, target_id}), base=0.58)
        edges.append(
            {
                "edge_id": f"{source_id}__{relation}__{target_id}",
                "layer": spec.layer,
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "supporting_chunk_ids": chunk_ids,
                "support_spans": support_spans,
                "confidence": confidence,
            }
        )
    return edges


def _build_chunk_links(
    chunk_ids: Iterable[str],
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links = {
        chunk_id: {"parent_chunk_id": chunk_id, "canonical_node_ids": [], "canonical_edge_ids": []}
        for chunk_id in chunk_ids
    }
    for node in nodes.values():
        for chunk_id in node["source_chunk_ids"]:
            links[chunk_id]["canonical_node_ids"].append(node["canonical_id"])
    for edge in edges:
        for chunk_id in edge["supporting_chunk_ids"]:
            links[chunk_id]["canonical_edge_ids"].append(edge["edge_id"])

    for link in links.values():
        link["canonical_node_ids"] = sorted(set(link["canonical_node_ids"]))
        link["canonical_edge_ids"] = sorted(set(link["canonical_edge_ids"]))
    return [links[chunk_id] for chunk_id in sorted(links, key=_chunk_sort_key)]


def _find_support_sentence(text: str, terms: tuple[str, ...]) -> str | None:
    for sentence in _sentences(text):
        if _contains_any(sentence, terms):
            return sentence
    return None


def _find_joint_support_sentence(
    text: str,
    source_terms: tuple[str, ...],
    target_terms: tuple[str, ...],
) -> str | None:
    for sentence in _sentences(text):
        if _contains_any(sentence, source_terms) and _contains_any(sentence, target_terms):
            return sentence
    return None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(_term_pattern(term).search(lowered) for term in terms)


def _normalize_relation_text(text: str) -> str:
    return _clean_text(text).lower().replace("\u2019", "'").replace("\u2018", "'")


def _relation_support_usable(support_span: str) -> bool:
    normalized = _normalize_relation_text(support_span)
    if any(
        marker in normalized
        for marker in (
            "criteria metric benchmark",
            "category building with traditional ml",
            "her book designing",
            "oreilly",
            "o'reilly",
            "table of contents",
            "table of contents |",
            "translated into over",
        )
    ):
        return False
    if re.match(r"^\d+\s*(?:\||[a-z])", normalized):
        return False
    numeric_tokens = re.findall(r"(?<![a-z])\d+(?:[.,:/-]\d+)*(?![a-z])", normalized)
    if len(normalized) > 180 and len(numeric_tokens) >= 12:
        return False
    return True


def _term_spans(text: str, terms: tuple[str, ...]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for term in terms:
        spans.extend((match.start(), match.end()) for match in _term_pattern(term).finditer(text))
    return spans


def _has_intervening_canonical_source(
    text: str,
    source_id: str,
    source_span: tuple[int, int],
    trigger_start: int,
) -> bool:
    _, source_end = source_span
    for term_id, rule in TERM_BY_ID.items():
        if term_id == source_id:
            continue
        for start, end in _term_spans(text, rule.match_terms):
            if start < source_end:
                continue
            if end <= trigger_start:
                return True
    return False


def _relation_trigger_target_blocked(
    text: str,
    relation: str,
    trigger_span: tuple[int, int],
    target_start: int,
) -> bool:
    _, trigger_end = trigger_span
    if target_start < trigger_end:
        return False
    between = text[trigger_end:target_start]
    if relation == "depends_on" and _contains_any(
        between,
        ("compared to", "than", "versus", "vs."),
    ):
        return True
    if relation == "part_of" and _contains_any(between, ("process", "processes")):
        return True
    if relation == "evaluates" and _contains_any(
        between,
        ("calculating", "datasets", "focus on", "suggestions for", "use it to", "while"),
    ):
        return True
    return False


def _has_nearby_terms(
    text: str,
    left_terms: tuple[str, ...],
    right_terms: tuple[str, ...],
    *,
    max_gap: int = IMPROVEMENT_TARGET_PROXIMITY,
) -> bool:
    left_spans = _term_spans(text, left_terms)
    right_spans = _term_spans(text, right_terms)
    return any(
        _span_gap(left_span, right_span) <= max_gap
        for left_span in left_spans
        for right_span in right_spans
    )


def _has_metric_improvement_phrase(text: str, target_terms: tuple[str, ...]) -> bool:
    improvement_spans = _term_spans(text, IMPROVEMENT_TERMS)
    target_spans = _term_spans(text, target_terms)
    for improve_start, improve_end in improvement_spans:
        for target_start, _ in target_spans:
            if target_start < improve_end:
                continue
            if target_start - improve_end > IMPROVEMENT_TARGET_PROXIMITY:
                continue
            between = text[improve_end:target_start]
            if not _contains_any(between, NEGATIVE_METRIC_IMPROVEMENT_BLOCKERS):
                return True
    return False


def _has_negative_metric_improvement(text: str, target_terms: tuple[str, ...]) -> bool:
    if _has_metric_improvement_phrase(text, target_terms):
        return True
    if _has_nearby_terms(text, OPTIMIZATION_TERMS, target_terms):
        return True

    downward_spans = _term_spans(text, DOWNWARD_CHANGE_TERMS)
    target_spans = _term_spans(text, target_terms)
    for down_start, down_end in downward_spans:
        for target_start, target_end in target_spans:
            if target_start >= down_end:
                if target_start - down_end > IMPROVEMENT_TARGET_PROXIMITY:
                    continue
                between = text[down_end:target_start]
                if not _contains_any(between, ("time", "times")):
                    return True
            elif down_start >= target_end and down_start - target_end <= 48:
                return True
    return False


def _compare_support_allowed(source_id: str, target_id: str, support_span: str) -> bool:
    normalized = _normalize_relation_text(support_span)
    source_kind = TERM_BY_ID[source_id].kind
    target_kind = TERM_BY_ID[target_id].kind

    if _contains_any(normalized, ("trade-off", "tradeoff")):
        return source_kind in {"metric", "objective"} and target_kind in {"metric", "objective"}

    if _contains_any(normalized, ("versus", "vs.")):
        return (
            source_kind == target_kind
            or {source_kind, target_kind} <= {"method", "metric"}
            or {source_kind, target_kind} <= {"method", "component"}
        )

    if _contains_any(normalized, ("compared to", "compared with")):
        if source_kind == target_kind:
            return True
        return {source_kind, target_kind} <= {"method", "component", "artifact"}

    return False


def _has_positive_metric_improvement(text: str, target_terms: tuple[str, ...]) -> bool:
    improvement_terms = (
        IMPROVEMENT_TERMS
        + UPWARD_CHANGE_TERMS
        + OPTIMIZATION_TERMS
        + PROTECTION_TERMS
        + ("exceed", "exceeds", "exceeded", "exceeding", "higher", "better")
    )
    improvement_spans = _term_spans(text, improvement_terms)
    target_spans = _term_spans(text, target_terms)
    for improve_start, improve_end in improvement_spans:
        for target_start, _ in target_spans:
            if target_start < improve_end:
                continue
            if target_start - improve_end <= IMPROVEMENT_TARGET_PROXIMITY:
                return True
    return False


def _has_requirement_target_context(text: str, target_terms: tuple[str, ...]) -> bool:
    requirement_terms = (
        "adhere",
        "adheres",
        "adhering",
        "need",
        "needs",
        "needed",
        "require",
        "requires",
        "required",
        "requirement",
        "requirements",
        "requiring",
    )
    if _has_nearby_terms(text, requirement_terms, target_terms, max_gap=56):
        return True
    return any(
        _contains_any(text[target_end:target_end + 32], ("requirement", "requirements"))
        for _, target_end in _term_spans(text, target_terms)
    )


def _has_negated_downward_target(text: str, target_terms: tuple[str, ...]) -> bool:
    downward_spans = _term_spans(text, DOWNWARD_CHANGE_TERMS)
    target_spans = _term_spans(text, target_terms)
    for down_start, down_end in downward_spans:
        prefix = text[max(0, down_start - 36):down_start]
        if not re.search(
            r"(?:not|never|without|is not|does not|do not|cannot|can't|isn't|doesn't|don't)\s+(?:to\s+)?$",
            prefix,
        ):
            continue
        for target_start, _ in target_spans:
            if target_start >= down_end and target_start - down_end <= IMPROVEMENT_TARGET_PROXIMITY:
                return True
    return False


def _span_gap(left: tuple[int, int], right: tuple[int, int]) -> int:
    if left[1] < right[0]:
        return right[0] - left[1]
    if right[1] < left[0]:
        return left[0] - right[1]
    return 0


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower())
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _ordered_pairs(term_ids: list[str], sentence: str) -> list[tuple[str, str]]:
    positions = []
    lowered = sentence.lower()
    for term_id in term_ids:
        rule = TERM_BY_ID[term_id]
        starts = [
            lowered.find(term.lower())
            for term in rule.match_terms
            if lowered.find(term.lower()) >= 0
        ]
        if starts:
            positions.append((min(starts), term_id))
    positions.sort()
    return [
        (source, target)
        for i, (_, source) in enumerate(positions)
        for _, target in positions[i + 1 :]
        if source != target
    ]


def _sentences(text: str) -> list[str]:
    cleaned = _clean_text(text)
    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = []
    for piece in pieces:
        sentence = piece.strip()
        if 24 <= len(sentence) <= 500:
            sentences.append(sentence)
    return sentences


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _node_description(rule: TermRule, support_spans: list[str]) -> str:
    if support_spans:
        preview = support_spans[0]
        if len(preview) > 180:
            preview = preview[:177].rstrip() + "..."
        return f"Canonical {rule.kind.replace('_', ' ')} grounded in book evidence: {preview}"
    return f"Canonical {rule.kind.replace('_', ' ')} from the AI Engineering book graph."


def _chapter_ref(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "book": metadata.get("book"),
        "chapter": metadata.get("chapter"),
        "chapter_title": metadata.get("chapter_title"),
        "section": metadata.get("section"),
        "page_number": metadata.get("page_number"),
    }


def _dedupe_dicts(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    result.sort(key=lambda ref: (ref.get("chapter") is None, ref.get("chapter") or 0, ref.get("page_number") or 0))
    return result


def _dedupe_strings(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _confidence(evidence_count: int, spread: int, *, base: float = 0.62) -> float:
    score = base + min(evidence_count, 8) * 0.035 + min(spread, 4) * 0.025
    return round(min(score, 0.96), 3)


def _chunk_sort_key(chunk_id: str) -> tuple[int, int]:
    match = re.search(r":p(\d+):pc(\d+)", chunk_id)
    if not match:
        return (10**9, 10**9)
    return (int(match.group(1)), int(match.group(2)))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical graph artifacts from parent_docs.pkl.")
    parser.add_argument("--parent-docs", type=Path, default=settings.faiss_dir / "parent_docs.pkl")
    parser.add_argument("--output-dir", type=Path, default=settings.graph_dir)
    parser.add_argument("--schema-dir", type=Path, default=settings.graph_schema_dir)
    args = parser.parse_args()
    report = build_canonical_graph(args.parent_docs, args.output_dir, args.schema_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
