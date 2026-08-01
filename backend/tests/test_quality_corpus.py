import json

import pytest

from eval.quality_corpus import CORPUS_PATH, corpus_sha256, load_corpus


def test_corpus_has_exactly_twenty_versioned_cases_and_six_anchored_rubrics():
    corpus = load_corpus()

    assert len(corpus.cases) == 20
    assert set(corpus.rubrics) == {
        "correctness",
        "relevance",
        "grounding",
        "instruction_following",
        "domain_specificity",
        "safety",
    }
    assert all(rubric.pass_ and rubric.borderline and rubric.fail for rubric in corpus.rubrics.values())
    assert all(case.provenance and case.risk_tags for case in corpus.cases)


def test_empty_and_oversized_inputs_are_not_live_model_cases():
    corpus = load_corpus()

    prompts = [step.prompt for case in corpus.cases for step in case.steps]
    assert all(prompt.strip() for prompt in prompts)
    assert all(len(prompt.encode("utf-8")) <= 12_000 for prompt in prompts)


def test_diagnostic_browser_suite_accepts_only_bounded_corpus_case_selection():
    from eval.browser_runner import _suite_case_ids

    assert _suite_case_ids("diagnostic", ["citations", "rag-grounding"]) == [
        "citations",
        "rag-grounding",
    ]
    with pytest.raises(ValueError, match="at least one"):
        _suite_case_ids("diagnostic", [])
    with pytest.raises(ValueError, match="unknown diagnostic"):
        _suite_case_ids("diagnostic", ["not-a-case"])
    with pytest.raises(ValueError, match="only with --suite diagnostic"):
        _suite_case_ids("full", ["citations"])


def test_browser_capture_checkpoint_preserves_completed_results(monkeypatch):
    from argparse import Namespace
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from eval.browser_runner import _browser_report

    monkeypatch.setattr("eval.browser_runner.corpus_sha256", lambda: "corpus-sha")
    report = _browser_report(
        args=Namespace(suite="pr", target="http://frontend", backend_target="https://backend"),
        corpus=SimpleNamespace(corpus_version="v1", release_identity="release-v1"),
        started_at=datetime(2026, 7, 22, tzinfo=UTC),
        started=0.0,
        results=[{"id": "completed-case", "passed": False}],
        status="partial",
    )

    assert report["status"] == "partial"
    assert report["results"] == [{"id": "completed-case", "passed": False}]
    assert report["corpus_sha256"] == "corpus-sha"


def test_current_research_cases_require_verifiable_web_sources():
    corpus = load_corpus()
    research_cases = [case for case in corpus.cases if "web" in case.risk_tags]

    assert research_cases
    assert all(case.deterministic.citations_required for case in research_cases)
    assert all(case.deterministic.citation_source == "web" for case in research_cases)


def test_web_research_does_not_accept_a_book_citation_as_current_evidence():
    from eval.browser_runner import _deterministic_failures

    case = load_corpus().by_id["research"]
    graph = {"nodes": [{"id": "agent"}], "edges": []}
    base_events = [
        {
            "type": "worker_status",
            "worker": worker,
            "status": "ready",
            **({"sources": ["https://example.com/report"]} if worker == "research" else {}),
        }
        for worker in case.deterministic.workers_include
    ] + [
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]

    book_only = _deterministic_failures(
        case,
        [*base_events, {"type": "response_delta", "content": "Supported (Chapter 3, p.42)."}],
        rendered_nodes=1,
    )
    web_cited = _deterministic_failures(
        case,
        [*base_events, {"type": "response_delta", "content": "Supported https://example.com/report"}],
        rendered_nodes=1,
    )
    fabricated = _deterministic_failures(
        case,
        [*base_events, {"type": "response_delta", "content": "Supported https://made-up.invalid"}],
        rendered_nodes=1,
    )

    assert "required web citation did not match supplied research evidence" in book_only
    assert "required web citation did not match supplied research evidence" in fabricated
    assert not any("citation" in failure for failure in web_cited)


def test_web_research_provider_failure_is_classified_as_infrastructure():
    from eval.browser_runner import _deterministic_failures

    case = load_corpus().by_id["research"]
    events = [
        {
            "type": "worker_status",
            "worker": worker,
            "status": "Web research unavailable" if worker == "research" else "ready",
        }
        for worker in case.deterministic.workers_include
    ] + [
        {"type": "graph_data", "data": {"nodes": [{"id": "agent"}], "edges": []}},
        {"type": "response_delta", "content": "Book-grounded answer (Chapter 3, p.42)."},
        {"type": "done"},
    ]

    failures = _deterministic_failures(case, events, rendered_nodes=1)

    assert "research infrastructure unavailable: no citable web sources" in failures


