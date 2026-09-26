import asyncio
from copy import deepcopy
from dataclasses import replace
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock

from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
    APITimeoutError as AnthropicAPITimeoutError,
    RateLimitError as AnthropicRateLimitError,
)
import httpx
import pytest

import eval.judge_adapter as judge_adapter
import eval.live_runner as live_runner
from eval.calibration import calculate_calibration
from eval.judge_adapter import (
    DEFAULT_ANTHROPIC_JUDGE_MODEL,
    JUDGE_PROMPT_RELEASE,
    SemanticJudge,
    _RawJudgment,
    _anthropic_response_schema,
    _artifact_sources,
    _add_bounded_sources,
    _judge_prompt,
    _response_schema,
    _validate_evidence,
    estimated_judge_cost_usd,
    judge_with_transport_retry,
)
from eval.live_runner import (
    _assert_approved_judge_identity,
    _classify_deterministic,
    _exit_code_for_statuses,
    _graph_review_diagnostics_from_events,
    _judge_payload,
    _load_resume_evaluations,
    _write_outputs,
    evaluate,
)
from eval.quality_corpus import corpus_sha256, load_corpus
from eval.semantic_gate import (
    DimensionJudgment,
    EvaluationBudget,
    JudgeResult,
    calibration_passes,
    decide_semantic_gate,
)


def result(*grades: tuple[str, str, bool]) -> JudgeResult:
    return JudgeResult(
        dimensions=tuple(
            DimensionJudgment(name, grade, critical, ("evidence",), "reason")
            for name, grade, critical in grades
        ),
        provider="judge-provider",
        model="judge-model",
        input_tokens=10,
        output_tokens=5,
    )


def test_deterministic_failure_blocks_without_semantic_override():
    decision = decide_semantic_gate(
        result(("correctness", "pass", False)),
        deterministic_failures=("graph missing",),
    )

    assert decision.status == "fail"
    assert "graph missing" in decision.reason


def test_two_clear_critical_failures_block():
    first = result(("safety", "fail", True), ("relevance", "pass", False))
    second = result(("safety", "fail", True), ("relevance", "pass", False))

    assert decide_semantic_gate(first, second).status == "fail"


def test_critical_failure_takes_precedence_over_borderline_dimension():
    judgment = result(("safety", "fail", True), ("relevance", "borderline", False))

    first = decide_semantic_gate(judgment)
    assert first.status == "fail"
    assert (
        decide_semantic_gate(
            judgment, result(("relevance", "borderline", False))
        ).status
        == "fail"
    )
    assert (
        decide_semantic_gate(result(("safety", "pass", True)), judgment).status
        == "fail"
    )


def test_noncritical_judge_disagreement_requires_manual_review():
    first = result(("safety", "pass", True), ("relevance", "fail", False))
    second = result(("safety", "pass", True), ("relevance", "pass", False))

    assert decide_semantic_gate(first, second).status == "manual_review"


def test_borderline_requires_manual_review_without_retry():
    first = result(("safety", "pass", True), ("relevance", "borderline", False))

    assert decide_semantic_gate(first).status == "manual_review"


def test_report_only_review_never_masks_clear_or_infrastructure_failures():
    assert _exit_code_for_statuses({"manual_review"}, "blocking") == 3
    assert _exit_code_for_statuses({"manual_review"}, "report-only") == 0
    assert _exit_code_for_statuses({"manual_review", "fail"}, "report-only") == 1
    assert (
        _exit_code_for_statuses({"manual_review", "infrastructure"}, "report-only") == 2
    )


def test_typed_browser_failure_details_override_legacy_error_text():
    assert (
        _classify_deterministic(
            ["provider timed out"],
            [{"kind": "quality"}],
        )
        == "quality"
    )
    assert (
        _classify_deterministic(
            ["graph data was withheld"],
            [{"kind": "infrastructure"}],
        )
        == "infrastructure"
    )


def test_legacy_deterministic_failure_without_details_uses_text_classification():
    assert _classify_deterministic(["provider timed out"]) == "infrastructure"


def test_invalid_typed_browser_failure_details_are_rejected():
    with pytest.raises(RuntimeError, match="invalid kind"):
        _classify_deterministic(["provider timed out"], [{"kind": "unknown"}])


def test_graph_review_diagnostics_project_only_allowlisted_metadata():
    fingerprint = "a" * 64
    events = [
        {
            "type": "workflow_progress",
            "diagnostic": {
                "schema_version": 1,
                "repair_round": 1,
                "critic_call_count": 2,
                "protocol_correction_count": 0,
                "contract_correction_count": 1,
                "depth": "prototype",
                "locked_layers": ["render"],
                "reopened_layers": ["composition", "connections"],
                "finding_codes": ["edge_semantics"],
                "blocker_ids": ["rubric:connections:edge_semantics"],
                "selector_fingerprints": [fingerprint],
                "prior_blocker_dispositions": [
                    {"prior_obligation_id": "blocker-1", "status": "resolved"}
                ],
                "review_disposition": "rejected",
                "validation_rule": "locked_record_changed",
                "validation_path_fingerprint": fingerprint,
                "raw_prompt": "discard this",
            },
        },
        {
            "type": "workflow_progress",
            "diagnostic": {
                "schema_version": 1,
                "repair_round": 1,
                "critic_call_count": 2,
                "protocol_correction_count": 0,
                "contract_correction_count": 1,
                "depth": "prototype",
                "locked_layers": ["render"],
                "reopened_layers": ["composition", "connections"],
                "finding_codes": ["edge_semantics"],
                "blocker_ids": ["rubric:connections:edge_semantics"],
                "selector_fingerprints": [fingerprint],
                "prior_blocker_dispositions": [
                    {"prior_obligation_id": "blocker-1", "status": "resolved"}
                ],
                "review_disposition": "rejected",
                "validation_rule": "locked_record_changed",
                "validation_path_fingerprint": fingerprint,
            },
        },
    ]

    assert _graph_review_diagnostics_from_events(events) == [
        {
            "schema_version": 1,
            "repair_round": 1,
            "critic_call_count": 2,
            "protocol_correction_count": 0,
            "contract_correction_count": 1,
            "depth": "prototype",
            "locked_layers": ["render"],
            "reopened_layers": ["composition", "connections"],
            "finding_codes": ["edge_semantics"],
            "blocker_ids": ["rubric:connections:edge_semantics"],
            "selector_fingerprints": [fingerprint],
            "prior_blocker_dispositions": [
                {"prior_obligation_id": "blocker-1", "status": "resolved"}
            ],
            "review_disposition": "rejected",
            "validation_rule": "locked_record_changed",
            "validation_path_fingerprint": fingerprint,
        }
    ]


def test_staged_gate_diagnostic_projects_only_fixed_safe_metadata():
    fingerprint = "c" * 64
    diagnostic = {
        "schema_version": 1,
        "kind": "staged_gate",
        "stage": "components",
        "attempt": 2,
        "code": "gate_rejected",
        "candidate_fingerprint": fingerprint,
        "findings": [
            {
                "rule_code": "domain_specificity",
                "record_paths": ["components", "components.0"],
            },
            {
                "rule_code": "capability_classification",
                "record_paths": ["components.3"],
            },
        ],
    }
    events = [
        {
            "type": "workflow_progress",
            "diagnostic": {
                **diagnostic,
                "extra": "discarded",
            },
        },
        {
            "type": "workflow_progress",
            "diagnostic": {**diagnostic, "kind": "staged_generation"},
        },
        {"type": "workflow_progress", "diagnostic": diagnostic},
    ]
    projected = {
        "schema_version": 1,
        "kind": "staged_gate",
        "stage": "components",
        "attempt": 2,
        "code": "gate_rejected",
        "candidate_fingerprint": fingerprint,
        "findings": [
            {
                "rule_code": "domain_specificity",
                "record_paths": ["components", "components.0"],
            },
            {
                "rule_code": "capability_classification",
                "record_paths": ["components.3"],
            },
        ],
    }

    assert _graph_review_diagnostics_from_events(events) == [projected]


def test_staged_generation_diagnostic_projects_only_fixed_safe_metadata():
    fingerprint = "f" * 64
    diagnostic = {
        "schema_version": 1,
        "kind": "staged_generation",
        "stage": "components",
        "attempt": 2,
        "code": "contract_rejected",
        "path": "components.0.label",
        "path_fingerprint": fingerprint,
        "candidate_fingerprint": fingerprint,
        "fingerprint_disposition": "rejected_before_render",
    }
    events = [
        {"type": "workflow_progress", "diagnostic": {**diagnostic, "prompt": "drop"}},
        {
            "type": "workflow_progress",
            "diagnostic": {**diagnostic, "path": "components/0/label"},
        },
        {"type": "workflow_progress", "diagnostic": diagnostic},
    ]

    assert _graph_review_diagnostics_from_events(events) == [diagnostic]


def test_staged_gate_diagnostic_rejects_malformed_payloads():
    fingerprint = "d" * 64
    finding = {
        "rule_code": "domain_specificity",
        "record_paths": ["components.0"],
    }
    diagnostic = {
        "schema_version": 1,
        "kind": "staged_gate",
        "stage": "components",
        "attempt": 2,
        "code": "gate_rejected",
        "candidate_fingerprint": fingerprint,
        "findings": [finding],
    }
    invalid_diagnostics = [
        {**diagnostic, "stage": "composition"},
        {**diagnostic, "attempt": True},
        {**diagnostic, "code": "raw_provider_error"},
        {**diagnostic, "candidate_fingerprint": "short"},
        {**diagnostic, "prompt": "raw prompt"},
        {
            **diagnostic,
            "findings": [{**finding, "reason": "raw model reason"}],
        },
        {
            **diagnostic,
            "findings": [
                {"rule_code": "safe_action_boundary", "record_paths": ["components"]}
            ],
        },
        {
            **diagnostic,
            "findings": [{**finding, "record_paths": ["components.-1"]}],
        },
        {
            **diagnostic,
            "findings": [{**finding, "record_paths": ["components.01"]}],
        },
        {
            **diagnostic,
            "findings": [{**finding, "record_paths": ["components.0", "components.0"]}],
        },
    ]
    events = [
        {"type": "workflow_progress", "diagnostic": value}
        for value in invalid_diagnostics
    ]

    assert _graph_review_diagnostics_from_events(events) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["empty", "subset", "duplicate", "unknown"])
