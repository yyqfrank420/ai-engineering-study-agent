"""Validate browser evidence for calibration and selective semantic replay."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
QUALITY_MANIFEST = ROOT / "ci" / "quality.json"
CASE_ID_PATTERN = re.compile(r"[a-z0-9-]+")
ARTIFACT_NAME_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,253}[A-Za-z0-9])?"
)
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
IMAGE_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
GRAPH_OPERATION_PREFIXES = (
    "graph_", "staged_graph_", "architecture_", "node_selected_"
)


class EvidenceReplayError(ValueError):
    """Raised when source evidence cannot be safely replayed."""


@dataclass(frozen=True)
class SourceEvidenceIdentity:
    run_id: str
    artifact_name: str
    artifact_sha256: str
    head_sha: str
    tested_commit_sha: str
    tree_sha: str
    image_digest: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SourceEvidenceIdentity:
        if not isinstance(value, Mapping):
            raise EvidenceReplayError("source identity must be an object")
        try:
            identity = cls(
                run_id=value["run_id"],
                artifact_name=value["artifact_name"],
                artifact_sha256=value["artifact_sha256"],
                head_sha=value["head_sha"],
                tested_commit_sha=value["tested_commit_sha"],
                tree_sha=value["tree_sha"],
                image_digest=value["image_digest"],
            )
        except KeyError as exc:
            raise EvidenceReplayError(
                f"source identity is missing {exc.args[0]}"
            ) from exc
        identity.validate()
        return identity

    def validate(self) -> None:
        if not isinstance(self.run_id, str) or not re.fullmatch(r"[0-9]+", self.run_id):
            raise EvidenceReplayError("source run_id must be numeric text")
        if not isinstance(self.artifact_name, str) or not ARTIFACT_NAME_PATTERN.fullmatch(
            self.artifact_name
        ):
            raise EvidenceReplayError("source artifact_name is unsafe")
        for name, value, pattern in (
            ("artifact_sha256", self.artifact_sha256, SHA256_PATTERN),
            ("head_sha", self.head_sha, SHA_PATTERN),
            ("tested_commit_sha", self.tested_commit_sha, SHA_PATTERN),
            ("tree_sha", self.tree_sha, SHA_PATTERN),
            ("image_digest", self.image_digest, IMAGE_DIGEST_PATTERN),
        ):
            if not isinstance(value, str) or not pattern.fullmatch(value):
                raise EvidenceReplayError(f"source {name} is invalid")


def canonical_pr_case_ids(
    manifest_path: Path = QUALITY_MANIFEST,
) -> tuple[str, ...]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_ids = manifest.get("live", {}).get("suites", {}).get("pr")
    if not isinstance(case_ids, list) or not case_ids:
        raise EvidenceReplayError("quality manifest has no canonical PR suite")
    _validate_case_id_sequence(case_ids, "canonical PR suite")
    return tuple(case_ids)


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_case_id_sequence(values: Sequence[Any], label: str) -> None:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EvidenceReplayError(f"{label} must be a sequence")
    if not values:
        raise EvidenceReplayError(f"{label} must not be empty")
    if any(
        not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id)
        for case_id in values
    ):
        raise EvidenceReplayError(f"{label} contains an invalid case ID")
    if len(values) != len(set(values)):
        raise EvidenceReplayError(f"{label} contains duplicate case IDs")


def _raw_items_by_id(
    document: Mapping[str, Any], key: str, label: str
) -> tuple[list[Mapping[str, Any]], list[str], dict[str, Mapping[str, Any]]]:
    raw_items = document.get(key)
    if not isinstance(raw_items, list):
        raise EvidenceReplayError(f"source capture {label} must be a list")
    items: list[Mapping[str, Any]] = []
    case_ids: list[str] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise EvidenceReplayError(f"source capture {label} contains a non-object")
        case_id = raw_item.get("id")
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
            raise EvidenceReplayError(f"source capture {label} contains an invalid case ID")
        items.append(raw_item)
        case_ids.append(case_id)
    if len(case_ids) != len(set(case_ids)):
        raise EvidenceReplayError(f"source capture {label} contains duplicate case IDs")
    return items, case_ids, dict(zip(case_ids, items, strict=True))


def validate_calibration_capture(
    capture: Mapping[str, Any], corpus: Mapping[str, Any]
) -> None:
    """Accept complete observations, including product failures, for human calibration.

    Callers authenticate the original capture bytes and source commit separately.
    Source provider accounting does not determine whether an answer is reviewable.
    """
    if (
        capture.get("format_version") != 1
        or capture.get("kind") != "browser_capture"
        or capture.get("suite") != "full"
        or capture.get("status") != "complete"
    ):
        raise EvidenceReplayError("calibration requires a complete full browser capture")
    for key in ("corpus_version", "release_identity"):
        if not corpus.get(key) or capture.get(key) != corpus[key]:
            raise EvidenceReplayError(f"calibration capture {key} does not match")
    cases, expected_ids, _ = _raw_items_by_id(corpus, "cases", "corpus cases")
    results, actual_ids, _ = _raw_items_by_id(capture, "results", "results")
    states, state_ids, _ = _raw_items_by_id(capture, "case_states", "case states")
    if not expected_ids or actual_ids != expected_ids or state_ids != expected_ids:
        raise EvidenceReplayError("calibration requires the exact ordered full corpus")
    if (capture.get("dashboard_smoke") or {}).get("passed") is not True:
        raise EvidenceReplayError("calibration browser dashboard smoke did not pass")
    for case, result, state in zip(cases, results, states, strict=True):
        case_id = case["id"]
        if result.get("execution_state") != "completed" or state.get("state") != "completed":
            raise EvidenceReplayError(f"calibration case {case_id} did not complete")
        failures = result.get("deterministic_failures")
        details = result.get("failure_details")
        if (
            type(result.get("passed")) is not bool
            or not isinstance(failures, list)
            or any(not isinstance(failure, str) or not failure for failure in failures)
            or not isinstance(details, list)
            or any(not isinstance(detail, Mapping) or detail.get("kind") != "quality" for detail in details)
            or result["passed"] != (not failures)
            or bool(failures) != bool(details)
        ):
            raise EvidenceReplayError(f"calibration case {case_id} has invalid or infrastructure failure evidence")
        turns = result.get("turns")
        steps = case.get("steps")
        events = result.get("events")
        if (
            not isinstance(steps, list) or not steps
            or not isinstance(turns, list) or len(turns) != len(steps)
            or not isinstance(events, list)
            or any(not isinstance(event, Mapping) for event in events)
        ):
            raise EvidenceReplayError(f"calibration case {case_id} has incomplete turn evidence")
        completed_turns = {
            event.get("eval_turn") for event in events
            if event.get("type") == "done" and type(event.get("eval_turn")) is int
        }
        if completed_turns != set(range(1, len(steps) + 1)):
            raise EvidenceReplayError(f"calibration case {case_id} is missing terminal turn events")
        for index, (turn, step) in enumerate(zip(turns, steps, strict=True), start=1):
            if (
                not isinstance(turn, Mapping) or not isinstance(step, Mapping)
                or type(turn.get("turn")) is not int or turn["turn"] != index
                or turn.get("prompt") != step.get("prompt")
                or not isinstance(turn.get("answer"), str) or not turn["answer"].strip()
            ):
                raise EvidenceReplayError(f"calibration case {case_id} turn {index} has missing or mismatched evidence")
        for field in ("screenshot", "trace"):
            reference = result.get(field)
            if (
                not isinstance(reference, str) or not reference
                or Path(reference).is_absolute() or ".." in Path(reference).parts
            ):
                raise EvidenceReplayError(f"calibration case {case_id} has invalid {field} evidence")


def _collect_thread_ids(value: Any) -> set[str]:
    thread_ids: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if key == "thread_id":
                    if not isinstance(child, str) or not child:
                        raise EvidenceReplayError("case evidence contains an invalid thread_id")
                    thread_ids.add(child)
                elif key == "thread_ids":
                    if not isinstance(child, list) or any(
                        not isinstance(thread_id, str) or not thread_id
                        for thread_id in child
                    ):
                        raise EvidenceReplayError("case evidence contains invalid thread_ids")
                    thread_ids.update(child)
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return thread_ids


def _validate_source_identity_fields(capture: Mapping[str, Any]) -> None:
    if capture.get("format_version") != 1:
        raise EvidenceReplayError("source capture format_version must be 1")
    if capture.get("kind") != "browser_capture" or capture.get("suite") != "pr":
        raise EvidenceReplayError("source capture must be a PR browser capture")
    if capture.get("status") != "complete":
        raise EvidenceReplayError("source capture is not complete")
    corpus_sha256 = capture.get("corpus_sha256")
    if not isinstance(corpus_sha256, str) or not SHA256_PATTERN.fullmatch(corpus_sha256):
        raise EvidenceReplayError("source capture corpus_sha256 is invalid")
    for key in (
        "corpus_version",
        "release_identity",
        "target",
        "backend_target",
        "started_at",
    ):
        if not isinstance(capture.get(key), str) or not capture[key]:
            raise EvidenceReplayError(f"source capture {key} is missing")


def subset_browser_capture(
    source_capture: Mapping[str, Any],
    *,
    selected_case_ids: Sequence[str],
    expected_source_case_ids: Sequence[str] | None = None,
    forbidden_operation_prefixes: Sequence[str] = GRAPH_OPERATION_PREFIXES,
) -> dict[str, Any]:
    """Return a diagnostic capture containing only reusable passing cases."""

    if not isinstance(source_capture, Mapping):
        raise EvidenceReplayError("source capture must be an object")
    _validate_source_identity_fields(source_capture)
    expected = tuple(
        canonical_pr_case_ids()
        if expected_source_case_ids is None
        else expected_source_case_ids
    )
    selected = tuple(selected_case_ids)
    _validate_case_id_sequence(expected, "expected source cases")
    _validate_case_id_sequence(selected, "selected cases")
    unknown = sorted(set(selected) - set(expected))
    if unknown:
        raise EvidenceReplayError(f"selected cases are not in the source suite: {unknown}")
    canonical_selection = tuple(case_id for case_id in expected if case_id in selected)
    if selected != canonical_selection:
        raise EvidenceReplayError("selected cases must follow canonical PR order")

    results, result_ids, results_by_id = _raw_items_by_id(
        source_capture, "results", "results"
    )
    states, state_ids, states_by_id = _raw_items_by_id(
        source_capture, "case_states", "case_states"
    )
    if tuple(result_ids) != expected:
        raise EvidenceReplayError("source result IDs do not match the canonical PR suite")
    if tuple(state_ids) != expected:
        raise EvidenceReplayError("source case-state IDs do not match the canonical PR suite")
    if any(result.get("execution_state") != "completed" for result in results):
        raise EvidenceReplayError("source capture contains an incomplete result")
    if any(state.get("state") != "completed" for state in states):
        raise EvidenceReplayError("source capture contains an incomplete case state")

    thread_owners: dict[str, str] = {}
    case_threads: dict[str, set[str]] = {}
    for case_id, result in results_by_id.items():
        thread_ids = _collect_thread_ids(result)
        case_threads[case_id] = thread_ids
        for thread_id in thread_ids:
            previous_owner = thread_owners.get(thread_id)
            if previous_owner is not None and previous_owner != case_id:
                raise EvidenceReplayError(
                    f"thread {thread_id} is attributed to multiple cases"
                )
            thread_owners[thread_id] = case_id

    selected_set = set(selected)
    selected_threads: set[str] = set()
    for case_id in selected:
        result = results_by_id[case_id]
        if result.get("passed") is not True:
            raise EvidenceReplayError(f"selected case {case_id} did not pass")
        attempts = result.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise EvidenceReplayError(f"selected case {case_id} has no attempt evidence")
        if not case_threads[case_id]:
            raise EvidenceReplayError(f"selected case {case_id} has no thread identity")
        selected_threads.update(case_threads[case_id])

    raw_telemetry = source_capture.get("application_telemetry")
    if not isinstance(raw_telemetry, list):
        raise EvidenceReplayError("source capture application_telemetry must be a list")
    selected_telemetry: list[dict[str, Any]] = []
    selected_threads_with_telemetry: set[str] = set()
    for call_index, raw_call in enumerate(raw_telemetry, start=1):
        if not isinstance(raw_call, Mapping):
            raise EvidenceReplayError(f"application telemetry call {call_index} is not an object")
        thread_id = raw_call.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise EvidenceReplayError(f"application telemetry call {call_index} has no thread_id")
        case_id = thread_owners.get(thread_id)
        if case_id is None:
            raise EvidenceReplayError(
                f"application telemetry call {call_index} is not attributed to a source case"
            )
        if case_id not in selected_set:
            continue
        operation = raw_call.get("operation")
        if not isinstance(operation, str) or not operation:
            raise EvidenceReplayError(
                f"selected application telemetry call {call_index} has no operation"
            )
        if any(operation.startswith(prefix) for prefix in forbidden_operation_prefixes):
            raise EvidenceReplayError(
                f"selected case {case_id} used graph operation {operation}"
            )
        provider_attempts = raw_call.get("provider_attempts")
        if (
            isinstance(provider_attempts, bool)
            or not isinstance(provider_attempts, int)
            or provider_attempts <= 0
        ):
            raise EvidenceReplayError(
                f"selected application telemetry call {call_index} has invalid provider_attempts"
            )
        selected_threads_with_telemetry.add(thread_id)
        selected_telemetry.append(copy.deepcopy(dict(raw_call)))
    missing_telemetry = sorted(selected_threads - selected_threads_with_telemetry)
    if missing_telemetry:
        raise EvidenceReplayError(
            f"selected case threads have no application telemetry: {missing_telemetry}"
        )

    return {
        "format_version": source_capture["format_version"],
        "kind": source_capture["kind"],
        "suite": "diagnostic",
        "corpus_version": source_capture["corpus_version"],
        "corpus_sha256": source_capture["corpus_sha256"],
        "release_identity": source_capture["release_identity"],
        "target": source_capture["target"],
        "backend_target": source_capture["backend_target"],
        "started_at": source_capture["started_at"],
        "status": "complete",
        "case_states": [copy.deepcopy(dict(states_by_id[case_id])) for case_id in selected],
        "results": [copy.deepcopy(dict(results_by_id[case_id])) for case_id in selected],
        "application_telemetry": selected_telemetry,
    }


def write_selective_replay_artifacts(
    *,
    source_capture_path: Path,
    source_identity: SourceEvidenceIdentity,
    output_capture_path: Path,
    output_provenance_path: Path,
    selected_case_ids: Sequence[str],
    replay_run_id: str,
    replay_commit_sha: str,
    actor: str,
    reason: str,
    expected_source_case_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate, subset, write, and hash selective replay artifacts."""

    source_identity.validate()
    if not isinstance(replay_run_id, str) or not re.fullmatch(r"[0-9]+", replay_run_id):
        raise EvidenceReplayError("replay run ID must be numeric")
    if not isinstance(replay_commit_sha, str) or not SHA_PATTERN.fullmatch(
        replay_commit_sha
    ):
        raise EvidenceReplayError("replay commit SHA is invalid")
    if not isinstance(actor, str) or not actor:
        raise EvidenceReplayError("replay actor is missing")
    if not isinstance(reason, str) or len(reason) < 20:
        raise EvidenceReplayError("replay reason must be at least 20 characters")
    resolved_paths = {
        source_capture_path.resolve(),
        output_capture_path.resolve(),
        output_provenance_path.resolve(),
    }
    if len(resolved_paths) != 3:
        raise EvidenceReplayError("source and output paths must be distinct")

    source_bytes = source_capture_path.read_bytes()
    try:
        source_capture = json.loads(source_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceReplayError("source capture is not valid UTF-8 JSON") from exc
    derived_capture = subset_browser_capture(
        source_capture,
        selected_case_ids=selected_case_ids,
        expected_source_case_ids=expected_source_case_ids,
    )
    derived_bytes = canonical_json_bytes(derived_capture)
    provider_attempts = sum(
        call["provider_attempts"] for call in derived_capture["application_telemetry"]
    )
    selected_threads = sorted(
        {call["thread_id"] for call in derived_capture["application_telemetry"]}
    )
    provenance = {
        "schema_version": 1,
        "kind": "selective_semantic_replay",
        "source": {
            **asdict(source_identity),
            "browser_capture_sha256": sha256_bytes(source_bytes),
        },
        "selection": {
            "case_ids": list(selected_case_ids),
            "thread_ids": selected_threads,
            "provider_attempts": provider_attempts,
            "forbidden_operation_prefixes": list(GRAPH_OPERATION_PREFIXES),
        },
        "derived": {
            "browser_capture_sha256": sha256_bytes(derived_bytes),
            "suite": "diagnostic",
            "corpus_version": derived_capture["corpus_version"],
            "corpus_sha256": derived_capture["corpus_sha256"],
            "release_identity": derived_capture["release_identity"],
            "backend_target": derived_capture["backend_target"],
        },
        "replay": {
            "run_id": replay_run_id,
            "commit_sha": replay_commit_sha,
            "actor": actor,
            "reason": reason,
        },
    }
    output_capture_path.parent.mkdir(parents=True, exist_ok=True)
    output_provenance_path.parent.mkdir(parents=True, exist_ok=True)
    output_capture_path.write_bytes(derived_bytes)
    output_provenance_path.write_bytes(canonical_json_bytes(provenance))
    return provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subset = subparsers.add_parser("subset")
    subset.add_argument("--source-capture", type=Path, required=True)
    subset.add_argument("--source-identity", type=Path, required=True)
    subset.add_argument("--output-capture", type=Path, required=True)
    subset.add_argument("--output-provenance", type=Path, required=True)
    subset.add_argument("--case", action="append", required=True)
    subset.add_argument("--replay-run-id", required=True)
    subset.add_argument("--replay-commit-sha", required=True)
    subset.add_argument("--actor", required=True)
    subset.add_argument("--reason", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        source_identity = SourceEvidenceIdentity.from_mapping(
            json.loads(args.source_identity.read_text(encoding="utf-8"))
        )
        provenance = write_selective_replay_artifacts(
            source_capture_path=args.source_capture,
            source_identity=source_identity,
            output_capture_path=args.output_capture,
            output_provenance_path=args.output_provenance,
            selected_case_ids=args.case,
            replay_run_id=args.replay_run_id,
            replay_commit_sha=args.replay_commit_sha,
            actor=args.actor,
            reason=args.reason,
        )
    except (EvidenceReplayError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(provenance, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
