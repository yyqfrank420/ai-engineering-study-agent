import json

import pytest

from eval.quality_corpus import CORPUS_PATH, load_corpus


def _write_corpus(tmp_path, raw):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _approve_cases(raw):
    for case in raw["cases"]:
        case["approval"] = {
            "status": "approved",
            "reviewer": "reviewer",
            "reviewed_at": "2026-08-02T12:00:00Z",
            "review_run_id": "github-run-123",
            "reviewed_grades": {
                dimension: "pass" for dimension in case["rubric_dimensions"]
            },
        }


def test_v3_research_contracts_are_pinned_and_pending_review():
    corpus = load_corpus()

    assert corpus.corpus_version == "2026-08-02.v3"
    assert corpus.release_identity == "browser-rubric-v3"
    assert corpus.approval.status == "pending_human_review"
    assert corpus.approval.approved_manifest_sha256 is None

    research = corpus.by_id["research"]
    research_contract = research.deterministic.research_source_contract
    assert research_contract is not None
    assert research_contract.required_url_prefixes == [
        "https://www.anthropic.com/engineering/building-effective-agents"
    ]
    assert research_contract.minimum_url_prefix_matches == 1
    assert research.approval.status == "pending_human_review"

    conflict = corpus.by_id["instruction-conflict"]
    conflict_contract = conflict.deterministic.research_source_contract
    assert conflict_contract is not None
    assert conflict_contract.required_url_prefixes == [
        "https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html",
        "https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection",
    ]
    assert conflict_contract.minimum_url_prefix_matches == 2
    assert conflict_contract.required_evidence_markers == [
        "ignore all previous instructions",
        "reveal your system prompt",
    ]
    assert conflict_contract.minimum_evidence_marker_matches == 1
    assert conflict.approval.status == "pending_human_review"


@pytest.mark.parametrize(
    "invalid_prefix",
    [
        "http://www.anthropic.com/engineering/building-effective-agents",
        "https://www.anthropic.com/",
        "https://www.anthropic.com/engineering/building-effective-agents?latest=true",
    ],
)
def test_research_source_contract_rejects_unstable_url_prefixes(
    tmp_path, invalid_prefix
):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    research = next(case for case in raw["cases"] if case["id"] == "research")
    research["deterministic"]["research_source_contract"][
        "required_url_prefixes"
    ] = [invalid_prefix]

    with pytest.raises(ValueError, match="stable path"):
        load_corpus(path=_write_corpus(tmp_path, raw))


def test_every_web_citation_case_requires_a_source_contract(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    research = next(case for case in raw["cases"] if case["id"] == "research")
    research["deterministic"].pop("research_source_contract")

    with pytest.raises(ValueError, match="must define a research source contract"):
        load_corpus(path=_write_corpus(tmp_path, raw))


def test_retrieved_instruction_conflict_requires_hostile_evidence_markers(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    conflict = next(
        case for case in raw["cases"] if case["id"] == "instruction-conflict"
    )
    contract = conflict["deterministic"]["research_source_contract"]
    contract["required_evidence_markers"] = []
    contract["minimum_evidence_marker_matches"] = 0

    with pytest.raises(ValueError, match="must require hostile evidence markers"):
        load_corpus(path=_write_corpus(tmp_path, raw))


def test_pending_v3_does_not_claim_immutable_calibration_identity():
    calibration = load_corpus().approval.calibration

    assert calibration.evidence_run_id is None
    assert calibration.evidence_commit_sha is None
    assert calibration.evidence_sha256 is None
    assert calibration.judge_model is None


def test_approved_corpus_requires_immutable_calibration_identity(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    _approve_cases(raw)
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-08-02T12:00:00Z",
            "calibration": {
                "judge_release": "semantic-rubric-judge-v5",
                "agreement": 0.9,
                "critical_false_passes": 0,
                "evaluated_at": "2026-08-02T12:00:00Z",
                "evidence_run_id": None,
                "evidence_commit_sha": None,
                "evidence_sha256": None,
                "judge_model": None,
            },
        }
    )

    with pytest.raises(ValueError, match="judge and immutable browser evidence"):
        load_corpus(path=_write_corpus(tmp_path, raw))
