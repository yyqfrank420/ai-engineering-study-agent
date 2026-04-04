from eval.staging_cases import STAGING_CASES, StagingStep, StepExpectation
from eval.staging_runner import (
    _blocking_request,
    count_visible_threads,
    detect_route,
    evaluate_expectation,
    extract_graph_data,
    extract_response_text,
    extract_worker_statuses,
    extract_workers,
    parse_sse_event_line,
    parse_sse_events,
    resolve_node_selected_payload,
    run_case,
)
import asyncio
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

    assert {"happy_path", "memory_followup", "research_mode", "edge_cases", "real_workflow"} <= categories


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
    assert extract_response_text(events) == "Hello world"


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
