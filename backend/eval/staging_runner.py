import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from websockets.asyncio.client import connect

from eval.diagram_renderer import render_staging_diagram
from eval.response_capture import extract_response_text
from eval.runtime_budget import application_turn_timeout_seconds

try:
    from rich import box
    from rich.console import Console
    from rich.table import Table
except ModuleNotFoundError:
    box = None
    Console = None
    Table = None

from eval.staging_cases import STAGING_CASES, StagingCase, StagingStep

_console = Console() if Console is not None else None

_DASHBOARD_SMOKE_ENDPOINTS = (
    ("/api/internal/dashboard/overview", frozenset({"kpis", "providers"})),
    ("/api/internal/dashboard/trends?bucket=day", frozenset({"bucket", "points"})),
    ("/api/internal/dashboard/trends?bucket=hour", frozenset({"bucket", "points"})),
    ("/api/internal/dashboard/funnel", frozenset({"window_days", "steps"})),
    (
        "/api/internal/dashboard/failures",
        frozenset({"recent_failed_requests", "slow_requests", "provider_fallbacks"}),
    ),
    (
        "/api/internal/dashboard/llm-performance",
        frozenset({"operations", "recent_fallbacks"}),
    ),
)


def _console_print(message: str = "") -> None:
    if _console is not None:
        _console.print(message)
        return
    print(message)


def _console_rule(title: str) -> None:
    if _console is not None:
        _console.rule(title)
        return
    print(title)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run staging evals against a deployed backend.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--auth-token", default=os.getenv("EVAL_AUTH_TOKEN", ""), help="Existing bearer token")
    parser.add_argument("--email", default=os.getenv("EVAL_EMAIL", ""), help="Email for OTP verification")
    parser.add_argument("--otp", default=os.getenv("EVAL_OTP", ""), help="OTP token for verification")
    parser.add_argument(
        "--internal-password",
        default=os.getenv("EVAL_INTERNAL_PASSWORD", ""),
        help="Internal test login password",
    )
    parser.add_argument("--request-otp", action="store_true", help="Request an OTP email and exit")
    parser.add_argument("--case", action="append", default=[], help="Specific case ID to run")
    parser.add_argument("--category", action="append", default=[], help="Specific category to run")
    parser.add_argument("--max-cases", type=int, default=None, help="Run only the first N selected cases")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("STAGING_EVAL_CONCURRENCY", "1")),
        help="Maximum staging cases to run at once",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=int(os.getenv("STAGING_EVAL_ATTEMPTS", "1")),
        help="Attempts per staging case; increase only for manual transient-failure checks",
    )
    parser.add_argument("--keep-threads", action="store_true", help="Do not auto-delete eval threads")
    parser.add_argument(
        "--check-dashboard",
        action="store_true",
        help="Require the authenticated internal dashboard API to pass before running evals",
    )
    return parser


def select_cases(args: argparse.Namespace) -> list[StagingCase]:
    selected = STAGING_CASES
    case_filters = args.case or os.getenv("STAGING_EVAL_CASES", "").split()
    if case_filters:
        wanted = {case_id.upper() for case_id in case_filters}
        selected = [case for case in selected if case.id.upper() in wanted]
    if args.category:
        wanted_categories = set(args.category)
        selected = [case for case in selected if case.category in wanted_categories]
    if args.max_cases is not None:
        selected = selected[:args.max_cases]
    return selected


async def request_otp(base_url: str, email: str) -> None:
    result = await perform_json_request(
        None,
        "POST",
        f"{base_url}/api/auth/request-otp",
        "",
        json_payload={"email": email},
    )
    if result["status_code"] >= 400:
        raise RuntimeError(f"OTP request failed: {result['body_text']}")

    body = result.get("json_body") or {}
    if not body.get("ok"):
        if body.get("captcha_required"):
            raise RuntimeError("OTP request requires captcha; use the browser flow for this environment")
        raise RuntimeError(f"OTP request was not accepted: {result['body_text']}")


