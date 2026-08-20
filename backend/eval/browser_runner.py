from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Literal, TypedDict
import urllib.request
import urllib.parse
from urllib.error import HTTPError
import zipfile

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    WebSocket,
    async_playwright,
)

from eval.quality_corpus import EvaluationCase, corpus_sha256, load_corpus
from eval.response_capture import extract_response_text, extract_response_turns
from eval.runtime_budget import (
    application_turn_timeout_seconds,
    browser_case_concurrency,
    browser_graph_case_concurrency,
    browser_infrastructure_retry_count,
    browser_suite_timeout_seconds,
)
from eval.staging_runner import (
    detect_route,
    extract_workers,
)


ROOT = Path(__file__).resolve().parents[2]
QUALITY_MANIFEST = ROOT / "ci" / "quality.json"
EVAL_AUTH_STORAGE_KEY = "ai-engineering-eval-auth"
_BOOK_CITATION = re.compile(
    r"Chapter\s+(?P<chapter>\d+)\s*[,;:]?\s*(?:p(?:age)?\.?\s*)(?P<page>\d+)",
    re.I,
)
_PROVIDER_OR_TRANSPORT_FAILURE = re.compile(
    r"(?:rate.?limit|\b429\b|provider.{0,40}unavailable|"
    r"research infrastructure unavailable|timed?\s*out|\btimeout\b|"
    r"connection (?:reset|refused|failed|closed)|network (?:error|failure)|"
    r"websocket (?:error|closed|disconnected)|browser.{0,20}(?:closed|disconnected))",
    re.I,
)
_PRIVATE_RENDER_INFRASTRUCTURE_FAILURE_CODES = frozenset(
    {
        "diagram_evaluation_timeout",
        "diagram_evaluation_error",
        "diagram_evaluation_transport_unavailable",
    }
)

FailureKind = Literal["quality", "infrastructure"]


class FailureDetail(TypedDict):
    kind: FailureKind
    code: str
    message: str
    blocking: bool
    retryable: bool


class GraphDomState(TypedDict):
    node_ids: list[str]
    edges: list[dict[str, str]]
    version: str | None


