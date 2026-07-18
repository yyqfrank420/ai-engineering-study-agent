from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CORPUS_PATH = Path(__file__).resolve().parent / "corpus" / "v1" / "cases.json"
ApprovalStatus = Literal["pending_human_review", "approved"]
DimensionGrade = Literal["pass", "borderline", "fail"]


class JudgeCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judge_release: str
    agreement: float | None = Field(default=None, ge=0, le=1)
    critical_false_passes: int | None = Field(default=None, ge=0)
    evaluated_at: str | None


class CorpusApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApprovalStatus
    reviewed_by: str | None
    reviewed_at: str | None
    approved_manifest_sha256: str | None
    calibration: JudgeCalibration
    notes: str


class RubricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critical: bool
    pass_: str = Field(alias="pass")
    borderline: str
    fail: str


class CaseApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApprovalStatus
    reviewer: str | None
    reviewed_at: str | None
    review_run_id: str | None = None
    reviewed_grades: dict[str, DimensionGrade] = Field(default_factory=dict)
    approved_exemplar: str | None = Field(default=None, max_length=2000)


class UIMode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complexity: Literal["auto", "low", "prototype", "production"]
    graph_mode: Literal["auto", "on", "off"]
    research_enabled: bool


class ConversationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12_000)
    ui: UIMode


class DeterministicExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int = Field(ge=100, le=599)
    route: Literal["simple", "memory", "search"] | None
    workers_include: list[str]
    workers_exclude: list[str]
    persistence: bool
    streaming_complete: bool
    graph_emitted: bool | None
    graph_renderable: bool | None
    citations_required: bool
    error_expected: bool
    cleanup: bool


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    category: str
    risk_tags: list[str] = Field(min_length=1)
    provenance: str
    steps: list[ConversationStep] = Field(min_length=1)
    deterministic: DeterministicExpectation
    rubric_dimensions: list[str] = Field(min_length=1)
    approval: CaseApproval


class EvaluationCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[1]
    corpus_version: str
    release_identity: str
    approval: CorpusApproval
    rubrics: dict[str, RubricDefinition]
    cases: list[EvaluationCase] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def validate_references_and_approval(self) -> "EvaluationCorpus":
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation case IDs must be unique")
        rubric_names = set(self.rubrics)
        for case in self.cases:
            unknown = sorted(set(case.rubric_dimensions) - rubric_names)
            if unknown:
                raise ValueError(f"case {case.id} references unknown rubrics: {unknown}")
            if case.approval.status == "approved":
                if not case.approval.reviewer or not case.approval.reviewed_at:
                    raise ValueError(f"approved case {case.id} must identify its reviewer and review time")
                if not case.approval.review_run_id:
                    raise ValueError(f"approved case {case.id} must identify its reviewed artifact run")
                if set(case.approval.reviewed_grades) != set(case.rubric_dimensions):
                    raise ValueError(f"approved case {case.id} must label every rubric dimension")
        if self.approval.status == "approved":
            pending = [case.id for case in self.cases if case.approval.status != "approved"]
            if pending:
                raise ValueError("an approved corpus cannot contain pending cases")
            if not self.approval.reviewed_by or not self.approval.reviewed_at:
                raise ValueError("approved corpus metadata must identify the reviewer and review time")
            calibration = self.approval.calibration
            if calibration.agreement is None or calibration.agreement < 0.85:
                raise ValueError("approved corpus requires at least 85% judge agreement")
            if calibration.critical_false_passes is None or calibration.critical_false_passes > 1:
                raise ValueError("approved corpus permits at most one critical false pass")
            if not calibration.evaluated_at:
                raise ValueError("approved corpus calibration must record its evaluation time")
        return self

    @property
    def by_id(self) -> dict[str, EvaluationCase]:
        return {case.id: case for case in self.cases}


def corpus_sha256(path: Path = CORPUS_PATH) -> str:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    # The approval records the digest and therefore cannot itself participate
    # in that digest. All behavior-bearing case/rubric content remains covered.
    parsed["approval"]["approved_manifest_sha256"] = None
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_corpus(*, require_approved: bool = False, path: Path = CORPUS_PATH) -> EvaluationCorpus:
    corpus = EvaluationCorpus.model_validate_json(path.read_text(encoding="utf-8"))
    if require_approved:
        digest = corpus_sha256(path)
        if corpus.approval.status != "approved":
            raise RuntimeError(
                "The semantic corpus is pending human review. Review all 20 cases and record the approved manifest hash before enabling the blocking judge."
            )
        if corpus.approval.approved_manifest_sha256 != digest:
            raise RuntimeError("The approved corpus hash does not match the current manifest")
    return corpus
