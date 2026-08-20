from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from agent.architecture_rubric import (
    RUBRIC_CODES,
    RUBRIC_CODE_OWNERS,
    TOPOLOGY_PROOF_REQUIREMENTS,
)
from eval.cost_gate import (
    CostPolicy,
    account_application_cost,
    account_judge_cost,
    evaluate_cost_policy,
)
from eval.judge_adapter import (
    JUDGE_PROMPT_RELEASE,
    SemanticJudge,
    estimated_judge_cost_usd,
    judge_with_transport_retry,
)
from eval.quality_corpus import corpus_sha256, load_corpus
from eval.response_capture import extract_response_turns
from eval.runtime_budget import semantic_suite_timeout_seconds
from eval.semantic_gate import EvaluationBudget, GateDecision, decide_semantic_gate


ROOT = Path(__file__).resolve().parents[2]
QUALITY_MANIFEST = ROOT / "ci" / "quality.json"
PROVIDER_FAILURE = re.compile(
    r"(?:rate.?limit|429|provider.*unavailable|timed?\s*out|connection.*failed)", re.I
)
ManualReviewPolicy = Literal["blocking", "report-only"]
_FAILURE_KINDS = frozenset({"infrastructure", "quality"})
_GRAPH_REVIEW_DIAGNOSTIC_FIELDS = frozenset(
    {
        "schema_version",
        "repair_round",
        "critic_call_count",
        "protocol_correction_count",
        "contract_correction_count",
        "depth",
        "locked_layers",
        "reopened_layers",
        "finding_codes",
        "blocker_ids",
        "selector_fingerprints",
        "prior_blocker_dispositions",
        "review_disposition",
        "validation_rule",
        "validation_path_fingerprint",
    }
)
_STAGED_GRAPH_DIAGNOSTIC_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "stage",
        "attempt",
        "code",
        "candidate_fingerprint",
        "findings",
    }
)
_STAGED_GENERATION_DIAGNOSTIC_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "stage",
        "attempt",
        "code",
        "path",
        "path_fingerprint",
        "candidate_fingerprint",
        "fingerprint_disposition",
    }
)
_STAGED_GRAPH_STAGES = frozenset({"components", "connections"})
_STAGED_GATE_CODES = frozenset({"gate_rejected", "gate_unavailable"})
_STAGED_GRAPH_FINGERPRINT_DISPOSITIONS = frozenset(
    {"matches_prior_candidate", "rejected_before_render"}
)
_STAGED_GATE_RULE_CODES = {
    "components": frozenset(
        code for code in RUBRIC_CODES if RUBRIC_CODE_OWNERS[code] == "components"
    )
    | {"capability_classification"},
    "connections": frozenset(
        code for code in RUBRIC_CODES if RUBRIC_CODE_OWNERS[code] == "connections"
    )
    | frozenset(TOPOLOGY_PROOF_REQUIREMENTS),
}
_GRAPH_REVIEW_COUNTER_FIELDS = (
    "repair_round",
    "critic_call_count",
    "protocol_correction_count",
    "contract_correction_count",
)
_GRAPH_REVIEW_LAYERS = frozenset({"components", "connections", "composition", "render"})
_GRAPH_REVIEW_DEPTHS = frozenset({"low", "prototype", "production"})
_GRAPH_REVIEW_DISPOSITIONS = frozenset({"approved", "rejected", "unavailable"})
_GRAPH_REVIEW_PRIOR_STATUSES = frozenset({"resolved", "still_fail"})
_SAFE_GRAPH_REVIEW_TEXT = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
_SAFE_GRAPH_REVIEW_RULE = re.compile(r"[a-z][a-z0-9_]{0,95}")
_SHA256_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_graph_review_texts(value: object) -> list[str] | None:
    if not isinstance(value, list) or len(value) > 64:
        return None
    if not all(
        isinstance(item, str) and _SAFE_GRAPH_REVIEW_TEXT.fullmatch(item)
        for item in value
    ):
        return None
    if len(value) != len(set(value)):
        return None
    return sorted(value)


def _safe_graph_review_dispositions(value: object) -> list[dict[str, str]] | None:
    if not isinstance(value, list) or len(value) > 64:
        return None
    dispositions: list[dict[str, str]] = []
    prior_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"prior_obligation_id", "status"}:
            return None
        prior_id = item.get("prior_obligation_id")
        status = item.get("status")
        if (
            not isinstance(prior_id, str)
            or not _SAFE_GRAPH_REVIEW_TEXT.fullmatch(prior_id)
            or status not in _GRAPH_REVIEW_PRIOR_STATUSES
            or prior_id in prior_ids
        ):
            return None
        prior_ids.add(prior_id)
        dispositions.append({"prior_obligation_id": prior_id, "status": status})
    return sorted(dispositions, key=lambda item: item["prior_obligation_id"])


