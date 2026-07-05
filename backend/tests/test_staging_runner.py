from eval.staging_cases import BLOCKING_STAGING_CASE_IDS, STAGING_CASES, StagingStep, StepExpectation
from eval.staging_runner import (
    _blocking_request,
    build_parser,
    count_visible_threads,
    detect_route,
    evaluate_expectation,
    extract_graph_data,
    extract_graph_node_labels,
    extract_response_text,
    extract_worker_statuses,
    extract_workers,
    parse_sse_event_line,
    parse_sse_events,
    resolve_node_selected_payload,
    run_case,
    run_cases_with_concurrency,
    select_cases,
)
import asyncio
from pathlib import Path
import urllib.request


def test_parse_sse_events_extracts_multiple_events():
    body = (
        'data: {"type":"worker_status","worker":"rag","status":"Searching"}\n\n'
        'data: {"type":"done"}\n\n'
    )

    events = parse_sse_events(body)

    assert [event["type"] for event in events] == ["worker_status", "done"]


def test_parse_sse_event_line_returns_single_event():
    event = parse_sse_event_line('data: {"type":"done"}')

    assert event == {"type": "done"}


def test_route_detection_treats_rag_as_search():
    events = [{"type": "worker_status", "worker": "rag", "status": "Searching"}]

    assert detect_route(events) == "search"


def test_route_detection_treats_lookup_without_rag_as_simple():
    events = [{"type": "worker_status", "worker": "orchestrator", "status": "Looking it up..."}]

    assert detect_route(events) == "simple"


def test_route_detection_defaults_to_memory_when_only_writing():
    events = [{"type": "worker_status", "worker": "orchestrator", "status": "Writing the explanation..."}]

    assert detect_route(events) == "memory"


def test_evaluate_expectation_checks_thread_roles_and_response_text():
    step = StagingStep(
        kind="get_thread",
        description="thread audit",
        expect=StepExpectation(
            thread_message_count=2,
            thread_message_roles=["user", "assistant"],
        ),
    )
    run = {
        "status_code": 200,
        "events": [],
        "json_body": {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]
        },
        "body_text": "",
    }

    failures = evaluate_expectation(step, run, {})

    assert failures == []


def test_resolve_node_selected_payload_uses_first_graph_node():
    step = StagingStep(
        kind="node_selected",
        description="select node",
        payload={"use_first_graph_node": True},
    )
    payload = resolve_node_selected_payload(
        step,
        {
            "last_graph_data": {
                "nodes": [
                    {
                        "id": "n1",
                        "label": "Retriever",
                        "description": "Finds relevant chunks.",
                    }
                ]
            }
        },
    )

    assert payload == {
        "node_id": "n1",
        "title": "Retriever",
        "description": "Finds relevant chunks.",
    }


def test_staging_suite_covers_multiple_categories():
    categories = {case.category for case in STAGING_CASES}

    assert {"happy_path", "memory_followup", "research_mode", "edge_cases", "real_workflow", "graph_quality"} <= categories


def test_staging_suite_has_customer_support_graph_quality_gate():
    graph_quality_case = next(case for case in STAGING_CASES if case.id == "S10")

    assert graph_quality_case.category == "graph_quality"
    first_expect = graph_quality_case.steps[0].expect
    followup_expect = graph_quality_case.steps[1].expect
    assert first_expect.graph_type == "architecture"
    assert "Billing Agent" in first_expect.graph_node_labels_include
    assert "Returns Agent" in first_expect.graph_node_labels_include
    assert "Escalation Agent" in first_expect.graph_node_labels_include
    assert "Tool Use" in first_expect.graph_node_labels_exclude
    assert "Billing Agent" in followup_expect.graph_node_labels_include


def test_staging_runner_defaults_case_filter_from_environment(monkeypatch):
    monkeypatch.setenv("STAGING_EVAL_CASES", "S1 S10")

    args = build_parser().parse_args([])

    assert [case.id for case in select_cases(args)] == ["S1", "S10"]


def test_staging_runner_cli_case_filter_overrides_environment(monkeypatch):
    monkeypatch.setenv("STAGING_EVAL_CASES", "S1 S10")

    args = build_parser().parse_args(["--case", "S4"])

    assert [case.id for case in select_cases(args)] == ["S4"]


def test_staging_runner_defaults_to_serial_single_attempt_execution(monkeypatch):
    monkeypatch.delenv("STAGING_EVAL_CONCURRENCY", raising=False)
    monkeypatch.delenv("STAGING_EVAL_ATTEMPTS", raising=False)

    args = build_parser().parse_args([])

    assert args.concurrency == 1
    assert args.attempts == 1


