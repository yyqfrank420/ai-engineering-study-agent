from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import html
import json
import os
from pathlib import Path
import re
from typing import Any

from eval.judge_adapter import (
    JUDGE_PROMPT_RELEASE,
    SemanticJudge,
    estimated_judge_cost_usd,
    judge_with_transport_retry,
)
from eval.quality_corpus import corpus_sha256, load_corpus
from eval.semantic_gate import EvaluationBudget, GateDecision, decide_semantic_gate


ROOT = Path(__file__).resolve().parents[2]
QUALITY_MANIFEST = ROOT / "ci" / "quality.json"
PROVIDER_FAILURE = re.compile(r"(?:rate.?limit|429|provider.*unavailable|timed?\s*out|connection.*failed)", re.I)
APPLICATION_PRICES = {
    # Price release 2026-07-18. Sonnet 5 uses its introductory price through 2026-08-31.
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-4-8": (5.00, 25.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply deterministic and reviewed semantic gates")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--target", required=True, help="Backend candidate URL")
    parser.add_argument("--input", help="Browser capture JSON from eval.browser_runner")
    parser.add_argument("--output", default="artifacts/live-eval/live-results.json")
    parser.add_argument("--require-approved-corpus", action="store_true")
    parser.add_argument(
        "--capture-replay",
        action="store_true",
        help="Rejudge saved browser evidence without charging application calls again",
    )
    return parser


def _manifest() -> dict[str, Any]:
    return json.loads(QUALITY_MANIFEST.read_text(encoding="utf-8"))


def _load_capture(args: argparse.Namespace) -> dict[str, Any]:
    if not args.input:
        raise RuntimeError(
            "live evaluation requires a browser capture. Run './scripts/ci browser --suite ...' first and pass --input."
        )
    capture = json.loads((ROOT / args.input).read_text(encoding="utf-8"))
    if capture.get("kind") != "browser_capture" or capture.get("suite") != args.suite:
        raise RuntimeError("browser capture kind or suite does not match this live evaluation")
    if capture.get("backend_target", "").rstrip("/") != args.target.rstrip("/"):
        raise RuntimeError("browser capture backend target does not match --target")
    if capture.get("corpus_sha256") != corpus_sha256():
        raise RuntimeError("browser capture was produced with a different corpus manifest")
    return capture


def _judge_payload(result: dict[str, Any]) -> dict[str, Any]:
    graph = result.get("graph")
    compact_graph = None
    if isinstance(graph, dict):
        compact_graph = {
            key: graph[key]
            for key in (
                "graph_type",
                "title",
                "design_origin",
                "resolved_complexity",
                "assumptions",
                "groups",
                "sequence",
                "version",
            )
            if graph.get(key) is not None
        }
        compact_graph["nodes"] = [
            {
                key: node[key]
                for key in ("id", "label", "type", "technology", "description", "tier", "layer")
                if node.get(key) is not None
            }
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
        ]
        compact_graph["edges"] = [
            {
                key: edge[key]
                for key in ("source", "target", "label", "technology")
                if edge.get(key) is not None
            }
            for edge in graph.get("edges") or []
            if isinstance(edge, dict)
        ]
    return {
        "answer": str(result.get("answer") or "")[:40_000],
        "graph": compact_graph,
        "events": [
            event
            for event in result.get("events") or []
            if event.get("type") in {
                "worker_status",
                "retrieval_notice",
                "graph_notice",
                "provider_switch",
                "done",
                "error",
            }
        ],
    }


def _result_to_json(result) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "model": result.model,
        "prompt_release": JUDGE_PROMPT_RELEASE,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": estimated_judge_cost_usd(result),
        "dimensions": [
            {
                "dimension": item.dimension,
                "grade": item.grade,
                "critical": item.critical,
                "evidence": list(item.evidence),
                "rationale": item.rationale,
            }
            for item in result.dimensions
        ],
    }


def _classify_deterministic(failures: list[str]) -> str:
    return "infrastructure" if any(PROVIDER_FAILURE.search(failure) for failure in failures) else "quality"


def _application_cost(telemetry: list[dict[str, Any]]) -> float:
    total = 0.0
    for call in telemetry:
        model = str(call.get("model") or "")
        price = next((value for prefix, value in APPLICATION_PRICES.items() if model.startswith(prefix)), None)
        if price is None:
            continue
        total += int(call.get("input_tokens") or 0) * price[0] / 1_000_000
        total += int(call.get("output_tokens") or 0) * price[1] / 1_000_000
    return round(total, 6)