async def verify_otp(base_url: str, email: str, otp: str) -> str:
    result = await perform_json_request(
        None,
        "POST",
        f"{base_url}/api/auth/verify-otp",
        "",
        json_payload={"email": email, "token": otp},
    )
    if result["status_code"] >= 400:
        raise RuntimeError(f"OTP verification failed: {result['body_text']}")
    body = result.get("json_body") or {}
    session = body.get("session") or {}
    access_token = session.get("access_token", "")
    if not access_token:
        raise RuntimeError("OTP verification succeeded but no access token was returned")
    return access_token


async def internal_login(base_url: str, email: str, password: str) -> str:
    result = await perform_json_request(
        None,
        "POST",
        f"{base_url}/api/auth/internal-login",
        "",
        json_payload={"email": email, "password": password},
    )
    if result["status_code"] >= 400:
        raise RuntimeError(f"Internal login failed: {result['body_text']}")
    body = result.get("json_body") or {}
    session = body.get("session") or {}
    access_token = session.get("access_token", "")
    if not access_token:
        raise RuntimeError("Internal login succeeded but no access token was returned")
    return access_token


async def ensure_auth_token(args: argparse.Namespace) -> str:
    if args.auth_token:
        return args.auth_token
    if args.email and args.internal_password:
        return await internal_login(args.base_url, args.email, args.internal_password)
    if args.email and args.otp:
        return await verify_otp(args.base_url, args.email, args.otp)
    raise RuntimeError("Pass --auth-token, or --email with --internal-password, or --email with --otp")


async def smoke_test_internal_dashboard(base_url: str, auth_token: str) -> None:
    """Exercise the same dashboard requests the frontend makes before promotion."""
    root_url = base_url.rstrip("/")
    for path, required_keys in _DASHBOARD_SMOKE_ENDPOINTS:
        result = await perform_json_request(None, "GET", f"{root_url}{path}", auth_token)
        if result["status_code"] != 200:
            body = result.get("body_text", "")[:500]
            raise RuntimeError(
                f"Dashboard smoke check failed for {path}: "
                f"HTTP {result['status_code']} {body}"
            )

        body = result.get("json_body")
        if not isinstance(body, dict):
            raise RuntimeError(f"Dashboard smoke check returned non-object JSON for {path}")

        missing_keys = required_keys.difference(body)
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise RuntimeError(f"Dashboard smoke check for {path} is missing: {missing}")


def parse_sse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for chunk in text.split("\n\n"):
        line = chunk.strip()
        if not line.startswith("data: "):
            continue
        try:
            events.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            continue
    return events


def parse_sse_event_line(line: str) -> dict | None:
    if not line.startswith("data: "):
        return None
    try:
        return json.loads(line[6:])
    except json.JSONDecodeError:
        return None


def extract_workers(events: list[dict]) -> set[str]:
    return {
        event["worker"]
        for event in events
        if event.get("type") == "worker_status" and event.get("worker")
    }


def extract_worker_statuses(events: list[dict], worker: str | None = None) -> list[str]:
    statuses: list[str] = []
    for event in events:
        if event.get("type") != "worker_status":
            continue
        if worker and event.get("worker") != worker:
            continue
        status = event.get("status")
        if isinstance(status, str):
            statuses.append(status)
    return statuses


def extract_graph_data(events: list[dict]) -> dict | None:
    for event in reversed(events):
        if event.get("type") == "graph_data":
            data = event.get("data")
            if isinstance(data, dict):
                return data
    return None


def extract_graph_node_labels(graph_data: dict | None) -> set[str]:
    if not graph_data:
        return set()
    labels: set[str] = set()
    for node in graph_data.get("nodes") or []:
        label = node.get("label")
        if isinstance(label, str):
            labels.add(label)
    return labels


