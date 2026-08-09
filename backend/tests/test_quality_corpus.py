import asyncio
import json
import time

import pytest

from eval.quality_corpus import (
    CORPUS_PATH,
    approval_manifest_sha256,
    corpus_sha256,
    load_corpus,
)
from eval.runtime_budget import (
    application_turn_timeout_seconds,
    browser_case_concurrency,
    browser_graph_case_concurrency,
    browser_infrastructure_retry_count,
    browser_suite_timeout_seconds,
    semantic_suite_timeout_seconds,
)


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
    assert all(
        rubric.pass_ and rubric.borderline and rubric.fail
        for rubric in corpus.rubrics.values()
    )
    assert all(case.provenance and case.risk_tags for case in corpus.cases)


def test_empty_and_oversized_inputs_are_not_live_model_cases():
    corpus = load_corpus()

    prompts = [step.prompt for case in corpus.cases for step in case.steps]
    assert all(prompt.strip() for prompt in prompts)
    assert all(len(prompt.encode("utf-8")) <= 12_000 for prompt in prompts)


def test_browser_budget_scales_with_turns_and_retains_a_hard_ceiling():
    corpus = load_corpus()
    one_turn = [corpus.by_id["rag-grounding"]]
    two_turns = [corpus.by_id["graph-expansion"]]
    manifest = json.loads(
        (CORPUS_PATH.parents[4] / "ci" / "quality.json").read_text(encoding="utf-8")
    )
    pr_cases = [corpus.by_id[case_id] for case_id in manifest["live"]["suites"]["pr"]]

    assert browser_suite_timeout_seconds(pr_cases) > browser_suite_timeout_seconds(
        one_turn
    )
    assert browser_suite_timeout_seconds(one_turn) > application_turn_timeout_seconds()
    assert (
        browser_suite_timeout_seconds(two_turns)
        > 2 * application_turn_timeout_seconds()
    )
    pr_graph_turns = sum(
        len(case.steps) for case in pr_cases if case.deterministic.graph_emitted is True
    )
    assert browser_suite_timeout_seconds(pr_cases) >= (
        manifest["live"]["budgets"]["browser_suite_base_timeout_seconds"]
        + pr_graph_turns * application_turn_timeout_seconds()
    )
    assert browser_suite_timeout_seconds(corpus.cases * 10) == 3600
    assert browser_case_concurrency() == 2
    assert browser_graph_case_concurrency() == 1
    assert browser_infrastructure_retry_count() == 1
    assert application_turn_timeout_seconds() == 390
    assert semantic_suite_timeout_seconds("pr") == 1200
    assert semantic_suite_timeout_seconds("full") == 3600


@pytest.mark.asyncio
async def test_browser_cases_run_with_bounded_concurrency_and_keep_corpus_order():
    from eval.browser_runner import _run_cases_bounded

    corpus = load_corpus()
    cases = [
        corpus.by_id[case_id] for case_id in ("rag-grounding", "research", "memory")
    ]
    active = 0
    maximum_active = 0
    graph_active = 0
    maximum_graph_active = 0
    two_cases_started = asyncio.Event()
    checkpoint_ids: list[list[str]] = []

    async def run_case(case):
        nonlocal active, maximum_active, graph_active, maximum_graph_active
        active += 1
        maximum_active = max(maximum_active, active)
        is_graph = case.deterministic.graph_emitted is True
        if is_graph:
            graph_active += 1
            maximum_graph_active = max(maximum_graph_active, graph_active)
        if active == 2:
            two_cases_started.set()
        await asyncio.wait_for(two_cases_started.wait(), timeout=1)
        await asyncio.sleep(
            {"rag-grounding": 0.03, "research": 0.01, "memory": 0.0}[case.id]
        )
        if is_graph:
            graph_active -= 1
        active -= 1
        return {"id": case.id}

    async def checkpoint(results):
        checkpoint_ids.append([result["id"] for result in results])

    results = await _run_cases_bounded(
        cases,
        max_concurrency=2,
        graph_max_concurrency=1,
        run_case=run_case,
        on_result=checkpoint,
    )

    assert maximum_active == 2
    assert maximum_graph_active == 1
    assert [result["id"] for result in results] == [
        "rag-grounding",
        "research",
        "memory",
    ]
    assert checkpoint_ids[-1] == ["rag-grounding", "research", "memory"]


