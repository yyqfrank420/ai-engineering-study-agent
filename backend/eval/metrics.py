# ─────────────────────────────────────────────────────────────────────────────
# File: backend/eval/metrics.py
# Purpose: Structural scoring functions for the agent evaluation suite.
#          All checks are deterministic (no LLM calls) — they inspect the
#          SSE events or HTTP response body collected by runner.py and score
#          them against the expected outcomes defined in test_cases.py.
# Language: Python
# ─────────────────────────────────────────────────────────────────────────────

import json
import re


_VALID_NODE_TYPES = {"client", "service", "datastore", "gateway", "network", "external"}
_VALID_SYNC_VALUES = {"sync", "async"}
_NODE_REQUIRED = ("id", "label", "type", "technology", "description")
_EDGE_REQUIRED = ("source", "target", "label", "technology", "sync", "description")


def score_transport(run: dict, expected: dict) -> dict[str, object]:
    results: dict[str, object] = {}
    status_code = run.get("status_code")
    if "http_status" in expected:
        results["http_status"] = status_code
        results["http_status_pass"] = status_code == expected["http_status"]
    return results


def score_routing(events: list[dict], expected: dict) -> dict[str, object]:
    workers_fired = {
        e["worker"]
        for e in events
        if e.get("type") == "worker_status" and e.get("worker")
    }
    graph_emitted = any(e.get("type") == "graph_data" for e in events)
    actual_route = "search" if "rag" in workers_fired else "memory"

    results: dict[str, object] = {"actual_route": actual_route, "workers_fired": sorted(workers_fired)}

    if "route" in expected:
        results["route_correct"] = actual_route == expected["route"]
        results["route_pass"] = results["route_correct"]

    if "graph_emitted" in expected:
        results["graph_emitted"] = graph_emitted
        results["graph_emitted_correct"] = graph_emitted == expected["graph_emitted"]
        results["graph_emitted_pass"] = results["graph_emitted_correct"]

    return results


def score_format(response_text: str, expected: dict) -> dict[str, object]:
    lines = response_text.strip().split("\n")
    bullet_lines = [l for l in lines if l.strip().startswith("- ")]
    numbered_lines = [l for l in lines if re.match(r"^\s*\d+\.\s", l)]

    raw_results = {
        "has_story_heading": "## Story" in response_text,
        "has_walkthrough_heading": "## Walkthrough" in response_text,
        "has_on_graph_heading": "## On the graph" in response_text,
        "has_numbered_steps": len(numbered_lines) >= 3,
        "has_citations": bool(re.search(r"\(Chapter\s+\d+", response_text)),
        "no_bullet_dump": len(bullet_lines) <= 2,
    }

    results: dict[str, object] = {}
    for metric, value in raw_results.items():
        if metric in expected:
            results[metric] = value
            results[f"{metric}_pass"] = value == expected[metric]

    results["_raw"] = raw_results
    return results


def score_schema(graph_data: dict, expected: dict) -> dict[str, object]:
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    node_type_errors = [
        f"node:{n.get('id', '?')} invalid type '{n.get('type')}'"
        for n in nodes
        if n.get("type") not in _VALID_NODE_TYPES
    ]
    node_field_errors = [
        f"node:{n.get('id', '?')} missing '{f}'"
        for n in nodes
        for f in _NODE_REQUIRED
        if not n.get(f)
    ]
    edge_field_errors = [
        f"edge[{i}] missing '{f}'"
        for i, e in enumerate(edges)
        for f in _EDGE_REQUIRED
        if not e.get(f)
    ]
    sync_errors = [
        f"edge[{i}] invalid sync '{e.get('sync')}'"
        for i, e in enumerate(edges)
        if e.get("sync") not in _VALID_SYNC_VALUES
    ]
    internal_errors = [
        f"edge[{i}] forbidden technology 'internal'"
        for i, e in enumerate(edges)
        if (e.get("technology") or "").lower() == "internal"
    ]

    raw_results = {
        "node_types_valid": len(node_type_errors) == 0,
        "nodes_have_required_fields": len(node_field_errors) == 0,
        "edges_have_required_fields": len(edge_field_errors) == 0,
        "sync_field_valid": len(sync_errors) == 0,
        "no_internal_technology": len(internal_errors) == 0,
    }
    all_errors = node_type_errors + node_field_errors + edge_field_errors + sync_errors + internal_errors

    results: dict[str, object] = {"errors": all_errors}
    for metric, value in raw_results.items():
        if metric in expected:
            results[metric] = value
            results[f"{metric}_pass"] = value == expected[metric]

    results["_raw"] = raw_results
    return results


