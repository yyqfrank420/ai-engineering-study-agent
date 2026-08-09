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
    graph_lane_count = manifest["live"]["budgets"]["browser_graph_case_concurrency"]
    graph_lane_batches = (pr_graph_turns + graph_lane_count - 1) // graph_lane_count
    assert browser_suite_timeout_seconds(pr_cases) >= (
        manifest["live"]["budgets"]["browser_suite_base_timeout_seconds"]
        + graph_lane_batches * application_turn_timeout_seconds()
    )
    assert browser_suite_timeout_seconds(corpus.cases * 10) == 3600
    assert browser_case_concurrency() == 4
    assert browser_graph_case_concurrency() == 2
    assert browser_infrastructure_retry_count() == 0
    assert application_turn_timeout_seconds() == 970
    assert semantic_suite_timeout_seconds("pr") == 1200
    assert semantic_suite_timeout_seconds("full") == 3600


@pytest.mark.asyncio
async def test_browser_cases_run_with_bounded_concurrency_and_keep_corpus_order():
    from eval.browser_runner import _run_cases_bounded

    corpus = load_corpus()
    case_ids = ("rag-grounding", "research", "memory", "graph-off")
    cases = [corpus.by_id[case_id] for case_id in case_ids]
    active = 0
    maximum_active = 0
    graph_active = 0
    maximum_graph_active = 0
    four_cases_started = asyncio.Event()
    checkpoint_ids: list[list[str]] = []

    async def run_case(case):
        nonlocal active, maximum_active, graph_active, maximum_graph_active
        active += 1
        maximum_active = max(maximum_active, active)
        is_graph = case.deterministic.graph_emitted is True
        if is_graph:
            graph_active += 1
            maximum_graph_active = max(maximum_graph_active, graph_active)
        if active == 4:
            four_cases_started.set()
        await asyncio.wait_for(four_cases_started.wait(), timeout=1)
        await asyncio.sleep(
            {
                "rag-grounding": 0.03,
                "research": 0.01,
                "memory": 0.02,
                "graph-off": 0.0,
            }[case.id]
        )
        if is_graph:
            graph_active -= 1
        active -= 1
        return {"id": case.id}

    async def checkpoint(results):
        checkpoint_ids.append([result["id"] for result in results])

    results = await _run_cases_bounded(
        cases,
        max_concurrency=4,
        graph_max_concurrency=2,
        run_case=run_case,
        on_result=checkpoint,
    )

    assert maximum_active == 4
    assert maximum_graph_active == 2
    assert [result["id"] for result in results] == list(case_ids)
    assert checkpoint_ids[-1] == list(case_ids)
    assert checkpoint_ids.count(list(case_ids)) == 1