def _safe_staged_gate_record_path(value: object, *, stage: str) -> str | None:
    if not isinstance(value, str):
        return None
    if value == stage:
        return value
    prefix = f"{stage}."
    if not value.startswith(prefix):
        return None
    suffix = value[len(prefix) :]
    if re.fullmatch(r"(?:0|[1-9][0-9]*)", suffix) is None:
        return None
    return value


def _safe_staged_gate_findings(
    value: object, *, stage: str
) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(value) > 24:
        return None
    findings: list[dict[str, Any]] = []
    for finding in value:
        if not isinstance(finding, dict) or set(finding) != {
            "rule_code",
            "record_paths",
        }:
            return None
        rule_code = finding.get("rule_code")
        if (
            not isinstance(rule_code, str)
            or rule_code not in _STAGED_GATE_RULE_CODES[stage]
        ):
            return None
        record_paths = finding.get("record_paths")
        if not isinstance(record_paths, list) or len(record_paths) > 32:
            return None
        safe_paths = []
        seen_paths: set[str] = set()
        for record_path in record_paths:
            path = _safe_staged_gate_record_path(record_path, stage=stage)
            if path is None or path in seen_paths:
                return None
            seen_paths.add(path)
            safe_paths.append(path)
        findings.append({"rule_code": rule_code, "record_paths": safe_paths})
    return findings


def _project_graph_review_diagnostic(value: object) -> dict[str, Any] | None:
    """Copy only fixed-shape review metadata from internal evaluation events."""
    if isinstance(value, dict) and value.get("kind") == "staged_gate":
        if (
            set(value) != _STAGED_GRAPH_DIAGNOSTIC_FIELDS
            or value.get("schema_version") != 1
            or value.get("stage") not in _STAGED_GRAPH_STAGES
            or not isinstance(value.get("attempt"), int)
            or isinstance(value.get("attempt"), bool)
            or not 1 <= value["attempt"] <= 2
            or value.get("code") not in _STAGED_GATE_CODES
            or not isinstance(value.get("candidate_fingerprint"), str)
            or not _SHA256_FINGERPRINT.fullmatch(value["candidate_fingerprint"])
        ):
            return None
        findings = _safe_staged_gate_findings(
            value.get("findings"), stage=value["stage"]
        )
        if findings is None:
            return None
        return {
            "schema_version": 1,
            "kind": "staged_gate",
            "stage": value["stage"],
            "attempt": value["attempt"],
            "code": value["code"],
            "candidate_fingerprint": value["candidate_fingerprint"],
            "findings": findings,
        }
    if isinstance(value, dict) and value.get("kind") == "staged_generation":
        if (
            set(value) != _STAGED_GENERATION_DIAGNOSTIC_FIELDS
            or value.get("schema_version") != 1
            or value.get("stage") not in _STAGED_GRAPH_STAGES
            or not isinstance(value.get("attempt"), int)
            or isinstance(value.get("attempt"), bool)
            or not 1 <= value["attempt"] <= 2
            or not isinstance(value.get("code"), str)
            or not _SAFE_GRAPH_REVIEW_RULE.fullmatch(value["code"])
            or not isinstance(value.get("path"), str)
            or not _SAFE_GRAPH_REVIEW_TEXT.fullmatch(value.get("path"))
            or value.get("fingerprint_disposition")
            not in _STAGED_GRAPH_FINGERPRINT_DISPOSITIONS
            or not all(
                isinstance(value.get(field), str)
                and _SHA256_FINGERPRINT.fullmatch(value[field])
                for field in ("path_fingerprint", "candidate_fingerprint")
            )
        ):
            return None
        return {field: value[field] for field in _STAGED_GENERATION_DIAGNOSTIC_FIELDS}
    if not isinstance(value, dict) or set(value) - _GRAPH_REVIEW_DIAGNOSTIC_FIELDS:
        return None
    required_fields = _GRAPH_REVIEW_DIAGNOSTIC_FIELDS - {
        "validation_rule",
        "validation_path_fingerprint",
    }
    if not required_fields.issubset(value) or value.get("schema_version") != 1:
        return None
    if not all(
        _is_nonnegative_int(value.get(field)) for field in _GRAPH_REVIEW_COUNTER_FIELDS
    ):
        return None
    if value.get("depth") not in _GRAPH_REVIEW_DEPTHS:
        return None
    if value.get("review_disposition") not in _GRAPH_REVIEW_DISPOSITIONS:
        return None

    layers = {}
    for field in ("locked_layers", "reopened_layers"):
        layer_values = _safe_graph_review_texts(value.get(field))
        if layer_values is None or not set(layer_values).issubset(_GRAPH_REVIEW_LAYERS):
            return None
        layers[field] = layer_values
    if set(layers["locked_layers"]) & set(layers["reopened_layers"]):
        return None

    lists = {}
    for field in ("finding_codes", "blocker_ids"):
        field_values = _safe_graph_review_texts(value.get(field))
        if field_values is None:
            return None
        lists[field] = field_values
    fingerprints = value.get("selector_fingerprints")
    if (
        not isinstance(fingerprints, list)
        or len(fingerprints) > 64
        or not all(
            isinstance(item, str) and _SHA256_FINGERPRINT.fullmatch(item)
            for item in fingerprints
        )
        or len(fingerprints) != len(set(fingerprints))
    ):
        return None
    dispositions = _safe_graph_review_dispositions(
        value.get("prior_blocker_dispositions")
    )
    if dispositions is None:
        return None

    projected = {
        "schema_version": 1,
        **{field: value[field] for field in _GRAPH_REVIEW_COUNTER_FIELDS},
        "depth": value["depth"],
        **layers,
        **lists,
        "selector_fingerprints": sorted(fingerprints),
        "prior_blocker_dispositions": dispositions,
        "review_disposition": value["review_disposition"],
    }
    validation_rule = value.get("validation_rule")
    if validation_rule is not None:
        if not isinstance(
            validation_rule, str
        ) or not _SAFE_GRAPH_REVIEW_RULE.fullmatch(validation_rule):
            return None
        projected["validation_rule"] = validation_rule
    validation_path_fingerprint = value.get("validation_path_fingerprint")
    if validation_path_fingerprint is not None:
        if not isinstance(
            validation_path_fingerprint, str
        ) or not _SHA256_FINGERPRINT.fullmatch(validation_path_fingerprint):
            return None
        projected["validation_path_fingerprint"] = validation_path_fingerprint
    return projected


