import hashlib
import json
import sys

import pytest

from eval import calibration
from eval.quality_corpus import (
    CORPUS_PATH,
    approval_manifest_sha256,
    corpus_sha256,
    load_corpus,
)


@pytest.fixture
def calibration_cli_files(tmp_path, monkeypatch):
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    corpus["approval"].update(
        status="pending_human_review",
        reviewed_by=None,
        reviewed_at=None,
        approved_manifest_sha256=None,
    )
    evidence_path = tmp_path / "browser-results.json"
    evidence_path.write_text('{"fixture": "reviewed capture"}\n', encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    corpus["approval"]["calibration"].update(
        evidence_run_id="123",
        evidence_commit_sha="a" * 40,
        evidence_sha256=evidence_digest,
        agreement=None,
        critical_false_passes=None,
        evaluated_at=None,
    )
    for case in corpus["cases"]:
        case["approval"].update(
            status="approved",
            reviewer="Test reviewer",
            reviewed_at="2026-09-11T12:00:00Z",
            review_run_id="123",
            reviewed_grades={
                dimension: "pass" for dimension in case["rubric_dimensions"]
            },
        )
    corpus_path = tmp_path / "cases.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    identity = corpus["approval"]["calibration"]
    report = {
        "kind": "live_gate",
        "suite": "full",
        "execution_mode": "semantic_replay",
        "status": "pass",
        "corpus_version": corpus["corpus_version"],
        "corpus_sha256": corpus_sha256(),
        "evaluations": [
            {
                "id": case["id"],
                "decision": "pass",
                "judgments": [
                    {
                        "provider": identity["judge_provider"],
                        "model": identity["judge_model"],
                        "prompt_release": identity["judge_release"],
                        "dimensions": [
                            {"dimension": dimension, "grade": "pass"}
                            for dimension in case["rubric_dimensions"]
                        ],
                    }
                ],
            }
            for case in corpus["cases"]
        ],
    }
    files = {
        "input": report,
        "context": {"source_run_id": "123", "source_commit_sha": "a" * 40},
        "judge-selection": {
            "format_version": 1,
            "provider": identity["judge_provider"],
            "model": identity["judge_model"],
        },
    }
    argv = ["calibration", "--evidence", str(evidence_path)]
    for name, payload in files.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        argv.extend([f"--{name}", str(path)])
    output = tmp_path / "calibration.json"
    argv.extend(["--output", str(output)])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        calibration,
        "load_corpus",
        lambda **kwargs: load_corpus(path=corpus_path, **kwargs),
    )
    return corpus_path, output


@pytest.mark.parametrize("aggregate_approved", [False, True])
def test_calibration_cli_computes_reviewed_baseline_without_aggregate_approval(
    calibration_cli_files, aggregate_approved
):
    corpus_path, output = calibration_cli_files
    if aggregate_approved:
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        corpus["approval"].update(
            status="approved",
            reviewed_by="Test reviewer",
            reviewed_at="2026-09-11T12:00:00Z",
        )
        corpus["approval"]["calibration"].update(
            agreement=1.0,
            critical_false_passes=0,
            evaluated_at="2026-09-11T12:00:00Z",
        )
        corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
        corpus["approval"]["approved_manifest_sha256"] = approval_manifest_sha256(
            corpus_path
        )
        corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    before = corpus_path.read_bytes()

    calibration.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["agreement"] == 1
    assert report["critical_false_passes"] == 0
    assert report["approved_agreement"] == (1 if aggregate_approved else None)
    assert report["labels"] == sum(
        len(case.rubric_dimensions) for case in load_corpus().cases
    )
    assert corpus_path.read_bytes() == before


@pytest.mark.parametrize(
    ("case_change", "error"),
    [
        ({"status": "pending_human_review"}, "has not completed human review"),
        (
            {"review_run_id": "456"},
            "human review does not match calibration evidence run",
        ),
    ],
)
def test_calibration_cli_rejects_unreviewed_or_different_capture_labels(
    calibration_cli_files, case_change, error
):
    corpus_path, output = calibration_cli_files
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus["cases"][0]["approval"].update(case_change)
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        calibration.main()

    assert not output.exists()


@pytest.mark.parametrize(
    "field",
    ["judge_model", "evidence_run_id", "evidence_commit_sha", "evidence_sha256"],
)
def test_calibration_cli_rejects_missing_pinned_identity(calibration_cli_files, field):
    corpus_path, output = calibration_cli_files
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus["approval"]["calibration"][field] = None
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(
        ValueError, match="requires pinned judge and browser evidence identity"
    ):
        calibration.main()

    assert not output.exists()