class BrowserInfrastructureError(RuntimeError):
    """A typed browser/auth/provider failure with an explicit retry policy."""

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class BrowserQualityError(RuntimeError):
    """A deterministic browser or product failure that must not be retried."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real frontend journeys in Playwright"
    )
    parser.add_argument("--suite", required=True)
    parser.add_argument(
        "--target", required=True, help="Frontend URL to open in Chromium"
    )
    parser.add_argument("--backend-target", default=os.getenv("EVAL_BACKEND_URL", ""))
    parser.add_argument("--email", default=os.getenv("EVAL_EMAIL", ""))
    parser.add_argument(
        "--internal-password", default=os.getenv("EVAL_INTERNAL_PASSWORD", "")
    )
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


async def _internal_session(
    backend_target: str, email: str, password: str
) -> dict[str, Any]:
    if not backend_target or not email or not password:
        raise RuntimeError(
            "browser eval requires --backend-target, --email, and --internal-password"
        )
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
        await page.screenshot(
            path=artifact_dir / "browser-bootstrap-failure.png", full_page=True
        )
    except Exception as exc:
        screenshot_error = f"{type(exc).__name__}: {exc}"

    trace_error = ""
    raw_trace = artifact_dir / ".playwright-trace.bootstrap.raw.zip"
    try:
        await context.tracing.stop(path=raw_trace)
        _redact_trace(
            raw_trace,
            artifact_dir / "playwright-trace.zip",
            [
                session.get("access_token", ""),
                session.get("refresh_token", ""),
                internal_password,
            ],
        )
    except Exception as exc:
        trace_error = f"{type(exc).__name__}: {exc}"
    finally:
        raw_trace.unlink(missing_ok=True)

    auth_overlay_visible = False
    try:
        auth_overlay_visible = await page.get_by_role(
            "heading", name="Sign in"
        ).is_visible()
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
    serialized_diagnostics = (
        json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n"
    )
    for secret in (
        session.get("access_token", ""),
        session.get("refresh_token", ""),
        internal_password,
    ):
        if secret:
            serialized_diagnostics = serialized_diagnostics.replace(
                secret, "[REDACTED]"
            )
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
            frames.append(
                {
                    "direction": direction,
                    "message": message,
                    "at": time.time(),
                    "at_monotonic": time.monotonic(),
                }
            )

    socket.on("framesent", lambda payload: record("sent", payload))
    socket.on("framereceived", lambda payload: record("received", payload))


async def _set_modes(page: Page, case: EvaluationCase, step_index: int) -> None:
    mode = case.steps[step_index].ui
    await page.get_by_label("Message options").click()
    await (
        page.get_by_role("radiogroup", name="complexity")
        .get_by_role("radio", name=mode.complexity)
        .click()
    )
    await (
        page.get_by_role("radiogroup", name="graph")
        .get_by_role("radio", name=mode.graph_mode)
        .click()
    )
    research = page.get_by_role("switch", name="research")
    checked = await research.get_attribute("aria-checked") == "true"
    if checked != mode.research_enabled:
        await research.click()
    await page.get_by_label("Message options").click()


async def _send_step(
    page: Page,
    case: EvaluationCase,
    step_index: int,
    frames: list[dict[str, Any]],
    *,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    start = len(frames)
    graph_deadline_started_s = time.monotonic()
    try:
        await _set_modes(page, case, step_index)
        textarea = page.get_by_placeholder(re.compile(r"Ask a question"))
        await textarea.fill(case.steps[step_index].prompt)
        await page.get_by_label("Send message").click()
        await page.get_by_label("Stop generation").wait_for(
            state="visible", timeout=20_000
        )
    except PlaywrightError as exc:
        raise BrowserQualityError(
            "browser_ui_interaction_failed",
            f"case {case.id} turn {step_index + 1} browser interaction failed: "
            f"{type(exc).__name__}: {exc}",
        ) from exc

    completion_task = asyncio.create_task(
        page.get_by_label("Send message").wait_for(
            state="visible",
            timeout=timeout_seconds * 1000,
        )
    )
    graph_deadline_task: asyncio.Task[None] | None = None
    graph_limit_ms = case.steps[step_index].graph_output_max_latency_ms
    try:
        if graph_limit_ms is not None:
            graph_deadline_s = graph_deadline_started_s + graph_limit_ms / 1000
            graph_deadline_task = asyncio.create_task(
                asyncio.sleep(max(0.0, graph_deadline_s - time.monotonic()))
            )
            completed, _ = await asyncio.wait(
                {completion_task, graph_deadline_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if graph_deadline_task in completed and not completion_task.done():
                received_frames = [
                    frame
                    for frame in frames[start:]
                    if frame["direction"] == "received"
                ]
                timely_graph = any(
                    frame["message"].get("type") in {"graph_preview", "graph_data"}
                    and isinstance(frame["message"].get("data"), dict)
                    and (
                        not isinstance(frame.get("at_monotonic"), (int, float))
                        or frame["at_monotonic"] <= graph_deadline_s
                    )
                    for frame in received_frames
                )
                if not timely_graph:
                    received_events = [frame["message"] for frame in received_frames]
                    try:
                        await page.get_by_label("Stop generation").click()
                    except PlaywrightError:
                        pass
                    private_render_failure_code = (
                        _private_render_infrastructure_failure_code(
                            True,
                            None,
                            received_events,
                        )
                    )
                    if private_render_failure_code is not None:
                        raise BrowserInfrastructureError(
                            private_render_failure_code,
                            f"case {case.id} turn {step_index + 1} required a graph but "
                            "private browser rendering did not complete",
                        )
                    errors = "; ".join(
                        str(event.get("content") or "")
                        for event in received_events
                        if event.get("type") == "error"
                    )
                    if errors and re.search(r"\bresponse timed out\b", errors, re.I):
                        raise BrowserInfrastructureError(
                            "application_response_timeout",
                            f"case {case.id} turn {step_index + 1} exceeded the "
                            f"backend response SLA: {errors}",
                            retryable=False,
                        )
                    if errors and _PROVIDER_OR_TRANSPORT_FAILURE.search(errors):
                        raise BrowserInfrastructureError(
                            "provider_or_transport_failed",
                            f"case {case.id} turn {step_index + 1} failed before "
                            f"completion: {errors}",
                        )
                    if errors:
                        raise BrowserQualityError(
                            "unexpected_backend_error",
                            f"case {case.id} turn {step_index + 1} returned an "
                            f"unexpected backend error: {errors}",
                        )
                    raise BrowserQualityError(
                        "required_graph_slow",
                        f"case {case.id} turn {step_index + 1} received no visible "
                        f"graph output within {graph_limit_ms} ms",
                    )
        await completion_task
    except PlaywrightTimeoutError as exc:
        raise BrowserInfrastructureError(
            "application_turn_timeout",
            f"application turn timed out: case {case.id} turn {step_index + 1} exceeded "
            f"the {timeout_seconds}s application deadline",
            retryable=False,
        ) from exc
    except PlaywrightError as exc:
        message = f"{type(exc).__name__}: {exc}"
        if _PROVIDER_OR_TRANSPORT_FAILURE.search(message):
            raise BrowserInfrastructureError(
                "browser_transport_failed", message
            ) from exc
        raise BrowserQualityError(
            "browser_ui_interaction_failed",
            f"case {case.id} turn {step_index + 1} completion UI failed: {message}",
        ) from exc
    finally:
        for task in (completion_task, graph_deadline_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(
                task
                for task in (completion_task, graph_deadline_task)
                if task is not None
            ),
            return_exceptions=True,
        )
    step_frames = [
        frame for frame in frames[start:] if frame["direction"] == "received"
    ]
    events = [frame["message"] for frame in step_frames]
    if not any(event.get("type") == "done" for event in events):
        errors = "; ".join(
            str(event.get("content") or "")
            for event in events
            if event.get("type") == "error"
        )
        if errors and re.search(r"\bresponse timed out\b", errors, re.I):
            raise BrowserInfrastructureError(
                "application_response_timeout",
                f"case {case.id} turn {step_index + 1} exceeded the backend response SLA: "
                f"{errors}",
                retryable=False,
            )
        if errors and _PROVIDER_OR_TRANSPORT_FAILURE.search(errors):
            raise BrowserInfrastructureError(
                "provider_or_transport_failed",
                f"case {case.id} turn {step_index + 1} failed before completion: "
                f"{errors}",
            )
        raise BrowserQualityError(
            "websocket_done_missing",
            f"case {case.id} turn {step_index + 1} did not receive a WebSocket done event",
        )
    return events


def _required_graph_turn_failure(
    case: EvaluationCase,
    step_index: int,
    events: list[dict[str, Any]],
    seen_versions: set[str] | None = None,
) -> tuple[str, str] | None:
    if (
        case.deterministic.graph_emitted is not True
        or case.steps[step_index].ui.graph_mode != "on"
    ):
        return None
    if any(event.get("type") == "graph_notice" for event in events):
        return (
            "required_graph_withheld",
            f"case {case.id} turn {step_index + 1} required a graph but received "
            "graph_notice",
        )
    graph = _extract_public_graph_data(events)
    if not graph:
        return (
            "required_graph_missing",
            f"case {case.id} turn {step_index + 1} required graph_data",
        )
    version = graph.get("version")
    if not isinstance(version, str) or not version.strip():
        return (
            "required_graph_version_missing",
            f"case {case.id} turn {step_index + 1} graph_data has no version",
        )
    if seen_versions is not None and version in seen_versions:
        return (
            "required_graph_version_reused",
            f"case {case.id} turn {step_index + 1} reused graph version {version}",
        )
    return None


def _extract_public_graph_data(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") == "graph_data":
            data = event.get("data")
            if isinstance(data, dict):
                return data
    return None


def _graph_expansion_failure(
    previous_graph: dict[str, Any],
    current_graph: dict[str, Any],
    *,
    anchor_label_contains: str,
) -> tuple[str, str] | None:
    if current_graph.get("title") != previous_graph.get("title"):
        return (
            "graph_expansion_topic_changed",
            "graph expansion changed the prior graph title",
        )
    previous_nodes = {
        str(node.get("id") or ""): node for node in previous_graph.get("nodes") or []
    }
    current_nodes = {
        str(node.get("id") or ""): node for node in current_graph.get("nodes") or []
    }
    previous_node_ids = set(previous_nodes)
    current_node_ids = set(current_nodes)
    missing_nodes = previous_node_ids - current_node_ids
    if missing_nodes:
        return (
            "graph_expansion_prior_node_missing",
            "graph expansion removed a prior node",
        )
    if any(current_nodes[node_id] != node for node_id, node in previous_nodes.items()):
        return (
            "graph_expansion_prior_node_changed",
            "graph expansion changed a prior component record",
        )

    record_identity = lambda record: json.dumps(  # noqa: E731
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    previous_edges = Counter(
        record_identity(edge) for edge in previous_graph.get("edges") or []
    )
    current_edges = Counter(
        record_identity(edge) for edge in current_graph.get("edges") or []
    )
    if previous_edges - current_edges:
        return (
            "graph_expansion_prior_edge_missing",
            "graph expansion removed a prior edge",
        )

    current_groups = {
        str(group.get("id") or ""): group for group in current_graph.get("groups") or []
    }
    for previous_group in previous_graph.get("groups") or []:
        group_id = str(previous_group.get("id") or "")
        current_group = current_groups.get(group_id)
        if current_group is None:
            return (
                "graph_expansion_prior_group_missing",
                "graph expansion removed a prior group",
            )
        previous_members = set(previous_group.get("nodeIds") or [])
        current_members = set(current_group.get("nodeIds") or [])
        previous_metadata = {
            key: value for key, value in previous_group.items() if key != "nodeIds"
        }
        current_metadata = {
            key: value for key, value in current_group.items() if key != "nodeIds"
        }
        if previous_metadata != current_metadata or not previous_members.issubset(
            current_members
        ):
            return (
                "graph_expansion_prior_group_changed",
                "graph expansion changed a prior group or membership",
            )

    previous_sequence = [
        record_identity(item) for item in previous_graph.get("sequence") or []
    ]
    current_sequence = [
        record_identity(item) for item in current_graph.get("sequence") or []
    ]
    sequence_cursor = iter(current_sequence)
    if any(
        not any(candidate == item for candidate in sequence_cursor)
        for item in previous_sequence
    ):
        return (
            "graph_expansion_prior_sequence_changed",
            "graph expansion changed the prior sequence",
        )
    previous_assumptions = Counter(
        record_identity(item) for item in previous_graph.get("assumptions") or []
    )
    current_assumptions = Counter(
        record_identity(item) for item in current_graph.get("assumptions") or []
    )
    if previous_assumptions - current_assumptions:
        return (
            "graph_expansion_prior_assumption_missing",
            "graph expansion removed a prior assumption",
        )
    added_node_ids = current_node_ids - previous_node_ids
    if len(added_node_ids) != 1:
        return (
            "graph_expansion_added_node_count_mismatch",
            f"graph expansion added {len(added_node_ids)} nodes; expected 1",
        )
    added_node_id = next(iter(added_node_ids))
    anchor_text = anchor_label_contains.casefold()
    anchor_node_ids = {
        node_id
        for node_id, node in previous_nodes.items()
        if anchor_text in str(node.get("label") or "").casefold()
    }
    if not anchor_node_ids:
        return (
            "graph_expansion_anchor_missing",
            f"prior graph has no component matching {anchor_label_contains!r}",
        )
    connected = any(
        (
            str(edge.get("source") or "") == added_node_id
            and str(edge.get("target") or "") in anchor_node_ids
        )
        or (
            str(edge.get("target") or "") == added_node_id
            and str(edge.get("source") or "") in anchor_node_ids
        )
        for edge in current_graph.get("edges") or []
    )
    if not connected:
        return (
            "graph_expansion_new_node_not_connected",
            "graph expansion did not connect the new node to the requested prior component",
        )
    return None


async def _required_graph_turn_render_failure(
    page: Page | None,
    case: EvaluationCase,
    step_index: int,
    events: list[dict[str, Any]],
) -> tuple[str, str] | None:
    if (
        page is None
        or not case.deterministic.graph_renderable
        or case.deterministic.graph_emitted is not True
        or case.steps[step_index].ui.graph_mode != "on"
    ):
        return None
    graph = _extract_public_graph_data(events)
    if not graph:
        return None
    dom = await _graph_dom_state(page, graph)
    expected_nodes = len(graph.get("nodes") or [])
    expected_edges = len(graph.get("edges") or [])
    if len(dom["node_ids"]) != expected_nodes:
        return (
            "required_graph_turn_render_mismatch",
            f"case {case.id} turn {step_index + 1} rendered {len(dom['node_ids'])} "
            f"nodes for a {expected_nodes}-node graph",
        )
    if len(dom["edges"]) != expected_edges:
        return (
            "required_graph_turn_edge_render_mismatch",
            f"case {case.id} turn {step_index + 1} rendered {len(dom['edges'])} "
            f"edges for a {expected_edges}-edge graph",
        )
    expected_node_ids = sorted(
        str(node.get("id") or "") for node in (graph.get("nodes") or [])
    )
    if sorted(dom["node_ids"]) != expected_node_ids:
        return (
            "required_graph_turn_node_identity_mismatch",
            f"case {case.id} turn {step_index + 1} rendered the wrong node identities",
        )
    expected_edge_identities = sorted(
        (
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
            str(edge.get("label") or ""),
        )
        for edge in (graph.get("edges") or [])
    )
    rendered_edge_identities = sorted(
        (edge["source"], edge["target"], edge["label"]) for edge in dom["edges"]
    )
    if rendered_edge_identities != expected_edge_identities:
        return (
            "required_graph_turn_edge_identity_mismatch",
            f"case {case.id} turn {step_index + 1} rendered the wrong edge identities",
        )
    graph_version = graph.get("version")
    if graph_version and dom["version"] != graph_version:
        return (
            "required_graph_turn_version_mismatch",
            f"case {case.id} turn {step_index + 1} did not render graph version "
            f"{graph_version}",
        )
    return None


def _should_inspect_graph_dom(
    case: EvaluationCase,
    graph: dict[str, Any] | None,
) -> bool:
    return bool(graph) and case.deterministic.graph_renderable is True


async def _graph_dom_state(
    page: Page,
    graph: dict[str, Any] | None,
) -> GraphDomState:
    graph_version = graph.get("version") if isinstance(graph, dict) else None
    wait_for_function = getattr(page, "wait_for_function", None)
    if graph_version and callable(wait_for_function):
        expected_version_js = json.dumps(graph_version)
        try:
            await wait_for_function(
                f"""() => document.querySelector('[data-testid="graph-canvas"]')"""
                f"""?.getAttribute('data-rendered-graph-version') === {expected_version_js}""",
                timeout=10_000,
            )
        except PlaywrightTimeoutError:
            pass
    canvas = page.locator('[data-testid="graph-canvas"]')
    node_ids = await canvas.locator("g.node").evaluate_all(
        "elements => elements.map(element => element.getAttribute('data-node-id') || '')"
    )
    edges = await canvas.locator("path.edge-vis").evaluate_all(
        """elements => elements.map(element => ({
            source: element.getAttribute('data-source-id') || '',
            target: element.getAttribute('data-target-id') || '',
            label: element.getAttribute('data-edge-label') || '',
        }))"""
    )
    return {
        "node_ids": node_ids,
        "edges": edges,
        "version": await canvas.get_attribute("data-rendered-graph-version"),
    }


async def _send_case_steps(
    page: Page,
    case: EvaluationCase,
    frames: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    timeout_seconds: int,
    turn_timings: list[dict[str, Any]] | None = None,
    turn_graphs: list[dict[str, Any]] | None = None,
) -> None:
    """Run a case's conversation turns in order on the same page and thread."""
    seen_graph_versions: set[str] = set()
    previous_turn_graph: dict[str, Any] | None = None
    for step_index in range(len(case.steps)):
        frame_start = len(frames)
        turn_started = time.monotonic()
        turn_started_at = time.time()
        step_events: list[dict[str, Any]] = []
        graph_output_latency_ms: int | None = None
        try:
            received_events = await _send_step(
                page,
                case,
                step_index,
                frames,
                timeout_seconds=timeout_seconds,
            )
            step_events = [
                {**event, "eval_turn": step_index + 1} for event in received_events
            ]
            events.extend(step_events)
        finally:
            step_frames = frames[frame_start:]
            if not step_events:
                events.extend(
                    {**frame["message"], "eval_turn": step_index + 1}
                    for frame in step_frames
                    if frame["direction"] == "received"
                )
            received = [
                frame for frame in step_frames if frame["direction"] == "received"
            ]
            first_graph_output = next(
                (
                    frame
                    for frame in received
                    if frame["message"].get("type") in {"graph_preview", "graph_data"}
                    and isinstance(frame["message"].get("data"), dict)
                ),
                None,
            )
            if first_graph_output is not None:
                graph_output_latency_ms = max(
                    0,
                    int((first_graph_output["at"] - turn_started_at) * 1000),
                )
            elif _extract_public_graph_data(step_events) is not None:
                # Unit-level transports may return events without timestamped
                # frames. Completion time is a conservative fallback.
                graph_output_latency_ms = int((time.monotonic() - turn_started) * 1000)
            if turn_timings is not None:
                sent_start = next(
                    (
                        frame
                        for frame in step_frames
                        if frame["direction"] == "sent"
                        and frame["message"].get("type") == "start"
                    ),
                    None,
                )
                first_visible_content = next(
                    (
                        frame
                        for frame in received
                        if frame["message"].get("type")
                        in {
                            "explanation_block",
                            "graph_data",
                            "graph_preview",
                            "response_delta",
                        }
                    ),
                    None,
                )
                request_id = next(
                    (
                        frame["message"].get("request_id")
                        for frame in received
                        if frame["message"].get("request_id")
                    ),
                    None,
                )
                turn_timings.append(
                    {
                        "turn": step_index + 1,
                        "started_at_epoch": turn_started_at,
                        "latency_ms": int((time.monotonic() - turn_started) * 1000),
                        "first_event_ms": (
                            int((received[0]["at"] - turn_started_at) * 1000)
                            if received
                            else None
                        ),
                        "first_token_ms": (
                            int((first_visible_content["at"] - turn_started_at) * 1000)
                            if first_visible_content
                            else None
                        ),
                        "graph_output_latency_ms": graph_output_latency_ms,
                        "client_request_id": (
                            sent_start["message"].get("client_request_id")
                            if sent_start
                            else None
                        ),
                        "request_id": request_id,
                    }
                )
        if not case.deterministic.error_expected:
            unexpected_errors = [
                str(event.get("content") or event.get("message") or "unknown error")
                for event in step_events
                if event.get("type") == "error"
            ]
            if unexpected_errors:
                message = "; ".join(unexpected_errors)
                if re.search(r"\bresponse timed out\b", message, re.I):
                    raise BrowserInfrastructureError(
                        "application_response_timeout",
                        f"case {case.id} turn {step_index + 1} exceeded the "
                        f"backend response SLA: {message}",
                        retryable=False,
                    )
                if _PROVIDER_OR_TRANSPORT_FAILURE.search(message):
                    raise BrowserInfrastructureError(
                        "provider_or_transport_failed",
                        f"case {case.id} turn {step_index + 1} returned an "
                        f"unexpected backend error: {message}",
                    )
                raise BrowserQualityError(
                    "unexpected_backend_error",
                    f"case {case.id} turn {step_index + 1} returned an "
                    f"unexpected backend error: {message}",
                )
        if not case.deterministic.provider_fallback_allowed and any(
            event.get("type") == "provider_switch" for event in step_events
        ):
            raise BrowserQualityError(
                "provider_fallback_used",
                f"case {case.id} turn {step_index + 1} used a provider fallback",
            )
        graph_failure = _required_graph_turn_failure(
            case,
            step_index,
            step_events,
            seen_graph_versions,
        )
        if graph_failure is not None:
            private_render_failure_code = _private_render_infrastructure_failure_code(
                True,
                _extract_public_graph_data(step_events),
                step_events,
            )
            if private_render_failure_code is not None:
                raise BrowserInfrastructureError(
                    private_render_failure_code,
                    f"case {case.id} turn {step_index + 1} required a graph but "
                    "private browser rendering did not complete",
                )
            raise BrowserQualityError(*graph_failure)
        graph_output_max_latency_ms = case.steps[step_index].graph_output_max_latency_ms
        if (
            graph_output_max_latency_ms is not None
            and graph_output_latency_ms is not None
            and graph_output_latency_ms > graph_output_max_latency_ms
        ):
            raise BrowserQualityError(
                "required_graph_slow",
                f"case {case.id} turn {step_index + 1} received visible graph output after "
                f"{graph_output_latency_ms} ms; limit is {graph_output_max_latency_ms} ms",
            )
        turn_graph = _extract_public_graph_data(step_events)
        if turn_graph and isinstance(turn_graph.get("version"), str):
            seen_graph_versions.add(turn_graph["version"])
        try:
            render_failure = await _required_graph_turn_render_failure(
                page,
                case,
                step_index,
                step_events,
            )
        except Exception as exc:
            raise BrowserInfrastructureError(
                "graph_dom_inspection_failed",
                f"case {case.id} turn {step_index + 1} graph DOM inspection "
                f"failed: {type(exc).__name__}: {exc}",
            ) from exc
        if render_failure is not None:
            raise BrowserQualityError(*render_failure)
        if case.steps[step_index].graph_expansion is not None:
            if previous_turn_graph is None or turn_graph is None:
                raise BrowserQualityError(
                    "graph_expansion_baseline_missing",
                    f"case {case.id} turn {step_index + 1} has no prior graph baseline",
                )
            expansion_failure = _graph_expansion_failure(
                previous_turn_graph,
                turn_graph,
                anchor_label_contains=(
                    case.steps[
                        step_index
                    ].graph_expansion.new_node_connected_to_prior_label_contains
                ),
            )
            if expansion_failure is not None:
                raise BrowserQualityError(*expansion_failure)
        if turn_graph is not None:
            previous_turn_graph = turn_graph
        if turn_graphs is not None and turn_graph:
            dom = await _graph_dom_state(page, turn_graph)
            turn_graphs.append(
                {
                    "turn": step_index + 1,
                    "graph": turn_graph,
                    "rendered_graph_version": dom["version"],
                    "rendered_node_ids": dom["node_ids"],
                    "rendered_edge_identities": dom["edges"],
                }
            )