def _graph_review_diagnostics_from_events(events: object) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    diagnostics = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "workflow_progress":
            continue
        diagnostic = _project_graph_review_diagnostic(event.get("diagnostic"))
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return diagnostics


def _assert_approved_judge_identity(corpus: Any, judge: Any) -> None:
    identity = corpus.approval.calibration
    if identity.judge_release != JUDGE_PROMPT_RELEASE:
        raise RuntimeError(
            "active judge prompt release is not approved for this corpus"
        )
    if identity.judge_provider != getattr(judge, "provider", "openai"):
        raise RuntimeError("active judge provider is not approved for this corpus")
    if identity.judge_model != judge.model:
        raise RuntimeError("active judge model is not approved for this corpus")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply deterministic and reviewed semantic gates"
    )
    parser.add_argument("--suite", required=True)
    parser.add_argument("--target", required=True, help="Backend candidate URL")
    parser.add_argument("--input", help="Browser capture JSON from eval.browser_runner")
    parser.add_argument("--output", default="artifacts/live-eval/live-results.json")
    parser.add_argument("--require-approved-corpus", action="store_true")
    parser.add_argument(
        "--manual-review-policy",
        choices=("blocking", "report-only"),
        default="blocking",
        help=(
            "Whether an otherwise healthy manual-review result blocks the command. "
            "Report-only is restricted to an approved corpus and never masks clear "
            "quality or infrastructure failures."
        ),
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Expected explicit corpus case in the diagnostic suite (repeatable)",
    )
    parser.add_argument(
        "--capture-replay",
        action="store_true",
        help="Rejudge saved browser evidence without charging application calls again",
    )
    parser.add_argument(
        "--resume-input",
        help="Prior semantic-replay report whose authenticated valid judgments can be reused",
    )
    return parser


def _manifest() -> dict[str, Any]:
    return json.loads(QUALITY_MANIFEST.read_text(encoding="utf-8"))


def _load_capture(args: argparse.Namespace) -> dict[str, Any]:
    if not args.input:
        raise RuntimeError(
            "live evaluation requires a browser capture. Run './scripts/ci browser --suite ...' first and pass --input."
        )
    capture = json.loads((ROOT / args.input).read_text(encoding="utf-8"))
    if capture.get("kind") != "browser_capture" or capture.get("suite") != args.suite:
        raise RuntimeError(
            "browser capture kind or suite does not match this live evaluation"
        )
    if capture.get("backend_target", "").rstrip("/") != args.target.rstrip("/"):
        raise RuntimeError("browser capture backend target does not match --target")
    if capture.get("corpus_sha256") != corpus_sha256():
        raise RuntimeError(
            "browser capture was produced with a different corpus manifest"
        )
    return capture