def test_staging_runner_allows_manual_parallel_retry_override(monkeypatch):
    monkeypatch.setenv("STAGING_EVAL_CONCURRENCY", "3")
    monkeypatch.setenv("STAGING_EVAL_ATTEMPTS", "2")

    args = build_parser().parse_args([])

    assert args.concurrency == 3
    assert args.attempts == 2


def test_blocking_staging_smoke_set_covers_risky_paths_without_excess_llm_calls():
    cases_by_id = {case.id: case for case in STAGING_CASES}
    smoke_cases = [cases_by_id[case_id] for case_id in BLOCKING_STAGING_CASE_IDS]
    categories = {case.category for case in smoke_cases}

    assert categories == {"happy_path", "mode_controls", "edge_cases", "graph_quality"}
    assert "S10" in BLOCKING_STAGING_CASE_IDS

    model_backed_chat_steps = [
        step
        for case in smoke_cases
        for step in case.steps
        if step.kind == "chat" and not step.expect.has_error_event
    ]
    assert len(model_backed_chat_steps) <= 4


def test_ci_staging_eval_is_serial_and_single_attempt():
    workflow = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert 'STAGING_EVAL_CONCURRENCY: "1"' in workflow
    assert 'STAGING_EVAL_ATTEMPTS: "1"' in workflow


def test_extract_helpers_return_expected_values():
    events = [
        {"type": "worker_status", "worker": "orchestrator", "status": "Routing"},
        {"type": "graph_data", "data": {"title": "Graph", "nodes": [], "edges": [], "sequence": []}},
        {"type": "response_delta", "content": "Hello"},
        {"type": "response_delta", "content": " world"},
    ]

    assert extract_workers(events) == {"orchestrator"}
    assert extract_worker_statuses(events) == ["Routing"]
    assert extract_graph_data(events)["title"] == "Graph"
    assert extract_graph_node_labels({"nodes": [{"label": "Retriever"}, {"id": "missing-label"}]}) == {"Retriever"}
    assert extract_response_text(events) == "Hello world"


def test_evaluate_expectation_checks_graph_quality_contract():
    step = StagingStep(
        kind="chat",
        description="graph quality gate",
        expect=StepExpectation(
            graph_emitted=True,
            graph_type="architecture",
            graph_title_contains="Customer Support",
            graph_node_labels_include=["Billing Agent", "Returns Agent"],
            graph_node_labels_exclude=["Tool Use", "Planning"],
        ),
    )
    run = {
        "status_code": 200,
        "events": [
            {
                "type": "graph_data",
                "data": {
                    "title": "Customer Support Multi-Agent Architecture",
                    "graph_type": "architecture",
                    "nodes": [
                        {"label": "Billing Agent"},
                        {"label": "Returns Agent"},
                        {"label": "Tool Service"},
                    ],
                    "edges": [],
                    "sequence": [],
                },
            }
        ],
        "json_body": None,
        "body_text": "",
    }

    assert evaluate_expectation(step, run, {}) == []


def test_evaluate_expectation_rejects_generic_customer_support_graph():
    step = StagingStep(
        kind="chat",
        description="bad graph quality gate",
        expect=StepExpectation(
            graph_emitted=True,
            graph_type="architecture",
            graph_title_contains="Customer Support",
            graph_node_labels_include=["Billing Agent", "Returns Agent", "Escalation Agent"],
            graph_node_labels_exclude=["Tool Use", "Planning", "Evaluation"],
        ),
    )
    run = {
        "status_code": 200,
        "events": [
            {
                "type": "graph_data",
                "data": {
                    "title": "Agent Architecture",
                    "graph_type": "concept",
                    "nodes": [
                        {"label": "Agent"},
                        {"label": "Tool Use"},
                        {"label": "Planning"},
                        {"label": "Evaluation"},
                    ],
                    "edges": [],
                    "sequence": [],
                },
            }
        ],
        "json_body": None,
        "body_text": "",
    }

    failures = evaluate_expectation(step, run, {})

    assert "graph_type expected architecture, got concept" in failures
    assert "graph title expected to contain 'Customer Support', got 'Agent Architecture'" in failures
    assert "graph missing node label 'Billing Agent'" in failures
    assert "graph unexpectedly included node label 'Tool Use'" in failures


def test_evaluate_expectation_reports_unexpected_sse_error_text():
    step = StagingStep(
        kind="chat",
        description="unexpected error",
        expect=StepExpectation(has_error_event=False),
    )
    run = {
        "status_code": 200,
        "events": [{"type": "error", "content": "Another response is already running."}],
        "json_body": None,
        "body_text": "",
    }

    failures = evaluate_expectation(step, run, {})

    assert "has_error_event expected False, got True" in failures
    assert "error event: Another response is already running." in failures


