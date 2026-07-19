import pytest

from eval.calibration import calculate_calibration
from eval.judge_adapter import (
    JUDGE_PROMPT_RELEASE,
    _RawJudgment,
    _artifact_sources,
    _judge_prompt,
    _response_schema,
    _validate_evidence,
    judge_with_transport_retry,
)
from eval.live_runner import _judge_payload, _write_outputs
from eval.quality_corpus import load_corpus
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
    decision = decide_semantic_gate(result(("correctness", "pass", False)), deterministic_failures=("graph missing",))

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


def test_noncritical_pass_threshold_is_enforced():
    dimensions = tuple((f"d{i}", "pass" if i < 8 else "fail", False) for i in range(10))

    assert decide_semantic_gate(result(*dimensions)).status == "infrastructure"
    assert decide_semantic_gate(result(*dimensions), result(*dimensions)).status == "fail"


def test_calibration_requires_85_percent_agreement_and_at_most_one_critical_false_pass():
    expected = [("pass", False)] * 17 + [("fail", True)] * 3
    acceptable = [("pass", False)] * 17 + [("pass", True), ("fail", True), ("fail", True)]
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
    raw = _RawJudgment.model_validate({
        "dimensions": {"correctness": {
            "grade": "pass",
            "evidence": [{"source_id": "answer-1"}],
            "rationale": "The answer states the promotion guard.",
        }},
    })

    _validate_evidence(raw, sources)

    assert sources["answer-1"] == 'The service says "ready" before promotion.'
    assert sources["graph-node-1-1"] == '{"id": "candidate"}'
    assert sources["event-1-1"] == '{"type": "done"}'
    assert all(len(source) <= 500 for source in sources.values())

    long_token_sources = _artifact_sources({"answer": "x" * 1001})
    assert [len(source) for source in long_token_sources.values()] == [500, 500, 1]


def test_judge_evidence_preserves_ordered_conversation_turns():
    sources = _artifact_sources({
        "answer": "legacy concatenated answer",
        "turns": [
            {"turn": 1, "answer": "First explanation."},
            {"turn": 2, "answer": "Two concise mitigations."},
        ],
    })

    assert sources == {
        "turn-1-answer-1": "First explanation.",
        "turn-2-answer-1": "Two concise mitigations.",
    }


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
    assert (
        dimensions["properties"]["correctness"]["properties"]["evidence"]
        ["items"]["properties"]["source_id"]["enum"]
        == ["turn-1-answer-1"]
    )


def test_judge_evidence_rejects_an_unknown_source():
    sources = _artifact_sources({"answer": "answer text", "events": [{"status": "ready"}]})
    raw = _RawJudgment.model_validate({
        "dimensions": {"correctness": {
            "grade": "pass",
            "evidence": [{"source_id": "missing-source"}],
            "rationale": "Invalid provenance.",
        }},
    })

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


def test_judge_payload_removes_duplicate_graph_events_and_internal_graph_metadata():
    payload = _judge_payload({
        "answer": "answer",
        "graph": {
            "title": "Candidate",
            "nodes": [{
                "id": "service",
                "label": "Service",
                "description": "Handles requests.",
                "evidence_chunk_ids": ["private-internal-id"],
            }],
            "edges": [],
        },
        "events": [
            {"type": "graph_data", "data": {"duplicate": True}},
            {"type": "worker_status", "worker": "graph", "status": "ready"},
        ],
    })

    assert payload["graph"]["title"] == "Candidate"
    assert "evidence_chunk_ids" not in payload["graph"]["nodes"][0]
    assert payload["events"] == [
        {"type": "worker_status", "worker": "graph", "status": "ready"}
    ]


def test_judge_payload_reconstructs_turns_and_discards_reset_drafts():
    payload = _judge_payload({
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
    })

    assert payload["turns"] == [
        {"turn": 1, "answer": "first answer"},
        {"turn": 2, "answer": "revised answer"},
    ]
    assert "answer" not in payload


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


def test_calibration_report_uses_every_reviewed_case_and_dimension():
    corpus = load_corpus().model_copy(deep=True)
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
                "judgments": [
                    {
                        "dimensions": [
                            {"dimension": dimension, "grade": "pass"}
                            for dimension in case.rubric_dimensions
                        ]
                    }
                ],
            }
        )

    report = calculate_calibration(corpus, {"evaluations": evaluations})

    assert report["passed"] is True
    assert report["judge_release"] == JUDGE_PROMPT_RELEASE
    assert report["agreement"] == 1
    assert report["labels"] == label_count


def test_infrastructure_startup_failure_still_writes_review_artifacts(tmp_path, monkeypatch):
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
