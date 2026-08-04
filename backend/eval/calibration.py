from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from eval.judge_adapter import JUDGE_PROMPT_RELEASE
from eval.quality_corpus import EvaluationCorpus, corpus_sha256, load_corpus
from eval.semantic_gate import calibration_passes


def calculate_calibration(
    corpus: EvaluationCorpus,
    live_report: dict[str, Any],
    *,
    evidence_sha256: str,
    source_context: dict[str, Any],
) -> dict[str, Any]:
    if live_report.get("kind") != "live_gate" or live_report.get("suite") != "full":
        raise ValueError("calibration requires a full live-gate report")
    if live_report.get("execution_mode") != "semantic_replay":
        raise ValueError("calibration requires semantic replay mode")
    if live_report.get("status") == "infrastructure":
        raise ValueError("calibration cannot score an infrastructure-failed replay")
    if live_report.get("status") not in {"pass", "fail", "manual_review"}:
        raise ValueError("calibration report has an unknown status")
    if live_report.get("corpus_version") != corpus.corpus_version:
        raise ValueError("calibration report corpus version does not match")
    if live_report.get("corpus_sha256") != corpus_sha256():
        raise ValueError("calibration report corpus digest does not match")
    calibration_identity = corpus.approval.calibration
    if calibration_identity.judge_release != JUDGE_PROMPT_RELEASE:
        raise ValueError("approved judge release is not the active judge release")
    if evidence_sha256 != calibration_identity.evidence_sha256:
        raise ValueError("calibration evidence digest does not match approved identity")
    if str(source_context.get("source_run_id") or "") != calibration_identity.evidence_run_id:
        raise ValueError("calibration evidence run does not match approved identity")
    if source_context.get("source_commit_sha") != calibration_identity.evidence_commit_sha:
        raise ValueError("calibration evidence commit does not match approved identity")
    raw_evaluations = live_report.get("evaluations") or []
    evaluation_ids = [item.get("id") for item in raw_evaluations]
    expected_ids = [case.id for case in corpus.cases]
    if evaluation_ids != expected_ids:
        raise ValueError("calibration requires judgments for the exact 20-case corpus")
    evaluations = {item["id"]: item for item in raw_evaluations}

    expected: list[tuple[str, bool]] = []
    actual: list[tuple[str, bool]] = []
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    dimension_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    disagreements: list[dict[str, str]] = []
    critical_false_pass_case_ids: set[str] = set()
    judge_models: set[str] = set()
    for case in corpus.cases:
        if case.approval.status != "approved":
            raise ValueError(f"case {case.id} has not completed human review")
        evaluation = evaluations[case.id]
        if evaluation.get("decision") == "infrastructure":
            raise ValueError(f"case {case.id} has an infrastructure-failed judgment")
        judgments = evaluation.get("judgments") or []
        if not judgments:
            raise ValueError(f"case {case.id} has no semantic judgment")
        for judgment in judgments:
            if judgment.get("prompt_release") != calibration_identity.judge_release:
                raise ValueError(f"case {case.id} judge release does not match calibration identity")
            if judgment.get("model") != calibration_identity.judge_model:
                raise ValueError(f"case {case.id} judge model does not match calibration identity")
        first_judgment = judgments[0]
        model = str(first_judgment.get("model") or "")
        judge_models.add(model)
        raw_dimensions = first_judgment.get("dimensions") or []
        proposed = {dimension["dimension"]: dimension["grade"] for dimension in raw_dimensions}
        if len(proposed) != len(raw_dimensions):
            raise ValueError(f"case {case.id} judgment contains duplicate dimensions")
        if set(proposed) != set(case.rubric_dimensions):
            raise ValueError(f"case {case.id} judgment dimensions do not match its rubric")
        for dimension in case.rubric_dimensions:
            critical = corpus.rubrics[dimension].critical
            expected_grade = case.approval.reviewed_grades[dimension]
            actual_grade = proposed[dimension]
            expected.append((expected_grade, critical))
            actual.append((actual_grade, critical))
            confusion[expected_grade][actual_grade] += 1
            dimension_totals[dimension][1] += 1
            if expected_grade == actual_grade:
                dimension_totals[dimension][0] += 1
            else:
                disagreements.append({
                    "case_id": case.id,
                    "dimension": dimension,
                    "expected": expected_grade,
                    "actual": actual_grade,
                })
            if expected_grade == "fail" and actual_grade == "pass" and critical:
                critical_false_pass_case_ids.add(case.id)

    passed, agreement, critical_false_passes = calibration_passes(expected, actual)
    approved_agreement = corpus.approval.calibration.agreement
    agreement_drop = (
        max(0.0, approved_agreement - agreement)
        if approved_agreement is not None
        else 0.0
    )
    passed = passed and agreement_drop <= 0.05
    return {
        "format_version": 1,
        "judge_release": JUDGE_PROMPT_RELEASE,
        "corpus_version": corpus.corpus_version,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "labels": len(expected),
        "agreement": round(agreement, 6),
        "approved_agreement": approved_agreement,
        "agreement_drop": round(agreement_drop, 6),
        "critical_false_passes": critical_false_passes,
        "critical_false_pass_case_ids": sorted(critical_false_pass_case_ids),
        "judge_models": sorted(judge_models),
        "evidence_sha256": evidence_sha256,
        "source_context": source_context,
        "per_dimension_agreement": {
            dimension: round(matched / total, 6)
            for dimension, (matched, total) in sorted(dimension_totals.items())
        },
        "confusion_matrix": {
            expected_grade: dict(sorted(actual_grades.items()))
            for expected_grade, actual_grades in sorted(confusion.items())
        },
        "disagreements": disagreements,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare judge proposals with the reviewed corpus labels")
    parser.add_argument("--input", required=True, help="Full-suite live-results.json")
    parser.add_argument("--evidence", required=True, help="Immutable browser-results.json used for replay")
    parser.add_argument("--context", required=True, help="Replay context JSON identifying source run and commit")
    parser.add_argument("--output", default="artifacts/live-eval/calibration.json")
    args = parser.parse_args()
    evidence_sha256 = hashlib.sha256(Path(args.evidence).read_bytes()).hexdigest()
    source_context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    report = calculate_calibration(
        load_corpus(require_approved=True),
        json.loads(Path(args.input).read_text(encoding="utf-8")),
        evidence_sha256=evidence_sha256,
        source_context=source_context,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