def _load_resume_evaluations(
    args: argparse.Namespace,
    corpus: Any,
    judge: Any,
    actual_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not args.resume_input:
        return {}
    if not args.capture_replay:
        raise RuntimeError("judge resume is restricted to authenticated capture replay")
    report = json.loads((ROOT / args.resume_input).read_text(encoding="utf-8"))
    expected_identity = {
        "kind": "live_gate",
        "execution_mode": "semantic_replay",
        "suite": args.suite,
        "target": args.target,
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": corpus_sha256(),
        "release_identity": corpus.release_identity,
    }
    for key, expected in expected_identity.items():
        if report.get(key) != expected:
            raise RuntimeError(f"resume report {key} does not match this replay")
    raw_evaluations = report.get("evaluations")
    if not isinstance(raw_evaluations, list):
        raise RuntimeError("resume report evaluations are missing")
    resume_ids = [item.get("id") for item in raw_evaluations if isinstance(item, dict)]
    if resume_ids != actual_ids:
        raise RuntimeError("resume report cases do not match the browser capture")

    reusable: dict[str, dict[str, Any]] = {}
    for evaluation in raw_evaluations:
        judgments = evaluation.get("judgments") or []
        if evaluation.get("decision") == "infrastructure" or not judgments:
            continue
        case_id = str(evaluation.get("id") or "")
        case = corpus.by_id[case_id]
        if evaluation.get("decision") not in {"pass", "manual_review", "fail"}:
            raise RuntimeError(f"resume report has an invalid decision for {case_id}")
        if evaluation.get("deterministic_failures"):
            raise RuntimeError(
                f"resume judgment for {case_id} has deterministic failures"
            )
        for judgment in judgments:
            if judgment.get("provider") != judge.provider:
                raise RuntimeError(
                    f"resume judge provider does not match for {case_id}"
                )
            if judgment.get("model") != judge.model:
                raise RuntimeError(f"resume judge model does not match for {case_id}")
            if judgment.get("prompt_release") != JUDGE_PROMPT_RELEASE:
                raise RuntimeError(f"resume judge release does not match for {case_id}")
            dimensions = judgment.get("dimensions") or []
            names = [item.get("dimension") for item in dimensions]
            if names != list(case.rubric_dimensions):
                raise RuntimeError(
                    f"resume judgment dimensions do not match for {case_id}"
                )
            for dimension in dimensions:
                evidence = dimension.get("evidence")
                if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
                    raise RuntimeError(
                        f"resume judgment evidence is invalid for {case_id}"
                    )
        reusable[case_id] = evaluation
    return reusable


def _compact_judge_graph(graph: Any) -> dict[str, Any] | None:
    if isinstance(graph, dict):
        compact_graph = {
            key: graph[key]
            for key in (
                "graph_type",
                "title",
                "design_origin",
                "resolved_complexity",
                "assumptions",
                "groups",
                "sequence",
                "version",
            )
            if graph.get(key) is not None
        }
        compact_graph["artifact_role"] = "browser-rendered diagram"
        compact_graph["nodes"] = [
            {
                key: node[key]
                for key in (
                    "id",
                    "label",
                    "type",
                    "technology",
                    "description",
                    "tier",
                    "layer",
                )
                if node.get(key) is not None
            }
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
        ]
        compact_graph["edges"] = [
            {
                key: edge[key]
                for key in ("source", "target", "label", "technology")
                if edge.get(key) is not None
            }
            for edge in graph.get("edges") or []
            if isinstance(edge, dict)
        ]
        return compact_graph
    return None


def _compact_judge_turns(
    turn_records: list[dict[str, Any]],
    *,
    answer_limit: int,
) -> list[dict[str, Any]]:
    compact_turns: list[dict[str, Any]] = []
    for index, source in enumerate(turn_records, start=1):
        answer = str(source.get("answer") or "")
        compact_turn = {"turn": index, "answer": answer[:answer_limit]}
        graph = _compact_judge_graph(source.get("graph"))
        if graph is not None:
            compact_turn.update(
                {
                    "graph": graph,
                    "rendered_graph_version": source.get("rendered_graph_version"),
                    "rendered_node_ids": source.get("rendered_node_ids") or [],
                    "rendered_edge_identities": source.get("rendered_edge_identities")
                    or [],
                }
            )
        compact_turns.append(compact_turn)
    return compact_turns


def _judge_payload(result: dict[str, Any]) -> dict[str, Any]:
    compact_graph = _compact_judge_graph(result.get("graph"))
    captured_turns = result.get("turns")
    if isinstance(captured_turns, list) and captured_turns:
        captured_turn_records = [
            turn if isinstance(turn, dict) else {"answer": str(turn or "")}
            for turn in captured_turns
        ]
    else:
        captured_turn_records = [
            {"answer": answer}
            for answer in extract_response_turns(result.get("events") or [])
        ]
    per_turn_limit = (
        max(1, 40_000 // len(captured_turn_records)) if captured_turn_records else 0
    )

    retrieval_chunks: list[dict[str, Any]] = []
    research_results: list[dict[str, Any]] = []
    for event in result.get("events") or []:
        if event.get("type") == "research_evidence":
            query = str(event.get("query") or "")[:500]
            eval_turn = event.get("eval_turn")
            event_results = event.get("results")
            if isinstance(event_results, list):
                for item in event_results[:6]:
                    result_record = {"query": query, "result": str(item)[:1_000]}
                    if eval_turn is not None:
                        result_record["eval_turn"] = eval_turn
                    research_results.append(result_record)
            continue
        if event.get("type") != "retrieval_evidence":
            continue
        query = str(event.get("query") or "")[:500]
        eval_turn = event.get("eval_turn")
        for chunk in event.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            chunk_record = {
                "query": query,
                **{
                    key: chunk.get(key)
                    for key in (
                        "book",
                        "chapter",
                        "chapter_title",
                        "section",
                        "page_number",
                        "parent_chunk_id",
                    )
                },
                "text": str(chunk.get("text") or ""),
            }
            if eval_turn is not None:
                chunk_record["eval_turn"] = eval_turn
            retrieval_chunks.append(chunk_record)
    retrieval_text_limit = (
        max(500, 20_000 // len(retrieval_chunks)) if retrieval_chunks else 0
    )
    for chunk in retrieval_chunks:
        chunk["text"] = chunk["text"][:retrieval_text_limit]

    payload = {
        "graph": compact_graph,
        "retrieval_evidence": retrieval_chunks,
        "research_evidence": research_results[:12],
        "events": [
            event
            for event in result.get("events") or []
            if event.get("type")
            in {
                "worker_status",
                "retrieval_notice",
                "graph_notice",
                "provider_switch",
                "done",
                "error",
            }
        ],
    }
    if captured_turn_records:
        payload["turns"] = _compact_judge_turns(
            captured_turn_records,
            answer_limit=per_turn_limit,
        )
    else:
        payload["answer"] = str(result.get("answer") or "")[:40_000]
    return payload


def _result_to_json(result) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "model": result.model,
        "prompt_release": JUDGE_PROMPT_RELEASE,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": estimated_judge_cost_usd(result),
        "dimensions": [
            {
                "dimension": item.dimension,
                "grade": item.grade,
                "critical": item.critical,
                "evidence": list(item.evidence),
                "rationale": item.rationale,
            }
            for item in result.dimensions
        ],
    }


def _classify_deterministic(
    failures: list[str],
    failure_details: object = None,
) -> str:
    if failure_details is not None:
        if not isinstance(failure_details, list) or not failure_details:
            raise RuntimeError(
                "browser capture failure_details must be a non-empty list"
            )
        failure_kinds = []
        for detail in failure_details:
            if not isinstance(detail, dict) or detail.get("kind") not in _FAILURE_KINDS:
                raise RuntimeError(
                    "browser capture failure_details contains an invalid kind"
                )
            failure_kinds.append(detail["kind"])
        return (
            "infrastructure"
            if all(kind == "infrastructure" for kind in failure_kinds)
            else "quality"
        )
    return (
        "infrastructure"
        if any(PROVIDER_FAILURE.search(failure) for failure in failures)
        else "quality"
    )


def _exit_code_for_statuses(
    statuses: set[str],
    manual_review_policy: ManualReviewPolicy,
) -> int:
    """Map semantic outcomes to process health without conflating review with failure."""
    if "fail" in statuses:
        return 1
    if "infrastructure" in statuses:
        return 2
    if "manual_review" in statuses and manual_review_policy == "blocking":
        return 3
    return 0


async def evaluate(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    manual_review_policy: ManualReviewPolicy = args.manual_review_policy
    if manual_review_policy == "report-only" and (
        not args.require_approved_corpus or not args.capture_replay
    ):
        raise RuntimeError(
            "report-only manual review is restricted to approved semantic replay"
        )
    manifest = _manifest()
    limits = manifest["live"]["budgets"]
    corpus = load_corpus(require_approved=args.require_approved_corpus)
    capture = _load_capture(args)
    expected_ids = manifest["live"]["suites"].get(args.suite)
    if args.suite == "diagnostic":
        expected_ids = args.case
        if (
            not expected_ids
            or len(expected_ids) > 8
            or len(expected_ids) != len(set(expected_ids))
        ):
            raise RuntimeError(
                "diagnostic live suite requires one to eight unique --case values"
            )
        unknown = sorted(set(expected_ids) - set(corpus.by_id))
        if unknown:
            raise RuntimeError("unknown diagnostic live cases: " + ", ".join(unknown))
    elif args.case:
        raise RuntimeError("--case is accepted only with --suite diagnostic")
    elif expected_ids is None and args.suite != "nightly":
        raise RuntimeError(f"unknown live suite: {args.suite}")
    actual_ids = [result["id"] for result in capture["results"]]
    if expected_ids is not None and actual_ids != expected_ids:
        raise RuntimeError(
            f"browser capture cases do not match suite: expected {expected_ids}, got {actual_ids}"
        )
    if args.suite == "pr" and len(actual_ids) > limits["pr_cases"]:
        raise RuntimeError("PR case budget exceeded")

    is_pr_budget = args.suite in {"pr", "smoke", "diagnostic"}
    budget = EvaluationBudget(
        application_calls=(
            limits["application_calls"]
            if is_pr_budget
            else limits["application_full_calls"]
        ),
        judge_calls=limits["judge_calls"] if is_pr_budget else 40,
    )
    app_telemetry = capture.get("application_telemetry") or []
    if capture.get("results") and not app_telemetry:
        raise RuntimeError(
            "browser capture contains no application model-call telemetry"
        )
    budget.record_application_calls(
        sum(max(1, int(call.get("provider_attempts") or 1)) for call in app_telemetry)
    )
    application_cost = account_application_cost(capture["results"], app_telemetry)
    cost_policy_config = manifest["live"].get("cost_policy") or {}
    if not isinstance(cost_policy_config, dict):
        raise RuntimeError("live cost policy must be an object")
    cost_policy = evaluate_cost_policy(
        application_cost,
        CostPolicy(
            mode=cost_policy_config.get("mode", "report-only"),
            suite_limit_usd=cost_policy_config.get("suite_limit_usd"),
            case_limit_usd=cost_policy_config.get("case_limit_usd"),
            baseline_min_runs=int(cost_policy_config.get("baseline_min_runs", 5)),
        ),
    )
    judge = SemanticJudge()
    if args.require_approved_corpus:
        _assert_approved_judge_identity(corpus, judge)
    resume_evaluations = _load_resume_evaluations(
        args,
        corpus,
        judge,
        actual_ids,
    )
    evaluations: list[dict[str, Any]] = []

    for browser_result in capture["results"]:
        case = corpus.by_id[browser_result["id"]]
        graph_review_diagnostics = _graph_review_diagnostics_from_events(
            browser_result.get("events")
        )
        resumed = resume_evaluations.get(case.id)
        if resumed is not None:
            for _judgment in resumed["judgments"]:
                budget.record_judge_call()
            evaluations.append(
                {**resumed, "graph_review_diagnostics": graph_review_diagnostics}
            )
            continue
        deterministic_failures = tuple(
            browser_result.get("deterministic_failures") or []
        )
        if deterministic_failures:
            classification = _classify_deterministic(
                list(deterministic_failures),
                browser_result.get("failure_details"),
            )
            decision = GateDecision(
                "infrastructure" if classification == "infrastructure" else "fail",
                "; ".join(deterministic_failures),
            )
            evaluations.append(
                {
                    "id": case.id,
                    "decision": decision.status,
                    "reason": decision.reason,
                    "deterministic_failures": list(deterministic_failures),
                    "judgments": [],
                    "graph_review_diagnostics": graph_review_diagnostics,
                }
            )
            continue

        payload = _judge_payload(browser_result)
        judgments = []
        try:
            first = await judge_with_transport_retry(
                judge,
                corpus,
                case,
                payload,
                on_attempt=budget.record_judge_call,
            )
            judgments.append(first)
            decision = decide_semantic_gate(first)
            if (
                decision.status == "infrastructure"
                and "second independent" in decision.reason
            ):
                second = await judge_with_transport_retry(
                    judge,
                    corpus,
                    case,
                    payload,
                    on_attempt=budget.record_judge_call,
                )
                judgments.append(second)
                decision = decide_semantic_gate(first, second)
        except Exception as exc:
            decision = GateDecision(
                "infrastructure",
                f"judge infrastructure failure: {type(exc).__name__}: {exc}",
            )
        evaluations.append(
            {
                "id": case.id,
                "decision": decision.status,
                "reason": decision.reason,
                "deterministic_failures": [],
                "judgments": [_result_to_json(item) for item in judgments],
                "graph_review_diagnostics": graph_review_diagnostics,
            }
        )

    statuses = {item["decision"] for item in evaluations}
    if cost_policy["status"] == "infrastructure":
        statuses.add("infrastructure")
    elif cost_policy["blocking_status"] == "fail":
        statuses.add("fail")
    # Quality failures retain their higher-priority exit even when accounting is
    # also unavailable, so telemetry health never hides a product regression.
    semantic_exit_code = _exit_code_for_statuses(statuses, "blocking")
    exit_code = _exit_code_for_statuses(statuses, manual_review_policy)
    judge_cost = account_judge_cost(evaluations)
    source_application_cost = application_cost["total"]["estimated_usd"]
    report = {
        "format_version": 1,
        "kind": "live_gate",
        "execution_mode": "semantic_replay" if args.capture_replay else "staging_gate",
        "suite": args.suite,
        "target": args.target,
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": corpus_sha256(),
        "corpus_approval": corpus.approval.status,
        "release_identity": corpus.release_identity,
        "created_at": datetime.now(UTC).isoformat(),
        "status": (
            "pass"
            if semantic_exit_code == 0
            else "fail"
            if semantic_exit_code == 1
            else "infrastructure"
            if semantic_exit_code == 2
            else "manual_review"
        ),
        "manual_review_policy": manual_review_policy,
        "blocking_status": "pass" if exit_code == 0 else "fail",
        "reason": cost_policy["reason"],
        "budget": {
            "application_calls": budget.application_calls,
            "application_limit": budget.application_limit,
            "judge_calls": budget.judge_calls,
            "judge_limit": budget.judge_limit,
        },
        "resumed_case_ids": list(resume_evaluations),
        "application_telemetry": app_telemetry,
        "cost_accounting": {
            "policy": cost_policy,
            "application": application_cost,
            "judge": judge_cost,
        },
        "estimated_cost": {
            "currency": "USD",
            "price_release": application_cost["price_release"],
            "application_usd": (0 if args.capture_replay else source_application_cost),
            "source_application_usd": source_application_cost,
            "judge_usd": judge_cost["total"]["estimated_usd"],
        },
        "evaluations": evaluations,
    }
    return report, exit_code


def _write_outputs(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_only_review = report.get("manual_review_policy") == "report-only"

    def junit_outcome(item: dict[str, Any]) -> str:
        if item["decision"] == "pass":
            return ""
        message = html.escape(item["reason"], quote=True)
        if item["decision"] == "manual_review" and report_only_review:
            return f'<skipped message="{message}" />'
        return f'<failure message="{message}" />'

    failures = sum(
        item["decision"] != "pass"
        and not (item["decision"] == "manual_review" and report_only_review)
        for item in report["evaluations"]
    )
    skipped = sum(
        item["decision"] == "manual_review" and report_only_review
        for item in report["evaluations"]
    )
    cost_accounting = report.get("cost_accounting") or {}
    cost_policy = cost_accounting.get("policy") or {}
    cost_test = ""
    if cost_policy:
        cost_status = str(cost_policy.get("status") or "infrastructure")
        cost_reason = str(cost_policy.get("reason") or cost_status)
        cost_is_failure = (
            cost_status == "infrastructure"
            or cost_policy.get("blocking_status") == "fail"
        )
        cost_is_skipped = cost_status == "over_budget" and not cost_is_failure
        if cost_is_failure:
            cost_outcome = (
                f'<failure message="{html.escape(cost_reason, quote=True)}" />'
            )
            failures += 1
        elif cost_is_skipped:
            cost_outcome = (
                f'<skipped message="{html.escape(cost_reason, quote=True)}" />'
            )
            skipped += 1
        else:
            cost_outcome = ""
        cost_test = (
            '<testcase classname="live.accounting" name="application-cost-policy">'
            + cost_outcome
            + "</testcase>"
        )
    cases = "".join(
        f'<testcase classname="live.semantic" name="{html.escape(item["id"])}">'
        + junit_outcome(item)
        + "</testcase>"
        for item in report["evaluations"]
    )
    test_count = len(report["evaluations"]) + bool(cost_test)
    (path.parent / "live-junit.xml").write_text(
        f'<testsuite name="live semantic gate" tests="{test_count}" '
        f'failures="{failures}" skipped="{skipped}">{cases}{cost_test}</testsuite>\n',
        encoding="utf-8",
    )
    _write_semantic_review(path.parent / "semantic-review.html", report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Live evaluation",
            "",
            f"Status: **{report.get('status', 'infrastructure')}**",
            f"CI outcome: **{report.get('blocking_status', 'fail')}**",
        ]
        if report.get("manual_review_policy"):
            lines.append(f"Manual-review policy: `{report['manual_review_policy']}`")
        if report.get("corpus_version"):
            lines.append(
                f"Corpus: `{report['corpus_version']}` ({report.get('corpus_approval', 'unknown')})"
            )
        if report.get("budget"):
            lines.append(
                f"Calls: {report['budget']['application_calls']} application / "
                f"{report['budget']['judge_calls']} judge"
            )
        if cost_policy:
            lines.append(
                "Cost policy: "
                f"`{cost_policy.get('status', 'infrastructure')}` "
                f"({cost_policy.get('mode', 'unknown')})"
            )
            application_total = (
                (cost_accounting.get("application") or {})
                .get("total", {})
                .get("estimated_usd")
            )
            lines.append(
                "Application cost: "
                + (
                    f"`${float(application_total):.6f}`"
                    if application_total is not None
                    else "`unknown`"
                )
            )
        if report.get("reason"):
            lines.append(f"Reason: {report['reason']}")
        lines.extend(["", "| Case | Decision | Reason |", "| --- | --- | --- |"])
        lines.extend(
            f"| {item['id']} | {item['decision']} | {item['reason'].replace('|', '/')} |"
            for item in report["evaluations"]
        )
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")


def _write_semantic_review(path: Path, report: dict[str, Any]) -> None:
    cases = []
    for evaluation in report.get("evaluations") or []:
        judgments = evaluation.get("judgments") or []
        dimensions = []
        for index, judgment in enumerate(judgments, start=1):
            for item in judgment.get("dimensions") or []:
                evidence = "; ".join(item.get("evidence") or [])
                dimensions.append(
                    "<tr>"
                    f"<td>{index}</td><td>{html.escape(item['dimension'])}</td>"
                    f"<td>{html.escape(item['grade'])}</td>"
                    f"<td>{html.escape(evidence)}</td>"
                    f"<td>{html.escape(item.get('rationale') or '')}</td>"
                    "</tr>"
                )
        cases.append(
            f"<article><h2>{html.escape(evaluation['id'])} — "
            f"{html.escape(evaluation['decision'])}</h2>"
            f"<p>{html.escape(evaluation.get('reason') or '')}</p>"
            "<table><thead><tr><th>Judge</th><th>Dimension</th><th>Grade</th>"
            "<th>Cited evidence</th><th>Rationale</th></tr></thead><tbody>"
            + "".join(dimensions)
            + "</tbody></table></article>"
        )
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Semantic review</title>"
        "<style>body{font:15px system-ui;max-width:1200px;margin:auto;background:#111;color:#eee}"
        "article{border-bottom:1px solid #444;padding:24px}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #555;padding:8px;text-align:left;vertical-align:top}</style>"
        f"<h1>Semantic proposals — {html.escape(report.get('status') or 'unknown')}</h1>"
        + "".join(cases),
        encoding="utf-8",
    )


async def main() -> None:
    args = build_parser().parse_args()
    output = ROOT / args.output
    try:
        timeout_seconds = semantic_suite_timeout_seconds(args.suite)
        report, exit_code = await asyncio.wait_for(
            evaluate(args), timeout=timeout_seconds
        )
    except TimeoutError:
        report = {
            "format_version": 1,
            "kind": "live_gate",
            "suite": args.suite,
            "target": args.target,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "infrastructure",
            "manual_review_policy": args.manual_review_policy,
            "blocking_status": "fail",
            "evaluations": [],
            "reason": f"{timeout_seconds}-second semantic evaluation budget exhausted",
        }
        exit_code = 2
    except Exception as exc:
        report = {
            "format_version": 1,
            "kind": "live_gate",
            "suite": args.suite,
            "target": args.target,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "infrastructure",
            "manual_review_policy": args.manual_review_policy,
            "blocking_status": "fail",
            "evaluations": [],
            "reason": f"live evaluation could not start: {type(exc).__name__}: {exc}",
        }
        exit_code = 2
    _write_outputs(output, report)
    if report.get("status") == "manual_review" and exit_code == 0:
        print(
            "::warning title=Semantic evaluation requires review::"
            "Borderline or disagreeing judgments were retained as report-only evidence."
        )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
