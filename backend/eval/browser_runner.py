from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.request
import urllib.parse
from urllib.error import HTTPError
import zipfile

from playwright.async_api import BrowserContext, Page, WebSocket, async_playwright

from eval.quality_corpus import EvaluationCase, corpus_sha256, load_corpus
from eval.response_capture import extract_response_text, extract_response_turns
from eval.staging_runner import (
    detect_route,
    extract_graph_data,
    extract_workers,
)


ROOT = Path(__file__).resolve().parents[2]
QUALITY_MANIFEST = ROOT / "ci" / "quality.json"
EVAL_AUTH_STORAGE_KEY = "ai-engineering-eval-auth"
_BOOK_CITATION = re.compile(
    r"Chapter\s+(?P<chapter>\d+)\s*[,;:]?\s*(?:p(?:age)?\.?\s*)(?P<page>\d+)",
    re.I,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real frontend journeys in Playwright")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--target", required=True, help="Frontend URL to open in Chromium")
    parser.add_argument("--backend-target", default=os.getenv("EVAL_BACKEND_URL", ""))
    parser.add_argument("--email", default=os.getenv("EVAL_EMAIL", ""))
    parser.add_argument("--internal-password", default=os.getenv("EVAL_INTERNAL_PASSWORD", ""))
    parser.add_argument("--output", default="artifacts/live-eval/browser-results.json")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run an explicit corpus case in the diagnostic suite (repeatable, maximum eight)",
    )
    return parser


def _suite_case_ids(suite: str, selected_cases: list[str] | None = None) -> list[str]:
    manifest = json.loads(QUALITY_MANIFEST.read_text(encoding="utf-8"))
    suites = manifest["live"]["suites"]
    selected = selected_cases or []
    if suite == "diagnostic":
        if not selected:
            raise ValueError("diagnostic browser suite requires at least one --case")
        if len(selected) > 8:
            raise ValueError("diagnostic browser suite is limited to eight cases")
        if len(selected) != len(set(selected)):
            raise ValueError("diagnostic browser suite contains duplicate cases")
        unknown = sorted(set(selected) - set(suites["full"]))
        if unknown:
            raise ValueError("unknown diagnostic browser cases: " + ", ".join(unknown))
        return selected
    if selected:
        raise ValueError("--case is accepted only with --suite diagnostic")
    if suite == "nightly":
        full = suites["full"]
        day = datetime.now(UTC).timetuple().tm_yday
        start = (day * 4) % len(full)
        return [full[(start + offset) % len(full)] for offset in range(4)]
    if suite not in suites:
        raise ValueError(f"unknown browser suite: {suite}")
    return list(suites[suite])