def detect_route(events: list[dict]) -> str:
    workers = extract_workers(events)
    if "rag" in workers:
        return "search"

    orchestrator_statuses = [status.lower() for status in extract_worker_statuses(events, worker="orchestrator")]
    if any("looking it up" in status for status in orchestrator_statuses):
        return "simple"
    return "memory"


def count_suggested_questions(events: list[dict]) -> int:
    for event in reversed(events):
        if event.get("type") == "suggested_questions":
            return len(event.get("questions") or [])
    return 0


def count_visible_threads(thread_json: dict, case_state: dict) -> int:
    thread_id = case_state.get("thread_id")
    threads = thread_json.get("threads") or []
    return sum(1 for thread in threads if thread.get("id") != thread_id)


async def perform_json_request(
    client,
    method: str,
    url: str,
    auth_token: str,
    *,
    json_payload: dict | None = None,
) -> dict:
    return await asyncio.to_thread(_blocking_request, method, url, auth_token, json_payload, False)


async def perform_sse_request(
    client,
    url: str,
    auth_token: str,
    *,
    json_payload: dict,
) -> dict:
    return await asyncio.to_thread(_blocking_request, "POST", url, auth_token, json_payload, True)


async def perform_websocket_chat(
    base_url: str,
    auth_token: str,
    *,
    json_payload: dict,
) -> dict:
    """Run one chat over the production WebSocket and satisfy diagram gates."""
    parsed_url = urllib.parse.urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Staging requests require an absolute HTTP(S) URL")
    ws_scheme = "wss" if parsed_url.scheme == "https" else "ws"
    base_path = parsed_url.path.rstrip("/")
    websocket_url = urllib.parse.urlunparse(
        (ws_scheme, parsed_url.netloc, f"{base_path}/api/chat/ws", "", "", "")
    )
    events: list[dict] = []

    async with asyncio.timeout(application_turn_timeout_seconds()):
        async with connect(
            websocket_url,
            open_timeout=20,
            close_timeout=5,
            max_size=1_000_000,
        ) as websocket:
            await websocket.send(json.dumps({"type": "auth", "access_token": auth_token}))
            ready = _decode_websocket_event(await websocket.recv())
            if ready.get("type") != "ready":
                raise RuntimeError(f"WebSocket authentication failed: {ready}")

            start_payload = {
                "type": "start",
                **json_payload,
                "client_request_id": json_payload.get("client_request_id") or str(uuid.uuid4()),
            }
            await websocket.send(json.dumps(start_payload))

            async for raw_event in websocket:
                event = _decode_websocket_event(raw_event)
                events.append(event)
                if event.get("type") == "graph_candidate":
                    await _submit_staging_diagram(websocket, event)
                if event.get("type") == "done":
                    break

    return {
        # The shared expectation model describes the logical request result,
        # not the HTTP 101 protocol upgrade.
        "status_code": 200,
        "events": events,
        "json_body": None,
        "body_text": "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
    }


def _decode_websocket_event(raw_event: str | bytes) -> dict:
    if isinstance(raw_event, bytes):
        raw_event = raw_event.decode("utf-8")
    event = json.loads(raw_event)
    if not isinstance(event, dict):
        raise RuntimeError("WebSocket server returned a non-object event")
    return event


async def _submit_staging_diagram(websocket, candidate: dict) -> None:
    graph = candidate.get("data")
    if not isinstance(graph, dict):
        raise RuntimeError("graph_candidate did not contain graph data")
    encoded, media_type, report = render_staging_diagram(graph)
    evaluation_id = str(candidate.get("evaluation_id") or "")
    graph_version = candidate.get("graph_version")
    chunk_size = 8_000
    chunks = [encoded[offset : offset + chunk_size] for offset in range(0, len(encoded), chunk_size)]
    if not chunks:
        raise RuntimeError("staging diagram renderer returned an empty image")

    await websocket.send(json.dumps({
        "type": "diagram_evaluation_start",
        "evaluation_id": evaluation_id,
        "graph_version": graph_version,
        "media_type": media_type,
        "total_chunks": len(chunks),
        "report": report,
    }))
    for index, data in enumerate(chunks):
        await websocket.send(json.dumps({
            "type": "diagram_evaluation_chunk",
            "evaluation_id": evaluation_id,
            "index": index,
            "data": data,
        }))
    await websocket.send(json.dumps({
        "type": "diagram_evaluation_complete",
        "evaluation_id": evaluation_id,
    }))