def test_count_visible_threads_excludes_eval_thread():
    thread_json = {
        "threads": [
            {"id": "eval-thread"},
            {"id": "user-thread-1"},
            {"id": "user-thread-2"},
        ]
    }

    assert count_visible_threads(thread_json, {"thread_id": "eval-thread"}) == 2


def test_thread_count_delta_uses_visible_threads_only():
    step = StagingStep(
        kind="list_threads",
        description="thread count after cleanup",
        expect=StepExpectation(thread_count_delta=0),
    )
    run = {
        "status_code": 200,
        "events": [],
        "json_body": {"threads": [{"id": "user-thread-1"}]},
        "body_text": "",
    }

    failures = evaluate_expectation(
        step,
        run,
        {
            "thread_id": "eval-thread",
            "baseline_thread_count": 1,
        },
    )

    assert failures == []


def test_evaluate_expectation_marks_deleted_thread_from_404_get_thread():
    step = StagingStep(
        kind="get_thread",
        description="deleted thread audit",
        expect=StepExpectation(http_status=404, thread_deleted=True),
    )
    run = {
        "status_code": 404,
        "events": [],
        "json_body": None,
        "body_text": "",
    }

    failures = evaluate_expectation(step, run, {})

    assert failures == []


def test_real_workflow_case_uses_thread_specific_delete_check():
    workflow_case = next(case for case in STAGING_CASES if case.id == "S9")

    assert [step.kind for step in workflow_case.steps] == [
        "chat",
        "chat",
        "get_thread",
        "delete_thread",
        "get_thread",
    ]
    assert workflow_case.steps[-1].expect.thread_deleted is True


def test_blocking_request_reads_until_stream_eof(monkeypatch):
    class _FakeResponse:
        status = 200

        def __init__(self):
            self._lines = iter(
                [
                    b'data: {"type":"worker_status","worker":"orchestrator","status":"Routing"}\n',
                    b"\n",
                    b'data: {"type":"done"}\n',
                    b"\n",
                    b": trailer\n",
                    b"",
                ]
            )

        def readline(self):
            return next(self._lines)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, data=None, timeout=120: _FakeResponse())

    run = _blocking_request("POST", "https://example.com/api/chat", "token", {"content": "hi"}, True)

    assert [event["type"] for event in run["events"]] == ["worker_status", "done"]
    assert ": trailer" in run["body_text"]


def test_run_case_records_step_exception_without_crashing(monkeypatch):
    from eval.staging_cases import StagingCase

    async def _fake_create_thread(client, base_url, auth_token, title):
        return {"id": "thread-1"}

    async def _fake_delete_thread(client, method, url, auth_token, json_payload=None):
        return {"status_code": 204, "json_body": None, "events": [], "body_text": ""}

    monkeypatch.setattr("eval.staging_runner.create_thread", _fake_create_thread)
    monkeypatch.setattr("eval.staging_runner.perform_json_request", _fake_delete_thread)

    case = StagingCase(
        id="SX",
        category="edge_cases",
        description="node-selected without prior graph should fail in-place",
        steps=[
            StagingStep(
                kind="node_selected",
                description="missing graph context",
                payload={"use_first_graph_node": True},
            )
        ],
    )

    result = asyncio.run(
        run_case(
            client=None,
            base_url="https://example.com",
            auth_token="token",
            case=case,
            keep_threads=False,
        )
    )

    assert result["passed"] is False
    assert result["steps"][0]["passed"] is False
    assert "no graph was emitted" in result["steps"][0]["failures"][0]


def test_run_cases_with_concurrency_bounds_parallel_cases():
    from eval.staging_cases import StagingCase

    active = 0
    max_active = 0
    first_pair_started = asyncio.Event()

    cases = [
        StagingCase(id="S1", category="test", description="one", steps=[]),
        StagingCase(id="S2", category="test", description="two", steps=[]),
        StagingCase(id="S3", category="test", description="three", steps=[]),
    ]

    async def _fake_run_case(case):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if active == 2:
            first_pair_started.set()
        await first_pair_started.wait()
        active -= 1
        return {"id": case.id, "passed": True, "steps": []}

    results = asyncio.run(
        run_cases_with_concurrency(cases, _fake_run_case, concurrency=2)
    )

    assert [result["id"] for result in results] == ["S1", "S2", "S3"]
    assert max_active == 2