async def test_nightly_evaluation_rejects_incomplete_case_selection(
    monkeypatch, selection
):
    case_ids = live_runner._manifest()["live"]["suites"]["full"][:4]
    selected = {
        "empty": [],
        "subset": case_ids[:3],
        "duplicate": [*case_ids[:3], case_ids[0]],
        "unknown": [*case_ids[:3], "unknown-case"],
    }[selection]
    capture = {"results": [{"id": case_id} for case_id in selected]}
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)

    def unexpected_judge():
        pytest.fail("invalid nightly selections must fail before judge initialization")

    monkeypatch.setattr(live_runner, "SemanticJudge", unexpected_judge)
    with pytest.raises(RuntimeError, match="exactly four unique full-suite cases"):
        await evaluate(
            SimpleNamespace(
                manual_review_policy="blocking",
                require_approved_corpus=False,
                capture_replay=False,
                suite="nightly",
                case=[],
                target="https://candidate.example",
                resume_input=None,
            )
        )


@pytest.mark.asyncio
async def test_nightly_evaluation_accepts_saved_case_selection(monkeypatch):
    case_ids = live_runner._manifest()["live"]["suites"]["full"][:4]
    capture = {
        "started_at": "2026-01-01T00:00:00+00:00",
        "results": [
            {
                "id": case_id,
                "deterministic_failures": ["provider unavailable"],
                "failure_details": [{"kind": "infrastructure"}],
            }
            for case_id in case_ids
        ],
        "application_telemetry": [],
    }
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    report, exit_code = await evaluate(
        SimpleNamespace(
            manual_review_policy="blocking",
            require_approved_corpus=False,
            capture_replay=False,
            suite="nightly",
            case=[],
            target="https://candidate.example",
            resume_input=None,
        )
    )

    assert exit_code == 2
    assert [evaluation["id"] for evaluation in report["evaluations"]] == case_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("telemetry_count", [0, 1, 2])
@pytest.mark.parametrize(
    ("failure_kinds", "expected_exit"),
    [(("quality", "infrastructure"), 1), (("infrastructure", "infrastructure"), 2)],
)
async def test_live_evaluation_preserves_failures_when_telemetry_is_missing(
    monkeypatch, telemetry_count, failure_kinds, expected_exit
):
    cases = load_corpus().cases[:2]
    diagnostic = {
        "schema_version": 1,
        "kind": "staged_gate",
        "stage": "components",
        "attempt": 1,
        "code": "gate_rejected",
        "candidate_fingerprint": "a" * 64,
        "findings": [],
    }
    capture = {
        "results": [
            {
                "id": case.id,
                "thread_id": f"thread-{index}",
                "deterministic_failures": [f"failure-{index}"],
                "failure_details": [{"kind": failure_kinds[index]}],
                "events": [{"type": "workflow_progress", "diagnostic": diagnostic}],
            }
            for index, case in enumerate(cases)
        ],
        "application_telemetry": [
            {
                "thread_id": f"thread-{index}",
                "operation": "synthesis",
                "model": "claude-sonnet-5",
                "input_tokens": 10,
                "output_tokens": 2,
            }
            for index in range(telemetry_count)
        ],
    }
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)

    def unexpected_judge():
        pytest.fail("deterministic failures must not initialize a semantic judge")

    monkeypatch.setattr(live_runner, "SemanticJudge", unexpected_judge)
    report, exit_code = await evaluate(
        SimpleNamespace(
            manual_review_policy="blocking",
            require_approved_corpus=False,
            capture_replay=False,
            suite="diagnostic",
            case=[case.id for case in cases],
            target="https://candidate.example",
            resume_input=None,
        )
    )

    assert exit_code == expected_exit
    assert [item["decision"] for item in report["evaluations"]] == [
        "fail" if kind == "quality" else "infrastructure" for kind in failure_kinds
    ]
    for index, evaluation in enumerate(report["evaluations"]):
        assert evaluation["deterministic_failures"] == [f"failure-{index}"]
        assert evaluation["graph_review_diagnostics"] == [diagnostic]
        assert evaluation["judgments"] == []
    assert report["budget"]["judge_calls"] == 0
    assert report["cost_accounting"]["application"]["status"] == (
        "pass" if telemetry_count == 2 else "infrastructure"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_id", [None, "thread-1"])
async def test_live_evaluation_rejects_success_without_telemetry(
    monkeypatch, thread_id
):
    case = load_corpus().cases[0]
    capture = {
        "results": [
            {
                "id": case.id,
                "thread_id": thread_id,
                "deterministic_failures": [],
                "events": [],
                "answer": "successful-looking answer",
            }
        ],
        "application_telemetry": [],
    }
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)

    def unexpected_judge():
        pytest.fail("missing application telemetry must not trigger judge spending")

    monkeypatch.setattr(live_runner, "SemanticJudge", unexpected_judge)
    report, exit_code = await evaluate(
        SimpleNamespace(
            manual_review_policy="blocking",
            require_approved_corpus=False,
            capture_replay=False,
            suite="diagnostic",
            case=[case.id],
            target="https://candidate.example",
            resume_input=None,
        )
    )

    assert exit_code == 2
    assert report["status"] == "infrastructure"
    assert report["evaluations"][0]["decision"] == "infrastructure"
    assert "no application model-call telemetry" in report["reason"]
    assert report["reason"] == f"{case.id}: {report['evaluations'][0]['reason']}"
    assert report["budget"]["judge_calls"] == 0


@pytest.mark.asyncio
async def test_live_evaluation_records_projected_graph_review_diagnostics(monkeypatch):
    case = load_corpus().cases[0]
    fingerprint = "b" * 64
    capture = {
        "results": [
            {
                "id": case.id,
                "deterministic_failures": ["graph was withheld"],
                "failure_details": [{"kind": "quality"}],
                "events": [
                    {
                        "type": "workflow_progress",
                        "diagnostic": {
                            "schema_version": 1,
                            "repair_round": 0,
                            "critic_call_count": 1,
                            "protocol_correction_count": 0,
                            "contract_correction_count": 0,
                            "depth": "prototype",
                            "locked_layers": [],
                            "reopened_layers": [
                                "components",
                                "connections",
                                "composition",
                            ],
                            "finding_codes": ["edge_semantics"],
                            "blocker_ids": ["rubric:connections:edge_semantics"],
                            "selector_fingerprints": [fingerprint],
                            "prior_blocker_dispositions": [],
                            "review_disposition": "rejected",
                        },
                    }
                ],
            }
        ],
        "application_telemetry": [{"provider_attempts": 1}],
    }
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    monkeypatch.setattr(
        live_runner,
        "_manifest",
        lambda: {
            "live": {
                "budgets": {
                    "application_calls": 2,
                    "application_full_calls": 2,
                    "judge_calls": 2,
                    "pr_cases": 2,
                },
                "cost_policy": {},
                "suites": {},
            }
        },
    )
    monkeypatch.setattr(
        live_runner,
        "account_application_cost",
        lambda *_args: {"total": {"estimated_usd": 0}, "price_release": "test"},
    )
    monkeypatch.setattr(
        live_runner,
        "evaluate_cost_policy",
        lambda *_args: {
            "status": "pass",
            "blocking_status": "pass",
            "reason": "within budget",
        },
    )
    monkeypatch.setattr(
        live_runner,
        "SemanticJudge",
        lambda: SimpleNamespace(provider="anthropic", model="claude-sonnet-5"),
    )

    report, exit_code = await evaluate(
        SimpleNamespace(
            manual_review_policy="blocking",
            require_approved_corpus=False,
            capture_replay=False,
            suite="diagnostic",
            case=[case.id],
            target="https://candidate.example",
            resume_input=None,
        )
    )

    assert exit_code == 1
    assert report["evaluations"][0]["graph_review_diagnostics"] == [
        {
            "schema_version": 1,
            "repair_round": 0,
            "critic_call_count": 1,
            "protocol_correction_count": 0,
            "contract_correction_count": 0,
            "depth": "prototype",
            "locked_layers": [],
            "reopened_layers": ["components", "composition", "connections"],
            "finding_codes": ["edge_semantics"],
            "blocker_ids": ["rubric:connections:edge_semantics"],
            "selector_fingerprints": [fingerprint],
            "prior_blocker_dispositions": [],
            "review_disposition": "rejected",
        }
    ]


@pytest.mark.asyncio
async def test_live_evaluation_records_projected_staged_gate_diagnostics(monkeypatch):
    case = load_corpus().cases[0]
    fingerprint = "e" * 64
    capture = {
        "results": [
            {
                "id": case.id,
                "deterministic_failures": ["graph was withheld"],
                "failure_details": [{"kind": "quality"}],
                "events": [
                    {
                        "type": "workflow_progress",
                        "diagnostic": {
                            "schema_version": 1,
                            "kind": "staged_gate",
                            "stage": "connections",
                            "attempt": 1,
                            "code": "gate_unavailable",
                            "candidate_fingerprint": fingerprint,
                            "findings": [
                                {
                                    "rule_code": "runtime_completeness",
                                    "record_paths": ["connections", "connections.0"],
                                },
                                {
                                    "rule_code": "authorization_and_compensation",
                                    "record_paths": ["connections.1", "connections.11"],
                                },
                                {
                                    "rule_code": "safe_action_boundary",
                                    "record_paths": ["connections.2", "connections.3"],
                                },
                            ],
                        },
                    }
                ],
            }
        ],
        "application_telemetry": [{"provider_attempts": 1}],
    }
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    monkeypatch.setattr(
        live_runner,
        "_manifest",
        lambda: {
            "live": {
                "budgets": {
                    "application_calls": 2,
                    "application_full_calls": 2,
                    "judge_calls": 2,
                    "pr_cases": 2,
                },
                "cost_policy": {},
                "suites": {},
            }
        },
    )
    monkeypatch.setattr(
        live_runner,
        "account_application_cost",
        lambda *_args: {"total": {"estimated_usd": 0}, "price_release": "test"},
    )
    monkeypatch.setattr(
        live_runner,
        "evaluate_cost_policy",
        lambda *_args: {
            "status": "pass",
            "blocking_status": "pass",
            "reason": "within budget",
        },
    )
    monkeypatch.setattr(
        live_runner,
        "SemanticJudge",
        lambda: SimpleNamespace(provider="anthropic", model="claude-sonnet-5"),
    )

    report, exit_code = await evaluate(
        SimpleNamespace(
            manual_review_policy="blocking",
            require_approved_corpus=False,
            capture_replay=False,
            suite="diagnostic",
            case=[case.id],
            target="https://candidate.example",
            resume_input=None,
        )
    )

    assert exit_code == 1
    assert report["evaluations"][0]["graph_review_diagnostics"] == [
        {
            "schema_version": 1,
            "kind": "staged_gate",
            "stage": "connections",
            "attempt": 1,
            "code": "gate_unavailable",
            "candidate_fingerprint": fingerprint,
            "findings": [
                {
                    "rule_code": "runtime_completeness",
                    "record_paths": ["connections", "connections.0"],
                },
                {
                    "rule_code": "authorization_and_compensation",
                    "record_paths": ["connections.1", "connections.11"],
                },
                {
                    "rule_code": "safe_action_boundary",
                    "record_paths": ["connections.2", "connections.3"],
                },
            ],
        }
    ]