def _blocking_request(
    method: str,
    url: str,
    auth_token: str,
    json_payload: dict | None,
    expect_sse: bool,
) -> dict:
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Staging requests require an absolute HTTP(S) URL")
    request = urllib.request.Request(url, method=method)
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")

    data = None
    if json_payload is not None:
        request.add_header("Content-Type", "application/json")
        data = json.dumps(json_payload).encode("utf-8")

    try:
        # urlopen is safe here because the absolute HTTP(S) scheme was validated above.
        with urllib.request.urlopen(request, data=data, timeout=120) as response:  # nosec B310
            status_code = response.status
            if expect_sse:
                raw_lines: list[str] = []
                events: list[dict] = []
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8")
                    raw_lines.append(line)
                    event = parse_sse_event_line(line.strip())
                    if event is None:
                        continue
                    events.append(event)
                body_text = "".join(raw_lines)
                return {
                    "status_code": status_code,
                    "events": events,
                    "json_body": None,
                    "body_text": body_text,
                }
            body_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        body_text = exc.read().decode("utf-8")

    json_body = None
    if not expect_sse:
        try:
            json_body = json.loads(body_text) if body_text else None
        except json.JSONDecodeError:
            json_body = None

    return {
        "status_code": status_code,
        "events": parse_sse_events(body_text) if expect_sse else [],
        "json_body": json_body,
        "body_text": body_text,
    }


async def create_thread(client, base_url: str, auth_token: str, title: str) -> dict:
    result = await perform_json_request(
        client,
        "POST",
        f"{base_url}/api/threads",
        auth_token,
        json_payload={"title": title},
    )
    body = result.get("json_body") or {}
    thread = body.get("thread") or {}
    if result["status_code"] >= 400 or not thread.get("id"):
        raise RuntimeError(f"Thread creation failed: {result['body_text']}")
    return thread