async def evaluate(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    manifest = _manifest()
    limits = manifest["live"]["budgets"]
    corpus = load_corpus(require_approved=args.require_approved_corpus)
    capture = _load_capture(args)
    expected_ids = manifest["live"]["suites"].get(args.suite)
    if expected_ids is None and args.suite != "nightly":
        raise RuntimeError(f"unknown live suite: {args.suite}")
    actual_ids = [result["id"] for result in capture["results"]]
    if expected_ids is not None and actual_ids != expected_ids:
        raise RuntimeError(f"browser capture cases do not match suite: expected {expected_ids}, got {actual_ids}")
    if args.suite == "pr" and len(actual_ids) > limits["pr_cases"]:
        raise RuntimeError("PR case budget exceeded")

    is_pr_budget = args.suite in {"pr", "smoke"}
    budget = EvaluationBudget(
        application_calls=limits["application_calls"] if is_pr_budget else 150,
        judge_calls=limits["judge_calls"] if is_pr_budget else 40,
    )
    app_telemetry = capture.get("application_telemetry") or []
    if capture.get("results") and not app_telemetry:
        raise RuntimeError("browser capture contains no application model-call telemetry")
    budget.record_application_calls(
        sum(max(1, int(call.get("provider_attempts") or 1)) for call in app_telemetry)
    )
    judge = SemanticJudge()
    evaluations: list[dict[str, Any]] = []

    for browser_result in capture["results"]:
        case = corpus.by_id[browser_result["id"]]
        deterministic_failures = tuple(browser_result.get("deterministic_failures") or [])
        if deterministic_failures:
            classification = _classify_deterministic(list(deterministic_failures))
            decision = GateDecision(
                "infrastructure" if classification == "infrastructure" else "fail",
                "; ".join(deterministic_failures),
            )
            evaluations.append(
                {
                    "id": case.id,
                    "decision": decision.status,
                    "reason": decision.reason,
                    "deterministic_failures": list(deterministic_failures),
                    "judgments": [],
                }
            )
            continue

        payload = _judge_payload(browser_result)
        judgments = []
        try:
            first = await judge_with_transport_retry(
                judge,
                corpus,
                case,
                payload,
                on_attempt=budget.record_judge_call,
            )
            judgments.append(first)
            decision = decide_semantic_gate(first)
            if decision.status == "infrastructure" and "second independent" in decision.reason:
                second = await judge_with_transport_retry(
                    judge,
                    corpus,
                    case,
                    payload,
                    on_attempt=budget.record_judge_call,
                )
                judgments.append(second)
                decision = decide_semantic_gate(first, second)
        except Exception as exc:
            decision = GateDecision("infrastructure", f"judge infrastructure failure: {type(exc).__name__}: {exc}")
        evaluations.append(
            {
                "id": case.id,
                "decision": decision.status,
                "reason": decision.reason,
                "deterministic_failures": [],
                "judgments": [_result_to_json(item) for item in judgments],
            }
        )

    statuses = {item["decision"] for item in evaluations}
    exit_code = 1 if "fail" in statuses else 2 if "infrastructure" in statuses else 3 if "manual_review" in statuses else 0
    source_application_cost = _application_cost(app_telemetry)
    report = {
        "format_version": 1,
        "kind": "live_gate",
        "execution_mode": "semantic_replay" if args.capture_replay else "staging_gate",
        "suite": args.suite,
        "target": args.target,
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": corpus_sha256(),
        "corpus_approval": corpus.approval.status,
        "release_identity": corpus.release_identity,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "pass" if exit_code == 0 else "fail" if exit_code == 1 else "infrastructure" if exit_code == 2 else "manual_review",
        "budget": {
            "application_calls": budget.application_calls,
            "application_limit": budget.application_limit,
            "judge_calls": budget.judge_calls,
            "judge_limit": budget.judge_limit,
        },
        "application_telemetry": app_telemetry,
        "estimated_cost": {
            "currency": "USD",
            "price_release": "2026-07-18",
            "application_usd": 0 if args.capture_replay else source_application_cost,
            "source_application_usd": source_application_cost,
            "judge_usd": round(
                sum(
                    judgment["estimated_cost_usd"]
                    for evaluation in evaluations
                    for judgment in evaluation["judgments"]
                ),
                6,
            ),
        },
        "evaluations": evaluations,
    }
    return report, exit_code


def _write_outputs(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    failures = sum(item["decision"] != "pass" for item in report["evaluations"])
    cases = "".join(
        f'<testcase classname="live.semantic" name="{html.escape(item["id"])}">'
        + ("" if item["decision"] == "pass" else f'<failure message="{html.escape(item["reason"], quote=True)}" />')
        + "</testcase>"
        for item in report["evaluations"]
    )
    (path.parent / "live-junit.xml").write_text(
        f'<testsuite name="live semantic gate" tests="{len(report["evaluations"])}" failures="{failures}">{cases}</testsuite>\n',
        encoding="utf-8",
    )
    _write_semantic_review(path.parent / "semantic-review.html", report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Live evaluation",
            "",
            f"Status: **{report.get('status', 'infrastructure')}**",
        ]
        if report.get("corpus_version"):
            lines.append(
                f"Corpus: `{report['corpus_version']}` ({report.get('corpus_approval', 'unknown')})"
            )
        if report.get("budget"):
            lines.append(
                f"Calls: {report['budget']['application_calls']} application / "
                f"{report['budget']['judge_calls']} judge"
            )
        if report.get("reason"):
            lines.append(f"Reason: {report['reason']}")
        lines.extend(["", "| Case | Decision | Reason |", "| --- | --- | --- |"])
        lines.extend(
            f"| {item['id']} | {item['decision']} | {item['reason'].replace('|', '/')} |"
            for item in report["evaluations"]
        )
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")


def _write_semantic_review(path: Path, report: dict[str, Any]) -> None:
    cases = []
    for evaluation in report.get("evaluations") or []:
        judgments = evaluation.get("judgments") or []
        dimensions = []
        for index, judgment in enumerate(judgments, start=1):
            for item in judgment.get("dimensions") or []:
                evidence = "; ".join(item.get("evidence") or [])
                dimensions.append(
                    "<tr>"
                    f"<td>{index}</td><td>{html.escape(item['dimension'])}</td>"
                    f"<td>{html.escape(item['grade'])}</td>"
                    f"<td>{html.escape(evidence)}</td>"
                    f"<td>{html.escape(item.get('rationale') or '')}</td>"
                    "</tr>"
                )
        cases.append(
            f"<article><h2>{html.escape(evaluation['id'])} — "
            f"{html.escape(evaluation['decision'])}</h2>"
            f"<p>{html.escape(evaluation.get('reason') or '')}</p>"
            "<table><thead><tr><th>Judge</th><th>Dimension</th><th>Grade</th>"
            "<th>Cited evidence</th><th>Rationale</th></tr></thead><tbody>"
            + "".join(dimensions)
            + "</tbody></table></article>"
        )
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Semantic review</title>"
        "<style>body{font:15px system-ui;max-width:1200px;margin:auto;background:#111;color:#eee}"
        "article{border-bottom:1px solid #444;padding:24px}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #555;padding:8px;text-align:left;vertical-align:top}</style>"
        f"<h1>Semantic proposals — {html.escape(report.get('status') or 'unknown')}</h1>"
        + "".join(cases),
        encoding="utf-8",
    )


async def main() -> None:
    args = build_parser().parse_args()
    output = ROOT / args.output
    try:
        timeout_seconds = 900 if args.suite in {"pr", "smoke"} else 3600
        report, exit_code = await asyncio.wait_for(evaluate(args), timeout=timeout_seconds)
    except TimeoutError:
        report = {
            "format_version": 1,
            "kind": "live_gate",
            "suite": args.suite,
            "target": args.target,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "infrastructure",
            "evaluations": [],
            "reason": "15-minute evaluation budget exhausted",
        }
        exit_code = 2
    except Exception as exc:
        report = {
            "format_version": 1,
            "kind": "live_gate",
            "suite": args.suite,
            "target": args.target,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "infrastructure",
            "evaluations": [],
            "reason": f"live evaluation could not start: {type(exc).__name__}: {exc}",
        }
        exit_code = 2
    _write_outputs(output, report)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