def _blocking_json_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    token: str | None = None,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("evaluation targets must use an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("evaluation targets must not contain URL credentials")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    # The scheme, host, and absence of URL credentials are validated above.
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


async def _internal_session(backend_target: str, email: str, password: str) -> dict[str, Any]:
    if not backend_target or not email or not password:
        raise RuntimeError("browser eval requires --backend-target, --email, and --internal-password")
    result = await asyncio.to_thread(
        _blocking_json_request,
        "POST",
        backend_target.rstrip("/") + "/api/auth/internal-login",
        {"email": email, "password": password},
    )
    session = result.get("session")
    if not isinstance(session, dict) or not session.get("access_token"):
        raise RuntimeError("internal browser bootstrap did not return a session")
    session["expires_at"] = int(time.time()) + int(session.get("expires_in") or 1800)
    return session


def _serialized_session(session: dict[str, Any]) -> str:
    return json.dumps(session, separators=(",", ":"))


def _session_expires_soon(session: dict[str, Any], *, buffer_seconds: int = 600) -> bool:
    expires_at = session.get("expires_at")
    return not isinstance(expires_at, int | float) or expires_at - time.time() <= buffer_seconds


async def _replace_page_session(page: Page, session: dict[str, Any]) -> None:
    await page.evaluate(
        "([key, value]) => window.localStorage.setItem(key, value)",
        [EVAL_AUTH_STORAGE_KEY, _serialized_session(session)],
    )


async def _wait_for_composer_ready(page: Page, *, timeout_seconds: int = 30) -> None:
    composer = page.get_by_placeholder(re.compile(r"Ask a question"))
    await composer.wait_for(state="visible", timeout=timeout_seconds * 1000)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if await composer.is_enabled():
            return
        await asyncio.sleep(0.25)
    raise RuntimeError("evaluation frontend did not create an authenticated thread")


async def _capture_bootstrap_failure(
    page: Page,
    context: BrowserContext,
    artifact_dir: Path,
    session: dict[str, Any],
    internal_password: str,
    error: Exception,
    browser_events: list[dict[str, str]],
) -> None:
    screenshot_error = ""
    try:
        await page.screenshot(path=artifact_dir / "browser-bootstrap-failure.png", full_page=True)
    except Exception as exc:
        screenshot_error = f"{type(exc).__name__}: {exc}"

    trace_error = ""
    raw_trace = artifact_dir / ".playwright-trace.bootstrap.raw.zip"
    try:
        await context.tracing.stop(path=raw_trace)
        _redact_trace(
            raw_trace,
            artifact_dir / "playwright-trace.zip",
            [session.get("access_token", ""), session.get("refresh_token", ""), internal_password],
        )
    except Exception as exc:
        trace_error = f"{type(exc).__name__}: {exc}"
    finally:
        raw_trace.unlink(missing_ok=True)

    auth_overlay_visible = False
    try:
        auth_overlay_visible = await page.get_by_role("heading", name="Sign in").is_visible()
    except Exception as exc:
        browser_events.append(
            {"type": "diagnostic_error", "text": f"{type(exc).__name__}: {exc}"[:1000]}
        )
    diagnostics = {
        "format_version": 1,
        "phase": "browser_bootstrap",
        "error": f"{type(error).__name__}: {error}",
        "page_url": page.url,
        "auth_overlay_visible": auth_overlay_visible,
        "browser_events": browser_events[-50:],
        "screenshot_error": screenshot_error,
        "trace_error": trace_error,
    }
    serialized_diagnostics = json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n"
    for secret in (session.get("access_token", ""), session.get("refresh_token", ""), internal_password):
        if secret:
            serialized_diagnostics = serialized_diagnostics.replace(secret, "[REDACTED]")
    (artifact_dir / "browser-bootstrap-diagnostics.json").write_text(
        serialized_diagnostics,
        encoding="utf-8",
    )


def _capture_socket(frames: list[dict[str, Any]], socket: WebSocket) -> None:
    def record(direction: str, payload: str | bytes) -> None:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            return
        if isinstance(message, dict):
            frames.append({"direction": direction, "message": message, "at": time.time()})

    socket.on("framesent", lambda payload: record("sent", payload))
    socket.on("framereceived", lambda payload: record("received", payload))


async def _set_modes(page: Page, case: EvaluationCase, step_index: int) -> None:
    mode = case.steps[step_index].ui
    await page.get_by_label("Message options").click()
    await page.get_by_role("radiogroup", name="complexity").get_by_role("radio", name=mode.complexity).click()
    await page.get_by_role("radiogroup", name="graph").get_by_role("radio", name=mode.graph_mode).click()
    research = page.get_by_role("switch", name="research")
    checked = await research.get_attribute("aria-checked") == "true"
    if checked != mode.research_enabled:
        await research.click()
    await page.get_by_label("Message options").click()


async def _send_step(page: Page, case: EvaluationCase, step_index: int, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    await _set_modes(page, case, step_index)
    start = len(frames)
    textarea = page.get_by_placeholder(re.compile(r"Ask a question"))
    await textarea.fill(case.steps[step_index].prompt)
    await page.get_by_label("Send message").click()
    await page.get_by_label("Stop generation").wait_for(state="visible", timeout=20_000)
    await page.get_by_label("Send message").wait_for(state="visible", timeout=210_000)
    step_frames = [frame for frame in frames[start:] if frame["direction"] == "received"]
    events = [frame["message"] for frame in step_frames]
    if not any(event.get("type") == "done" for event in events):
        raise RuntimeError(f"case {case.id} did not receive a WebSocket done event")
    return events


def _thread_id(frames: list[dict[str, Any]]) -> str | None:
    for frame in reversed(frames):
        message = frame["message"]
        if frame["direction"] == "sent" and message.get("type") == "start":
            return message.get("thread_id")
    return None


def _deterministic_failures(case: EvaluationCase, events: list[dict[str, Any]], rendered_nodes: int) -> list[str]:
    expected = case.deterministic
    failures: list[str] = []
    workers = extract_workers(events)
    observed_status = 200 if any(event.get("type") == "done" for event in events) else 500
    if observed_status != expected.status:
        failures.append(f"status expected {expected.status}, got {observed_status}")
    for worker in expected.workers_include:
        if worker not in workers:
            failures.append(f"missing worker: {worker}")
    for worker in expected.workers_exclude:
        if worker in workers:
            failures.append(f"unexpected worker: {worker}")
    if expected.route and detect_route(events) != expected.route:
        failures.append(f"route expected {expected.route}, got {detect_route(events)}")
    graph = extract_graph_data(events)
    if expected.graph_emitted is not None and bool(graph) != expected.graph_emitted:
        failures.append(f"graph_emitted expected {expected.graph_emitted}, got {bool(graph)}")
    if expected.graph_renderable and graph and rendered_nodes < len(graph.get("nodes") or []):
        failures.append(f"browser rendered {rendered_nodes} of {len(graph.get('nodes') or [])} graph nodes")
    if expected.streaming_complete and not any(event.get("type") == "done" for event in events):
        failures.append("stream did not complete")
    errors = [str(event.get("content") or "") for event in events if event.get("type") == "error"]
    if bool(errors) != expected.error_expected:
        failures.append("unexpected error events: " + "; ".join(errors))
    answer = extract_response_text(events)
    if expected.citations_required:
        if expected.citation_source == "web":
            research_unavailable = any(
                event.get("type") == "worker_status"
                and event.get("worker") == "research"
                and "unavailable" in str(event.get("status") or "").lower()
                for event in events
            )
            supplied_sources: set[str] = set()
            for event in events:
                if event.get("type") != "worker_status" or event.get("worker") != "research":
                    continue
                sources = event.get("sources")
                if not isinstance(sources, list):
                    continue
                supplied_sources.update(
                    source
                    for source in sources
                    if isinstance(source, str) and source.startswith(("http://", "https://"))
                )
            if research_unavailable:
                failures.append("research infrastructure unavailable: no citable web sources")
            elif not supplied_sources:
                failures.append("research completed without source provenance telemetry")
            elif not any(source in answer for source in supplied_sources):
                failures.append("required web citation did not match supplied research evidence")
        else:
            cited_book_refs = {
                (int(match.group("chapter")), int(match.group("page")))
                for match in _BOOK_CITATION.finditer(answer)
            }
            supplied_book_refs = {
                (int(chunk["chapter"]), int(chunk["page_number"]))
                for event in events
                if event.get("type") == "retrieval_evidence"
                for chunk in event.get("chunks") or []
                if isinstance(chunk, dict)
                and str(chunk.get("chapter") or "").isdigit()
                and str(chunk.get("page_number") or "").isdigit()
            }
            if not cited_book_refs:
                failures.append("required chapter-and-page citation was not visible in the answer")
            elif not supplied_book_refs:
                failures.append("book retrieval completed without source provenance telemetry")
            elif not cited_book_refs.issubset(supplied_book_refs):
                failures.append("book citation did not match supplied retrieval evidence")
    return failures


async def _delete_thread(backend_target: str, token: str, thread_id: str) -> None:
    try:
        await asyncio.to_thread(
            _blocking_json_request,
            "DELETE",
            backend_target.rstrip("/") + f"/api/threads/{thread_id}",
            None,
            token,
        )
        try:
            await asyncio.to_thread(
                _blocking_json_request,
                "GET",
                backend_target.rstrip("/") + f"/api/threads/{thread_id}",
                None,
                token,
            )
        except HTTPError as exc:
            if exc.code == 404:
                return
            raise
        raise RuntimeError("thread remained readable after cleanup")
    except Exception as exc:
        raise RuntimeError(f"failed to clean up eval thread {thread_id}") from exc


async def run_browser(args: argparse.Namespace) -> dict[str, Any]:
    corpus = load_corpus()
    case_ids = _suite_case_ids(args.suite, args.case)
    cases = [corpus.by_id[case_id] for case_id in case_ids]
    if args.suite == "pr" and len(cases) != 8:
        raise RuntimeError("the PR browser suite must contain exactly eight journeys")
    output_path = ROOT / args.output
    artifact_dir = output_path.parent
    screenshot_dir = artifact_dir / "screenshots"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    session = await _internal_session(args.backend_target, args.email, args.internal_password)
    frames: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    started_at = datetime.now(UTC)

    timeout_seconds = 900 if args.suite in {"pr", "smoke", "diagnostic"} else 3600
    async with asyncio.timeout(timeout_seconds):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headed)
            context = await browser.new_context(viewport={"width": 1440, "height": 960})
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            await context.add_init_script(
                "if (!localStorage.getItem("
                + json.dumps(EVAL_AUTH_STORAGE_KEY)
                + ")) localStorage.setItem("
                + json.dumps(EVAL_AUTH_STORAGE_KEY)
                + ", "
                + json.dumps(_serialized_session(session))
                + ");"
            )
            page = await context.new_page()
            browser_events: list[dict[str, str]] = []
            page.on(
                "console",
                lambda message: browser_events.append(
                    {"type": f"console.{message.type}", "text": message.text[:1000]}
                ),
            )
            page.on(
                "pageerror",
                lambda error: browser_events.append(
                    {"type": "pageerror", "text": str(error)[:1000]}
                ),
            )
            page.on("websocket", lambda socket: _capture_socket(frames, socket))
            try:
                await page.goto(args.target, wait_until="domcontentloaded", timeout=60_000)
                if await page.get_by_role("heading", name="Sign in").is_visible():
                    raise RuntimeError("evaluation frontend did not accept the internal session")
                prepare = page.get_by_label("Prepare backend")
                if await prepare.is_visible():
                    await prepare.click()
                await _wait_for_composer_ready(page)
            except Exception as exc:
                await _capture_bootstrap_failure(
                    page,
                    context,
                    artifact_dir,
                    session,
                    args.internal_password,
                    exc,
                    browser_events,
                )
                await browser.close()
                raise

            for index, case in enumerate(cases):
                if index:
                    if _session_expires_soon(session):
                        session = await _internal_session(args.backend_target, args.email, args.internal_password)
                        await _replace_page_session(page, session)
                    await page.reload(wait_until="domcontentloaded", timeout=60_000)
                    await _wait_for_composer_ready(page)
                case_started = time.monotonic()
                case_events: list[dict[str, Any]] = []
                start_frame = len(frames)
                failure: str | None = None
                try:
                    for step_index in range(len(case.steps)):
                        case_events.extend(await _send_step(page, case, step_index, frames))
                    if case.id == "node-followup":
                        # Use the same accessible activation path available to
                        # keyboard users and prove the optional refinement starts.
                        first_node = page.get_by_role(
                            "button", name=re.compile(r"^Explore ")
                        ).first
                        async with page.expect_request(
                            lambda request: request.method == "POST"
                            and request.url.rstrip("/").endswith("/api/node-selected"),
                            timeout=10_000,
                        ):
                            await first_node.press("Enter", timeout=10_000)
                        await page.locator('[data-testid="suggested-question"]').first.wait_for(timeout=10_000)
                except Exception as exc:
                    failure = f"{type(exc).__name__}: {exc}"

                graph = extract_graph_data(case_events)
                rendered_nodes = await page.locator('[data-testid="graph-canvas"] g.node').count()
                deterministic = [failure] if failure else _deterministic_failures(case, case_events, rendered_nodes)
                screenshot = screenshot_dir / f"{case.id}.png"
                await page.screenshot(path=screenshot, full_page=True)
                case_frames = frames[start_frame:]
                thread_id = _thread_id(case_frames)
                persisted = False
                if thread_id:
                    try:
                        thread = await asyncio.to_thread(
                            _blocking_json_request,
                            "GET",
                            args.backend_target.rstrip("/") + f"/api/threads/{thread_id}",
                            None,
                            session["access_token"],
                        )
                        persisted = len(thread.get("messages") or []) >= len(case.steps) * 2
                    except Exception:
                        persisted = False
                if case.deterministic.persistence and not persisted:
                    deterministic.append("conversation was not durably visible after streaming")

                result = {
                    "id": case.id,
                    "category": case.category,
                    "risk_tags": case.risk_tags,
                    "deterministic_failures": deterministic,
                    "answer": extract_response_text(case_events),
                    "turns": [
                        {
                            "turn": turn_index,
                            "prompt": case.steps[turn_index - 1].prompt,
                            "answer": answer,
                        }
                        for turn_index, answer in enumerate(
                            extract_response_turns(case_events),
                            start=1,
                        )
                    ],
                    "events": case_events,
                    "graph": graph,
                    "rendered_nodes": rendered_nodes,
                    "thread_id": thread_id,
                    "screenshot": str(screenshot.relative_to(artifact_dir)),
                    "latency_ms": int((time.monotonic() - case_started) * 1000),
                    "fallback_used": any(event.get("type") == "provider_switch" for event in case_events),
                }
                if thread_id and case.deterministic.cleanup:
                    try:
                        await _delete_thread(args.backend_target, session["access_token"], thread_id)
                    except Exception as exc:
                        deterministic.append(f"cleanup failed: {type(exc).__name__}: {exc}")
                result["passed"] = not deterministic
                results.append(result)

            raw_trace = artifact_dir / ".playwright-trace.raw.zip"
            await context.tracing.stop(path=raw_trace)
            _redact_trace(
                raw_trace,
                artifact_dir / "playwright-trace.zip",
                [session.get("access_token", ""), session.get("refresh_token", ""), args.internal_password],
            )
            raw_trace.unlink(missing_ok=True)
            await browser.close()

    report = {
        "format_version": 1,
        "kind": "browser_capture",
        "suite": args.suite,
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": corpus_sha256(),
        "release_identity": corpus.release_identity,
        "target": args.target,
        "backend_target": args.backend_target,
        "started_at": started_at.isoformat(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "results": results,
    }
    thread_ids = [result["thread_id"] for result in results if result.get("thread_id")]
    query = urllib.parse.urlencode(
        [("since_epoch", str(started_at.timestamp())), *(("thread_id", thread_id) for thread_id in thread_ids)]
    )
    telemetry = await asyncio.to_thread(
        _blocking_json_request,
        "GET",
        args.backend_target.rstrip("/") + "/api/internal/dashboard/eval-telemetry?" + query,
        None,
        session["access_token"],
    )
    report["application_telemetry"] = telemetry.get("calls") or []
    dashboard = await asyncio.to_thread(
        _blocking_json_request,
        "GET",
        args.backend_target.rstrip("/") + "/api/internal/dashboard/overview",
        None,
        session["access_token"],
    )
    dashboard_passed = isinstance(dashboard.get("kpis"), dict) and isinstance(dashboard.get("providers"), dict)
    report["dashboard_smoke"] = {"passed": dashboard_passed, "required_keys": ["kpis", "providers"]}
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_junit(artifact_dir / "browser-junit.xml", results)
    _write_html(artifact_dir / "review.html", report)
    return report


def _redact_trace(source: Path, destination: Path, secrets: list[str]) -> None:
    replacements = [secret.encode("utf-8") for secret in secrets if secret]
    with zipfile.ZipFile(source) as input_zip, zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
        for info in input_zip.infolist():
            content = input_zip.read(info.filename)
            for secret in replacements:
                content = content.replace(secret, b"[REDACTED]")
            output_zip.writestr(info, content)


def _write_junit(path: Path, results: list[dict[str, Any]]) -> None:
    failures = sum(not result["passed"] for result in results)
    cases = []
    for result in results:
        failure = ""
        if not result["passed"]:
            message = html.escape("; ".join(result["deterministic_failures"]), quote=True)
            failure = f'<failure message="{message}" />'
        cases.append(f'<testcase classname="live.browser" name="{html.escape(result["id"])}">{failure}</testcase>')
    path.write_text(
        f'<testsuite name="browser journeys" tests="{len(results)}" failures="{failures}">' + "".join(cases) + "</testsuite>\n",
        encoding="utf-8",
    )


def _write_html(path: Path, report: dict[str, Any]) -> None:
    rows = []
    for result in report["results"]:
        answer = html.escape(result["answer"][:4000])
        failures = html.escape("; ".join(result["deterministic_failures"]) or "none")
        evidence = html.escape(json.dumps(
            [
                event
                for event in result.get("events") or []
                if event.get("type") in {"retrieval_evidence", "research_evidence"}
            ],
            indent=2,
            ensure_ascii=False,
        )[:20_000])
        rows.append(
            f"<article><h2>{html.escape(result['id'])} — {'PASS' if result['passed'] else 'FAIL'}</h2>"
            f"<p><b>Deterministic:</b> {failures}</p><img src='{html.escape(result['screenshot'])}' loading='lazy'>"
            f"<details><summary>Answer</summary><pre>{answer}</pre></details>"
            f"<details><summary>Retrieved evidence</summary><pre>{evidence}</pre></details></article>"
        )
    body = "".join(rows)
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Evaluation review</title>"
        "<style>body{font:15px system-ui;max-width:1100px;margin:auto;background:#111;color:#eee}article{border-bottom:1px solid #444;padding:24px}img{max-width:100%}pre{white-space:pre-wrap}</style>"
        f"<h1>Corpus review — {html.escape(report['corpus_version'])}</h1>{body}",
        encoding="utf-8",
    )


async def main() -> None:
    args = build_parser().parse_args()
    report = await run_browser(args)
    if not all(result["passed"] for result in report["results"]) or not report["dashboard_smoke"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
