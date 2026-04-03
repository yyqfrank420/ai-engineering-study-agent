# ─────────────────────────────────────────────────────────────────────────────
# File: backend/eval/runner.py
# Purpose: Main entry point for the agent evaluation suite.
#
# Usage:
#     cd backend
#     EVAL_AUTH_TOKEN=<token> .venv/bin/python -m eval.runner
#     EVAL_AUTH_TOKEN=<token> .venv/bin/python -m eval.runner --category preflight_security
#     EVAL_AUTH_TOKEN=<token> .venv/bin/python -m eval.runner --case F1 --case F2 --self-assessment
#
# Requires: backend running on http://localhost:8000 and a valid Supabase access token
# Language: Python
# Connects to: eval/test_cases.py, eval/metrics.py, eval/report.py,
#              backend /api/chat SSE endpoint
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import asyncio
import copy
import json
import os

import httpx
from rich.console import Console

from eval.metrics import score_test_case
from eval.report import print_report, print_self_assessment
from eval.test_cases import SELF_ASSESSMENT_QUERY, TEST_CASES, TestCase

_console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the backend eval suite.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument(
        "--auth-token",
        default=os.getenv("EVAL_AUTH_TOKEN", ""),
        help="Supabase access token for the authenticated thread-based API (or set EVAL_AUTH_TOKEN)",
    )
    parser.add_argument("--case", action="append", default=[], help="Specific test case ID to run")
    parser.add_argument("--category", action="append", default=[], help="Specific category to run")
    parser.add_argument("--max-cases", type=int, default=None, help="Run only the first N selected cases")
    parser.add_argument("--self-assessment", action="store_true", help="Spend one extra LLM call on the self-assessment prompt")
    return parser


async def perform_request(base_url: str, endpoint: str, payload: dict, auth_token: str) -> dict:
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{base_url}{endpoint}", json=payload, headers=headers)
        content_type = response.headers.get("content-type", "")
        text = response.text

        if "text/event-stream" in content_type:
            events: list[dict] = []
            for chunk in text.split("\n\n"):
                line = chunk.strip()
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                    events.append(data)
                except json.JSONDecodeError:
                    pass
            return {
                "status_code": response.status_code,
                "content_type": content_type,
                "events": events,
                "body_text": text,
                "json_body": None,
            }

        try:
            json_body = response.json()
        except json.JSONDecodeError:
            json_body = None

        return {
            "status_code": response.status_code,
            "content_type": content_type,
            "events": [],
            "body_text": text,
            "json_body": json_body,
        }


async def create_thread(base_url: str, auth_token: str, title: str) -> str:
    result = await perform_request(
        base_url,
        "/api/threads",
        {"title": title},
        auth_token,
    )
    if result["status_code"] >= 400:
        raise RuntimeError(f"Thread creation failed: {result['body_text']}")
    json_body = result.get("json_body") or {}
    thread = json_body.get("thread") or {}
    thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError("Thread creation response did not include thread.id")
    return thread_id


async def query_agent(base_url: str, auth_token: str, thread_id: str, message: str) -> dict:
    return await perform_request(
        base_url,
        "/api/chat",
        {"thread_id": thread_id, "content": message},
        auth_token,
    )


async def run_self_assessment(base_url: str, auth_token: str) -> str:
    thread_id = await create_thread(base_url, auth_token, "Eval self-assessment")
    result = await query_agent(base_url, auth_token, thread_id, SELF_ASSESSMENT_QUERY)
    return "".join(
        e.get("content", "")
        for e in result["events"]
        if e.get("type") == "response_delta"
    )


def select_cases(args: argparse.Namespace) -> list[TestCase]:
    selected = TEST_CASES
    if args.case:
        wanted = {case_id.upper() for case_id in args.case}
        selected = [case for case in selected if case.id.upper() in wanted]
    if args.category:
        wanted_categories = set(args.category)
        selected = [case for case in selected if case.category in wanted_categories]
    if args.max_cases is not None:
        selected = selected[:args.max_cases]
    return selected


async def run_test_case(base_url: str, auth_token: str, case: TestCase) -> dict:
    thread_id = await create_thread(base_url, auth_token, f"Eval {case.id}")
    final_run: dict = {"status_code": None, "events": [], "body_text": "", "json_body": None}

    _console.print(f"  [dim]{case.id}[/] {case.description}", end="")
    try:
        if case.request_payloads:
            for payload in case.request_payloads:
                request_payload = copy.deepcopy(payload)
                request_payload.setdefault("thread_id", thread_id)
                final_run = await perform_request(base_url, case.endpoint, request_payload, auth_token)
        else:
            for i, message in enumerate(case.messages):
                result = await query_agent(base_url, auth_token, thread_id, message)
                if i == len(case.messages) - 1:
                    final_run = result

        result = score_test_case(case, final_run)
    except Exception as exc:
        result = {
            "id": case.id,
            "category": case.category,
            "description": case.description,
            "passed": False,
            "errors": [f"Exception: {exc}"],
        }

    status = "[green]✓[/]" if result.get("passed") else "[red]✗[/]"
    _console.print(f"  {status}")
    return result


async def main() -> None:
    args = build_parser().parse_args()
    selected_cases = select_cases(args)

    _console.rule("[bold #a78bfa]AI Engineering Agent — Eval Suite[/]")
    _console.print()

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"{args.base_url}/health")
    except Exception:
        _console.print(
            f"[bold red]ERROR:[/] Backend not reachable at {args.base_url}\n"
            "Run:  .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000",
            style="red",
        )
        return

    if not selected_cases:
        _console.print("[bold yellow]No test cases selected.[/]")
        return

    if not args.auth_token:
        _console.print(
            "[bold red]ERROR:[/] The eval suite now targets the authenticated thread-based API.\n"
            "Set `EVAL_AUTH_TOKEN` or pass `--auth-token <token>`.",
            style="red",
        )
        return

    if args.self_assessment:
        _console.print("[bold]Step 1:[/] Asking the agent to describe its own evaluation criteria…\n")
        self_assessment = await run_self_assessment(args.base_url, args.auth_token)
        print_self_assessment(self_assessment)

    _console.print(f"[bold]Running {len(selected_cases)} test cases…[/]\n")
    results: list[dict] = []
    for case in selected_cases:
        result = await run_test_case(args.base_url, args.auth_token, case)
        results.append(result)

    print_report(results)


if __name__ == "__main__":
    asyncio.run(main())