def test_live_defaults_allow_automated_evaluation_without_corpus_approval():
    args = live_runner.build_parser().parse_args([
        "--suite", "full", "--target", "https://candidate.example",
    ])
    assert args.manual_review_policy == "report-only"
    assert args.require_approved_corpus is False
    explicit = live_runner.build_parser().parse_args([
        "--suite", "full", "--target", "https://candidate.example",
        "--require-approved-corpus", "--manual-review-policy", "blocking",
    ])
    assert explicit.require_approved_corpus is True
    assert explicit.manual_review_policy == "blocking"


def test_noncritical_pass_threshold_is_enforced():
    dimensions = tuple((f"d{i}", "pass" if i < 8 else "fail", False) for i in range(10))

    assert decide_semantic_gate(result(*dimensions)).status == "infrastructure"
    assert (
        decide_semantic_gate(result(*dimensions), result(*dimensions)).status == "fail"
    )


def test_calibration_requires_85_percent_agreement_and_at_most_one_critical_false_pass():
    expected = [("pass", False)] * 17 + [("fail", True)] * 3
    acceptable = [("pass", False)] * 17 + [
        ("pass", True),
        ("fail", True),
        ("fail", True),
    ]
    unsafe = [("pass", False)] * 17 + [("pass", True)] * 3

    assert calibration_passes(expected, acceptable) == (True, 0.95, 1)
    assert calibration_passes(expected, unsafe) == (False, 0.85, 3)


def test_budget_exhaustion_is_explicit():
    budget = EvaluationBudget(application_calls=2, judge_calls=1)
    budget.record_application_calls(2)
    budget.record_judge_call()

    with pytest.raises(RuntimeError, match="application model-call budget exceeded"):
        budget.record_application_calls(1)
    with pytest.raises(RuntimeError, match="judge model-call budget exceeded"):
        budget.record_judge_call()


def test_judge_evidence_uses_typed_bounded_artifact_sources():
    evidence = {
        "answer": 'The service says "ready" before promotion.',
        "graph": {"nodes": [{"id": "candidate"}]},
        "events": [{"type": "done"}],
    }
    sources = _artifact_sources(evidence)
    raw = _RawJudgment.model_validate(
        {
            "dimensions": {
                "correctness": {
                    "grade": "pass",
                    "evidence": [{"source_id": "answer-1"}],
                    "rationale": "The answer states the promotion guard.",
                }
            },
        }
    )

    _validate_evidence(raw, sources)

    assert sources["answer-1"] == 'The service says "ready" before promotion.'
    assert sources["graph-node-1-1"] == '{"id": "candidate"}'
    assert sources["event-1-1"] == '{"type": "done"}'
    assert all(len(source) <= 500 for source in sources.values())

    long_token_sources = _artifact_sources({"answer": "x" * 1001})
    assert [len(source) for source in long_token_sources.values()] == [500, 500, 1]


def test_judge_evidence_preserves_ordered_conversation_turns():
    sources = _artifact_sources(
        {
            "answer": "legacy concatenated answer",
            "turns": [
                {"turn": 1, "answer": "First explanation."},
                {"turn": 2, "answer": "Two concise mitigations."},
            ],
        }
    )

    assert sources == {
        "turn-1-answer-1": "First explanation.",
        "turn-2-answer-1": "Two concise mitigations.",
    }


def test_judge_evidence_exposes_each_turn_graph_and_render_identity():
    sources = _artifact_sources(
        {
            "turns": [
                {
                    "answer": "Initial architecture.",
                    "graph": {
                        "version": "graph-1",
                        "nodes": [{"id": "original-monitor"}],
                        "edges": [],
                    },
                    "rendered_graph_version": "graph-1",
                    "rendered_node_ids": ["original-monitor"],
                    "rendered_edge_identities": [],
                },
                {
                    "answer": "Focused edit.",
                    "graph": {
                        "version": "graph-2",
                        "nodes": [{"id": "replacement-monitor"}],
                        "edges": [],
                    },
                    "rendered_graph_version": "graph-2",
                    "rendered_node_ids": ["replacement-monitor"],
                    "rendered_edge_identities": [],
                },
            ]
        }
    )

    assert sources["turn-1-graph-node-1-1"] == '{"id": "original-monitor"}'
    assert "original-monitor" in sources["turn-1-render-1"]
    assert sources["turn-2-graph-node-1-1"] == '{"id": "replacement-monitor"}'


def test_judge_evidence_keeps_retrieval_text_and_provenance_separate():
    sources = _artifact_sources(
        {
            "retrieval_evidence": [
                {
                    "query": "Why should eval data grow?",
                    "book": "AI Engineering",
                    "chapter": 8,
                    "page_number": 404,
                    "parent_chunk_id": "ai-engineering:8:404:0",
                    "text": "Evaluation examples can seed synthesized data.",
                }
            ],
        }
    )

    assert (
        sources["retrieval-1-text-1"]
        == "Evaluation examples can seed synthesized data."
    )
    assert '"page_number": 404' in sources["retrieval-1-metadata-1"]
    assert "text" not in sources["retrieval-1-metadata-1"]

    research_sources = _artifact_sources(
        {
            "research_evidence": [
                {
                    "query": "current agent practice",
                    "result": "Report — <https://example.com/report>: external snippet",
                }
            ],
        }
    )
    assert "https://example.com/report" in research_sources["research-1-result-1"]


def test_judge_schema_local_refs_expand_to_previous_exact_contract():
    source_ids = ("turn-1-answer-1", "turn-1-graph-edge-77-1")
    dimensions = tuple(load_corpus().rubrics)
    schema = _response_schema(source_ids, dimensions)
    dimension_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["grade", "evidence", "rationale"],
        "properties": {
            "grade": {"type": "string", "enum": ["pass", "borderline", "fail"]},
            "evidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_id"],
                    "properties": {
                        "source_id": {"type": "string", "enum": list(source_ids)}
                    },
                },
            },
            "rationale": {"type": "string"},
        },
    }
    expected = {
        "type": "object",
        "additionalProperties": False,
        "required": ["dimensions"],
        "properties": {
            "dimensions": {
                "type": "object",
                "additionalProperties": False,
                "required": list(dimensions),
                "properties": {
                    dimension: deepcopy(dimension_schema) for dimension in dimensions
                },
            }
        },
    }
    expanded = deepcopy(schema)
    assert expanded.pop("$defs") == {"dimension": dimension_schema}
    for dimension in dimensions:
        slot = expanded["properties"]["dimensions"]["properties"][dimension]
        assert slot == {"$ref": "#/$defs/dimension"}
        expanded["properties"]["dimensions"]["properties"][dimension] = deepcopy(
            dimension_schema
        )
    assert expanded == expected

    anthropic_schema = _anthropic_response_schema(schema)
    assert anthropic_schema["$defs"]["dimension"]["properties"]["evidence"] == {
        "type": "array",
        "items": dimension_schema["properties"]["evidence"]["items"],
    }
    assert anthropic_schema["properties"]["dimensions"]["required"] == list(dimensions)
    assert anthropic_schema["properties"]["dimensions"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("grade", "evidence", "rationale"),
    [
        ("unknown", [{"source_id": "answer-1"}], "Reason."),
        ("pass", [], "Reason."),
        ("pass", [{"source_id": "answer-1"}] * 4, "Reason."),
        ("pass", [{"source_id": "answer-1"}], ""),
        ("pass", [{"source_id": "answer-1"}], "x" * 1001),
    ],
)
def test_judge_response_still_rejects_bad_grades_counts_and_rationales(
    grade, evidence, rationale
):
    with pytest.raises(ValueError):
        _RawJudgment.model_validate(
            {
                "dimensions": {
                    "correctness": {
                        "grade": grade,
                        "evidence": evidence,
                        "rationale": rationale,
                    }
                }
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "extra"])
async def test_judge_response_still_rejects_missing_or_extra_dimensions(
    monkeypatch, change
):
    corpus = load_corpus()
    case = corpus.by_id["rag-grounding"]
    dimensions = {
        dimension: {
            "grade": "pass",
            "evidence": [{"source_id": "answer-1"}],
            "rationale": "The cited artifact satisfies the rubric.",
        }
        for dimension in case.rubric_dimensions
    }
    if change == "missing":
        dimensions.pop(case.rubric_dimensions[0])
    else:
        dimensions["unexpected"] = dimensions[case.rubric_dimensions[0]]
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=__import__("json").dumps({"dimensions": dimensions}),
            )
        ],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )
    monkeypatch.setattr(
        "eval.judge_adapter.create_anthropic_client", lambda **_: client
    )
    monkeypatch.setattr("eval.judge_adapter.get_posthog_client", lambda: None)

    with pytest.raises(RuntimeError, match="judge dimensions must be exactly"):
        await SemanticJudge(api_key="test-key", provider="anthropic").judge(
            corpus, case, {"answer": "Artifact text."}
        )


def test_judge_evidence_rejects_an_unknown_source():
    sources = _artifact_sources(
        {"answer": "answer text", "events": [{"status": "ready"}]}
    )
    raw = _RawJudgment.model_validate(
        {
            "dimensions": {
                "correctness": {
                    "grade": "pass",
                    "evidence": [{"source_id": "missing-source"}],
                    "rationale": "Invalid provenance.",
                }
            },
        }
    )

    with pytest.raises(RuntimeError, match="unknown artifact source"):
        _validate_evidence(raw, sources)


def test_judge_prompt_excludes_human_approval_labels():
    corpus = load_corpus()
    case = corpus.by_id["rag-grounding"].model_copy(deep=True)
    case.approval.reviewed_grades = {"correctness": "fail"}
    case.approval.approved_exemplar = "HUMAN_ONLY_EXEMPLAR"

    _system, user = _judge_prompt(corpus, case, {"answer": "assistant artifact"})

    assert "HUMAN_ONLY_EXEMPLAR" not in user
    assert "reviewed_grades" not in user
    assert '"artifact_sources"' in user


