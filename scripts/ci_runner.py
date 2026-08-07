from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
# Argument-vector subprocesses are the runner's core execution boundary.
import subprocess  # nosec B404
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "ci" / "quality.json"
ZERO_SHA = "0" * 40

TEST_ENV_DEFAULTS = {
    "ANTHROPIC_API_KEY": "test-disabled",
    "OPENAI_API_KEY": "",
    "SUPABASE_URL": "https://ci-dummy.supabase.co",
    "SUPABASE_ANON_KEY": "ci-dummy",
    "SUPABASE_DB_URL": "",
    "SUPABASE_JWT_ISSUER": "https://ci-dummy.supabase.co/auth/v1",
    "SUPABASE_JWT_SECRET": "ci-dummy-secret-at-least-32-characters-long",
    "TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
    "FAISS_ARTIFACT_URL": "https://ci-dummy.example.com/faiss.tar.gz",
    "FAISS_ARTIFACT_SHA256": "0" * 64,
    "FRONTEND_ORIGIN": "http://localhost:5173",
    "VITE_API_URL": "https://ci-placeholder.run.app",
    "PYTHONPATH": "backend",
}


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("ci/quality.json must use schema_version 1")
    return data


def group_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = manifest.get("offline_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("ci/quality.json must define offline_groups")
    mapped = {group["name"]: group for group in groups}
    if len(mapped) != len(groups):
        raise ValueError("offline group names must be unique")
    return mapped


def _command_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name, value in TEST_ENV_DEFAULTS.items():
        environment.setdefault(name, value)
    return environment


def run_offline(manifest: dict[str, Any], selected_group: str | None) -> None:
    groups = group_map(manifest)
    selected = [groups[selected_group]] if selected_group else list(groups.values())
    for group in selected:
        print(f"\n[{group['name']}]", flush=True)
        for command in group["commands"]:
            cwd = ROOT / command.get("cwd", ".")
            argv = list(command["argv"])
            if argv[0] == "python":
                argv[0] = sys.executable
            print(f"  [run] {command['name']}", flush=True)
            # argv comes only from the reviewed, versioned quality manifest.
            subprocess.run(argv, cwd=cwd, env=_command_environment(), check=True)  # nosec B603


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_paths(paths: list[str], manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = sorted({path.strip().removeprefix("./") for path in paths if path.strip()})
    rules = manifest["impact"]
    docs = [path for path in normalized if _matches(path, rules["documentation"])]
    visual = [path for path in normalized if _matches(path, rules["visual_only"])]
    explicit_ai = [path for path in normalized if _matches(path, rules["ai"])]
    classified_non_ai = set(docs) | set(visual)
    fail_safe_ai = [path for path in normalized if path not in classified_non_ai and path not in explicit_ai]
    ai_paths = sorted(set(explicit_ai) | set(fail_safe_ai))
    return {
        "paths": normalized,
        "docs_only": bool(normalized) and len(docs) == len(normalized),
        "visual_only": bool(normalized) and len(classified_non_ai) == len(normalized) and bool(visual),
        "ai_impact": bool(ai_paths),
        "ai_paths": ai_paths,
        "reasons": {
            "explicit_ai": explicit_ai,
            "unclassified_fail_safe": fail_safe_ai,
        },
    }


def trust_for_event(event: dict[str, Any]) -> tuple[bool, str]:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    if "pull_request" in event:
        pull = event["pull_request"]
        head_repo = ((pull.get("head") or {}).get("repo") or {}).get("full_name")
        base_repo = ((pull.get("base") or {}).get("repo") or {}).get("full_name")
        trusted = bool(head_repo and base_repo and head_repo == base_repo)
        return trusted, "same-repository pull request" if trusted else "fork pull request"
    if event_name in {"push", "merge_group", "workflow_dispatch", "schedule", "workflow_run"}:
        return True, f"trusted {event_name} event"
    if "merge_group" in event:
        return True, "trusted merge queue event"
    return False, f"unsupported event '{event_name or 'unknown'}'"


def _git_changed_paths(base: str, head: str) -> list[str]:
    # Fixed git argv; no shell or path supplied by the event payload.
    completed = subprocess.run(  # nosec B603, B607
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.splitlines()


def _event_revisions(event: dict[str, Any]) -> tuple[str, str]:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    if "pull_request" in event:
        pull = event["pull_request"]
        return pull["base"]["sha"], pull["head"]["sha"]
    if "merge_group" in event:
        merge_group = event["merge_group"]
        return merge_group["base_sha"], merge_group["head_sha"]
    before = str(event.get("before") or "")
    after = str(event.get("after") or os.getenv("GITHUB_SHA", "HEAD"))
    if event_name == "push" and before and before != ZERO_SHA:
        return before, after
    return f"{after}^", after


def _write_github_output(payload: dict[str, Any]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        raise RuntimeError("--github-output requires GITHUB_OUTPUT")
    with Path(output_path).open("a", encoding="utf-8") as output:
        for key, value in payload.items():
            rendered = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value).lower() if isinstance(value, bool) else str(value)
            output.write(f"{key.replace('_', '-')}={rendered}\n")


def impact_command(args: argparse.Namespace, manifest: dict[str, Any]) -> None:
    event: dict[str, Any] = {}
    if args.event_file:
        event = json.loads(Path(args.event_file).read_text(encoding="utf-8"))
    if args.paths_from:
        paths = Path(args.paths_from).read_text(encoding="utf-8").splitlines()
    else:
        base, head = (args.base, args.head) if args.base and args.head else _event_revisions(event)
        paths = _git_changed_paths(base, head)
    result = classify_paths(paths, manifest)
    trusted, trust_reason = trust_for_event(event)
    result.update({"trusted": trusted, "trust_reason": trust_reason})
    if args.github_output:
        _write_github_output(result)
    print(json.dumps(result, indent=2, sort_keys=True))


def _explicit_test_paths(manifest: dict[str, Any]) -> set[str]:
    tracking = manifest["test_tracking"]
    owning_groups = set(tracking["explicit_backend_groups"])
    paths: set[str] = set()
    for group in manifest["offline_groups"]:
        if group["name"] not in owning_groups:
            continue
        for command in group["commands"]:
            paths.update(arg for arg in command["argv"] if arg.startswith("backend/tests/test_") and arg.endswith(".py"))
    return paths


def _test_owners(manifest: dict[str, Any]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    owning_groups = set(manifest["test_tracking"]["explicit_backend_groups"])
    for group in manifest["offline_groups"]:
        if group["name"] not in owning_groups:
            continue
        for command in group["commands"]:
            for argument in command["argv"]:
                if argument.startswith("backend/tests/test_") and argument.endswith(".py"):
                    owners.setdefault(argument, set()).add(group["name"])
    return owners


def select_offline_groups(paths: list[str], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Select owning groups, falling back to the full matrix for unknown or policy changes."""
    groups = group_map(manifest)
    selection = manifest["offline_selection"]
    normalized = sorted({path.strip().removeprefix("./") for path in paths if path.strip()})
    if not normalized or any(_matches(path, selection["full_run_paths"]) for path in normalized):
        return list(groups.values())

    selected = set(selection["always"])
    test_owners = _test_owners(manifest)
    documentation_patterns = manifest["impact"]["documentation"]
    for path in normalized:
        owners = set(test_owners.get(path, set()))
        owners.update(
            group_name
            for group_name, patterns in selection["groups"].items()
            if _matches(path, patterns)
        )
        if not owners and not _matches(path, documentation_patterns):
            return list(groups.values())
        selected.update(owners)

    return [group for group in groups.values() if group["name"] in selected]


def validate_manifest(manifest: dict[str, Any]) -> None:
    groups = group_map(manifest)
    for group in groups.values():
        if group.get("runtime") not in {"python", "node", "infra", "docker"}:
            raise ValueError(f"unsupported runtime for {group['name']}")
        if not group.get("commands"):
            raise ValueError(f"offline group {group['name']} has no commands")
    selection = manifest.get("offline_selection")
    if not isinstance(selection, dict):
        raise ValueError("ci/quality.json must define offline_selection")
    selection_groups = set(selection.get("groups", {}))
    unknown_selection_groups = sorted(selection_groups - set(groups))
    missing_selection_groups = sorted(set(groups) - selection_groups)
    if unknown_selection_groups or missing_selection_groups:
        raise ValueError(
            "offline selection group mismatch: unknown="
            f"{unknown_selection_groups}, missing={missing_selection_groups}"
        )
    unknown_always_groups = sorted(set(selection.get("always", [])) - set(groups))
    if unknown_always_groups:
        raise ValueError(f"offline selection has unknown always groups: {unknown_always_groups}")
    if not selection.get("full_run_paths"):
        raise ValueError("offline selection must define fail-safe full_run_paths")
    tracked = {str(path.relative_to(ROOT)) for path in ROOT.glob(manifest["test_tracking"]["explicit_backend_glob"])}
    explicit = _explicit_test_paths(manifest)
    missing = sorted(tracked - explicit)
    stale = sorted(explicit - tracked)
    if missing or stale:
        details = []
        if missing:
            details.append("unassigned tests: " + ", ".join(missing))
        if stale:
            details.append("missing test files: " + ", ".join(stale))
        raise ValueError("; ".join(details))
    suite_ids = manifest["live"]["suites"]
    if len(suite_ids["pr"]) != manifest["live"]["budgets"]["pr_cases"]:
        raise ValueError("the PR live suite must match live.budgets.pr_cases")


def _dispatch_eval(kind: str, args: argparse.Namespace) -> None:
    module = "eval.browser_runner" if kind == "browser" else "eval.live_runner"
    argv = [sys.executable, "-m", module, "--suite", args.suite, "--target", args.target]
    if args.output:
        argv.extend(["--output", args.output])
    if getattr(args, "input", None):
        argv.extend(["--input", args.input])
    if getattr(args, "require_approved_corpus", False):
        argv.append("--require-approved-corpus")
    if getattr(args, "manual_review_policy", "blocking") != "blocking":
        argv.extend(["--manual-review-policy", args.manual_review_policy])
    if getattr(args, "capture_replay", False):
        argv.append("--capture-replay")
    if getattr(args, "resume_input", None):
        argv.extend(["--resume-input", args.resume_input])
    for case_id in getattr(args, "case", []):
        argv.extend(["--case", case_id])
    # Module and argument structure are fixed; user values remain individual argv entries.
    subprocess.run(argv, cwd=ROOT, env=_command_environment(), check=True)  # nosec B603


def _groups_json(groups: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"include": [{"group": group["name"], "runtime": group["runtime"]} for group in groups]},
        separators=(",", ":"),
    )


def _changed_paths_for_args(args: argparse.Namespace) -> list[str] | None:
    if args.paths_from:
        return Path(args.paths_from).read_text(encoding="utf-8").splitlines()
    if args.event_file:
        event = json.loads(Path(args.event_file).read_text(encoding="utf-8"))
        base, head = _event_revisions(event)
        return _git_changed_paths(base, head)
    if args.base and args.head:
        return _git_changed_paths(args.base, args.head)
    return None


def _record_override(args: argparse.Namespace) -> None:
    required = {"run_id": args.run_id, "commit_sha": args.commit_sha, "reviewer": args.reviewer, "reason": args.reason}
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise ValueError("manual override is missing: " + ", ".join(missing))
    if len(args.commit_sha) != 40 or any(char not in "0123456789abcdefABCDEF" for char in args.commit_sha):
        raise ValueError("manual override commit SHA must be a full 40-character hexadecimal SHA")
    actor = os.getenv("GITHUB_ACTOR", args.reviewer)
    if actor != args.reviewer:
        raise ValueError("manual override reviewer must match the authenticated GitHub actor")
    audit = {**required, "actor": actor, "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local")}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote audited override to {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonical local and GitHub quality runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    offline = subparsers.add_parser("offline")
    offline.add_argument("--group", choices=[group["name"] for group in load_manifest()["offline_groups"]])
    groups = subparsers.add_parser("groups")
    groups.add_argument("--base")
    groups.add_argument("--head")
    groups.add_argument("--paths-from")
    groups.add_argument("--event-file")
    groups.add_argument("--github-output", action="store_true")
    impact = subparsers.add_parser("impact")
    impact.add_argument("--base")
    impact.add_argument("--head")
    impact.add_argument("--paths-from")
    impact.add_argument("--event-file")
    impact.add_argument("--github-output", action="store_true")
    subparsers.add_parser("validate")
    for name in ("live", "browser"):
        evaluation = subparsers.add_parser(name)
        evaluation.add_argument("--suite", required=True)
        evaluation.add_argument("--target", required=True)
        evaluation.add_argument("--output")
        evaluation.add_argument("--case", action="append", default=[])
        if name == "live":
            evaluation.add_argument("--input")
            evaluation.add_argument("--require-approved-corpus", action="store_true")
            evaluation.add_argument(
                "--manual-review-policy",
                choices=("blocking", "report-only"),
                default="blocking",
            )
            evaluation.add_argument("--capture-replay", action="store_true")
            evaluation.add_argument("--resume-input")
    override = subparsers.add_parser("override")
    override.add_argument("--run-id", required=True)
    override.add_argument("--commit-sha", required=True)
    override.add_argument("--reviewer", required=True)
    override.add_argument("--reason", required=True)
    override.add_argument("--output", default="artifacts/live-eval/manual-override.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = load_manifest()
    if args.command == "offline":
        run_offline(manifest, args.group)
    elif args.command == "groups":
        changed_paths = _changed_paths_for_args(args)
        selected_groups = (
            select_offline_groups(changed_paths, manifest)
            if changed_paths is not None
            else list(group_map(manifest).values())
        )
        payload = _groups_json(selected_groups)
        if args.github_output:
            _write_github_output({"matrix": json.loads(payload)})
        print(payload)
    elif args.command == "impact":
        impact_command(args, manifest)
    elif args.command == "validate":
        validate_manifest(manifest)
        digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        print(f"CI manifest valid ({digest})")
    elif args.command in {"live", "browser"}:
        _dispatch_eval(args.command, args)
    elif args.command == "override":
        _record_override(args)


if __name__ == "__main__":
    main()
