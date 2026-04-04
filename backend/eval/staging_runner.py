import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request

from rich import box
from rich.console import Console
from rich.table import Table

from eval.staging_cases import STAGING_CASES, StagingCase, StagingStep

_console = Console()


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
    parser.add_argument("--keep-threads", action="store_true", help="Do not auto-delete eval threads")
    return parser


def select_cases(args: argparse.Namespace) -> list[StagingCase]:
    selected = STAGING_CASES
    if args.case:
        wanted = {case_id.upper() for case_id in args.case}
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


def extract_response_text(events: list[dict]) -> str:
    return "".join(event.get("content", "") for event in events if event.get("type") == "response_delta")


def extract_workers(events: list[dict]) -> set[str]:
    return {
        event["worker"]
        for event in events
        if event.get("type") == "worker_status" and event.get("worker")
    }


def extract_graph_data(events: list[dict]) -> dict | None:
    graph_events = [event for event in events if event.get("type") == "graph_data"]
    if not graph_events:
        return None
    return graph_events[-1].get("data")


def detect_route(events: list[dict]) -> str:
    return "search" if "rag" in extract_workers(events) else "memory"


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


def _blocking_request(
    method: str,
    url: str,
    auth_token: str,
    json_payload: dict | None,
    expect_sse: bool,
) -> dict:
    request = urllib.request.Request(url, method=method)
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")

    data = None
    if json_payload is not None:
        request.add_header("Content-Type", "application/json")
        data = json.dumps(json_payload).encode("utf-8")

    try:
        with urllib.request.urlopen(request, data=data, timeout=120) as response:
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
                    if event.get("type") == "done":
                        break
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

    if expect.error_contains and expect.error_contains not in (error_text or run.get("body_text", "")):
        failures.append(f"error did not contain '{expect.error_contains}'")

    if expect.graph_emitted is not None and (graph_data is not None) != expect.graph_emitted:
        failures.append(f"graph_emitted expected {expect.graph_emitted}, got {graph_data is not None}")

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
        return await perform_sse_request(client, f"{base_url}/api/chat", auth_token, json_payload=payload)

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
            run = await run_step(client, base_url, auth_token, thread_id, step, case_state)
            graph_data = extract_graph_data(run.get("events", []))
            if graph_data is not None:
                case_state["last_graph_data"] = graph_data

            if step.kind == "list_threads" and "baseline_thread_count" not in case_state:
                body = run.get("json_body") or {}
                case_state["baseline_thread_count"] = count_visible_threads(body, case_state)

            failures = evaluate_expectation(step, run, case_state)
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


def print_report(results: list[dict]) -> None:
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

    _console.rule("[bold]Staging Eval Suite[/]")
    _console.print(f"Base URL: [bold]{args.base_url}[/]")
    _console.print(f"Cases: [bold]{len(selected_cases)}[/]\n")

    results: list[dict] = []
    for case in selected_cases:
        _console.print(f"Running [bold]{case.id}[/] {case.description}")
        result = await run_case(
            None,
            args.base_url,
            auth_token,
            case,
            keep_threads=args.keep_threads,
        )
        results.append(result)
        _console.print("[green]PASS[/]\n" if result["passed"] else "[red]FAIL[/]\n")

    print_report(results)
    path = write_results(results)
    _console.print(f"\nResults written to [dim]{path}[/]")

    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