@pytest.mark.asyncio
async def test_multi_turn_browser_case_sends_each_step_sequentially(monkeypatch):
    from eval.browser_runner import _send_case_steps

    case = load_corpus().by_id["memory"]
    active = 0
    maximum_active = 0
    step_order: list[int] = []

    async def fake_send_step(page, sent_case, step_index, frames, *, timeout_seconds):
        nonlocal active, maximum_active
        assert sent_case is case
        assert timeout_seconds == 390
        active += 1
        maximum_active = max(maximum_active, active)
        step_order.append(step_index)
        await asyncio.sleep(0)
        active -= 1
        return [{"type": "done", "step": step_index}]

    monkeypatch.setattr("eval.browser_runner._send_step", fake_send_step)
    events: list[dict] = []
    await _send_case_steps(None, case, [], events, timeout_seconds=390)

    assert step_order == [0, 1]
    assert maximum_active == 1
    assert [event["step"] for event in events] == [0, 1]


@pytest.mark.asyncio
async def test_browser_turn_timing_captures_request_identifiers(monkeypatch):
    from eval.browser_runner import _send_case_steps

    case = load_corpus().by_id["rag-grounding"]

    async def fake_send_step(page, sent_case, step_index, frames, *, timeout_seconds):
        del page, sent_case, step_index, timeout_seconds
        now = time.time()
        frames.extend(
            [
                {
                    "direction": "sent",
                    "message": {
                        "type": "start",
                        "client_request_id": "client-123",
                    },
                    "at": now,
                },
                {
                    "direction": "received",
                    "message": {"type": "worker_status", "request_id": "request-456"},
                    "at": now + 0.01,
                },
                {
                    "direction": "received",
                    "message": {"type": "response_delta", "content": "answer"},
                    "at": now + 0.02,
                },
                {
                    "direction": "received",
                    "message": {"type": "done"},
                    "at": now + 0.03,
                },
            ]
        )
        return [
            frame["message"] for frame in frames if frame["direction"] == "received"
        ]

    monkeypatch.setattr("eval.browser_runner._send_step", fake_send_step)
    timings = []
    await _send_case_steps(
        None,
        case,
        [],
        [],
        timeout_seconds=390,
        turn_timings=timings,
    )

    assert timings[0]["client_request_id"] == "client-123"
    assert timings[0]["request_id"] == "request-456"
    assert timings[0]["first_event_ms"] is not None
    assert timings[0]["first_token_ms"] >= timings[0]["first_event_ms"]