def evaluate_expectation(step: StagingStep, run: dict, case_state: dict) -> list[str]:
    failures: list[str] = []
    expect = step.expect
    events = run.get("events", [])
    response_text = extract_response_text(events)
    workers = extract_workers(events)
    graph_data = extract_graph_data(events)
    error_events = [event for event in events if event.get("type") == "error"]
    error_text = "\n".join(event.get("content", "") for event in error_events)
    thread_json = run.get("json_body") or {}

    if run.get("status_code") != expect.http_status:
        failures.append(f"http_status expected {expect.http_status}, got {run.get('status_code')}")

    if expect.route and detect_route(events) != expect.route:
        failures.append(f"route expected {expect.route}, got {detect_route(events)}")

    if expect.has_error_event is not None and bool(error_events) != expect.has_error_event:
        failures.append(f"has_error_event expected {expect.has_error_event}, got {bool(error_events)}")
        if error_text:
            failures.append(f"error event: {error_text[:500]}")

    if expect.error_contains and expect.error_contains not in (error_text or run.get("body_text", "")):
        failures.append(f"error did not contain '{expect.error_contains}'")

    if expect.graph_emitted is not None and (graph_data is not None) != expect.graph_emitted:
        failures.append(f"graph_emitted expected {expect.graph_emitted}, got {graph_data is not None}")

    if (
        expect.graph_type is not None
        or expect.graph_title_contains is not None
        or expect.graph_node_labels_include
        or expect.graph_node_labels_exclude
        or expect.graph_node_label_keywords_include
        or expect.graph_max_generic_label_count is not None
        or expect.graph_maturity
        or expect.graph_min_retained_node_ratio is not None
    ):
        if graph_data is None:
            failures.append("graph quality expectations were set but no graph_data was emitted")
        else:
            if expect.graph_type is not None and graph_data.get("graph_type") != expect.graph_type:
                failures.append(f"graph_type expected {expect.graph_type}, got {graph_data.get('graph_type')}")

            if expect.graph_title_contains is not None:
                title = graph_data.get("title") or ""
                if expect.graph_title_contains.lower() not in title.lower():
                    failures.append(
                        f"graph title expected to contain '{expect.graph_title_contains}', got '{title}'"
                    )

            labels = extract_graph_node_labels(graph_data)
            for label in expect.graph_node_labels_include:
                if label not in labels:
                    failures.append(f"graph missing node label '{label}'")

            for label in expect.graph_node_labels_exclude:
                if label in labels:
                    failures.append(f"graph unexpectedly included node label '{label}'")

            label_text = " ".join(labels).lower()
            for keyword in expect.graph_node_label_keywords_include:
                alternatives = [item.strip().lower() for item in keyword.split("|") if item.strip()]
                if not any(alternative in label_text for alternative in alternatives):
                    failures.append(f"graph node labels missing domain keyword '{keyword}'")

            if expect.graph_max_generic_label_count is not None:
                generic_labels = {
                    "agent",
                    "application",
                    "evaluation",
                    "foundation model",
                    "generation",
                    "memory",
                    "planning",
                    "tokenization",
                    "tool use",
                }
                generic_count = sum(label.lower() in generic_labels for label in labels)
                if generic_count > expect.graph_max_generic_label_count:
                    failures.append(
                        "graph generic label count exceeded "
                        f"({generic_count} > {expect.graph_max_generic_label_count})"
                    )

            if expect.graph_maturity:
                failures.extend(_graph_maturity_failures(graph_data))

            if expect.graph_min_retained_node_ratio is not None:
                previous_graph = case_state.get("last_graph_data") or {}
                previous_ids = {
                    str(node.get("id"))
                    for node in (previous_graph.get("nodes") or [])
                    if node.get("id")
                }
                current_ids = {
                    str(node.get("id"))
                    for node in (graph_data.get("nodes") or [])
                    if node.get("id")
                }
                if not previous_ids:
                    failures.append("graph retention expectation had no previous graph")
                else:
                    retained_ratio = len(previous_ids & current_ids) / len(previous_ids)
                    if retained_ratio < expect.graph_min_retained_node_ratio:
                        failures.append(
                            "graph retained too few stable component identities "
                            f"({retained_ratio:.2f} < {expect.graph_min_retained_node_ratio:.2f})"
                        )

    for worker in expect.workers_include:
        if worker not in workers:
            failures.append(f"missing worker '{worker}'")

    for worker in expect.workers_exclude:
        if worker in workers:
            failures.append(f"unexpected worker '{worker}'")

    if expect.response_min_length is not None and len(response_text) < expect.response_min_length:
        failures.append(
            f"response shorter than expected ({len(response_text)} < {expect.response_min_length})"
        )

    for needle in expect.response_contains:
        if needle.lower() not in response_text.lower():
            failures.append(f"response missing '{needle}'")

    if expect.suggested_questions_count is not None:
        actual_count = count_suggested_questions(events)
        if actual_count != expect.suggested_questions_count:
            failures.append(
                f"suggested_questions_count expected {expect.suggested_questions_count}, got {actual_count}"
            )

    if expect.thread_message_count is not None:
        messages = thread_json.get("messages") or []
        if len(messages) != expect.thread_message_count:
            failures.append(
                f"thread_message_count expected {expect.thread_message_count}, got {len(messages)}"
            )

    if expect.thread_message_roles:
        messages = thread_json.get("messages") or []
        actual_roles = [message.get("role") for message in messages]
        if actual_roles != expect.thread_message_roles:
            failures.append(f"thread_message_roles expected {expect.thread_message_roles}, got {actual_roles}")

    if expect.thread_count_delta is not None:
        baseline = case_state.get("baseline_thread_count")
        current = count_visible_threads(thread_json, case_state)
        if baseline is None:
            failures.append("baseline thread count was not recorded")
        elif current - baseline != expect.thread_count_delta:
            failures.append(
                f"thread_count_delta expected {expect.thread_count_delta}, got {current - baseline}"
            )

    if expect.thread_deleted is not None:
        deleted = run.get("status_code") == 404
        if deleted != expect.thread_deleted:
            failures.append(f"thread_deleted expected {expect.thread_deleted}, got {deleted}")

    return failures