def extract_response_text(events: list[dict]) -> str:
    return "".join(
        e.get("content", "")
        for e in events
        if e.get("type") == "response_delta"
    )


def extract_graph_data(events: list[dict]) -> dict | None:
    graph_events = [e for e in events if e.get("type") == "graph_data"]
    return graph_events[-1]["data"] if graph_events else None


def extract_error_text(run: dict) -> str:
    events = run.get("events", [])
    error_events = [e.get("content", "") for e in events if e.get("type") == "error"]
    if error_events:
        return "\n".join(error_events)

    json_body = run.get("json_body")
    if json_body is not None:
        return json.dumps(json_body)

    return run.get("body_text", "")


def score_error_behavior(run: dict, expected: dict) -> dict[str, object]:
    events = run.get("events", [])
    response_text = extract_response_text(events)
    graph_data = extract_graph_data(events)
    suggested_questions = [
        e for e in events
        if e.get("type") == "suggested_questions"
    ]
    error_text = extract_error_text(run)
    has_error_event = any(e.get("type") == "error" for e in events)

    raw_results = {
        "has_error_event": has_error_event,
        "error_contains": error_text,
        "no_response_delta": response_text == "",
        "no_graph_data": graph_data is None,
        "no_suggested_questions": len(suggested_questions) == 0,
    }

    results: dict[str, object] = {}
    if "has_error_event" in expected:
        results["has_error_event"] = raw_results["has_error_event"]
        results["has_error_event_pass"] = raw_results["has_error_event"] == expected["has_error_event"]

    if "error_contains" in expected:
        results["error_contains"] = error_text
        results["error_contains_pass"] = expected["error_contains"] in error_text

    for metric in ("no_response_delta", "no_graph_data", "no_suggested_questions"):
        if metric in expected:
            results[metric] = raw_results[metric]
            results[f"{metric}_pass"] = raw_results[metric] == expected[metric]

    results["_raw_error"] = raw_results
    return results


def score_test_case(case, run: dict) -> dict:
    expected = case.expected
    events = run.get("events", [])
    results: dict[str, object] = {
        "id": case.id,
        "category": case.category,
        "description": case.description,
    }

    results.update(score_transport(run, expected))
    results.update(score_error_behavior(run, expected))

    routing_keys = {"route", "graph_emitted"}
    if routing_keys & set(expected.keys()):
        results.update(score_routing(events, expected))

    format_keys = {
        "has_story_heading",
        "has_walkthrough_heading",
        "has_on_graph_heading",
        "has_numbered_steps",
        "has_citations",
        "no_bullet_dump",
    }
    if format_keys & set(expected.keys()):
        response_text = extract_response_text(events)
        results.update(score_format(response_text, expected))

    schema_keys = {
        "node_types_valid",
        "nodes_have_required_fields",
        "edges_have_required_fields",
        "sync_field_valid",
        "no_internal_technology",
    }
    if schema_keys & set(expected.keys()):
        graph_data = extract_graph_data(events)
        if graph_data:
            results.update(score_schema(graph_data, expected))
        else:
            for key in schema_keys & set(expected.keys()):
                results[key] = None
                results[f"{key}_pass"] = False
            existing_errors = list(results.get("errors", []))
            results["errors"] = [*existing_errors, "No graph_data event received"]

    pass_fields = [v for k, v in results.items() if k.endswith("_pass") and isinstance(v, bool)]
    results["passed"] = all(pass_fields) if pass_fields else True
    return results