@pytest.mark.asyncio
async def test_browser_case_retries_once_only_for_infrastructure_failures():
    from eval.browser_runner import _run_case_with_retries

    case = load_corpus().by_id["rag-grounding"]
    calls = 0

    async def run_attempt(_case, attempt_number):
        nonlocal calls
        calls += 1
        if attempt_number == 1:
            return {
                "id": case.id,
                "thread_id": "thread-first",
                "screenshot": "screenshots/first.png",
                "trace": "traces/first.zip",
                "failure_details": [
                    {
                        "kind": "infrastructure",
                        "code": "provider_timeout",
                        "message": "provider timed out",
                        "blocking": True,
                        "retryable": True,
                    },
                    {
                        "kind": "infrastructure",
                        "code": "screenshot_failed",
                        "message": "screenshot capture failed",
                        "blocking": True,
                        "retryable": False,
                    },
                ],
                "deterministic_failures": [
                    "provider timed out",
                    "screenshot capture failed",
                ],
                "passed": False,
            }
        return {
            "id": case.id,
            "thread_id": "thread-second",
            "screenshot": "screenshots/second.png",
            "trace": "traces/second.zip",
            "failure_details": [],
            "deterministic_failures": [],
            "passed": True,
        }

    result = await _run_case_with_retries(
        case,
        retry_count=1,
        run_attempt=run_attempt,
    )

    assert calls == 2
    assert result["passed"] is True
    assert result["thread_ids"] == ["thread-first", "thread-second"]
    assert [attempt["screenshot"] for attempt in result["attempts"]] == [
        "screenshots/first.png",
        "screenshots/second.png",
    ]
    assert [attempt["trace"] for attempt in result["attempts"]] == [
        "traces/first.zip",
        "traces/second.zip",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_details",
    [
        [
            {
                "kind": "quality",
                "code": "graph_missing",
                "message": "graph missing",
                "blocking": True,
            }
        ],
        [
            {
                "kind": "infrastructure",
                "code": "provider_timeout",
                "message": "provider timed out",
                "blocking": True,
                "retryable": True,
            },
            {
                "kind": "quality",
                "code": "graph_missing",
                "message": "graph missing",
                "blocking": True,
            },
        ],
        [
            {
                "kind": "infrastructure",
                "code": "screenshot_failed",
                "message": "screenshot capture failed",
                "blocking": True,
                "retryable": False,
            }
        ],
    ],
)
async def test_browser_case_does_not_retry_quality_or_mixed_failures(failure_details):
    from eval.browser_runner import _run_case_with_retries

    case = load_corpus().by_id["rag-grounding"]
    calls = 0

    async def run_attempt(_case, attempt_number):
        nonlocal calls
        calls += 1
        return {
            "id": case.id,
            "thread_id": f"thread-{attempt_number}",
            "failure_details": failure_details,
            "deterministic_failures": [item["message"] for item in failure_details],
            "passed": False,
        }

    result = await _run_case_with_retries(case, retry_count=1, run_attempt=run_attempt)

    assert calls == 1
    assert result["retried"] is False


@pytest.mark.asyncio
async def test_browser_case_does_not_retry_a_missing_done_event():
    from eval.browser_runner import BrowserQualityError, _run_case_with_retries

    case = load_corpus().by_id["rag-grounding"]
    calls = 0

    async def run_attempt(_case, _attempt_number):
        nonlocal calls
        calls += 1
        raise BrowserQualityError(
            "websocket_done_missing", "WebSocket done event was missing"
        )

    result = await _run_case_with_retries(case, retry_count=1, run_attempt=run_attempt)

    assert calls == 1
    assert result["retried"] is False
    assert result["failure_details"][0]["kind"] == "quality"
    assert result["failure_details"][0]["code"] == "websocket_done_missing"
    assert result["failure_details"][0]["retryable"] is False


