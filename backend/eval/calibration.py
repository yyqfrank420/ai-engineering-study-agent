from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from eval.judge_adapter import JUDGE_PROMPT_RELEASE
from eval.quality_corpus import EvaluationCorpus, load_corpus
from eval.semantic_gate import calibration_passes


def calculate_calibration(
    corpus: EvaluationCorpus,
    live_report: dict[str, Any],
) -> dict[str, Any]:
    evaluations = {item["id"]: item for item in live_report.get("evaluations") or []}
    if set(evaluations) != set(corpus.by_id):
        raise ValueError("calibration requires judgments for the exact 20-case corpus")

    expected: list[tuple[str, bool]] = []
    actual: list[tuple[str, bool]] = []
    for case in corpus.cases:
        if case.approval.status != "approved":
            raise ValueError(f"case {case.id} has not completed human review")
        judgments = evaluations[case.id].get("judgments") or []
        if not judgments:
            raise ValueError(f"case {case.id} has no semantic judgment")
        proposed = {
            dimension["dimension"]: dimension["grade"]
            for dimension in judgments[0].get("dimensions") or []
        }
        if set(proposed) != set(case.rubric_dimensions):
            raise ValueError(f"case {case.id} judgment dimensions do not match its rubric")
        for dimension in case.rubric_dimensions:
            critical = corpus.rubrics[dimension].critical
            expected.append((case.approval.reviewed_grades[dimension], critical))
            actual.append((proposed[dimension], critical))

    passed, agreement, critical_false_passes = calibration_passes(expected, actual)
    return {
        "format_version": 1,
        "judge_release": JUDGE_PROMPT_RELEASE,
        "corpus_version": corpus.corpus_version,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "labels": len(expected),
        "agreement": round(agreement, 6),
        "critical_false_passes": critical_false_passes,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare judge proposals with the reviewed corpus labels")
    parser.add_argument("--input", required=True, help="Full-suite live-results.json")
    parser.add_argument("--output", default="artifacts/live-eval/calibration.json")
    args = parser.parse_args()
    report = calculate_calibration(
        load_corpus(),
        json.loads(Path(args.input).read_text(encoding="utf-8")),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