def _graph_maturity_failures(graph: dict) -> list[str]:
    """Check composition without prescribing exact model-authored component names."""
    failures: list[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_ids = [str(node.get("id")) for node in nodes if node.get("id")]
    node_id_set = set(node_ids)
    if len(node_ids) != len(nodes) or len(node_id_set) != len(node_ids):
        failures.append("mature graph requires one unique id per node")
        return failures

    valid_edges = [
        edge for edge in edges
        if edge.get("source") in node_id_set and edge.get("target") in node_id_set
    ]
    if len(valid_edges) != len(edges):
        failures.append("mature graph contains an edge with an unknown endpoint")
    if node_ids:
        adjacency = {node_id: set() for node_id in node_ids}
        for edge in valid_edges:
            source, target = str(edge["source"]), str(edge["target"])
            adjacency[source].add(target)
            adjacency[target].add(source)
        visited = {node_ids[0]}
        pending = [node_ids[0]]
        while pending:
            current = pending.pop()
            for neighbour in adjacency[current] - visited:
                visited.add(neighbour)
                pending.append(neighbour)
        if len(visited) != len(node_ids):
            failures.append("mature graph must be one connected architecture")

    if not any(edge.get("type") == "loop" or edge.get("flow") == "feedback" for edge in edges):
        failures.append("mature graph requires an explicit measured feedback path")

    groups = graph.get("groups") or []
    memberships = [str(node_id) for group in groups for node_id in (group.get("nodeIds") or [])]
    if len(groups) < 3:
        failures.append("mature graph requires at least three named responsibility zones")
    if set(memberships) != node_id_set or len(memberships) != len(set(memberships)):
        failures.append("mature graph must assign every node to exactly one responsibility zone")

    sequence = graph.get("sequence") or []
    if len(sequence) < 4:
        failures.append("mature graph requires at least four ordered runtime steps")
    if any(
        not step.get("nodes")
        or any(str(node_id) not in node_id_set for node_id in step.get("nodes") or [])
        for step in sequence
    ):
        failures.append("mature graph sequence contains an unknown or empty step")
    if not graph.get("assumptions"):
        failures.append("mature graph must keep inferred requirements visible as assumptions")
    return failures


def resolve_node_selected_payload(step: StagingStep, case_state: dict) -> dict:
    payload = dict(step.payload)
    if payload.pop("use_first_graph_node", False):
        graph_data = case_state.get("last_graph_data") or {}
        nodes = graph_data.get("nodes") or []
        if not nodes:
            raise RuntimeError("node-selected step requested first graph node but no graph was emitted")
        node = nodes[0]
        payload = {
            "node_id": node.get("id") or "node-1",
            "title": node.get("label") or node.get("id") or "Selected node",
            "description": node.get("description") or "Selected graph node",
        }
    return payload


async def run_step(
    client,
    base_url: str,
    auth_token: str,
    thread_id: str,
    step: StagingStep,
    case_state: dict,
) -> dict:
    if step.kind == "chat":
        payload = {
            "thread_id": thread_id,
            "content": step.payload.get("content", ""),
            "complexity": step.payload.get("complexity", "auto"),
            "graph_mode": step.payload.get("graph_mode", "auto"),
            "research_enabled": step.payload.get("research_enabled", False),
        }
        return await perform_websocket_chat(base_url, auth_token, json_payload=payload)

    if step.kind == "node_selected":
        payload = resolve_node_selected_payload(step, case_state)
        payload["thread_id"] = thread_id
        return await perform_sse_request(
            client,
            f"{base_url}/api/node-selected",
            auth_token,
            json_payload=payload,
        )

    if step.kind == "get_thread":
        return await perform_json_request(client, "GET", f"{base_url}/api/threads/{thread_id}", auth_token)

    if step.kind == "delete_thread":
        return await perform_json_request(client, "DELETE", f"{base_url}/api/threads/{thread_id}", auth_token)

    if step.kind == "list_threads":
        return await perform_json_request(client, "GET", f"{base_url}/api/threads", auth_token)

    raise RuntimeError(f"Unsupported step kind: {step.kind}")


async def run_case(
    client,
    base_url: str,
    auth_token: str,
    case: StagingCase,
    *,
    keep_threads: bool,
) -> dict:
    thread = await create_thread(client, base_url, auth_token, f"Staging eval {case.id}")
    thread_id = thread["id"]
    case_state: dict = {"thread_id": thread_id}
    step_results: list[dict] = []

    try:
        for index, step in enumerate(case.steps, start=1):
            try:
                run = await run_step(client, base_url, auth_token, thread_id, step, case_state)
                graph_data = extract_graph_data(run.get("events", []))

                if step.kind == "list_threads" and "baseline_thread_count" not in case_state:
                    body = run.get("json_body") or {}
                    case_state["baseline_thread_count"] = count_visible_threads(body, case_state)

                failures = evaluate_expectation(step, run, case_state)
                if graph_data is not None:
                    case_state["last_graph_data"] = graph_data
            except Exception as exc:
                run = {
                    "status_code": None,
                    "events": [],
                    "json_body": None,
                    "body_text": "",
                }
                failures = [f"step raised {type(exc).__name__}: {exc}"]
            step_results.append(
                {
                    "index": index,
                    "kind": step.kind,
                    "description": step.description,
                    "passed": not failures,
                    "failures": failures,
                    "status_code": run.get("status_code"),
                    "events": run.get("events", []),
                    "json_body": run.get("json_body"),
                }
            )
            if failures and run.get("status_code") is None:
                break

        passed = all(result["passed"] for result in step_results)
        return {
            "id": case.id,
            "category": case.category,
            "description": case.description,
            "thread_id": thread_id,
            "passed": passed,
            "steps": step_results,
        }
    finally:
        if case.cleanup_thread and not keep_threads:
            await perform_json_request(client, "DELETE", f"{base_url}/api/threads/{thread_id}", auth_token)


async def run_cases_with_concurrency(
    cases: list[StagingCase],
    run_case_with_retry,
    *,
    concurrency: int,
) -> list[dict]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_limited_case(case: StagingCase) -> dict:
        async with semaphore:
            return await run_case_with_retry(case)

    return list(await asyncio.gather(*[run_limited_case(case) for case in cases]))


def print_report(results: list[dict]) -> None:
    if _console is None or Table is None or box is None:
        print("Case | Category | Status | Failed Steps")
        for result in results:
            failed_steps = sum(1 for step in result["steps"] if not step["passed"])
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{result['id']} | {result['category']} | {status} | {failed_steps}")

        failures = [result for result in results if not result["passed"]]
        if failures:
            print("\nFailures")
            for result in failures:
                print(f"{result['id']} {result['description']}")
                for step in result["steps"]:
                    if step["passed"]:
                        continue
                    print(f"  {step['index']}. {step['description']}")
                    for failure in step["failures"]:
                        print(f"    - {failure}")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Case")
    table.add_column("Category")
    table.add_column("Status")
    table.add_column("Failed Steps", justify="right")

    for result in results:
        failed_steps = sum(1 for step in result["steps"] if not step["passed"])
        table.add_row(
            result["id"],
            result["category"],
            "[green]PASS[/]" if result["passed"] else "[red]FAIL[/]",
            str(failed_steps),
        )

    _console.print(table)

    failures = [result for result in results if not result["passed"]]
    if failures:
        _console.print()
        _console.rule("[bold red]Failures[/]")
        for result in failures:
            _console.print(f"[bold red]{result['id']}[/] {result['description']}")
            for step in result["steps"]:
                if step["passed"]:
                    continue
                _console.print(f"  [bold]{step['index']}. {step['description']}[/]")
                for failure in step["failures"]:
                    _console.print(f"    - {failure}")


def write_results(results: list[dict]) -> Path:
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"staging-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    path.write_text(json.dumps(results, indent=2, default=str))
    return path


async def main() -> None:
    args = build_parser().parse_args()
    selected_cases = select_cases(args)
    if args.request_otp:
        if not args.email:
            raise RuntimeError("Pass --email when using --request-otp")
        await request_otp(args.base_url, args.email)
        _console.print(f"OTP requested for [bold]{args.email}[/]")
        return

    if not selected_cases:
        raise RuntimeError("No staging cases selected")

    auth_token = await ensure_auth_token(args)

    ready = await perform_json_request(None, "GET", f"{args.base_url}/api/prepare", "")
    if ready["status_code"] >= 400:
        raise RuntimeError(f"Backend not ready: {ready['body_text']}")

    if args.check_dashboard:
        await smoke_test_internal_dashboard(args.base_url, auth_token)
        _console_print("Dashboard smoke check: PASS")

    _console_rule("[bold]Staging Eval Suite[/]")
    _console_print(f"Base URL: [bold]{args.base_url}[/]" if _console is not None else f"Base URL: {args.base_url}")
    _console_print(f"Cases: [bold]{len(selected_cases)}[/]\n" if _console is not None else f"Cases: {len(selected_cases)}\n")

    async def run_case_with_retry(case: StagingCase) -> dict:
        """Run a case with retry logic for flaky tests."""
        started_at = time.perf_counter()
        case_label = f"[bold]{case.id}[/]" if _console is not None else case.id
        _console_print(f"Running {case_label} {case.description}")
        result = None
        attempts = max(1, args.attempts)
        for attempt in range(1, attempts + 1):
            result = await run_case(
                None,
                args.base_url,
                auth_token,
                case,
                keep_threads=args.keep_threads,
            )
            if result["passed"]:
                elapsed = time.perf_counter() - started_at
                pass_message = f"[green]PASS[/] ({elapsed:.1f}s)" if _console is not None else f"PASS ({elapsed:.1f}s)"
                _console_print(f"{pass_message}\n")
                return result
            if attempt < attempts:
                retry_message = (
                    f"[yellow]{case.id} FAIL (attempt {attempt}/{attempts}, retrying...)[/]"
                    if _console is not None
                    else f"{case.id} FAIL (attempt {attempt}/{attempts}, retrying...)"
                )
                _console_print(retry_message)
        elapsed = time.perf_counter() - started_at
        fail_message = f"[red]FAIL[/] ({elapsed:.1f}s)" if _console is not None else f"FAIL ({elapsed:.1f}s)"
        _console_print(f"{fail_message}\n")
        return result

    results = await run_cases_with_concurrency(
        selected_cases,
        run_case_with_retry,
        concurrency=args.concurrency,
    )

    print_report(results)
    path = write_results(results)
    _console_print(f"\nResults written to [dim]{path}[/]" if _console is not None else f"\nResults written to {path}")

    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