def _thread_id(frames: list[dict[str, Any]]) -> str | None:
    for frame in reversed(frames):
        message = frame["message"]
        if frame["direction"] == "sent" and message.get("type") == "start":
            return message.get("thread_id")
    return None


def _failure_detail(
    kind: FailureKind,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> FailureDetail:
    return {
        "kind": kind,
        "code": code,
        "message": message,
        "blocking": True,
        "retryable": retryable,
    }


async def _node_followup_interaction_failure_details(
    page: Any,
    case: EvaluationCase,
    graph: dict[str, Any] | None,
    existing_failure_details: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if case.id != "node-followup" or graph is None or existing_failure_details:
        return []

    try:
        # Use the same accessible activation path available to keyboard users
        # and prove the optional refinement starts.
        first_node = page.get_by_role("button", name=re.compile(r"^Explore ")).first
        async with page.expect_request(
            lambda request: (
                request.method == "POST"
                and request.url.rstrip("/").endswith("/api/node-selected")
            ),
            timeout=10_000,
        ):
            await first_node.press("Enter", timeout=10_000)
        await page.locator('[data-testid="suggested-question"]').first.wait_for(
            timeout=10_000
        )
    except Exception as exc:
        return [
            _failure_detail(
                "quality",
                "node_followup_interaction_failed",
                f"node follow-up interaction failed: {type(exc).__name__}: {exc}",
            )
        ]
    return []


def _deterministic_failure_details(
    case: EvaluationCase,
    events: list[dict[str, Any]],
    rendered_nodes: int,
    rendered_edges: int | None = None,
    rendered_graph_version: str | None = None,
    rendered_node_ids: list[str] | None = None,
    rendered_edge_identities: list[dict[str, str]] | None = None,
) -> list[FailureDetail]:
    expected = case.deterministic
    failures: list[FailureDetail] = []
    errors = [
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "error"
    ]
    error_message = "unexpected error events: " + "; ".join(errors)
    if bool(
        errors
    ) != expected.error_expected and _PROVIDER_OR_TRANSPORT_FAILURE.search(
        error_message
    ):
        # The provider/transport failure is the root cause of any downstream
        # missing worker, graph, or completion assertions in this attempt.
        return [
            _failure_detail(
                "infrastructure",
                "unexpected_error_event",
                error_message,
                retryable=True,
            )
        ]
    research_unavailable = any(
        event.get("type") == "worker_status"
        and event.get("worker") == "research"
        and "unavailable" in str(event.get("status") or "").lower()
        for event in events
    )
    if (
        expected.citations_required
        and expected.citation_source == "web"
        and research_unavailable
    ):
        return [
            _failure_detail(
                "infrastructure",
                "research_unavailable",
                "research infrastructure unavailable: no citable web sources",
                retryable=True,
            )
        ]
    graph = _extract_public_graph_data(events)
    private_render_failure_code = _private_render_infrastructure_failure_code(
        expected.graph_emitted is True,
        graph,
        events,
    )
    if private_render_failure_code is not None:
        return [
            _failure_detail(
                "infrastructure",
                private_render_failure_code,
                "private browser rendering did not complete; required graph_data was withheld",
                retryable=True,
            )
        ]
    workers = extract_workers(events)
    observed_status = (
        200 if any(event.get("type") == "done" for event in events) else 500
    )
    if observed_status != expected.status:
        failures.append(
            _failure_detail(
                "quality",
                "status_mismatch",
                f"status expected {expected.status}, got {observed_status}",
            )
        )
    for worker in expected.workers_include:
        if worker not in workers:
            failures.append(
                _failure_detail(
                    "quality", "missing_worker", f"missing worker: {worker}"
                )
            )
    for worker in expected.workers_exclude:
        if worker in workers:
            failures.append(
                _failure_detail(
                    "quality",
                    "unexpected_worker",
                    f"unexpected worker: {worker}",
                )
            )
    if expected.route and detect_route(events) != expected.route:
        failures.append(
            _failure_detail(
                "quality",
                "route_mismatch",
                f"route expected {expected.route}, got {detect_route(events)}",
            )
        )
    if expected.graph_emitted is not None and bool(graph) != expected.graph_emitted:
        failures.append(
            _failure_detail(
                "quality",
                "graph_emission_mismatch",
                f"graph_emitted expected {expected.graph_emitted}, got {bool(graph)}",
            )
        )
    if (
        expected.graph_renderable
        and graph
        and rendered_nodes != len(graph.get("nodes") or [])
    ):
        failures.append(
            _failure_detail(
                "quality",
                "graph_render_mismatch",
                f"browser rendered {rendered_nodes} of {len(graph.get('nodes') or [])} graph nodes",
            )
        )
    if (
        expected.graph_renderable
        and graph
        and rendered_edges is not None
        and rendered_edges != len(graph.get("edges") or [])
    ):
        failures.append(
            _failure_detail(
                "quality",
                "graph_edge_render_mismatch",
                f"browser rendered {rendered_edges} of "
                f"{len(graph.get('edges') or [])} graph edges",
            )
        )
    if expected.graph_renderable and graph:
        graph_version = graph.get("version")
        if not isinstance(graph_version, str) or not graph_version.strip():
            failures.append(
                _failure_detail(
                    "quality",
                    "graph_version_missing",
                    "renderable graph_data has no graph version",
                )
            )
        elif rendered_graph_version != graph_version:
            failures.append(
                _failure_detail(
                    "quality",
                    "graph_version_render_mismatch",
                    f"browser rendered graph version {rendered_graph_version!r}, expected "
                    f"{graph_version!r}",
                )
            )
    if expected.graph_renderable and graph and rendered_node_ids is not None:
        expected_node_ids = sorted(
            str(node.get("id") or "") for node in (graph.get("nodes") or [])
        )
        if sorted(rendered_node_ids) != expected_node_ids:
            failures.append(
                _failure_detail(
                    "quality",
                    "graph_node_identity_mismatch",
                    "browser rendered node identities from a different graph",
                )
            )
    if expected.graph_renderable and graph and rendered_edge_identities is not None:
        expected_edges = sorted(
            (
                str(edge.get("source") or ""),
                str(edge.get("target") or ""),
                str(edge.get("label") or ""),
            )
            for edge in (graph.get("edges") or [])
        )
        rendered_edges_identity = sorted(
            (edge["source"], edge["target"], edge["label"])
            for edge in rendered_edge_identities
        )
        if rendered_edges_identity != expected_edges:
            failures.append(
                _failure_detail(
                    "quality",
                    "graph_edge_identity_mismatch",
                    "browser rendered edge identities from a different graph",
                )
            )
    if expected.streaming_complete and not any(
        event.get("type") == "done" for event in events
    ):
        failures.append(
            _failure_detail(
                "quality",
                "stream_incomplete",
                "stream did not complete",
            )
        )
    if bool(errors) != expected.error_expected:
        failures.append(
            _failure_detail(
                "quality",
                "unexpected_error_event",
                error_message,
            )
        )
    answer = extract_response_text(events)
    if expected.citations_required:
        if expected.citation_source == "web":
            supplied_sources: set[str] = set()
            for event in events:
                if (
                    event.get("type") != "worker_status"
                    or event.get("worker") != "research"
                ):
                    continue
                sources = event.get("sources")
                if not isinstance(sources, list):
                    continue
                supplied_sources.update(
                    source
                    for source in sources
                    if isinstance(source, str)
                    and source.startswith(("http://", "https://"))
                )
            if not supplied_sources:
                failures.append(
                    _failure_detail(
                        "quality",
                        "research_provenance_missing",
                        "research completed without source provenance telemetry",
                    )
                )
            elif not any(source in answer for source in supplied_sources):
                failures.append(
                    _failure_detail(
                        "quality",
                        "web_citation_mismatch",
                        "required web citation did not match supplied research evidence",
                    )
                )
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
                failures.append(
                    _failure_detail(
                        "quality",
                        "book_citation_missing",
                        "required chapter-and-page citation was not visible in the answer",
                    )
                )
            elif not supplied_book_refs:
                failures.append(
                    _failure_detail(
                        "quality",
                        "book_provenance_missing",
                        "book retrieval completed without source provenance telemetry",
                    )
                )
            elif not cited_book_refs.issubset(supplied_book_refs):
                failures.append(
                    _failure_detail(
                        "quality",
                        "book_citation_mismatch",
                        "book citation did not match supplied retrieval evidence",
                    )
                )
    return failures


def _private_render_infrastructure_failure_code(
    required_graph: bool,
    graph: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> str | None:
    if not required_graph or graph is not None:
        return None
    for event in reversed(events):
        if event.get("type") != "workflow_progress":
            continue
        failure_code = event.get("failure_code")
        if failure_code in _PRIVATE_RENDER_INFRASTRUCTURE_FAILURE_CODES:
            return failure_code
    return None


def _deterministic_failures(
    case: EvaluationCase,
    events: list[dict[str, Any]],
    rendered_nodes: int,
    rendered_edges: int | None = None,
    rendered_graph_version: str | None = None,
    rendered_node_ids: list[str] | None = None,
    rendered_edge_identities: list[dict[str, str]] | None = None,
) -> list[str]:
    """Retain the v1 string contract while emitting typed details in captures."""
    return [
        failure["message"]
        for failure in _deterministic_failure_details(
            case,
            events,
            rendered_nodes,
            rendered_edges,
            rendered_graph_version,
            rendered_node_ids,
            rendered_edge_identities,
        )
    ]


def _should_retry(result: dict[str, Any]) -> bool:
    failures = [
        detail
        for detail in result.get("failure_details") or []
        if detail.get("blocking", True)
    ]
    return (
        bool(failures)
        and all(detail.get("kind") == "infrastructure" for detail in failures)
        and any(detail.get("retryable") is True for detail in failures)
    )


def _exception_failure_detail(exc: Exception) -> FailureDetail:
    """Classify only explicit transient failures as retryable infrastructure."""
    if isinstance(exc, BrowserInfrastructureError):
        return _failure_detail(
            "infrastructure",
            exc.code,
            str(exc),
            retryable=exc.retryable,
        )
    if isinstance(exc, BrowserQualityError):
        return _failure_detail("quality", exc.code, str(exc))

    message = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, PlaywrightError) and _PROVIDER_OR_TRANSPORT_FAILURE.search(
        message
    ):
        return _failure_detail(
            "infrastructure",
            "browser_transport_failed",
            message,
            retryable=True,
        )
    return _failure_detail("quality", "browser_attempt_exception", message)


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


async def _run_cases_bounded(
    cases: list[EvaluationCase],
    *,
    max_concurrency: int,
    run_case: Callable[[EvaluationCase], Awaitable[dict[str, Any]]],
    graph_max_concurrency: int = 1,
    on_result: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """Run isolated cases concurrently without letting graph work monopolise capacity."""
    if max_concurrency <= 0:
        raise ValueError("browser case concurrency must be positive")
    if graph_max_concurrency <= 0 or graph_max_concurrency > max_concurrency:
        raise ValueError(
            "graph case concurrency must be positive and no greater than total"
        )

    semaphore = asyncio.Semaphore(max_concurrency)
    graph_semaphore = asyncio.Semaphore(graph_max_concurrency)
    ordered: list[dict[str, Any] | None] = [None] * len(cases)
    recorded_indices: set[int] = set()

    async def run_indexed(
        index: int, case: EvaluationCase
    ) -> tuple[int, dict[str, Any]]:
        if case.deterministic.graph_emitted is True:
            # Take the scarce graph lane first. A graph task waiting for that lane
            # must not occupy a general slot that a lightweight task can use.
            async with graph_semaphore:
                async with semaphore:
                    return index, await run_case(case)
        async with semaphore:
            return index, await run_case(case)

    tasks = [
        asyncio.create_task(run_indexed(index, case))
        for index, case in enumerate(cases)
    ]
    try:
        for completed in asyncio.as_completed(tasks):
            index, result = await completed
            ordered[index] = result
            recorded_indices.add(index)
            if on_result is not None:
                await on_result([item for item in ordered if item is not None])
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        recovered_result = False
        for outcome in outcomes:
            if (
                isinstance(outcome, tuple)
                and len(outcome) == 2
                and isinstance(outcome[0], int)
                and isinstance(outcome[1], dict)
                and outcome[0] not in recorded_indices
            ):
                ordered[outcome[0]] = outcome[1]
                recovered_result = True
        if on_result is not None and recovered_result:
            # Cancellation must not discard an attempt that completed its own
            # cleanup while the outer suite deadline was unwinding.
            await asyncio.shield(
                on_result([item for item in ordered if item is not None])
            )

    return [item for item in ordered if item is not None]


def _merge_attempt_results(
    previous: dict[str, Any], latest: dict[str, Any]
) -> dict[str, Any]:
    """Keep the latest outcome while retaining evidence from every case attempt."""
    previous_attempts = previous.get("attempts") or [previous]
    latest_attempts = latest.get("attempts") or [latest]
    attempts = [*previous_attempts, *latest_attempts]
    result = dict(latest)
    result["attempts"] = attempts
    result["attempt_count"] = len(attempts)
    result["retried"] = len(attempts) > 1
    result["thread_ids"] = list(
        dict.fromkeys(
            str(attempt["thread_id"])
            for attempt in attempts
            if attempt.get("thread_id")
        )
    )
    return result


async def _run_cases_with_deferred_retries(
    cases: list[EvaluationCase],
    *,
    max_concurrency: int,
    graph_max_concurrency: int,
    retry_count: int,
    run_attempt: Callable[[EvaluationCase, int], Awaitable[dict[str, Any]]],
    on_result: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """Prioritise first-pass corpus coverage before spending lanes on retries."""
    if retry_count < 0:
        raise ValueError("browser infrastructure retry count cannot be negative")
    case_order = {case.id: index for index, case in enumerate(cases)}
    current: dict[str, dict[str, Any]] = {}

    async def emit_checkpoint() -> None:
        if on_result is not None:
            await on_result(
                sorted(current.values(), key=lambda result: case_order[result["id"]])
            )

    async def run_batch(
        batch_cases: list[EvaluationCase], attempt_number: int
    ) -> list[dict[str, Any]]:
        base_results = dict(current)

        async def run_case(case: EvaluationCase) -> dict[str, Any]:
            return await _run_case_with_retries(
                case,
                retry_count=0,
                run_attempt=lambda attempted_case, _ignored: run_attempt(
                    attempted_case, attempt_number
                ),
            )

        async def update_batch(completed: list[dict[str, Any]]) -> None:
            for result in completed:
                previous = base_results.get(result["id"])
                current[result["id"]] = (
                    _merge_attempt_results(previous, result) if previous else result
                )
            await emit_checkpoint()

        return await _run_cases_bounded(
            batch_cases,
            max_concurrency=min(max_concurrency, len(batch_cases)),
            graph_max_concurrency=min(
                graph_max_concurrency, max_concurrency, len(batch_cases)
            ),
            run_case=run_case,
            on_result=update_batch,
        )

    await run_batch(cases, 1)
    for attempt_number in range(2, retry_count + 2):
        retry_cases = [case for case in cases if _should_retry(current[case.id])]
        if not retry_cases:
            break
        await run_batch(retry_cases, attempt_number)

    return sorted(current.values(), key=lambda result: case_order[result["id"]])


async def _run_case_with_retries(
    case: EvaluationCase,
    *,
    retry_count: int,
    run_attempt: Callable[[EvaluationCase, int], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Retry exactly the configured number of times, and only for infrastructure."""
    if retry_count < 0:
        raise ValueError("browser infrastructure retry count cannot be negative")

    attempts: list[dict[str, Any]] = []
    for attempt_number in range(1, retry_count + 2):
        attempt_started = time.monotonic()
        try:
            attempt = await run_attempt(case, attempt_number)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = _exception_failure_detail(exc)
            attempt = {
                "id": case.id,
                "category": case.category,
                "risk_tags": case.risk_tags,
                "attempt": attempt_number,
                "deterministic_failures": [detail["message"]],
                "failure_details": [detail],
                "answer": "",
                "turns": [],
                "events": [],
                "graph": None,
                "rendered_nodes": 0,
                "rendered_edges": 0,
                "rendered_graph_version": None,
                "rendered_node_ids": [],
                "rendered_edge_identities": [],
                "thread_id": None,
                "screenshot": None,
                "trace": None,
                "latency_ms": int((time.monotonic() - attempt_started) * 1000),
                "fallback_used": False,
                "passed": False,
            }
        attempts.append(attempt)
        if attempt.get("passed") or not _should_retry(attempt):
            break

    result = dict(attempts[-1])
    result["attempts"] = attempts
    result["attempt_count"] = len(attempts)
    result["retried"] = len(attempts) > 1
    result["thread_ids"] = [
        attempt["thread_id"] for attempt in attempts if attempt.get("thread_id")
    ]
    return result


async def _run_browser_attempt(
    browser: Browser,
    args: argparse.Namespace,
    case: EvaluationCase,
    *,
    artifact_dir: Path,
    screenshot_dir: Path,
    trace_dir: Path,
    turn_timeout_seconds: int,
    attempt_number: int,
) -> dict[str, Any]:
    """Run one journey attempt in an isolated authenticated browser context."""
    try:
        session = await _internal_session(
            args.backend_target, args.email, args.internal_password
        )
    except Exception as exc:
        raise BrowserInfrastructureError(
            "auth_bootstrap_failed",
            f"internal auth bootstrap failed: {type(exc).__name__}: {exc}",
        ) from exc
    frames: list[dict[str, Any]] = []
    try:
        context = await browser.new_context(viewport={"width": 1440, "height": 960})
        # The explicit full-page PNG is the visual review artifact. Continuous
        # trace screenshots during multi-minute model waits make captures huge
        # without adding useful timing evidence.
        await context.tracing.start(screenshots=False, snapshots=True, sources=True)
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
    except PlaywrightError as exc:
        if "context" in locals():
            await context.close()
        raise BrowserInfrastructureError(
            "browser_context_bootstrap_failed",
            f"browser context bootstrap failed: {type(exc).__name__}: {exc}",
        ) from exc
    page.on("websocket", lambda socket: _capture_socket(frames, socket))
    artifact_stem = f"{case.id}.attempt-{attempt_number}"
    raw_trace = artifact_dir / f".playwright-trace.{artifact_stem}.raw.zip"
    trace = trace_dir / f"{artifact_stem}.zip"

    case_started = time.monotonic()
    case_events: list[dict[str, Any]] = []
    turn_timings: list[dict[str, Any]] = []
    turn_graphs: list[dict[str, Any]] = []
    failure_details: list[FailureDetail] = []
    execution_state = "completed"
    try:
        try:
            try:
                await page.goto(
                    args.target, wait_until="domcontentloaded", timeout=60_000
                )
            except PlaywrightError as exc:
                raise BrowserInfrastructureError(
                    "browser_navigation_failed",
                    f"browser navigation failed: {type(exc).__name__}: {exc}",
                ) from exc
            if await page.get_by_role("heading", name="Sign in").is_visible():
                raise BrowserInfrastructureError(
                    "auth_session_rejected",
                    f"case {case.id} did not accept the internal session",
                )
            try:
                await _wait_for_composer_ready(page)
            except PlaywrightTimeoutError as exc:
                raise BrowserQualityError(
                    "composer_not_ready",
                    f"case {case.id} composer readiness UI timed out: "
                    f"{type(exc).__name__}: {exc}",
                ) from exc
            except PlaywrightError as exc:
                message = f"{type(exc).__name__}: {exc}"
                if _PROVIDER_OR_TRANSPORT_FAILURE.search(message):
                    raise BrowserInfrastructureError(
                        "browser_transport_failed", message
                    ) from exc
                raise BrowserQualityError(
                    "composer_not_ready",
                    f"case {case.id} composer was not ready: {message}",
                ) from exc
            except RuntimeError as exc:
                raise BrowserQualityError("composer_not_ready", str(exc)) from exc
            await _send_case_steps(
                page,
                case,
                frames,
                case_events,
                timeout_seconds=turn_timeout_seconds,
                turn_timings=turn_timings,
                turn_graphs=turn_graphs,
            )
        except asyncio.CancelledError:
            execution_state = "cancelled"
            failure_details.append(
                _failure_detail(
                    "infrastructure",
                    "browser_case_cancelled",
                    f"browser suite timed out and cancelled case {case.id}",
                )
            )
        except Exception as exc:
            failure_details.append(_exception_failure_detail(exc))

        graph = _extract_public_graph_data(case_events)
        rendered_nodes = 0
        rendered_edges = 0
        rendered_graph_version = None
        rendered_node_ids: list[str] = []
        rendered_edge_identities: list[dict[str, str]] = []
        if not failure_details and _should_inspect_graph_dom(case, graph):
            try:
                dom = await _graph_dom_state(page, graph)
                rendered_node_ids = dom["node_ids"]
                rendered_edge_identities = dom["edges"]
                rendered_nodes = len(rendered_node_ids)
                rendered_edges = len(rendered_edge_identities)
                rendered_graph_version = dom["version"]
            except Exception as exc:
                failure_details.append(
                    _failure_detail(
                        "infrastructure",
                        "graph_dom_inspection_failed",
                        f"graph DOM inspection failed: {type(exc).__name__}: {exc}",
                    )
                )
        if not failure_details:
            failure_details.extend(
                _deterministic_failure_details(
                    case,
                    case_events,
                    rendered_nodes,
                    rendered_edges,
                    rendered_graph_version,
                    rendered_node_ids,
                    rendered_edge_identities,
                )
            )
        failure_details.extend(
            await _node_followup_interaction_failure_details(
                page,
                case,
                graph,
                failure_details,
            )
        )
        evaluation_failed = bool(failure_details)
        screenshot = screenshot_dir / f"{artifact_stem}.png"
        screenshot_relative: str | None = None
        try:
            await page.screenshot(path=screenshot, full_page=True)
            screenshot_relative = str(screenshot.relative_to(artifact_dir))
        except Exception as exc:
            failure_details.append(
                _failure_detail(
                    "infrastructure",
                    "screenshot_failed",
                    f"screenshot failed: {type(exc).__name__}: {exc}",
                )
            )
        thread_id = _thread_id(frames)
        persisted = False
        persistence_error: Exception | None = None
        if thread_id and not evaluation_failed:
            try:
                thread = await asyncio.to_thread(
                    _blocking_json_request,
                    "GET",
                    args.backend_target.rstrip("/") + f"/api/threads/{thread_id}",
                    None,
                    session["access_token"],
                )
                persisted = len(thread.get("messages") or []) >= len(case.steps) * 2
            except Exception as exc:
                persistence_error = exc
        if case.deterministic.persistence and not evaluation_failed and not persisted:
            if persistence_error is not None:
                failure_details.append(
                    _failure_detail(
                        "infrastructure",
                        "persistence_check_failed",
                        "persistence check failed: "
                        f"{type(persistence_error).__name__}: {persistence_error}",
                    )
                )
            else:
                failure_details.append(
                    _failure_detail(
                        "quality",
                        "persistence_missing",
                        "conversation was not durably visible after streaming",
                    )
                )

        if thread_id and case.deterministic.cleanup:
            try:
                await _delete_thread(
                    args.backend_target,
                    session["access_token"],
                    thread_id,
                )
            except Exception as exc:
                failure_details.append(
                    _failure_detail(
                        "infrastructure",
                        "cleanup_failed",
                        f"cleanup failed: {type(exc).__name__}: {exc}",
                    )
                )

        answers = extract_response_turns(case_events)
        graph_evidence_by_turn = {
            int(item["turn"]): item
            for item in turn_graphs
            if isinstance(item.get("turn"), int)
        }
        deterministic = [failure["message"] for failure in failure_details]
        result = {
            "id": case.id,
            "category": case.category,
            "risk_tags": case.risk_tags,
            "attempt": attempt_number,
            "execution_state": execution_state,
            "deterministic_failures": deterministic,
            "failure_details": failure_details,
            "answer": extract_response_text(case_events),
            "turns": [
                {
                    **timing,
                    **graph_evidence_by_turn.get(timing["turn"], {}),
                    "prompt": case.steps[timing["turn"] - 1].prompt,
                    "answer": (
                        answers[timing["turn"] - 1]
                        if timing["turn"] <= len(answers)
                        else ""
                    ),
                }
                for timing in turn_timings
            ],
            "events": case_events,
            "graph": graph,
            "rendered_nodes": rendered_nodes,
            "rendered_edges": rendered_edges,
            "rendered_graph_version": rendered_graph_version,
            "rendered_node_ids": rendered_node_ids,
            "rendered_edge_identities": rendered_edge_identities,
            "thread_id": thread_id,
            "screenshot": screenshot_relative,
            "trace": str(trace.relative_to(artifact_dir)),
            "latency_ms": int((time.monotonic() - case_started) * 1000),
            "fallback_used": any(
                event.get("type") == "provider_switch" for event in case_events
            ),
        }
        result["passed"] = not deterministic
        return result
    finally:
        try:
            await context.tracing.stop(path=raw_trace)
            await asyncio.to_thread(
                _redact_trace,
                raw_trace,
                trace,
                [
                    session.get("access_token", ""),
                    session.get("refresh_token", ""),
                    args.internal_password,
                ],
            )
        except Exception as exc:
            detail = _failure_detail(
                "infrastructure",
                "trace_capture_failed",
                f"trace capture failed: {type(exc).__name__}: {exc}",
            )
            if "result" in locals():
                result["failure_details"].append(detail)
                result["deterministic_failures"].append(detail["message"])
                result["passed"] = False
        finally:
            raw_trace.unlink(missing_ok=True)
            try:
                await context.close()
            except Exception as exc:
                detail = _failure_detail(
                    "infrastructure",
                    "browser_context_close_failed",
                    f"browser context close failed: {type(exc).__name__}: {exc}",
                )
                if "result" in locals():
                    result["failure_details"].append(detail)
                    result["deterministic_failures"].append(detail["message"])
                    result["passed"] = False


async def _execute_browser(args: argparse.Namespace) -> dict[str, Any]:
    corpus = load_corpus()
    case_ids = _suite_case_ids(args.suite, args.case)
    cases = [corpus.by_id[case_id] for case_id in case_ids]
    if args.suite == "pr" and len(cases) != 8:
        raise RuntimeError("the PR browser suite must contain exactly eight journeys")
    output_path = ROOT / args.output
    artifact_dir = output_path.parent
    screenshot_dir = artifact_dir / "screenshots"
    trace_dir = artifact_dir / "playwright-traces"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    started_at = datetime.now(UTC)
    _write_json_atomic(
        output_path,
        _browser_report(
            args=args,
            corpus=corpus,
            started_at=started_at,
            started=started,
            results=results,
            status="running",
        ),
    )
    session = await _internal_session(
        args.backend_target, args.email, args.internal_password
    )

    timeout_seconds = browser_suite_timeout_seconds(cases)
    turn_timeout_seconds = application_turn_timeout_seconds()
    case_concurrency = browser_case_concurrency()
    graph_case_concurrency = browser_graph_case_concurrency()
    infrastructure_retry_count = browser_infrastructure_retry_count()
    async with asyncio.timeout(timeout_seconds):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headed)
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 960}
                )
                await context.tracing.start(
                    screenshots=True, snapshots=True, sources=True
                )
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
                try:
                    await page.goto(
                        args.target,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    if await page.get_by_role("heading", name="Sign in").is_visible():
                        raise RuntimeError(
                            "evaluation frontend did not accept the internal session"
                        )
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
                    raise
                else:
                    await context.tracing.stop()
                    await context.close()

                async def run_attempt(
                    attempted_case: EvaluationCase,
                    attempt_number: int,
                ) -> dict[str, Any]:
                    return await _run_browser_attempt(
                        browser,
                        args,
                        attempted_case,
                        artifact_dir=artifact_dir,
                        screenshot_dir=screenshot_dir,
                        trace_dir=trace_dir,
                        turn_timeout_seconds=turn_timeout_seconds,
                        attempt_number=attempt_number,
                    )

                async def write_checkpoint(
                    completed_results: list[dict[str, Any]],
                ) -> None:
                    nonlocal results
                    results = list(completed_results)
                    checkpoint = _browser_report(
                        args=args,
                        corpus=corpus,
                        started_at=started_at,
                        started=started,
                        results=completed_results,
                        status="partial",
                    )
                    _write_json_atomic(output_path, checkpoint)

                results = await _run_cases_with_deferred_retries(
                    cases,
                    max_concurrency=min(case_concurrency, len(cases)),
                    graph_max_concurrency=min(
                        graph_case_concurrency,
                        case_concurrency,
                        len(cases),
                    ),
                    retry_count=infrastructure_retry_count,
                    run_attempt=run_attempt,
                    on_result=write_checkpoint,
                )
            finally:
                await browser.close()

    session = await _internal_session(
        args.backend_target, args.email, args.internal_password
    )
    report = _browser_report(
        args=args,
        corpus=corpus,
        started_at=started_at,
        started=started,
        results=results,
        status="complete",
    )
    thread_ids = [
        thread_id
        for result in results
        for thread_id in result.get("thread_ids") or [result.get("thread_id")]
        if thread_id
    ]
    query = urllib.parse.urlencode(
        [
            ("since_epoch", str(started_at.timestamp())),
            *(("thread_id", thread_id) for thread_id in thread_ids),
        ]
    )
    telemetry = await asyncio.to_thread(
        _blocking_json_request,
        "GET",
        args.backend_target.rstrip("/")
        + "/api/internal/dashboard/eval-telemetry?"
        + query,
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
    dashboard_passed = isinstance(dashboard.get("kpis"), dict) and isinstance(
        dashboard.get("providers"), dict
    )
    report["dashboard_smoke"] = {
        "passed": dashboard_passed,
        "required_keys": ["kpis", "providers"],
    }
    _write_json_atomic(output_path, report)
    _write_junit(artifact_dir / "browser-junit.xml", results)
    _write_html(artifact_dir / "review.html", report)
    return report


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Replace a checkpoint atomically so cancellation cannot leave invalid JSON."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _unfinished_case_result(
    case: EvaluationCase, detail: FailureDetail, *, execution_state: str
) -> dict[str, Any]:
    """Emit a schema-complete result for work pre-empted by the suite deadline."""
    return {
        "id": case.id,
        "category": case.category,
        "risk_tags": case.risk_tags,
        "attempt": 0,
        "execution_state": execution_state,
        "deterministic_failures": [detail["message"]],
        "failure_details": [detail],
        "answer": "",
        "turns": [],
        "events": [],
        "graph": None,
        "rendered_nodes": 0,
        "rendered_edges": 0,
        "rendered_graph_version": None,
        "rendered_node_ids": [],
        "rendered_edge_identities": [],
        "thread_id": None,
        "thread_ids": [],
        "screenshot": None,
        "trace": None,
        "latency_ms": None,
        "fallback_used": False,
        "passed": False,
        "attempts": [],
        "attempt_count": 0,
        "retried": False,
    }


async def _finalize_timed_out_browser(args: argparse.Namespace) -> dict[str, Any]:
    """Turn the last durable checkpoint into enforceable timeout evidence."""
    corpus = load_corpus()
    case_ids = _suite_case_ids(args.suite, args.case)
    cases = [corpus.by_id[case_id] for case_id in case_ids]
    output_path = ROOT / args.output
    artifact_dir = output_path.parent
    timeout_seconds = browser_suite_timeout_seconds(cases)
    checkpoint: dict[str, Any] = {}
    if output_path.exists():
        try:
            candidate = json.loads(output_path.read_text(encoding="utf-8"))
            if (
                isinstance(candidate, dict)
                and candidate.get("kind") == "browser_capture"
            ):
                checkpoint = candidate
        except (OSError, json.JSONDecodeError):
            checkpoint = {}

    started_at_text = checkpoint.get("started_at")
    try:
        started_at = datetime.fromisoformat(str(started_at_text))
    except (TypeError, ValueError):
        started_at = datetime.now(UTC)
    existing = {
        str(result.get("id")): result
        for result in checkpoint.get("results") or []
        if isinstance(result, dict) and result.get("id")
    }
    suite_detail = _failure_detail(
        "infrastructure",
        "browser_suite_timeout",
        f"browser suite timed out after its {timeout_seconds}s deadline",
    )
    results = []
    for case in cases:
        result = existing.get(case.id)
        if result is None:
            result = _unfinished_case_result(
                case, suite_detail, execution_state="not_started"
            )
        else:
            result = dict(result)
            result.setdefault("execution_state", "completed")
        results.append(result)

    report = _browser_report(
        args=args,
        corpus=corpus,
        started_at=started_at,
        started=time.monotonic(),
        results=results,
        status="timed_out",
    )
    if checkpoint.get("duration_ms") is not None:
        report["duration_ms"] = max(
            int(checkpoint["duration_ms"]), timeout_seconds * 1000
        )
    report["failure"] = suite_detail
    report["case_states"] = [
        {"id": result["id"], "state": result.get("execution_state", "completed")}
        for result in results
    ]

    finalization_failures: list[FailureDetail] = []
    report["application_telemetry"] = []
    report["dashboard_smoke"] = {
        "passed": False,
        "required_keys": ["kpis", "providers"],
    }
    try:
        session = await _internal_session(
            args.backend_target, args.email, args.internal_password
        )
    except Exception as exc:
        finalization_failures.append(
            _failure_detail(
                "infrastructure",
                "timeout_finalization_auth_failed",
                f"timeout finalization auth failed: {type(exc).__name__}: {exc}",
            )
        )
    else:
        thread_ids = list(
            dict.fromkeys(
                str(thread_id)
                for result in results
                for thread_id in result.get("thread_ids") or [result.get("thread_id")]
                if thread_id
            )
        )
        if thread_ids:
            query = urllib.parse.urlencode(
                [
                    ("since_epoch", str(started_at.timestamp())),
                    *(("thread_id", thread_id) for thread_id in thread_ids),
                ]
            )
            try:
                telemetry = await asyncio.to_thread(
                    _blocking_json_request,
                    "GET",
                    args.backend_target.rstrip("/")
                    + "/api/internal/dashboard/eval-telemetry?"
                    + query,
                    None,
                    session["access_token"],
                )
                report["application_telemetry"] = telemetry.get("calls") or []
            except Exception as exc:
                finalization_failures.append(
                    _failure_detail(
                        "infrastructure",
                        "timeout_telemetry_collection_failed",
                        "timeout telemetry collection failed: "
                        f"{type(exc).__name__}: {exc}",
                    )
                )
        try:
            dashboard = await asyncio.to_thread(
                _blocking_json_request,
                "GET",
                args.backend_target.rstrip("/") + "/api/internal/dashboard/overview",
                None,
                session["access_token"],
            )
            report["dashboard_smoke"]["passed"] = isinstance(
                dashboard.get("kpis"), dict
            ) and isinstance(dashboard.get("providers"), dict)
        except Exception as exc:
            finalization_failures.append(
                _failure_detail(
                    "infrastructure",
                    "timeout_dashboard_collection_failed",
                    f"timeout dashboard collection failed: {type(exc).__name__}: {exc}",
                )
            )
    report["finalization_failures"] = finalization_failures
    _write_json_atomic(output_path, report)
    _write_junit(artifact_dir / "browser-junit.xml", results)
    _write_html(artifact_dir / "review.html", report)
    return report


async def run_browser(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return await _execute_browser(args)
    except TimeoutError:
        return await _finalize_timed_out_browser(args)


def _browser_report(
    *,
    args: argparse.Namespace,
    corpus: Any,
    started_at: datetime,
    started: float,
    results: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    """Build the durable capture written after every completed journey."""
    return {
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
        "status": status,
        "case_states": [
            {
                "id": result["id"],
                "state": result.get("execution_state", "completed"),
            }
            for result in results
        ],
        "latency": _latency_summary(results),
        "results": results,
    }


def _nearest_rank_percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    if percentile <= 0 or percentile > 100:
        raise ValueError("percentile must be greater than zero and at most 100")
    ordered = sorted(values)
    rank = (len(ordered) * percentile + 99) // 100
    return ordered[rank - 1]


def _latency_metric(values: list[int]) -> dict[str, int | None]:
    return {
        "sample_count": len(values),
        "p50_ms": _nearest_rank_percentile(values, 50),
        "p95_ms": _nearest_rank_percentile(values, 95),
    }


def _numeric_latency(value: Any) -> int | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return int(value)
    return None


def _latency_summary(
    results: list[dict[str, Any]],
    *,
    p50_threshold_ms: int | None = None,
    p95_threshold_ms: int | None = None,
    baseline_min_runs: int = 5,
    baseline_run_count: int = 1,
) -> dict[str, Any]:
    """Report case and turn latency without treating infrastructure as a baseline."""
    thresholds = {
        "p50_ms": p50_threshold_ms,
        "p95_ms": p95_threshold_ms,
    }
    if any(value is not None and value <= 0 for value in thresholds.values()):
        raise ValueError("latency thresholds must be positive")
    if baseline_min_runs <= 0:
        raise ValueError("latency baseline minimum runs must be positive")
    if baseline_run_count < 0:
        raise ValueError("latency baseline run count cannot be negative")

    eligible_results = [
        result
        for result in results
        if not any(
            detail.get("kind") == "infrastructure" and detail.get("blocking", True)
            for detail in result.get("failure_details") or []
        )
    ]
    case_samples = [
        sample
        for result in eligible_results
        if (sample := _numeric_latency(result.get("latency_ms"))) is not None
    ]
    turns = [
        turn
        for result in eligible_results
        for turn in result.get("turns") or []
        if isinstance(turn, dict)
    ]
    turn_samples = [
        sample
        for turn in turns
        if (sample := _numeric_latency(turn.get("latency_ms"))) is not None
    ]
    first_event_samples = [
        sample
        for turn in turns
        if (sample := _numeric_latency(turn.get("first_event_ms"))) is not None
    ]
    first_token_samples = [
        sample
        for turn in turns
        if (sample := _numeric_latency(turn.get("first_token_ms"))) is not None
    ]
    metrics = {
        "case_end_to_end": _latency_metric(case_samples),
        "turn_end_to_end": _latency_metric(turn_samples),
        "first_event": _latency_metric(first_event_samples),
        "first_token": _latency_metric(first_token_samples),
    }
    observed = metrics["case_end_to_end"]
    violations = [
        f"{name} observed {observed[name]}ms exceeds {threshold}ms"
        for name, threshold in thresholds.items()
        if threshold is not None
        and observed[name] is not None
        and observed[name] > threshold
    ]
    baseline_ready = baseline_run_count >= baseline_min_runs
    blocking = baseline_ready and any(
        value is not None for value in thresholds.values()
    )
    return {
        "sample_count": observed["sample_count"],
        "p50_ms": observed["p50_ms"],
        "p95_ms": observed["p95_ms"],
        "eligible_case_count": len(eligible_results),
        "excluded_infrastructure_case_count": len(results) - len(eligible_results),
        "metrics": metrics,
        "thresholds_ms": thresholds,
        "mode": "blocking" if blocking else "report-only",
        "baseline_min_runs": baseline_min_runs,
        "baseline_run_count": baseline_run_count,
        "baseline_ready": baseline_ready,
        "passed": not violations if blocking else True,
        "violations": violations if blocking else [],
    }


def _redact_trace(source: Path, destination: Path, secrets: list[str]) -> None:
    replacements = [secret.encode("utf-8") for secret in secrets if secret]
    with (
        zipfile.ZipFile(source) as input_zip,
        zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED
        ) as output_zip,
    ):
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
            message = html.escape(
                "; ".join(result["deterministic_failures"]), quote=True
            )
            failure = f'<failure message="{message}" />'
        cases.append(
            f'<testcase classname="live.browser" name="{html.escape(result["id"])}">{failure}</testcase>'
        )
    path.write_text(
        f'<testsuite name="browser journeys" tests="{len(results)}" failures="{failures}">'
        + "".join(cases)
        + "</testsuite>\n",
        encoding="utf-8",
    )


def _write_html(path: Path, report: dict[str, Any]) -> None:
    rows = []
    for result in report["results"]:
        answer = html.escape(str(result.get("answer") or "")[:4000])
        failures = html.escape("; ".join(result["deterministic_failures"]) or "none")
        screenshot = result.get("screenshot")
        screenshot_markup = (
            f"<img src='{html.escape(screenshot)}' loading='lazy'>"
            if isinstance(screenshot, str) and screenshot
            else "<p><i>No screenshot was captured for this attempt.</i></p>"
        )
        evidence = html.escape(
            json.dumps(
                [
                    event
                    for event in result.get("events") or []
                    if event.get("type") in {"retrieval_evidence", "research_evidence"}
                ],
                indent=2,
                ensure_ascii=False,
            )[:20_000]
        )
        rows.append(
            f"<article><h2>{html.escape(result['id'])} — {'PASS' if result['passed'] else 'FAIL'}</h2>"
            f"<p><b>Deterministic:</b> {failures}</p>{screenshot_markup}"
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
    if report.get("status") != "complete":
        raise SystemExit(2)
    if (
        not all(result["passed"] for result in report["results"])
        or not report["dashboard_smoke"]["passed"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
