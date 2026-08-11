from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
    APITimeoutError as AnthropicAPITimeoutError,
    RateLimitError as AnthropicRateLimitError,
)
import httpx
import pytest

from eval.calibration import calculate_calibration
from eval.judge_adapter import (
    DEFAULT_ANTHROPIC_JUDGE_MODEL,
    JUDGE_PROMPT_RELEASE,
    SemanticJudge,
    _RawJudgment,
    _anthropic_response_schema,
    _artifact_sources,
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


def test_judge_disagreement_requires_manual_review():
    first = result(("safety", "fail", True), ("relevance", "pass", False))
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


@pytest.mark.asyncio
async def test_report_only_policy_is_replay_only():
    args = SimpleNamespace(
        manual_review_policy="report-only",
        require_approved_corpus=True,
        capture_replay=False,
    )

    with pytest.raises(RuntimeError, match="approved semantic replay"):
        await evaluate(args)


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


def test_judge_schema_has_exact_dimension_keys():
    schema = _response_schema(
        ("turn-1-answer-1",),
        ("correctness", "instruction_following"),
    )
    dimensions = schema["properties"]["dimensions"]

    assert dimensions["type"] == "object"
    assert dimensions["additionalProperties"] is False
    assert dimensions["required"] == ["correctness", "instruction_following"]
    assert set(dimensions["properties"]) == {"correctness", "instruction_following"}
    assert dimensions["properties"]["correctness"]["properties"]["evidence"]["items"][
        "properties"
    ]["source_id"]["enum"] == ["turn-1-answer-1"]


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


def test_semantic_replay_reuses_only_identity_bound_valid_judgments(tmp_path):
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
                        "decision": "pass",
                        "reason": "judge passed every dimension",
                        "deterministic_failures": [],
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

    resumed = _load_resume_evaluations(
        args,
        corpus,
        SimpleNamespace(provider="anthropic", model="claude-sonnet-5"),
        [case.id],
    )

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
            "eval_turn": 2,
        }
    ]
    assert payload["events"] == []


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
        case.approval.review_run_id = "github-run-123"
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
