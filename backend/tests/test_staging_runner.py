from eval.staging_cases import STAGING_CASES, StagingStep, StepExpectation
from eval.staging_runner import (
    count_visible_threads,
    detect_route,
    evaluate_expectation,
    extract_graph_data,
    extract_response_text,
    extract_workers,
    parse_sse_event_line,
    parse_sse_events,
    resolve_node_selected_payload,
)


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