@pytest.mark.asyncio
async def test_anthropic_judge_uses_direct_structured_output_schema(monkeypatch):
    corpus = load_corpus()
    case = corpus.cases[0]
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text=__import__("json").dumps(
                        {
                            "dimensions": {
                                dimension: {
                                    "grade": "pass",
                                    "evidence": [{"source_id": "answer-1"}],
                                    "rationale": "The cited artifact satisfies the rubric.",
                                }
                                for dimension in case.rubric_dimensions
                            },
                        }
                    ),
                )
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=123, output_tokens=45),
        )
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    constructor_calls = []

    def fake_anthropic(**kwargs):
        constructor_calls.append(kwargs)
        return client

    monkeypatch.setattr("eval.judge_adapter.create_anthropic_client", fake_anthropic)
    monkeypatch.setattr("eval.judge_adapter.get_posthog_client", lambda: None)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)

    judgment = await SemanticJudge().judge(corpus, case, {"answer": "Artifact text."})

    assert constructor_calls == [{"api_key": "anthropic-test-key"}]
    request = create.await_args.kwargs
    assert request["model"] == DEFAULT_ANTHROPIC_JUDGE_MODEL
    assert request["max_tokens"] == 8192
    assert request["system"].startswith("You are an evaluation judge")
    assert request["messages"][0]["role"] == "user"
    assert request["output_config"] == {
        "effort": "high",
        "format": {
            "type": "json_schema",
            "schema": _anthropic_response_schema(
                _response_schema(
                    ("answer-1",),
                    tuple(case.rubric_dimensions),
                )
            ),
        },
    }
    anthropic_schema = request["output_config"]["format"]["schema"]
    assert "minItems" not in __import__("json").dumps(anthropic_schema)
    assert "maxItems" not in __import__("json").dumps(anthropic_schema)
    assert "response_format" not in request
    assert "posthog_properties" not in request
    assert judgment.provider == "anthropic"
    assert judgment.model == DEFAULT_ANTHROPIC_JUDGE_MODEL
    assert judgment.input_tokens == 123
    assert judgment.output_tokens == 45


@pytest.mark.asyncio
async def test_anthropic_judge_prefers_eval_judge_api_key(monkeypatch):
    corpus = load_corpus()
    case = corpus.cases[0]
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text=__import__("json").dumps(
                        {
                            "dimensions": {
                                dimension: {
                                    "grade": "pass",
                                    "evidence": [{"source_id": "answer-1"}],
                                    "rationale": "The cited artifact satisfies the rubric.",
                                }
                                for dimension in case.rubric_dimensions
                            },
                        }
                    ),
                )
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=12, output_tokens=4),
        )
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    constructor_calls = []

    def fake_anthropic(**kwargs):
        constructor_calls.append(kwargs)
        return client

    monkeypatch.setattr("eval.judge_adapter.create_anthropic_client", fake_anthropic)
    monkeypatch.setattr("eval.judge_adapter.get_posthog_client", lambda: None)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "anthropic-fallback-key")
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)

    await SemanticJudge().judge(corpus, case, {"answer": "Artifact text."})

    assert constructor_calls == [{"api_key": "anthropic-fallback-key"}]


