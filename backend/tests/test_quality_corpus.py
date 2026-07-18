import json

import pytest

from eval.quality_corpus import CORPUS_PATH, corpus_sha256, load_corpus


def test_corpus_has_exactly_twenty_versioned_cases_and_six_anchored_rubrics():
    corpus = load_corpus()

    assert len(corpus.cases) == 20
    assert set(corpus.rubrics) == {
        "correctness",
        "relevance",
        "grounding",
        "instruction_following",
        "domain_specificity",
        "safety",
    }
    assert all(rubric.pass_ and rubric.borderline and rubric.fail for rubric in corpus.rubrics.values())
    assert all(case.provenance and case.risk_tags for case in corpus.cases)


def test_empty_and_oversized_inputs_are_not_live_model_cases():
    corpus = load_corpus()

    prompts = [step.prompt for case in corpus.cases for step in case.steps]
    assert all(prompt.strip() for prompt in prompts)
    assert all(len(prompt.encode("utf-8")) <= 12_000 for prompt in prompts)


def test_pending_corpus_cannot_enable_the_blocking_judge():
    with pytest.raises(RuntimeError, match="pending human review"):
        load_corpus(require_approved=True)


def test_approved_hash_is_content_addressed(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-07-18T12:00:00Z",
            "calibration": {
                "judge_release": "semantic-rubric-judge-v1",
                "agreement": 0.9,
                "critical_false_passes": 1,
                "evaluated_at": "2026-07-18T12:00:00Z",
            },
        }
    )
    for case in raw["cases"]:
        case["approval"].update(
            {
                "status": "approved",
                "reviewer": "reviewer",
                "reviewed_at": "2026-07-18T12:00:00Z",
                "review_run_id": "github-run-123",
                "reviewed_grades": {dimension: "pass" for dimension in case["rubric_dimensions"]},
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    raw["approval"]["approved_manifest_sha256"] = corpus_sha256(path)
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert load_corpus(require_approved=True, path=path).approval.status == "approved"

    raw["cases"][0]["steps"][0]["prompt"] += " changed"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash does not match"):
        load_corpus(require_approved=True, path=path)


@pytest.mark.parametrize(
    ("agreement", "critical_false_passes", "message"),
    [
        (0.84, 0, "85% judge agreement"),
        (0.95, 2, "at most one critical false pass"),
    ],
)
def test_approved_corpus_rejects_uncalibrated_judge(
    tmp_path, agreement, critical_false_passes, message
):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-07-18T12:00:00Z",
            "calibration": {
                "judge_release": "semantic-rubric-judge-v1",
                "agreement": agreement,
                "critical_false_passes": critical_false_passes,
                "evaluated_at": "2026-07-18T12:00:00Z",
            },
        }
    )
    for case in raw["cases"]:
        case["approval"].update(
            {
                "status": "approved",
                "reviewer": "reviewer",
                "reviewed_at": "2026-07-18T12:00:00Z",
                "review_run_id": "github-run-123",
                "reviewed_grades": {dimension: "pass" for dimension in case["rubric_dimensions"]},
            }
        )
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_corpus(path=path)