def test_browser_latency_summary_reports_nearest_rank_and_optional_gates():
    from eval.browser_runner import _latency_summary

    results = [
        {
            "latency_ms": case_latency,
            "failure_details": [],
            "turns": [
                {
                    "latency_ms": turn_latency,
                    "first_event_ms": first_event,
                    "first_token_ms": first_token,
                }
            ],
        }
        for case_latency, turn_latency, first_event, first_token in zip(
            [100, 200, 300, 400, 1000],
            [80, 180, 280, 380, 980],
            [10, 20, 30, 40, 50],
            [20, 40, 60, 80, 100],
            strict=True,
        )
    ]
    results.append(
        {
            "latency_ms": 9000,
            "failure_details": [
                {
                    "kind": "infrastructure",
                    "code": "provider_timeout",
                    "message": "provider timed out",
                    "blocking": True,
                    "retryable": True,
                }
            ],
            "turns": [{"latency_ms": 9000, "first_event_ms": 9000}],
        }
    )

    report_only = _latency_summary(results)
    blocking = _latency_summary(
        results,
        p50_threshold_ms=250,
        p95_threshold_ms=900,
        baseline_run_count=5,
    )

    assert report_only["metrics"] == {
        "case_end_to_end": {"sample_count": 5, "p50_ms": 300, "p95_ms": 1000},
        "turn_end_to_end": {"sample_count": 5, "p50_ms": 280, "p95_ms": 980},
        "first_event": {"sample_count": 5, "p50_ms": 30, "p95_ms": 50},
        "first_token": {"sample_count": 5, "p50_ms": 60, "p95_ms": 100},
    }
    assert report_only["excluded_infrastructure_case_count"] == 1
    assert report_only["baseline_min_runs"] == 5
    assert report_only["baseline_run_count"] == 1
    assert report_only["baseline_ready"] is False
    assert report_only["mode"] == "report-only"
    assert report_only["passed"] is True
    assert blocking["mode"] == "blocking"
    assert blocking["passed"] is False
    assert len(blocking["violations"]) == 2


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
        args=Namespace(
            suite="pr", target="http://frontend", backend_target="https://backend"
        ),
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
            **(
                {"sources": ["https://example.com/report"]}
                if worker == "research"
                else {}
            ),
        }
        for worker in case.deterministic.workers_include
    ] + [
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]

    book_only = _deterministic_failures(
        case,
        [
            *base_events,
            {"type": "response_delta", "content": "Supported (Chapter 3, p.42)."},
        ],
        rendered_nodes=1,
    )
    web_cited = _deterministic_failures(
        case,
        [
            *base_events,
            {
                "type": "response_delta",
                "content": "Supported https://example.com/report",
            },
        ],
        rendered_nodes=1,
    )
    fabricated = _deterministic_failures(
        case,
        [
            *base_events,
            {"type": "response_delta", "content": "Supported https://made-up.invalid"},
        ],
        rendered_nodes=1,
    )

    assert "required web citation did not match supplied research evidence" in book_only
    assert (
        "required web citation did not match supplied research evidence" in fabricated
    )
    assert not any("citation" in failure for failure in web_cited)


def test_web_research_provider_failure_is_classified_as_infrastructure():
    from eval.browser_runner import (
        _deterministic_failure_details,
        _deterministic_failures,
    )

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
        {
            "type": "response_delta",
            "content": "Book-grounded answer (Chapter 3, p.42).",
        },
        {"type": "done"},
    ]

    failures = _deterministic_failures(case, events, rendered_nodes=1)
    details = _deterministic_failure_details(case, events, rendered_nodes=1)

    assert "research infrastructure unavailable: no citable web sources" in failures
    research_failure = next(
        detail for detail in details if detail["code"] == "research_unavailable"
    )
    assert research_failure["kind"] == "infrastructure"


def test_graph_dom_inspection_is_only_enabled_for_renderable_graph_cases():
    from eval.browser_runner import _should_inspect_graph_dom

    cases = load_corpus().by_id
    graph_case = cases["graph-expansion"]
    no_graph_case = cases["graph-off"]
    ambiguous_case = cases["ambiguity"]
    graph_data = {"nodes": [{"id": "n1"}], "edges": []}

    assert _should_inspect_graph_dom(graph_case, graph_data) is True
    assert _should_inspect_graph_dom(graph_case, None) is False
    assert _should_inspect_graph_dom(no_graph_case, graph_data) is False
    assert _should_inspect_graph_dom(ambiguous_case, graph_data) is False


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
            {
                "chapter": 8,
                "page_number": 404,
                "text": "evaluation examples can seed data",
            },
        ],
    }
    answer = {
        "type": "response_delta",
        "content": "Rubrics evolve (Chapter 4, p.224), and examples seed data (Chapter 8, p.404).",
    }

    matching = _deterministic_failures(
        case, [*base_events, evidence, answer], rendered_nodes=0
    )
    missing = _deterministic_failures(case, [*base_events, answer], rendered_nodes=0)
    unsupported = _deterministic_failures(
        case,
        [
            *base_events,
            evidence,
            {**answer, "content": "Unsupported (Chapter 9, p.999)."},
        ],
        rendered_nodes=0,
    )

    assert not any(
        "citation" in failure or "provenance" in failure for failure in matching
    )
    assert "book retrieval completed without source provenance telemetry" in missing
    assert "book citation did not match supplied retrieval evidence" in unsupported