@pytest.mark.asyncio
async def test_browser_cases_defer_retry_until_every_first_attempt_completes():
    from eval.browser_runner import _run_cases_with_deferred_retries

    corpus = load_corpus()
    cases = [corpus.by_id["research"], corpus.by_id["node-followup"]]
    calls: list[tuple[str, int]] = []

    async def run_attempt(case, attempt_number):
        calls.append((case.id, attempt_number))
        retryable_failure = case.id == "research" and attempt_number == 1
        detail = {
            "kind": "infrastructure",
            "code": "browser_transport_failed",
            "message": "temporary transport failure",
            "blocking": True,
            "retryable": True,
        }
        return {
            "id": case.id,
            "attempt": attempt_number,
            "thread_id": f"{case.id}-{attempt_number}",
            "passed": not retryable_failure,
            "failure_details": [detail] if retryable_failure else [],
            "deterministic_failures": (
                [detail["message"]] if retryable_failure else []
            ),
        }

    results = await _run_cases_with_deferred_retries(
        cases,
        max_concurrency=2,
        graph_max_concurrency=1,
        retry_count=1,
        run_attempt=run_attempt,
    )

    assert calls == [
        ("research", 1),
        ("node-followup", 1),
        ("research", 2),
    ]
    assert results[0]["attempt_count"] == 2
    assert results[0]["thread_ids"] == ["research-1", "research-2"]
    assert results[1]["attempt_count"] == 1
    assert results[1]["retried"] is False


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
    assert [event["eval_turn"] for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_multi_turn_case_stops_after_unexpected_timeout_error(monkeypatch):
    from eval.browser_runner import BrowserInfrastructureError, _send_case_steps

    case = load_corpus().by_id["graph-expansion"]
    step_order: list[int] = []

    async def fake_send_step(page, sent_case, step_index, frames, *, timeout_seconds):
        del page, sent_case, frames, timeout_seconds
        step_order.append(step_index)
        return [
            {"type": "error", "content": "Response timed out. Please try again."},
            {"type": "done"},
        ]

    monkeypatch.setattr("eval.browser_runner._send_step", fake_send_step)
    events: list[dict] = []
    timings: list[dict] = []
    with pytest.raises(BrowserInfrastructureError) as raised:
        await _send_case_steps(
            None,
            case,
            [],
            events,
            timeout_seconds=390,
            turn_timings=timings,
        )

    assert raised.value.code == "application_response_timeout"
    assert raised.value.retryable is False
    assert step_order == [0]
    assert [event["type"] for event in events] == ["error", "done"]
    assert len(timings) == 1


@pytest.mark.asyncio
async def test_required_graph_notice_stops_before_a_later_graph(monkeypatch):
    from eval.browser_runner import BrowserQualityError, _send_case_steps

    case = load_corpus().by_id["graph-expansion"]
    step_order = []

    async def fake_send_step(page, sent_case, step_index, frames, *, timeout_seconds):
        del page, sent_case, frames, timeout_seconds
        step_order.append(step_index)
        if step_index == 0:
            return [{"type": "graph_notice"}, {"type": "done"}]
        return [
            {
                "type": "graph_data",
                "data": {"version": "graph-v1", "nodes": [], "edges": []},
            },
            {"type": "done"},
        ]

    monkeypatch.setattr("eval.browser_runner._send_step", fake_send_step)
    with pytest.raises(BrowserQualityError) as raised:
        await _send_case_steps(None, case, [], [], timeout_seconds=390)

    assert raised.value.code == "required_graph_withheld"
    assert step_order == [0]


def test_required_graph_notice_wins_over_same_turn_graph_resync():
    from eval.browser_runner import _required_graph_turn_failure

    case = load_corpus().by_id["graph-expansion"]
    failure = _required_graph_turn_failure(
        case,
        0,
        [
            {"type": "graph_notice"},
            {"type": "graph_data", "data": {"nodes": [], "edges": []}},
        ],
    )

    assert failure is not None
    assert failure[0] == "required_graph_withheld"


def test_required_graph_turn_without_notice_requires_graph_data():
    from eval.browser_runner import _required_graph_turn_failure

    case = load_corpus().by_id["graph-expansion"]

    assert _required_graph_turn_failure(case, 0, [{"type": "done"}]) == (
        "required_graph_missing",
        "case graph-expansion turn 1 required graph_data",
    )


def test_graph_dom_inspection_is_only_enabled_for_renderable_graph_cases():
    from eval.browser_runner import _should_inspect_graph_dom

    cases = load_corpus().by_id
    graph_case = cases["graph-expansion"]
    non_renderable_case = cases["graph-off"]
    ambiguous_case = cases["ambiguity"]
    graph_data = {"nodes": [{"id": "n1"}], "edges": []}

    assert _should_inspect_graph_dom(graph_case, graph_data) is True
    assert _should_inspect_graph_dom(graph_case, None) is False
    assert _should_inspect_graph_dom(non_renderable_case, graph_data) is False
    assert _should_inspect_graph_dom(ambiguous_case, graph_data) is False


@pytest.mark.asyncio
async def test_required_graph_turn_must_render_before_the_next_turn(monkeypatch):
    from eval.browser_runner import BrowserQualityError, _send_case_steps

    case = load_corpus().by_id["graph-expansion"]
    step_order: list[int] = []

    class IdentityLocator:
        async def evaluate_all(self, _script):
            return []

    class Canvas:
        def locator(self, _selector):
            return IdentityLocator()

        async def get_attribute(self, _name):
            return "stale-version"

    class Page:
        def locator(self, selector):
            assert selector == '[data-testid="graph-canvas"]'
            return Canvas()

    async def fake_send_step(page, sent_case, step_index, frames, *, timeout_seconds):
        del page, sent_case, frames, timeout_seconds
        step_order.append(step_index)
        return [
            {
                "type": "graph_data",
                "data": {
                    "version": f"graph-{step_index}",
                    "nodes": [{"id": "source"}, {"id": "target"}],
                    "edges": [
                        {"source": "source", "target": "target", "label": "sends"}
                    ],
                },
            },
            {"type": "done"},
        ]

    monkeypatch.setattr("eval.browser_runner._send_step", fake_send_step)
    with pytest.raises(BrowserQualityError) as raised:
        await _send_case_steps(Page(), case, [], [], timeout_seconds=390)

    assert raised.value.code == "required_graph_turn_render_mismatch"
    assert step_order == [0]


def test_required_graph_turn_rejects_missing_and_reused_versions():
    from eval.browser_runner import _required_graph_turn_failure

    case = load_corpus().by_id["graph-expansion"]
    graph = {"nodes": [{"id": "source"}], "edges": []}

    assert _required_graph_turn_failure(
        case,
        0,
        [{"type": "graph_data", "data": graph}],
        set(),
    ) == (
        "required_graph_version_missing",
        "case graph-expansion turn 1 graph_data has no version",
    )
    versioned = {**graph, "version": "graph-v1"}
    assert _required_graph_turn_failure(
        case,
        1,
        [{"type": "graph_data", "data": versioned}],
        {"graph-v1"},
    ) == (
        "required_graph_version_reused",
        "case graph-expansion turn 2 reused graph version graph-v1",
    )


@pytest.mark.asyncio
async def test_required_graph_turn_rejects_wrong_same_count_dom_identity(monkeypatch):
    from eval.browser_runner import _required_graph_turn_render_failure

    case = load_corpus().by_id["graph-expansion"]
    graph = {
        "version": "graph-v2",
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [{"source": "source", "target": "target", "label": "sends"}],
    }

    async def stale_dom(_page, _graph):
        return {
            "node_ids": ["old-source", "old-target"],
            "edges": [
                {"source": "old-source", "target": "old-target", "label": "sends"}
            ],
            "version": "graph-v2",
        }

    monkeypatch.setattr("eval.browser_runner._graph_dom_state", stale_dom)
    failure = await _required_graph_turn_render_failure(
        object(),
        case,
        0,
        [{"type": "graph_data", "data": graph}],
    )

    assert failure is not None
    assert failure[0] == "required_graph_turn_node_identity_mismatch"


@pytest.mark.asyncio
async def test_expected_error_case_can_continue_to_a_later_turn(monkeypatch):
    from eval.browser_runner import _send_case_steps

    original = load_corpus().by_id["graph-expansion"]
    case = original.model_copy(
        update={
            "deterministic": original.deterministic.model_copy(
                update={"error_expected": True, "graph_emitted": False}
            )
        }
    )
    step_order: list[int] = []

    async def fake_send_step(page, sent_case, step_index, frames, *, timeout_seconds):
        del page, sent_case, frames, timeout_seconds
        step_order.append(step_index)
        if step_index == 0:
            return [{"type": "error", "content": "expected"}, {"type": "done"}]
        return [{"type": "done"}]

    monkeypatch.setattr("eval.browser_runner._send_step", fake_send_step)
    await _send_case_steps(None, case, [], [], timeout_seconds=390)

    assert step_order == [0, 1]


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
            {
                "type": "graph_data",
                "data": {"version": "graph-v1", "nodes": [], "edges": []},
            },
            *[frame["message"] for frame in frames if frame["direction"] == "received"],
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


def test_application_deadline_infrastructure_is_explicitly_non_retryable():
    from eval.browser_runner import (
        BrowserInfrastructureError,
        _exception_failure_detail,
    )

    detail = _exception_failure_detail(
        BrowserInfrastructureError(
            "application_turn_timeout",
            "application exceeded its deadline",
            retryable=False,
        )
    )

    assert detail["kind"] == "infrastructure"
    assert detail["code"] == "application_turn_timeout"
    assert detail["retryable"] is False


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


@pytest.mark.asyncio
async def test_browser_timeout_finalization_keeps_partial_results_and_telemetry(
    tmp_path, monkeypatch
):
    from argparse import Namespace
    from datetime import UTC, datetime

    from eval.browser_runner import _finalize_timed_out_browser, _write_json_atomic

    output = tmp_path / "browser-results.json"
    checkpoint = {
        "format_version": 1,
        "kind": "browser_capture",
        "suite": "diagnostic",
        "corpus_version": "v1",
        "corpus_sha256": corpus_sha256(),
        "release_identity": "release",
        "target": "http://frontend",
        "backend_target": "https://backend",
        "started_at": datetime(2026, 8, 2, tzinfo=UTC).isoformat(),
        "duration_ms": 11_000,
        "status": "partial",
        "results": [
            {
                "id": "rag-grounding",
                "execution_state": "completed",
                "deterministic_failures": [],
                "failure_details": [],
                "answer": "grounded answer",
                "turns": [],
                "events": [],
                "thread_id": "thread-1",
                "thread_ids": ["thread-1"],
                "screenshot": None,
                "latency_ms": 1_000,
                "passed": True,
            }
        ],
    }
    _write_json_atomic(output, checkpoint)
    args = Namespace(
        suite="diagnostic",
        case=["rag-grounding", "memory"],
        output=str(output),
        target="http://frontend",
        backend_target="https://backend",
        email="eval@example.com",
        internal_password="secret",
    )

    async def fake_internal_session(*_args):
        return {"access_token": "token"}

    def fake_request(_method, url, _payload, _token):
        if "eval-telemetry" in url:
            assert "thread_id=thread-1" in url
            return {"calls": [{"thread_id": "thread-1", "model": "claude-opus-5"}]}
        if url.endswith("/overview"):
            return {"kpis": {}, "providers": {}}
        raise AssertionError(url)

    monkeypatch.setattr("eval.browser_runner._internal_session", fake_internal_session)
    monkeypatch.setattr("eval.browser_runner._blocking_json_request", fake_request)
    monkeypatch.setattr(
        "eval.browser_runner.browser_suite_timeout_seconds", lambda _cases: 12
    )

    report = await _finalize_timed_out_browser(args)

    assert report["status"] == "timed_out"
    assert report["failure"]["code"] == "browser_suite_timeout"
    assert [result["id"] for result in report["results"]] == [
        "rag-grounding",
        "memory",
    ]
    assert report["results"][0]["passed"] is True
    assert report["results"][1]["execution_state"] == "not_started"
    assert report["results"][1]["failure_details"][0]["code"] == (
        "browser_suite_timeout"
    )
    assert report["application_telemetry"][0]["thread_id"] == "thread-1"
    assert report["dashboard_smoke"]["passed"] is True
    assert report["finalization_failures"] == []
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "timed_out"
    assert 'tests="2" failures="1"' in (tmp_path / "browser-junit.xml").read_text(
        encoding="utf-8"
    )


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


def test_graph_renderability_checks_declared_edges_in_the_live_dom():
    from eval.browser_runner import _deterministic_failure_details

    case = load_corpus().by_id["graph-renderability"]
    graph = {
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [{"source": "source", "target": "target", "label": "sends"}],
    }
    events = [
        *[
            {"type": "worker_status", "worker": worker, "status": "ready"}
            for worker in case.deterministic.workers_include
        ],
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]

    details = _deterministic_failure_details(
        case,
        events,
        rendered_nodes=2,
        rendered_edges=0,
    )

    assert any(detail["code"] == "graph_edge_render_mismatch" for detail in details)


def test_graph_renderability_rejects_a_stale_larger_canvas_and_version():
    from eval.browser_runner import _deterministic_failure_details

    case = load_corpus().by_id["graph-renderability"]
    graph = {
        "version": "current-graph",
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [{"source": "source", "target": "target", "label": "sends"}],
    }
    events = [
        *[
            {"type": "worker_status", "worker": worker, "status": "ready"}
            for worker in case.deterministic.workers_include
        ],
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]

    details = _deterministic_failure_details(
        case,
        events,
        rendered_nodes=3,
        rendered_edges=2,
        rendered_graph_version="stale-graph",
    )

    assert {detail["code"] for detail in details} >= {
        "graph_render_mismatch",
        "graph_edge_render_mismatch",
        "graph_version_render_mismatch",
    }


def test_auto_graph_mode_rejects_wrong_same_count_dom_identity():
    from eval.browser_runner import _deterministic_failure_details

    case = load_corpus().by_id["research"]
    graph = {
        "version": "current-graph",
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [{"source": "source", "target": "target", "label": "sends"}],
    }
    events = [
        *[
            {"type": "worker_status", "worker": worker, "status": "ready"}
            for worker in case.deterministic.workers_include
        ],
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]

    details = _deterministic_failure_details(
        case,
        events,
        rendered_nodes=2,
        rendered_edges=1,
        rendered_graph_version="current-graph",
        rendered_node_ids=["old-source", "old-target"],
        rendered_edge_identities=[
            {"source": "old-source", "target": "old-target", "label": "sends"}
        ],
    )

    assert {detail["code"] for detail in details} >= {
        "graph_node_identity_mismatch",
        "graph_edge_identity_mismatch",
    }


def test_auto_graph_mode_rejects_versionless_graph():
    from eval.browser_runner import _deterministic_failure_details

    case = load_corpus().by_id["research"]
    graph = {
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [{"source": "source", "target": "target", "label": "sends"}],
    }
    events = [
        *[
            {"type": "worker_status", "worker": worker, "status": "ready"}
            for worker in case.deterministic.workers_include
        ],
        {"type": "graph_data", "data": graph},
        {"type": "done"},
    ]

    details = _deterministic_failure_details(
        case,
        events,
        rendered_nodes=2,
        rendered_edges=1,
        rendered_node_ids=["source", "target"],
        rendered_edge_identities=[
            {"source": "source", "target": "target", "label": "sends"}
        ],
    )

    assert "graph_version_missing" in {detail["code"] for detail in details}


@pytest.mark.asyncio
async def test_node_followup_missing_graph_skips_activation_and_reports_graph_failure():
    from eval.browser_runner import (
        _deterministic_failure_details,
        _node_followup_interaction_failure_details,
    )

    class ActivationForbiddenPage:
        def get_by_role(self, *_args, **_kwargs):
            raise AssertionError(
                "node activation must not start without an accepted graph"
            )

        def expect_request(self, *_args, **_kwargs):
            raise AssertionError(
                "activation request must not start without an accepted graph"
            )

        def locator(self, *_args, **_kwargs):
            raise AssertionError("node locator must not run without an accepted graph")

    case = load_corpus().by_id["node-followup"]
    events = [
        {
            "type": "graph_notice",
            "message": "The graph was withheld after bounded repair.",
        },
        {"type": "done"},
    ]
    failure_details = _deterministic_failure_details(
        case,
        events,
        rendered_nodes=0,
    )

    interaction_failures = await _node_followup_interaction_failure_details(
        ActivationForbiddenPage(),
        case,
        None,
        failure_details,
    )

    assert any(
        detail["message"] == "graph_emitted expected True, got False"
        for detail in failure_details
    )
    assert interaction_failures == []
    assert not any(
        detail["code"] == "node_followup_interaction_failed"
        for detail in failure_details
    )


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
                "judge_provider": "openai",
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
                "judge_provider": "openai",
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


def test_approval_changes_do_not_change_behavior_identity_but_invalidate_approval(
    tmp_path,
):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "cases.json"
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
                "judge_provider": "openai",
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


_REPLAY_PR_CASES = (
    "rag-grounding",
    "memory",
    "graph-off",
    "research",
    "node-followup",
    "graph-expansion",
    "applied-domain",
    "prompt-injection",
)


def _selective_replay_source_capture():
    graph_cases = {
        "rag-grounding",
        "research",
        "node-followup",
        "graph-expansion",
        "applied-domain",
    }
    results = []
    telemetry = []
    for case_id in _REPLAY_PR_CASES:
        thread_id = f"thread-{case_id}"
        results.append(
            {
                "id": case_id,
                "passed": True,
                "execution_state": "completed",
                "thread_id": thread_id,
                "thread_ids": [thread_id],
                "attempts": [
                    {
                        "attempt": 1,
                        "thread_id": thread_id,
                        "thread_ids": [thread_id],
                    }
                ],
            }
        )
        telemetry.append(
            {
                "thread_id": thread_id,
                "operation": (
                    "graph_worker_applied_design"
                    if case_id in graph_cases
                    else "orchestrator_synthesise"
                ),
                "provider_attempts": 1,
                "attempts": [{"attempt": 1, "status": "success"}],
            }
        )
    return {
        "format_version": 1,
        "kind": "browser_capture",
        "suite": "pr",
        "corpus_version": "2026-07-19.v2",
        "corpus_sha256": "a" * 64,
        "release_identity": "browser-rubric-v2",
        "target": "http://localhost:5173",
        "backend_target": "https://candidate.example",
        "started_at": "2026-08-05T09:19:21+00:00",
        "duration_ms": 999999,
        "status": "complete",
        "case_states": [
            {"id": case_id, "state": "completed"} for case_id in _REPLAY_PR_CASES
        ],
        "results": results,
        "application_telemetry": telemetry,
        "latency": {"sample_count": 8},
        "dashboard_smoke": {"passed": True},
    }


def test_selective_replay_subsets_only_passing_non_graph_evidence():
    from eval.evidence_replay import subset_browser_capture

    source = _selective_replay_source_capture()
    source["results"][1]["thread_ids"].append("thread-memory-retry")
    source["results"][1]["attempts"].append(
        {
            "attempt": 2,
            "thread_id": "thread-memory-retry",
            "thread_ids": ["thread-memory-retry"],
        }
    )
    source["application_telemetry"].append(
        {
            "thread_id": "thread-memory-retry",
            "operation": "quick_synthesise",
            "provider_attempts": 2,
            "attempts": [
                {"attempt": 1, "status": "error"},
                {"attempt": 2, "status": "success"},
            ],
        }
    )

    derived = subset_browser_capture(
        source,
        selected_case_ids=("memory", "graph-off", "prompt-injection"),
        expected_source_case_ids=_REPLAY_PR_CASES,
    )

    assert derived["suite"] == "diagnostic"
    assert [item["id"] for item in derived["results"]] == [
        "memory",
        "graph-off",
        "prompt-injection",
    ]
    assert [item["id"] for item in derived["case_states"]] == [
        "memory",
        "graph-off",
        "prompt-injection",
    ]
    assert {item["thread_id"] for item in derived["application_telemetry"]} == {
        "thread-memory",
        "thread-memory-retry",
        "thread-graph-off",
        "thread-prompt-injection",
    }
    assert "latency" not in derived
    assert "dashboard_smoke" not in derived
    assert "duration_ms" not in derived
    for key in (
        "corpus_version",
        "corpus_sha256",
        "release_identity",
        "target",
        "backend_target",
    ):
        assert derived[key] == source[key]


def test_selective_replay_rejects_noncanonical_or_unusable_cases():
    import copy

    import pytest

    from eval.evidence_replay import EvidenceReplayError, subset_browser_capture

    duplicate = _selective_replay_source_capture()
    duplicate["results"][2]["id"] = "memory"
    with pytest.raises(EvidenceReplayError, match="duplicate case IDs"):
        subset_browser_capture(
            duplicate,
            selected_case_ids=("memory",),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )

    bad_state = _selective_replay_source_capture()
    bad_state["case_states"][1]["state"] = "pending"
    with pytest.raises(EvidenceReplayError, match="incomplete case state"):
        subset_browser_capture(
            bad_state,
            selected_case_ids=("memory",),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )

    for field, value, message in (
        ("passed", False, "did not pass"),
        ("execution_state", "partial", "incomplete result"),
    ):
        unusable = copy.deepcopy(_selective_replay_source_capture())
        unusable["results"][1][field] = value
        with pytest.raises(EvidenceReplayError, match=message):
            subset_browser_capture(
                unusable,
                selected_case_ids=("memory",),
                expected_source_case_ids=_REPLAY_PR_CASES,
            )

    with pytest.raises(EvidenceReplayError, match="canonical PR order"):
        subset_browser_capture(
            _selective_replay_source_capture(),
            selected_case_ids=("prompt-injection", "memory"),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )


def test_selective_replay_rejects_unattributed_ambiguous_or_graph_telemetry():
    import pytest

    from eval.evidence_replay import EvidenceReplayError, subset_browser_capture

    unattributed = _selective_replay_source_capture()
    unattributed["application_telemetry"].append(
        {
            "thread_id": "unknown-thread",
            "operation": "orchestrator_synthesise",
            "provider_attempts": 1,
        }
    )
    with pytest.raises(EvidenceReplayError, match="not attributed"):
        subset_browser_capture(
            unattributed,
            selected_case_ids=("memory",),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )

    ambiguous = _selective_replay_source_capture()
    ambiguous["results"][1]["thread_ids"].append("shared-thread")
    ambiguous["results"][2]["thread_ids"].append("shared-thread")
    with pytest.raises(EvidenceReplayError, match="multiple cases"):
        subset_browser_capture(
            ambiguous,
            selected_case_ids=("memory",),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )

    graph_operation = _selective_replay_source_capture()
    graph_operation["application_telemetry"][1]["operation"] = "graph_critic"
    with pytest.raises(EvidenceReplayError, match="used graph operation"):
        subset_browser_capture(
            graph_operation,
            selected_case_ids=("memory",),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )

    missing_telemetry = _selective_replay_source_capture()
    missing_telemetry["application_telemetry"] = [
        item
        for item in missing_telemetry["application_telemetry"]
        if item["thread_id"] != "thread-memory"
    ]
    with pytest.raises(
        EvidenceReplayError, match="threads have no application telemetry"
    ):
        subset_browser_capture(
            missing_telemetry,
            selected_case_ids=("memory",),
            expected_source_case_ids=_REPLAY_PR_CASES,
        )


def test_selective_replay_writes_authenticated_hash_provenance(tmp_path):
    import hashlib
    import json

    from eval.evidence_replay import (
        SourceEvidenceIdentity,
        write_selective_replay_artifacts,
    )

    source_path = tmp_path / "browser-results.json"
    output_path = tmp_path / "selective" / "browser-results.json"
    provenance_path = tmp_path / "selective" / "replay-provenance.json"
    source_path.write_text(
        json.dumps(_selective_replay_source_capture(), indent=2) + "\n",
        encoding="utf-8",
    )
    identity = SourceEvidenceIdentity(
        run_id="30990613938",
        artifact_name="live-eval-artifacts",
        artifact_sha256="b" * 64,
        head_sha="c" * 40,
        tested_commit_sha="d" * 40,
        tree_sha="e" * 40,
        image_digest="sha256:" + "f" * 64,
    )

    provenance = write_selective_replay_artifacts(
        source_capture_path=source_path,
        source_identity=identity,
        output_capture_path=output_path,
        output_provenance_path=provenance_path,
        selected_case_ids=("memory", "graph-off", "prompt-injection"),
        replay_run_id="31000000000",
        replay_commit_sha="1" * 40,
        actor="reviewer",
        reason="Reuse only cases outside the changed graph runtime.",
        expected_source_case_ids=_REPLAY_PR_CASES,
    )

    assert (
        provenance["source"]["browser_capture_sha256"]
        == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    assert (
        provenance["derived"]["browser_capture_sha256"]
        == hashlib.sha256(output_path.read_bytes()).hexdigest()
    )
    assert provenance["selection"]["case_ids"] == [
        "memory",
        "graph-off",
        "prompt-injection",
    ]
    assert provenance["selection"]["provider_attempts"] == 3
    assert json.loads(provenance_path.read_text(encoding="utf-8")) == provenance


def test_candidate_calibration_accepts_alternate_identity_but_production_rejects_it():
    from types import SimpleNamespace

    from eval.calibration import calculate_calibration
    from eval.live_runner import _assert_approved_judge_identity

    corpus = load_corpus(require_approved=True)
    candidate_provider = "openai"
    candidate_model = "gpt-5.4-mini-2026-03-17"
    evaluations = []
    for case in corpus.cases:
        evaluations.append(
            {
                "id": case.id,
                "decision": "pass",
                "judgments": [
                    {
                        "provider": candidate_provider,
                        "model": candidate_model,
                        "prompt_release": corpus.approval.calibration.judge_release,
                        "dimensions": [
                            {
                                "dimension": dimension,
                                "grade": case.approval.reviewed_grades[dimension],
                            }
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
            "execution_mode": "semantic_replay",
            "status": "pass",
            "corpus_version": corpus.corpus_version,
            "corpus_sha256": corpus_sha256(),
            "evaluations": evaluations,
        },
        evidence_sha256=corpus.approval.calibration.evidence_sha256,
        source_context={
            "source_run_id": corpus.approval.calibration.evidence_run_id,
            "source_commit_sha": corpus.approval.calibration.evidence_commit_sha,
        },
        judge_selection={
            "format_version": 1,
            "provider": candidate_provider,
            "model": candidate_model,
        },
    )

    assert report["passed"] is True
    assert report["candidate_judge"] == {
        "provider": candidate_provider,
        "model": candidate_model,
        "prompt_release": corpus.approval.calibration.judge_release,
    }
    with pytest.raises(RuntimeError, match="provider is not approved"):
        _assert_approved_judge_identity(
            corpus,
            SimpleNamespace(provider=candidate_provider, model=candidate_model),
        )