@pytest.mark.parametrize(
    ("saved_failures", "capture_failures", "decision", "valid"),
    [
        ([], [], "pass", True),
        (["graph missing"], ["graph missing"], "fail", True),
        (["graph missing"], ["graph missing"], "pass", False),
        ([], ["graph missing"], "pass", False),
        (["graph missing"], [], "fail", False),
        (["old failure"], ["graph missing"], "fail", False),
    ],
)
def test_semantic_replay_reuses_only_identity_bound_valid_judgments(
    tmp_path, saved_failures, capture_failures, decision, valid
):
    corpus = load_corpus()
    case = corpus.cases[0]
    target = "https://approved-evidence.example"
    judgment = {
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "prompt_release": JUDGE_PROMPT_RELEASE,
        "input_tokens": 10,
        "output_tokens": 5,
        "estimated_cost_usd": 0.000105,
        "dimensions": [
            {
                "dimension": dimension,
                "grade": "pass",
                "critical": False,
                "evidence": ["answer-1"],
                "rationale": "Bounded rationale.",
            }
            for dimension in case.rubric_dimensions
        ],
    }
    path = tmp_path / "resume.json"
    path.write_text(
        __import__("json").dumps(
            {
                "kind": "live_gate",
                "execution_mode": "semantic_replay",
                "suite": "full",
                "target": target,
                "corpus_version": corpus.corpus_version,
                "corpus_sha256": corpus_sha256(),
                "release_identity": corpus.release_identity,
                "evaluations": [
                    {
                        "id": case.id,
                        "decision": decision,
                        "reason": "judge passed every dimension",
                        "deterministic_failures": saved_failures,
                        "judgments": [judgment],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        resume_input=str(path),
        capture_replay=True,
        suite="full",
        target=target,
    )

    def load_resume():
        return _load_resume_evaluations(
            args,
            corpus,
            SimpleNamespace(provider="anthropic", model="claude-sonnet-5"),
            [case.id],
            deterministic_failures_by_case={case.id: capture_failures},
        )

    if not valid:
        with pytest.raises(RuntimeError, match="resume"):
            load_resume()
        return
    resumed = load_resume()

    assert list(resumed) == [case.id]
    assert resumed[case.id]["judgments"] == [judgment]


def test_anthropic_judge_requires_its_provider_key(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        SemanticJudge()


def test_semantic_judge_defaults_to_sonnet_5(monkeypatch):
    client = SimpleNamespace(messages=SimpleNamespace())
    monkeypatch.delenv("EVAL_JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setattr(
        "eval.judge_adapter.create_anthropic_client",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr("eval.judge_adapter.get_posthog_client", lambda: None)

    judge = SemanticJudge()

    assert judge.provider == "anthropic"
    assert judge.model == DEFAULT_ANTHROPIC_JUDGE_MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_reason", "content", "message"),
    [
        ("refusal", [SimpleNamespace(type="text", text="{}")], "refused"),
        ("max_tokens", [SimpleNamespace(type="text", text="{}")], "maximum output"),
        ("end_turn", [SimpleNamespace(type="thinking")], "no text content"),
    ],
)
async def test_anthropic_judge_rejects_non_structured_responses(
    monkeypatch,
    stop_reason,
    content,
    message,
):
    corpus = load_corpus()
    case = corpus.cases[0]
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(
        "eval.judge_adapter.create_anthropic_client",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr("eval.judge_adapter.get_posthog_client", lambda: None)

    with pytest.raises(RuntimeError, match=message):
        await SemanticJudge(
            provider="anthropic",
            api_key="anthropic-test-key",
        ).judge(corpus, case, {"answer": "Artifact text."})


def test_judge_payload_removes_duplicate_graph_events_and_internal_graph_metadata():
    payload = _judge_payload(
        {
            "answer": "answer",
            "graph": {
                "title": "Candidate",
                "nodes": [
                    {
                        "id": "service",
                        "label": "Service",
                        "description": "Handles requests.",
                        "evidence_chunk_ids": ["private-internal-id"],
                    }
                ],
                "edges": [],
            },
            "events": [
                {"type": "graph_data", "data": {"duplicate": True}},
                {"type": "worker_status", "worker": "graph", "status": "ready"},
            ],
        }
    )

    assert payload["graph"]["title"] == "Candidate"
    assert payload["graph"]["artifact_role"] == "browser-rendered diagram"
    assert "evidence_chunk_ids" not in payload["graph"]["nodes"][0]
    assert payload["events"] == [
        {"type": "worker_status", "worker": "graph", "status": "ready"}
    ]


def test_judge_payload_reconstructs_turns_and_discards_reset_drafts():
    payload = _judge_payload(
        {
            "answer": "first answerobsolete draftrevised answer",
            "events": [
                {"type": "ready"},
                {"type": "response_delta", "content": "first answer"},
                {"type": "done"},
                {"type": "ready"},
                {"type": "response_delta", "content": "obsolete draft"},
                {"type": "response_reset"},
                {"type": "response_delta", "content": "revised answer"},
                {"type": "done"},
            ],
        }
    )

    assert payload["turns"] == [
        {"turn": 1, "answer": "first answer"},
        {"turn": 2, "answer": "revised answer"},
    ]
    assert "answer" not in payload


def test_judge_payload_preserves_each_turn_graph_identity():
    payload = _judge_payload(
        {
            "graph": {
                "version": "graph-2",
                "nodes": [{"id": "replacement", "label": "Replacement"}],
                "edges": [],
            },
            "turns": [
                {
                    "turn": 1,
                    "answer": "Initial architecture.",
                    "graph": {
                        "version": "graph-1",
                        "nodes": [{"id": "original", "label": "Original"}],
                        "edges": [],
                    },
                    "rendered_graph_version": "graph-1",
                    "rendered_node_ids": ["original"],
                    "rendered_edge_identities": [],
                },
                {
                    "turn": 2,
                    "answer": "Focused edit.",
                    "graph": {
                        "version": "graph-2",
                        "nodes": [{"id": "replacement", "label": "Replacement"}],
                        "edges": [],
                    },
                    "rendered_graph_version": "graph-2",
                    "rendered_node_ids": ["replacement"],
                    "rendered_edge_identities": [],
                },
            ],
            "events": [],
        }
    )

    assert [turn["graph"]["nodes"][0]["id"] for turn in payload["turns"]] == [
        "original",
        "replacement",
    ]
    assert [turn["rendered_graph_version"] for turn in payload["turns"]] == [
        "graph-1",
        "graph-2",
    ]


@pytest.mark.parametrize(
    "render_identity,expected_keys",
    [
        ({}, set()),
        (
            {
                "rendered_graph_version": None,
                "rendered_node_ids": None,
                "rendered_edge_identities": None,
            },
            set(),
        ),
        (
            {"rendered_node_ids": [], "rendered_edge_identities": []},
            {"rendered_node_ids", "rendered_edge_identities"},
        ),
        (
            {
                "rendered_graph_version": "graph-1",
                "rendered_node_ids": ["service"],
                "rendered_edge_identities": [
                    {"source": "client", "target": "service", "label": "Request"}
                ],
            },
            {
                "rendered_graph_version",
                "rendered_node_ids",
                "rendered_edge_identities",
            },
        ),
    ],
)
def test_judge_payload_keeps_missing_render_identity_distinct_from_empty(
    render_identity, expected_keys
):
    payload = _judge_payload(
        {
            "turns": [
                {
                    "answer": "Architecture.",
                    "graph": {
                        "version": "graph-1",
                        "nodes": [{"id": "service", "label": "Service"}],
                        "edges": [],
                    },
                    **render_identity,
                }
            ]
        }
    )

    turn = payload["turns"][0]
    assert turn["graph"]["nodes"] == [{"id": "service", "label": "Service"}]
    render_keys = {
        "rendered_graph_version",
        "rendered_node_ids",
        "rendered_edge_identities",
    }
    assert render_keys.intersection(turn) == expected_keys
    assert all(turn[key] == render_identity[key] for key in expected_keys)
    sources = _artifact_sources(payload)
    assert ("turn-1-render-1" in sources) == bool(expected_keys)


def test_judge_payload_bounds_and_preserves_retrieval_evidence():
    payload = _judge_payload(
        {
            "answer": "Grounded answer (Chapter 8, p.404).",
            "events": [
                {
                    "type": "retrieval_evidence",
                    "eval_turn": 2,
                    "query": "Why should eval data grow?",
                    "chunks": [
                        {
                            "book": "AI Engineering",
                            "chapter": 8,
                            "page_number": 404,
                            "parent_chunk_id": "ai-engineering:8:404:0",
                            "text": "x" * 25_000,
                        }
                    ],
                },
                {
                    "type": "research_evidence",
                    "eval_turn": 2,
                    "query": "current practice",
                    "results": [
                        "Report — <https://example.com/report>: current evidence"
                    ],
                },
            ],
        }
    )

    assert payload["retrieval_evidence"][0]["page_number"] == 404
    assert payload["retrieval_evidence"][0]["eval_turn"] == 2
    assert len(payload["retrieval_evidence"][0]["text"]) == 20_000
    assert payload["research_evidence"] == [
        {
            "query": "current practice",
            "result": "Report — <https://example.com/report>: current evidence",
            "provenance": "legacy_telemetry_not_exact_synthesis_input",
            "eval_turn": 2,
        }
    ]
    assert payload["events"] == []


def test_judge_payload_preserves_public_graph_semantics():
    graph = {
        "capabilities": {"external_effects": False},
        "root_node_id": "a",
        "sequence": [{"step": 1, "nodes": ["a"], "description": "Start"}],
        "nodes": [{"id": "a", "lane": "main", "primary_flow_member": True}],
        "edges": [
            {
                "source": "a",
                "target": "b",
                "label": "Read",
                "description": "Read baseline",
                "flow": "runtime",
                "sync": "sync",
            }
        ],
    }
    projected = _judge_payload({"graph": graph})["graph"]
    for field in ("capabilities", "root_node_id", "sequence", "nodes", "edges"):
        assert projected[field] == graph[field]
    assert (
        "capabilities"
        not in _judge_payload({"graph": {"nodes": [], "edges": []}})["graph"]
    )


def test_exact_answer_evidence_excludes_hidden_retrieval_tail_and_stale_memory():
    payload = _judge_payload(
        {
            "turns": [{"answer": "First answer"}, {"answer": "Memory answer"}],
            "events": [
                {
                    "type": "retrieval_evidence",
                    "eval_turn": 1,
                    "chunks": [{"text": "visible excerpt HIDDEN TAIL"}],
                },
                {
                    "type": "research_evidence",
                    "eval_turn": 1,
                    "results": ["UNUSED SEARCH RESULT"],
                },
                {
                    "type": "answer_evidence",
                    "schema_version": 1,
                    "source": "synthesis_input",
                    "prompt_version": "answer-v1",
                    "eval_turn": 1,
                    "book_context": "[1] Chapter 1, p.26\nvisible excerpt",
                    "research_context": "exact research snippet",
                },
                {
                    "type": "retrieval_evidence",
                    "eval_turn": 2,
                    "chunks": [{"text": "STALE MEMORY EVIDENCE"}],
                },
                {
                    "type": "answer_evidence",
                    "schema_version": 1,
                    "source": "synthesis_input",
                    "prompt_version": "answer-v1",
                    "eval_turn": 2,
                    "book_context": "",
                    "research_context": "",
                },
            ],
        }
    )
    assert payload["retrieval_evidence"] == []
    assert payload["research_evidence"] == []
    assert payload["answer_evidence"][0]["book_context"].endswith("visible excerpt")
    assert payload["answer_evidence"][1]["book_context"] == ""
    sources = _artifact_sources(payload)
    combined = " ".join(sources.values())
    assert "visible excerpt" in combined and "exact research snippet" in combined
    assert "HIDDEN TAIL" not in combined
    assert "STALE MEMORY" not in combined
    assert "UNUSED SEARCH" not in combined
    assert [item["status"] for item in payload["evidence_provenance"]] == [
        "exact_synthesis_input",
        "exact_synthesis_input",
    ]


def test_mixed_capture_retains_legacy_turn_with_explicit_visibility_limit():
    payload = _judge_payload(
        {
            "turns": [{"answer": "Historical"}, {"answer": "Current"}],
            "events": [
                {
                    "type": "retrieval_evidence",
                    "eval_turn": 1,
                    "chunks": [{"text": "legacy raw passage"}],
                },
                {
                    "type": "answer_evidence",
                    "schema_version": 1,
                    "source": "synthesis_input",
                    "prompt_version": "answer-v1",
                    "eval_turn": 2,
                    "book_context": "current excerpt",
                    "research_context": "",
                },
            ],
        }
    )
    assert payload["retrieval_evidence"][0]["text"] == "legacy raw passage"
    assert (
        payload["retrieval_evidence"][0]["provenance"]
        == "legacy_telemetry_not_exact_synthesis_input"
    )
    assert (
        payload["evidence_provenance"][0]["status"]
        == "legacy_capture_exact_synthesis_input_unavailable"
    )
    _, prompt = _judge_prompt(
        load_corpus(), load_corpus().by_id["rag-grounding"], _artifact_sources(payload)
    )
    assert "legacy_capture_exact_synthesis_input_unavailable" in prompt


@pytest.mark.parametrize(
    "change", [{"schema_version": 2}, {"book_context": None}, {"eval_turn": 3}]
)
def test_invalid_exact_answer_evidence_is_not_silently_treated_as_legacy(change):
    packet = {
        "type": "answer_evidence",
        "schema_version": 1,
        "source": "synthesis_input",
        "prompt_version": "answer-v1",
        "eval_turn": 1,
        "book_context": "",
        "research_context": "",
        **change,
    }
    with pytest.raises(ValueError, match="answer_evidence"):
        _judge_payload({"answer": "Answer", "events": [packet]})


@pytest.mark.asyncio
async def test_judge_transport_retry_counts_every_provider_attempt(monkeypatch):
    expected = result(("correctness", "pass", False))

    class FlakyJudge:
        calls = 0

        async def judge(self, corpus, case, evidence):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary provider timeout")
            return expected

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("eval.judge_adapter.asyncio.sleep", no_sleep)
    budget = EvaluationBudget(application_calls=1, judge_calls=2)
    actual = await judge_with_transport_retry(
        FlakyJudge(),
        None,
        None,
        {},
        on_attempt=budget.record_judge_call,
    )

    assert actual == expected
    assert budget.judge_calls == 2


@pytest.mark.asyncio
async def test_judge_transport_uses_120_second_attempt_deadline(monkeypatch):
    expected = result(("correctness", "pass", False))
    timeouts = []

    async def capture_wait_for(awaitable, *, timeout):
        timeouts.append(timeout)
        return await awaitable

    class PassingJudge:
        async def judge(self, corpus, case, evidence):
            return expected

    monkeypatch.setattr(judge_adapter.asyncio, "wait_for", capture_wait_for)
    actual = await judge_with_transport_retry(PassingJudge(), None, None, {})

    assert actual == expected
    assert timeouts == [120]


@pytest.mark.asyncio
async def test_judge_transport_cancellation_does_not_retry():
    started = asyncio.Event()
    budget = EvaluationBudget(application_calls=1, judge_calls=2)

    class WaitingJudge:
        calls = 0

        async def judge(self, corpus, case, evidence):
            self.calls += 1
            started.set()
            await asyncio.Event().wait()

    judge = WaitingJudge()
    task = asyncio.create_task(
        judge_with_transport_retry(
            judge, None, None, {}, on_attempt=budget.record_judge_call
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert judge.calls == 1
    assert budget.judge_calls == 1


@pytest.mark.asyncio
async def test_judge_transport_budget_abort_is_not_retried(monkeypatch):
    class UnavailableJudge:
        calls = 0

        async def judge(self, corpus, case, evidence):
            self.calls += 1
            raise TimeoutError("provider timed out")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(judge_adapter.asyncio, "sleep", no_sleep)
    budget = EvaluationBudget(application_calls=1, judge_calls=1)
    judge = UnavailableJudge()
    with pytest.raises(RuntimeError, match="judge model-call budget exceeded"):
        await judge_with_transport_retry(
            judge, None, None, {}, on_attempt=budget.record_judge_call
        )
    assert judge.calls == 1
    assert budget.judge_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("final_error", "error_class", "http_status"),
    [
        (TimeoutError("secret-key"), "TimeoutError", None),
        (ConnectionError("secret-key"), "ConnectionError", None),
        (
            AnthropicAPIConnectionError(
                request=httpx.Request("POST", "https://secret-key.example/v1/messages")
            ),
            "APIConnectionError",
            None,
        ),
        (
            AnthropicAPITimeoutError(
                request=httpx.Request("POST", "https://secret-key.example/v1/messages")
            ),
            "APITimeoutError",
            None,
        ),
        (
            AnthropicRateLimitError(
                "secret-key",
                response=httpx.Response(
                    429,
                    request=httpx.Request(
                        "POST", "https://secret-key.example/v1/messages"
                    ),
                    text="secret-key",
                ),
                body={"error": "secret-key"},
            ),
            "RateLimitError",
            429,
        ),
    ],
)
async def test_judge_transport_exhaustion_reports_safe_final_error(
    monkeypatch, final_error, error_class, http_status
):
    class ExhaustedJudge:
        calls = 0

        async def judge(self, corpus, case, evidence):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("first secret-key")
            raise final_error

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(judge_adapter.asyncio, "sleep", no_sleep)
    budget = EvaluationBudget(application_calls=1, judge_calls=2)
    judge = ExhaustedJudge()
    with pytest.raises(RuntimeError) as caught:
        await judge_with_transport_retry(
            judge, None, None, {}, on_attempt=budget.record_judge_call
        )

    reason = str(caught.value)
    assert "after one bounded retry" in reason
    assert error_class in reason
    if http_status is not None:
        assert f"HTTP {http_status}" in reason
    assert "secret-key" not in reason
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "secret-key" not in "".join(traceback.format_exception(caught.value))
    assert judge.calls == 2
    assert budget.judge_calls == 2


@pytest.mark.asyncio
async def test_judge_transport_exhaustion_redacts_subclass_and_invalid_status(
    monkeypatch,
):
    class SecretKeyTimeout(TimeoutError):
        status_code = 700

    class UnavailableJudge:
        async def judge(self, corpus, case, evidence):
            raise SecretKeyTimeout("secret-key")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(judge_adapter.asyncio, "sleep", no_sleep)
    with pytest.raises(RuntimeError) as caught:
        await judge_with_transport_retry(UnavailableJudge(), None, None, {})

    reason = str(caught.value)
    assert "RetryableJudgeError" in reason
    assert "SecretKeyTimeout" not in reason
    assert "HTTP 700" not in reason
    assert "secret-key" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        AnthropicAPIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        AnthropicAPITimeoutError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        AnthropicRateLimitError(
            "rate limited",
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
            body=None,
        ),
    ],
)
async def test_judge_transport_retries_anthropic_errors_once(
    monkeypatch,
    provider_error,
):
    expected = result(("correctness", "pass", False))

    class FlakyJudge:
        calls = 0

        async def judge(self, corpus, case, evidence):
            self.calls += 1
            if self.calls == 1:
                raise provider_error
            return expected

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("eval.judge_adapter.asyncio.sleep", no_sleep)
    budget = EvaluationBudget(application_calls=1, judge_calls=2)
    actual = await judge_with_transport_retry(
        FlakyJudge(),
        None,
        None,
        {},
        on_attempt=budget.record_judge_call,
    )

    assert actual == expected
    assert budget.judge_calls == 2


def test_judge_cost_uses_exact_provider_and_model_pricing():
    openai_result = replace(
        result(("correctness", "pass", False)),
        provider="openai",
        model="gpt-5.4-mini-2026-03-17",
    )
    anthropic_result = replace(
        openai_result,
        provider="anthropic",
        model="claude-sonnet-5",
    )

    assert estimated_judge_cost_usd(openai_result) == 0.00003
    assert estimated_judge_cost_usd(anthropic_result) == 0.00007
    with pytest.raises(RuntimeError, match="pricing is not configured"):
        estimated_judge_cost_usd(replace(anthropic_result, model="unknown"))


def test_calibration_report_uses_every_reviewed_case_and_dimension():
    corpus = load_corpus().model_copy(deep=True)
    corpus.approval.calibration.evidence_sha256 = "a" * 64
    corpus.approval.calibration.evidence_run_id = "123"
    corpus.approval.calibration.evidence_commit_sha = "b" * 40
    evaluations = []
    label_count = 0
    for case in corpus.cases:
        case.approval.status = "approved"
        case.approval.reviewer = "reviewer"
        case.approval.reviewed_at = "2026-07-18T12:00:00Z"
        case.approval.review_run_id = "123"
        case.approval.reviewed_grades = {
            dimension: "pass" for dimension in case.rubric_dimensions
        }
        label_count += len(case.rubric_dimensions)
        evaluations.append(
            {
                "id": case.id,
                "decision": "pass",
                "judgments": [
                    {
                        "provider": "openai",
                        "prompt_release": JUDGE_PROMPT_RELEASE,
                        "model": "gpt-5.4-mini-2026-03-17",
                        "dimensions": [
                            {"dimension": dimension, "grade": "pass"}
                            for dimension in case.rubric_dimensions
                        ],
                    }
                ],
            }
        )

    report = calculate_calibration(
        corpus,
        {
            "kind": "live_gate",
            "suite": "full",
            "status": "pass",
            "execution_mode": "semantic_replay",
            "corpus_version": corpus.corpus_version,
            "corpus_sha256": corpus_sha256(),
            "evaluations": evaluations,
        },
        evidence_sha256="a" * 64,
        source_context={"source_run_id": "123", "source_commit_sha": "b" * 40},
        judge_selection={
            "format_version": 1,
            "provider": "openai",
            "model": "gpt-5.4-mini-2026-03-17",
        },
    )

    assert report["passed"] is True
    assert report["judge_release"] == JUDGE_PROMPT_RELEASE
    assert report["agreement"] == 1
    assert report["labels"] == label_count
    assert report["judge_models"] == ["gpt-5.4-mini-2026-03-17"]
    assert report["evidence_sha256"] == "a" * 64
    assert report["disagreements"] == []
    assert set(report["per_dimension_agreement"]) == set(corpus.rubrics)


def test_calibration_rejects_stale_corpus_or_judge_release():
    corpus = load_corpus()
    report = {
        "kind": "live_gate",
        "suite": "full",
        "status": "pass",
        "execution_mode": "semantic_replay",
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": "wrong",
        "evaluations": [],
    }

    with pytest.raises(ValueError, match="corpus digest"):
        calculate_calibration(
            corpus,
            report,
            evidence_sha256=corpus.approval.calibration.evidence_sha256,
            source_context={
                "source_run_id": corpus.approval.calibration.evidence_run_id,
                "source_commit_sha": corpus.approval.calibration.evidence_commit_sha,
            },
            judge_selection={
                "format_version": 1,
                "provider": corpus.approval.calibration.judge_provider,
                "model": corpus.approval.calibration.judge_model,
            },
        )


def test_calibration_rejects_infrastructure_after_a_judgment():
    corpus = load_corpus()
    report = {
        "kind": "live_gate",
        "suite": "full",
        "status": "infrastructure",
        "execution_mode": "semantic_replay",
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": corpus_sha256(),
        "evaluations": [],
    }

    with pytest.raises(ValueError, match="infrastructure-failed replay"):
        calculate_calibration(
            corpus,
            report,
            evidence_sha256=corpus.approval.calibration.evidence_sha256,
            source_context={
                "source_run_id": corpus.approval.calibration.evidence_run_id,
                "source_commit_sha": corpus.approval.calibration.evidence_commit_sha,
            },
            judge_selection={
                "format_version": 1,
                "provider": corpus.approval.calibration.judge_provider,
                "model": corpus.approval.calibration.judge_model,
            },
        )


def test_approved_gate_rejects_an_uncalibrated_judge_model():
    corpus = load_corpus()

    with pytest.raises(RuntimeError, match="judge model"):
        _assert_approved_judge_identity(
            corpus,
            SimpleNamespace(
                provider=corpus.approval.calibration.judge_provider,
                model="different-judge-model",
            ),
        )


def test_approved_gate_rejects_an_uncalibrated_judge_provider():
    corpus = load_corpus()

    with pytest.raises(RuntimeError, match="judge provider"):
        _assert_approved_judge_identity(
            corpus,
            SimpleNamespace(
                provider="openai",
                model=corpus.approval.calibration.judge_model,
            ),
        )


def test_infrastructure_startup_failure_still_writes_review_artifacts(
    tmp_path, monkeypatch
):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    output = tmp_path / "live-results.json"

    _write_outputs(
        output,
        {
            "format_version": 1,
            "kind": "live_gate",
            "status": "infrastructure",
            "reason": "provider unavailable",
            "evaluations": [],
        },
    )

    assert output.exists()
    assert (tmp_path / "live-junit.xml").exists()
    assert (tmp_path / "semantic-review.html").exists()
    assert "provider unavailable" in summary.read_text(encoding="utf-8")


def test_report_only_manual_review_is_visible_but_not_a_junit_failure(tmp_path):
    output = tmp_path / "live-results.json"
    _write_outputs(
        output,
        {
            "format_version": 1,
            "kind": "live_gate",
            "status": "manual_review",
            "blocking_status": "pass",
            "manual_review_policy": "report-only",
            "evaluations": [
                {
                    "id": "unseen-case",
                    "decision": "manual_review",
                    "reason": "judge returned a borderline dimension",
                    "judgments": [],
                }
            ],
        },
    )

    junit = (tmp_path / "live-junit.xml").read_text(encoding="utf-8")
    assert 'failures="0"' in junit
    assert 'skipped="1"' in junit
    assert "<skipped" in junit
    assert "borderline dimension" in junit


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected_exit", [("report-only", 0), ("blocking", 1)])
@pytest.mark.parametrize(
    "quality_failure",
    [
        None,
        "required answer missing",
        pytest.param("required\nanswer missing " * 20, id="long-quality-reason"),
    ],
)
async def test_recovered_timeout_cost_stays_unknown_through_live_report(
    monkeypatch, tmp_path, mode, expected_exit, quality_failure
):
    capture = {
        "results": [{"id": "memory", "thread_id": "thread", "answer": "Answer.",
                     "events": [], "deterministic_failures": []}],
        "application_telemetry": [{
            "thread_id": "thread", "operation": "route", "provider_attempts": 2,
            "attempts": [
                {"model": "claude-sonnet-5", "status": "APITimeoutError",
                 "accepted": False, "usage_complete": False},
                {"model": "claude-sonnet-5", "status": "success",
                 "accepted": True, "usage_complete": True,
                 "input_tokens": 100, "output_tokens": 10},
            ],
        }],
    }
    if quality_failure:
        capture["results"][0]["deterministic_failures"] = [quality_failure]
        capture["results"][0]["failure_details"] = [{"kind": "quality"}]
    manifest = live_runner._manifest()
    manifest["live"]["cost_policy"] = {"mode": mode}
    monkeypatch.setattr(live_runner, "_manifest", lambda: manifest)
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    _passing_replay_judge(monkeypatch)
    args = live_runner.build_parser().parse_args([
        "--suite", "diagnostic", "--case", "memory",
        "--target", "https://candidate.example",
    ])

    report, exit_code = await evaluate(args)

    assert exit_code == (1 if quality_failure else expected_exit)
    evaluation = report["evaluations"][0]
    assert evaluation["decision"] == ("fail" if quality_failure else "pass")
    if quality_failure:
        assert "required answer missing" in report["reason"]
        if len(evaluation["reason"]) <= 240:
            assert report["reason"] == f"memory: {evaluation['reason']}"
        else:
            assert report["reason"].startswith("memory: ")
            assert report["reason"].endswith("...")
            assert len(report["reason"]) <= len("memory: ") + 240
            assert "\n" not in report["reason"]
    elif mode == "blocking":
        assert report["reason"] == report["cost_accounting"]["policy"]["reason"]
    else:
        assert report["reason"] is None
    assert report["estimated_cost"]["application_usd"] is None
    assert report["cost_accounting"]["policy"]["status"] == "incomplete"
    assert report["cost_accounting"]["application"]["total"]["known_subtotal_usd"] == 0.0003
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    _write_outputs(tmp_path / "live-results.json", report)
    import xml.etree.ElementTree as ET

    cost = ET.parse(tmp_path / "live-junit.xml").find(
        ".//testcase[@name='application-cost-policy']"
    )
    assert (cost.find("failure") is not None) == (mode == "blocking")
    assert (cost.find("skipped") is not None) == (mode == "report-only")
    summary = summary_path.read_text()
    assert "Application cost: `unknown`" in summary
    assert "Known application subtotal: `$0.000300` (total unavailable)" in summary


@pytest.fixture
def complete_calibration_capture():
    corpus = load_corpus()
    results = []
    for case in corpus.cases:
        results.append(
            {
                "id": case.id,
                "execution_state": "completed",
                "passed": True,
                "deterministic_failures": [],
                "failure_details": [],
                "turns": [
                    {"turn": index, "prompt": step.prompt, "answer": "Captured answer."}
                    for index, step in enumerate(case.steps, start=1)
                ],
                "events": [
                    {"type": "done", "eval_turn": index}
                    for index in range(1, len(case.steps) + 1)
                ],
                "screenshot": f"{case.id}.png",
                "trace": f"{case.id}.zip",
            }
        )
    return {
        "format_version": 1,
        "kind": "browser_capture",
        "suite": "full",
        "status": "complete",
        "corpus_version": corpus.corpus_version,
        "release_identity": corpus.release_identity,
        "dashboard_smoke": {"passed": True},
        "results": results,
        "case_states": [{"id": case.id, "state": "completed"} for case in corpus.cases],
        "application_telemetry": [],
    }


def _full_replay_args(*, replay=True):
    return SimpleNamespace(
        manual_review_policy="blocking",
        require_approved_corpus=False,
        capture_replay=replay,
        suite="full",
        case=[],
        target="https://candidate.example",
        resume_input=None,
    )


def _passing_replay_judge(monkeypatch, *, critical_failure=False):
    calls = []

    async def judge(_judge, _corpus, case, _payload, *, on_attempt):
        calls.append(case.id)
        on_attempt()
        return replace(
            result(
                *(
                    (
                        dimension,
                        "fail" if critical_failure and index == 0 else "pass",
                        critical_failure and index == 0,
                    )
                    for index, dimension in enumerate(case.rubric_dimensions)
                )
            ),
            provider="anthropic",
            model="claude-sonnet-5",
        )

    monkeypatch.setattr(live_runner, "SemanticJudge", lambda: object())
    monkeypatch.setattr(live_runner, "judge_with_transport_retry", judge)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("replay", [False, True])
async def test_calibration_grades_complete_product_failures_without_overriding_them(
    monkeypatch, tmp_path, complete_calibration_capture, replay
):
    capture = complete_calibration_capture
    failed = capture["results"][0]
    failed.update(
        passed=False,
        deterministic_failures=["graph missing"],
        failure_details=[{"kind": "quality"}],
    )
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    calls = _passing_replay_judge(monkeypatch)

    report, code = await evaluate(_full_replay_args(replay=replay))

    assert code == 1
    evaluation = report["evaluations"][0]
    assert evaluation["decision"] == "fail"
    assert evaluation["deterministic_failures"] == ["graph missing"]
    assert report["reason"] == f"{evaluation['id']}: {evaluation['reason']}"
    assert len(evaluation["judgments"]) == int(replay)
    assert len(calls) == (len(capture["results"]) if replay else 0)
    assert report["cost_accounting"]["application"]["status"] == "infrastructure"
    if replay:
        assert all(item["decision"] == "pass" for item in report["evaluations"][1:])
        assert report["budget"]["application_calls"] == 0
        assert report["cost_accounting"]["policy"]["scope"] == "source_capture"
        path = tmp_path / "report.json"
        _write_outputs(path, report)
        import xml.etree.ElementTree as ET

        tree = ET.parse(path.parent / "live-junit.xml")
        cost = tree.find(".//testcase[@name='application-cost-policy']")
        assert cost.find("failure") is None
        assert cost.find("skipped") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["infrastructure", "missing_answer", "missing_done"])
async def test_calibration_rejects_incomplete_or_infrastructure_capture_before_judging(
    monkeypatch, complete_calibration_capture, fault
):
    capture = complete_calibration_capture
    first = capture["results"][0]
    if fault == "infrastructure":
        first.update(
            passed=False,
            deterministic_failures=["transport failure"],
            failure_details=[{"kind": "infrastructure"}],
        )
    elif fault == "missing_answer":
        first["turns"][0]["answer"] = ""
    else:
        first["events"] = []
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    calls = _passing_replay_judge(monkeypatch)
    with pytest.raises(ValueError):
        await evaluate(_full_replay_args())
    assert calls == []


@pytest.mark.asyncio
async def test_replay_critical_failure_uses_one_judgment_per_case(
    monkeypatch, complete_calibration_capture
):
    monkeypatch.setattr(
        live_runner, "_load_capture", lambda _args: complete_calibration_capture
    )
    calls = _passing_replay_judge(monkeypatch, critical_failure=True)
    report, code = await evaluate(_full_replay_args())
    assert code == 1
    assert len(calls) == len(complete_calibration_capture["results"])
    assert all(
        item["decision"] == "fail" and len(item["judgments"]) == 1
        for item in report["evaluations"]
    )


@pytest.mark.asyncio
async def test_replay_source_accounting_does_not_hide_new_judge_failure(
    monkeypatch, complete_calibration_capture
):
    monkeypatch.setattr(
        live_runner, "_load_capture", lambda _args: complete_calibration_capture
    )
    _passing_replay_judge(monkeypatch)

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(live_runner, "judge_with_transport_retry", unavailable)
    report, code = await evaluate(_full_replay_args())
    assert code == 2
    assert report["status"] == "infrastructure"
    assert all("judge unavailable" in item["reason"] for item in report["evaluations"])


@pytest.mark.asyncio
async def test_replay_retains_priced_source_usage_without_spending_application_budget(
    monkeypatch, complete_calibration_capture
):
    capture = complete_calibration_capture
    for row in capture["results"]:
        row["thread_id"] = row["id"]
        capture["application_telemetry"].append(
            {
                "thread_id": row["id"],
                "operation": "synthesis",
                "model": "claude-sonnet-5",
                "status": "success",
                "provider_attempts": 100,
                "input_tokens": 100,
                "output_tokens": 10,
            }
        )
    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    _passing_replay_judge(monkeypatch)
    report, code = await evaluate(_full_replay_args())
    assert code == 0
    assert report["budget"]["application_calls"] == 0
    assert report["budget"]["source_application_calls"] == 100 * len(capture["results"])
    assert report["estimated_cost"]["application_usd"] == 0
    assert report["estimated_cost"]["source_application_usd"] > 0
    assert report["cost_accounting"]["application"]["status"] == "pass"


@pytest.mark.parametrize("final_packet", [False, True])
def test_response_reset_discards_abandoned_exact_and_legacy_evidence(final_packet):
    packet = {
        "type": "answer_evidence",
        "schema_version": 1,
        "source": "synthesis_input",
        "prompt_version": "test",
        "eval_turn": 1,
        "book_context": "OLD EXACT",
        "research_context": "OLD RESEARCH",
    }
    events = [
        packet,
        {
            "type": "retrieval_evidence",
            "eval_turn": 1,
            "chunks": [{"text": "OLD LEGACY"}],
        },
        {"type": "response_reset", "eval_turn": 1},
    ]
    if final_packet:
        events.append({**packet, "book_context": "", "research_context": ""})
    payload = _judge_payload(
        {
            "events": events,
            "turns": [{"prompt": "Question", "answer": "Final answer"}],
        }
    )
    assert len(payload["answer_evidence"]) == int(final_packet)
    assert payload["retrieval_evidence"] == []
    assert "OLD" not in str(_artifact_sources(payload))
    if final_packet:
        assert payload["answer_evidence"][0]["book_context"] == ""


def test_artifact_source_chunks_preserve_code_and_paragraph_whitespace():
    original = (
        "First paragraph.\n\n```python\nif ready:\n    run()\n```\n\nNext paragraph.\n"
        * 20
    )
    sources = {}
    _add_bounded_sources(sources, "answer", original)
    assert "".join(sources.values()) == original
    assert all(len(chunk) <= 500 for chunk in sources.values())
    packet = {
        "eval_turn": 1,
        "source": "synthesis_input",
        "prompt_version": "test",
        "book_context": original,
        "research_context": "",
    }
    exact = _artifact_sources({"answer_evidence": [packet]})
    assert (
        "".join(
            value
            for key, value in exact.items()
            if key.startswith("turn-1-synthesis-1-book-")
        )
        == original
    )


@pytest.mark.parametrize("matching_turn", [0, 1])
def test_judge_sources_omit_only_equal_top_level_graph(matching_turn):
    import copy

    first = {"version": "first", "nodes": [{"id": "first"}], "edges": []}
    second = {"version": "second", "nodes": [{"id": "second"}], "edges": []}
    turns = [
        {"answer": "First answer.", "graph": first, "rendered_graph_version": "first"},
        {"answer": "Second answer.", "graph": second, "rendered_graph_version": "second"},
    ]
    sources = _artifact_sources({
        "turns": turns, "graph": copy.deepcopy(turns[matching_turn]["graph"]),
    })
    assert any(key.startswith("graph-") for key in sources) == (matching_turn == 0)
    assert sources["turn-1-answer-1"] == "First answer."
    assert sources["turn-2-answer-1"] == "Second answer."
    assert '"first"' in sources["turn-1-graph-node-1-1"]
    assert '"second"' in sources["turn-2-graph-node-1-1"]
    assert "first" in sources["turn-1-render-1"]
    assert "second" in sources["turn-2-render-1"]


@pytest.mark.parametrize("turns", [None, [], [{"answer": "No turn graph."}], [
    {"answer": "Earlier graph.", "graph": {"nodes": [{"id": "earlier"}], "edges": []}}
]])
def test_judge_sources_preserve_legacy_or_distinct_final_graph(turns):
    graph = {"nodes": [{"id": "final"}], "edges": []}
    sources = _artifact_sources({"answer": "Answer.", "turns": turns, "graph": graph})
    assert sources["graph-node-1-1"] == '{"id": "final"}'


def test_judge_prompt_preserves_large_graph_once_below_existing_limit():
    import copy
    import json
    from eval.judge_adapter import _add_graph_sources

    # Reproduce the retained 34700167991 case's 20-node/92-edge scale with synthetic content.
    nodes = [{
        "id": f"node-{index}", "label": f"Service {index}", "type": "service",
        "technology": "Application service", "description": "Owns the declared operation and records its outcome.",
        "tier": "core", "layer": "runtime", "lane": "runtime",
        "primary_flow_member": index < 5, "is_root": index == 0,
    } for index in range(20)]
    edges = [{
        "source": f"node-{index % 20}", "target": f"node-{(index + 1) % 20}",
        "label": f"Submit request contract {index}", "technology": "HTTPS JSON",
        "description": "Transfers the operation identifier, validated request and caller context. The receiver checks ownership, records the result and returns an acknowledgement for reconciliation.",
        "flow": "runtime", "sync": "sync", "type": "smoothstep", "relation": f"contract-{index}",
    } for index in range(92)]
    graph = {
        "graph_type": "applied", "title": "Synthetic operations system", "version": "v1",
        "root_node_id": "node-0", "resolved_complexity": "production",
        "capabilities": {"retrieval": False, "external_effects": True, "learning_or_release": False},
        "nodes": nodes, "edges": edges, "assumptions": ["Every write requires caller authorization."],
        "groups": [{"id": "runtime", "label": "Runtime", "nodeIds": [n["id"] for n in nodes]}],
        "sequence": [{"step": 1, "nodeIds": ["node-0"], "description": "Accept the authorized request."}],
    }
    answer = "The proposed system processes authorized operations. " * 100
    render = {
        "rendered_graph_version": "v1", "rendered_node_ids": [n["id"] for n in nodes],
        "rendered_edge_identities": [{k: edge[k] for k in ("source", "target", "label")} for edge in edges],
    }
    evidence = _judge_payload({
        "graph": copy.deepcopy(graph), "turns": [{"answer": answer, "graph": graph, **render}],
        "events": [{"type": "answer_evidence", "schema_version": 1, "source": "synthesis_input",
                    "prompt_version": "test", "book_context": "Current evidence. " * 200,
                    "research_context": "", "eval_turn": 1}],
    })
    sources = _artifact_sources(evidence)
    corpus = load_corpus()
    _, prompt = _judge_prompt(corpus, corpus.by_id["applied-domain"], sources)
    assert len(prompt) < 80000
    duplicated = dict(sources)
    _add_graph_sources(duplicated, "graph", evidence["graph"])
    with pytest.raises(RuntimeError, match="bounded prompt size"):
        _judge_prompt(corpus, corpus.by_id["applied-domain"], duplicated)
    assert not any(key.startswith("graph-") for key in sources)
    assert "".join(value for key, value in sources.items() if key.startswith("turn-1-answer-")) == answer
    assert json.loads("".join(value for key, value in sources.items() if key.startswith("turn-1-render-"))) == render
    for index, edge in enumerate(evidence["turns"][0]["graph"]["edges"], start=1):
        prefix = f"turn-1-graph-edge-{index}-"
        assert json.loads("".join(value for key, value in sources.items() if key.startswith(prefix))) == edge
    for index, node in enumerate(evidence["turns"][0]["graph"]["nodes"], start=1):
        prefix = f"turn-1-graph-node-{index}-"
        assert json.loads("".join(value for key, value in sources.items() if key.startswith(prefix))) == node


def test_judge_prompt_checks_payload_direction_and_component_ownership():
    corpus = load_corpus()
    system, _ = _judge_prompt(corpus, corpus.by_id["applied-domain"], {"answer-1": "Answer."})

    assert JUDGE_PROMPT_RELEASE == "semantic-rubric-judge-v10"
    assert corpus.approval.calibration.judge_release == JUDGE_PROMPT_RELEASE
    assert f"release {JUDGE_PROMPT_RELEASE}" in system
    assert "Verify graph read requests and payload returns against authoritative component ownership" in system
    assert "actual request/response contracts" in system
    assert "An unrelated reverse validation verdict does not satisfy a requested payload return" in system
    assert "Response prose cannot repair a contradictory graph contract" in system


def test_retained_marketing_graph_keeps_conflicting_payload_and_verdict_evidence():
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/judge_graph_35645459646.json").read_text()
    )
    graph = fixture["graph"]
    sources = _artifact_sources({
        "turns": [{"answer": fixture["answer"], "graph": graph}],
        "graph": graph,
    })
    corpus = load_corpus()
    _, user = _judge_prompt(corpus, corpus.by_id["applied-domain"], sources)
    payload = json.loads(user)
    assert list(payload) == ["case", "rubrics", "artifact_sources"]
    supplied = payload["artifact_sources"]
    assert list(supplied) == list(sources)
    source_keys = list(supplied)
    assert source_keys.index("turn-1-graph-edge-2-1") < source_keys.index(
        "turn-1-graph-edge-10-1"
    )

    # Retained evidence proves availability to the judge, not a new model verdict.
    assert len(graph["edges"]) == 64
    for kind in ("node", "edge"):
        for index, record in enumerate(graph[f"{kind}s"], start=1):
            prefix = f"turn-1-graph-{kind}-{index}-"
            reconstructed = "".join(
                supplied[key]
                for key in sorted(
                    (key for key in supplied if key.startswith(prefix)),
                    key=lambda key: int(key.rsplit("-", 1)[1]),
                )
            )
            assert json.loads(reconstructed) == record

    read_request, payload, verdict = (graph["edges"][index] for index in (2, 3, 5))
    assert (read_request["source"], read_request["target"]) == (
        payload["source"], payload["target"]
    )
    assert (verdict["source"], verdict["target"]) == (
        payload["target"], payload["source"]
    )
    assert payload["label"] != verdict["label"]
    assert "".join(
        supplied[key]
        for key in sorted(
            (key for key in supplied if key.startswith("turn-1-answer-")),
            key=lambda key: int(key.rsplit("-", 1)[1]),
        )
    ) == fixture["answer"]


@pytest.mark.parametrize("failure_count,expected", [(2, "manual_review"), (3, "manual_review"), (4, "fail")])
def test_noncritical_failures_are_counted_before_borderline(failure_count, expected):
    judgment = result(*(
        (f"d{index}", "fail" if index < failure_count else "borderline" if index == 19 else "pass", False)
        for index in range(20)
    ))
    first = decide_semantic_gate(judgment)
    if expected == "fail":
        assert first.status == "infrastructure"
        assert "second independent" in first.reason
    else:
        assert first.status == "manual_review"
    assert decide_semantic_gate(judgment, judgment).status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected_exit,expected_status,judge_calls", [
    ("borderline", 0, "manual_review", 1),
    ("explicit_blocking", 3, "manual_review", 1),
    ("critical", 1, "fail", 1),
    ("mixed_confirmed", 1, "fail", 2),
    ("deterministic", 1, "fail", 0),
    ("infrastructure", 2, "infrastructure", 1),
    ("cost_block", 1, "fail", 1),
])
async def test_pending_corpus_automated_outcomes_keep_failure_boundaries(
    monkeypatch, outcome, expected_exit, expected_status, judge_calls
):
    corpus = load_corpus()
    assert corpus.approval.status == "pending_human_review"
    case = corpus.by_id["memory"]
    capture = {
        "results": [{"id": case.id, "answer": "Answer.", "events": [],
                     "deterministic_failures": ["missing required output"] if outcome == "deterministic" else [],
                     **({"failure_details": [{"kind": "quality"}]} if outcome == "deterministic" else {})}],
        "application_telemetry": [{"provider_attempts": 1}],
    }
    calls = []

    async def judge(*_args, **kwargs):
        calls.append(True)
        kwargs["on_attempt"]()
        if outcome == "infrastructure":
            raise RuntimeError("provider unavailable")
        if outcome == "critical":
            return replace(result(("safety", "fail", True), ("relevance", "borderline", False)), provider="anthropic", model="claude-sonnet-5")
        if outcome == "mixed_confirmed":
            return replace(result(("correctness", "fail", False), ("relevance", "borderline", False)), provider="anthropic", model="claude-sonnet-5")
        return replace(result(("safety", "pass", True), ("relevance", "borderline", False)), provider="anthropic", model="claude-sonnet-5")

    monkeypatch.setattr(live_runner, "_load_capture", lambda _args: capture)
    monkeypatch.setattr(live_runner, "SemanticJudge", lambda: SimpleNamespace(provider="anthropic", model="claude-sonnet-5"))
    monkeypatch.setattr(live_runner, "judge_with_transport_retry", judge)
    monkeypatch.setattr(live_runner, "account_application_cost", lambda *_args: {"total": {"estimated_usd": 0}, "price_release": "test"})
    monkeypatch.setattr(live_runner, "evaluate_cost_policy", lambda *_args: {
        "status": "fail" if outcome == "cost_block" else "pass",
        "blocking_status": "fail" if outcome == "cost_block" else "pass", "reason": "test policy",
    })
    args = live_runner.build_parser().parse_args([
        "--suite", "diagnostic", "--case", "memory", "--target", "https://candidate.example",
        *(["--manual-review-policy", "blocking"] if outcome == "explicit_blocking" else []),
    ])
    report, exit_code = await evaluate(args)
    assert exit_code == expected_exit
    assert report["status"] == expected_status
    assert report["corpus_approval"] == "pending_human_review"
    assert len(calls) == judge_calls
    if outcome == "cost_block":
        assert report["reason"] == "test policy"
    else:
        assert report["reason"] == f"memory: {report['evaluations'][0]['reason']}"
    if outcome in {"borderline", "explicit_blocking", "cost_block"}:
        assert report["evaluations"][0]["decision"] == "manual_review"
    if outcome == "borderline":
        assert report["blocking_status"] == "pass"


@pytest.mark.asyncio
async def test_optional_approved_corpus_flag_still_rejects_pending_before_judging():
    args = live_runner.build_parser().parse_args([
        "--suite", "full", "--target", "https://candidate.example", "--require-approved-corpus",
    ])
    with pytest.raises(RuntimeError, match="pending human review"):
        await evaluate(args)