def test_browser_review_includes_retrieved_evidence_for_human_review(tmp_path):
    from eval.browser_runner import _write_html

    output = tmp_path / "review.html"
    _write_html(
        output,
        {
            "corpus_version": "test-v1",
            "results": [
                {
                    "id": "citations",
                    "passed": True,
                    "answer": "Grounded answer (Chapter 8, p.404).",
                    "deterministic_failures": [],
                    "screenshot": "screenshots/citations.png",
                    "events": [
                        {
                            "type": "retrieval_evidence",
                            "chunks": [
                                {
                                    "chapter": 8,
                                    "page_number": 404,
                                    "text": "source passage",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    review = output.read_text(encoding="utf-8")
    assert "Retrieved evidence" in review
    assert "source passage" in review


def test_browser_review_handles_an_attempt_without_a_screenshot(tmp_path):
    from eval.browser_runner import _write_html

    output = tmp_path / "review.html"
    _write_html(
        output,
        {
            "corpus_version": "test-v1",
            "results": [
                {
                    "id": "rag-grounding",
                    "passed": False,
                    "answer": "",
                    "deterministic_failures": ["browser failed before capture"],
                    "screenshot": None,
                    "events": [],
                }
            ],
        },
    )

    assert "No screenshot was captured" in output.read_text(encoding="utf-8")


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
                "judge_model": "claude-opus-5",
                "evidence_run_id": "123456789",
                "evidence_commit_sha": "a" * 40,
                "evidence_sha256": "b" * 64,
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
                "reviewed_grades": {
                    dimension: "pass" for dimension in case["rubric_dimensions"]
                },
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    raw["approval"]["approved_manifest_sha256"] = approval_manifest_sha256(path)
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert load_corpus(require_approved=True, path=path).approval.status == "approved"

    raw["cases"][0]["steps"][0]["prompt"] += " changed"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash does not match"):
        load_corpus(require_approved=True, path=path)


def test_approval_changes_do_not_change_behavior_identity_but_invalidate_approval(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-08-02T12:00:00Z",
            "calibration": {
                "judge_release": "semantic-rubric-judge-v5",
                "judge_model": "claude-opus-5",
                "evidence_run_id": "123456789",
                "evidence_commit_sha": "a" * 40,
                "evidence_sha256": "b" * 64,
                "agreement": 0.9,
                "critical_false_passes": 0,
                "evaluated_at": "2026-08-02T12:00:00Z",
            },
        }
    )
    for case in raw["cases"]:
        case["approval"].update(
            {
                "status": "approved",
                "reviewer": "reviewer",
                "reviewed_at": "2026-08-02T12:00:00Z",
                "review_run_id": "github-run-123",
                "reviewed_grades": {
                    dimension: "pass" for dimension in case["rubric_dimensions"]
                },
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    raw["approval"]["approved_manifest_sha256"] = approval_manifest_sha256(path)
    path.write_text(json.dumps(raw), encoding="utf-8")
    behavior_sha = corpus_sha256(path)

    raw["approval"]["calibration"]["evidence_sha256"] = "f" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert corpus_sha256(path) == behavior_sha
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
                "judge_model": "claude-opus-5",
                "evidence_run_id": "123456789",
                "evidence_commit_sha": "a" * 40,
                "evidence_sha256": "b" * 64,
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
                "reviewed_grades": {
                    dimension: "pass" for dimension in case["rubric_dimensions"]
                },
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_corpus(path=path)