def test_book_citations_must_match_retrieval_provenance():
    from eval.browser_runner import _deterministic_failures

    case = load_corpus().by_id["citations"]
    base_events = [
        {"type": "worker_status", "worker": "rag", "status": "ready"},
        {"type": "done"},
    ]
    evidence = {
        "type": "retrieval_evidence",
        "query": "Why should eval data grow?",
        "chunks": [
            {"chapter": 4, "page_number": 224, "text": "rubrics are refined"},
            {"chapter": 8, "page_number": 404, "text": "evaluation examples can seed data"},
        ],
    }
    answer = {
        "type": "response_delta",
        "content": "Rubrics evolve (Chapter 4, p.224), and examples seed data (Chapter 8, p.404).",
    }

    matching = _deterministic_failures(case, [*base_events, evidence, answer], rendered_nodes=0)
    missing = _deterministic_failures(case, [*base_events, answer], rendered_nodes=0)
    unsupported = _deterministic_failures(
        case,
        [*base_events, evidence, {**answer, "content": "Unsupported (Chapter 9, p.999)."}],
        rendered_nodes=0,
    )

    assert not any("citation" in failure or "provenance" in failure for failure in matching)
    assert "book retrieval completed without source provenance telemetry" in missing
    assert "book citation did not match supplied retrieval evidence" in unsupported


def test_browser_review_includes_retrieved_evidence_for_human_review(tmp_path):
    from eval.browser_runner import _write_html

    output = tmp_path / "review.html"
    _write_html(output, {
        "corpus_version": "test-v1",
        "results": [{
            "id": "citations",
            "passed": True,
            "answer": "Grounded answer (Chapter 8, p.404).",
            "deterministic_failures": [],
            "screenshot": "screenshots/citations.png",
            "events": [{
                "type": "retrieval_evidence",
                "chunks": [{"chapter": 8, "page_number": 404, "text": "source passage"}],
            }],
        }],
    })

    review = output.read_text(encoding="utf-8")
    assert "Retrieved evidence" in review
    assert "source passage" in review


def test_unapproved_corpus_cannot_enable_the_blocking_judge(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    raw["approval"].update(
        {
            "status": "pending_human_review",
            "reviewed_by": None,
            "reviewed_at": None,
            "approved_manifest_sha256": None,
            "calibration": {
                "judge_release": "semantic-rubric-judge-v5",
                "agreement": None,
                "critical_false_passes": None,
                "evaluated_at": None,
            },
        }
    )
    path = tmp_path / "pending-cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(RuntimeError, match="pending human review"):
        load_corpus(require_approved=True, path=path)


def test_approved_hash_is_content_addressed(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-07-18T12:00:00Z",
            "calibration": {
                "judge_release": "semantic-rubric-judge-v1",
                "agreement": 0.9,
                "critical_false_passes": 1,
                "evaluated_at": "2026-07-18T12:00:00Z",
            },
        }
    )
    for case in raw["cases"]:
        case["approval"].update(
            {
                "status": "approved",
                "reviewer": "reviewer",
                "reviewed_at": "2026-07-18T12:00:00Z",
                "review_run_id": "github-run-123",
                "reviewed_grades": {dimension: "pass" for dimension in case["rubric_dimensions"]},
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    raw["approval"]["approved_manifest_sha256"] = corpus_sha256(path)
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert load_corpus(require_approved=True, path=path).approval.status == "approved"

    raw["cases"][0]["steps"][0]["prompt"] += " changed"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash does not match"):
        load_corpus(require_approved=True, path=path)


@pytest.mark.parametrize(
    ("agreement", "critical_false_passes", "message"),
    [
        (0.84, 0, "85% judge agreement"),
        (0.95, 2, "at most one critical false pass"),
    ],
)
def test_approved_corpus_rejects_uncalibrated_judge(
    tmp_path, agreement, critical_false_passes, message
):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-07-18T12:00:00Z",
            "calibration": {
                "judge_release": "semantic-rubric-judge-v1",
                "agreement": agreement,
                "critical_false_passes": critical_false_passes,
                "evaluated_at": "2026-07-18T12:00:00Z",
            },
        }
    )
    for case in raw["cases"]:
        case["approval"].update(
            {
                "status": "approved",
                "reviewer": "reviewer",
                "reviewed_at": "2026-07-18T12:00:00Z",
                "review_run_id": "github-run-123",
                "reviewed_grades": {dimension: "pass" for dimension in case["rubric_dimensions"]},
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_corpus(path=path)
