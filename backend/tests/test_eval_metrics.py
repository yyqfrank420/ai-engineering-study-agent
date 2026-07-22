from eval.metrics import score_schema, score_test_case
from eval.test_cases import TestCase


def test_routing_metric_failure_marks_case_failed():
    case = TestCase(
        id="X1",
        category="routing_graph_expand",
        description="graph emission mismatch should fail",
        expected={"route": "search", "graph_emitted": True},
    )
    run = {
        "status_code": 200,
        "events": [
            {"type": "worker_status", "worker": "rag", "status": "running"},
            {"type": "worker_status", "worker": "graph", "status": "running"},
        ],
        "body_text": "",
        "json_body": None,
    }

    result = score_test_case(case, run)

    assert result["route_pass"] is True
    assert result["graph_emitted_pass"] is False
    assert result["passed"] is False


def test_http_422_body_can_satisfy_error_assertions():
    case = TestCase(
        id="X2",
        category="preflight_security",
        description="missing thread id should fail validation",
        expected={"http_status": 422, "error_contains": "thread_id", "no_response_delta": True},
    )
    run = {
        "status_code": 422,
        "events": [],
        "body_text": '{"detail":[{"loc":["body","thread_id"],"msg":"Field required"}]}',
        "json_body": {"detail": [{"loc": ["body", "thread_id"], "msg": "Field required"}]},
    }

    result = score_test_case(case, run)

    assert result["http_status_pass"] is True
    assert result["error_contains_pass"] is True
    assert result["no_response_delta_pass"] is True
    assert result["passed"] is True


def test_sse_error_case_checks_side_effect_absence():
    case = TestCase(
        id="X3",
        category="preflight_security",
        description="preflight SSE error should not stream model output",
        expected={
            "has_error_event": True,
            "error_contains": "Message too large",
            "no_response_delta": True,
            "no_graph_data": True,
        },
    )
    run = {
        "status_code": 200,
        "events": [
            {"type": "error", "content": "Message too large (max 2KB)"},
        ],
        "body_text": "data: {\"type\": \"error\", \"content\": \"Message too large (max 2KB)\"}\n\n",
        "json_body": None,
    }

    result = score_test_case(case, run)

    assert result["has_error_event_pass"] is True
    assert result["error_contains_pass"] is True
    assert result["no_response_delta_pass"] is True
    assert result["no_graph_data_pass"] is True
    assert result["passed"] is True


def test_schema_accepts_supported_architecture_node_types():
    graph_data = {
        "nodes": [
            {
                "id": "authz",
                "label": "Authorization policy",
                "type": "control",
                "technology": "RBAC",
                "description": "Controls access to protected routes.",
            },
            {
                "id": "routing-choice",
                "label": "Routing choice",
                "type": "decision",
                "technology": "Architecture decision",
                "description": "Chooses between memory and search routes.",
            },
            {
                "id": "event-stream",
                "label": "Durable event stream",
                "type": "queue",
                "technology": "Partitioned message queue",
                "description": "Buffers asynchronous work with bounded delivery semantics.",
            },
        ],
        "edges": [],
    }

    result = score_schema(graph_data, {"node_types_valid": True})

    assert result["node_types_valid"] is True
    assert result["node_types_valid_pass"] is True
    assert result["errors"] == []
