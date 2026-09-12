from __future__ import annotations

import inspect
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from config import Settings
from eval.browser_runner import _execute_browser, _run_browser_attempt
from eval.quality_corpus import approval_manifest_sha256, corpus_sha256, load_corpus
from scripts.ci_runner import (
    _command_environment,
    classify_paths,
    TEST_ENV_DEFAULTS,
    load_manifest,
    run_offline,
    select_offline_groups,
    trust_for_event,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


def test_ci_environment_defaults_include_frontend_supabase_client_config(monkeypatch):
    monkeypatch.delenv("VITE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("VITE_SUPABASE_ANON_KEY", raising=False)

    environment = _command_environment()

    assert environment["VITE_SUPABASE_URL"] == "http://127.0.0.1:54321"
    assert environment["VITE_SUPABASE_ANON_KEY"] == "ci-test-anon-key"


def test_ci_environment_preserves_explicit_frontend_supabase_config(monkeypatch):
    monkeypatch.setenv("VITE_SUPABASE_URL", "http://localhost:6543")
    monkeypatch.setenv("VITE_SUPABASE_ANON_KEY", "explicit-test-key")

    environment = _command_environment()

    assert environment["VITE_SUPABASE_URL"] == "http://localhost:6543"
    assert environment["VITE_SUPABASE_ANON_KEY"] == "explicit-test-key"


def test_run_offline_frontend_commands_receive_vite_supabase_defaults(monkeypatch):
    manifest = load_manifest()
    captured = []

    def fake_run(argv, *, cwd=None, env=None, check=False, **kwargs):
        captured.append(env)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.delenv("VITE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("VITE_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr("scripts.ci_runner.subprocess.run", fake_run)

    run_offline(manifest, "frontend")

    assert len(captured) == 4
    for environment in captured:
        assert (
            environment["VITE_SUPABASE_URL"] == TEST_ENV_DEFAULTS["VITE_SUPABASE_URL"]
        )
        assert (
            environment["VITE_SUPABASE_ANON_KEY"]
            == TEST_ENV_DEFAULTS["VITE_SUPABASE_ANON_KEY"]
        )


def test_manifest_tracks_every_backend_test():
    validate_manifest(load_manifest())


def test_browser_navigation_does_not_wait_for_long_lived_connections_to_close():
    source = inspect.getsource(_execute_browser) + inspect.getsource(
        _run_browser_attempt
    )

    assert 'wait_until="networkidle"' not in source
    assert source.count('wait_until="domcontentloaded"') == 2
    assert source.count("_wait_for_composer_ready(page)") == 2
    assert "tracing.start(screenshots=False" in source


def test_manifest_validation_fails_when_a_tracked_test_is_omitted():
    manifest = load_manifest()
    for group in manifest["offline_groups"]:
        for command in group["commands"]:
            if "backend/tests/test_api_security.py" in command["argv"]:
                command["argv"].remove("backend/tests/test_api_security.py")

    with pytest.raises(
        ValueError, match="unassigned tests: backend/tests/test_api_security.py"
    ):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("paths", "expected_groups"),
    [
        (["docs/current-architecture.md"], {"pipeline-policy"}),
        (
            ["backend/agent/nodes/research_worker.py"],
            {
                "agent-rag-llm",
                "backend-coverage",
                "static-security",
                "container",
                "pipeline-policy",
            },
        ),
        (
            ["backend/tests/test_quality_corpus.py"],
            {
                "eval-quality",
                "backend-coverage",
                "static-security",
                "pipeline-policy",
            },
        ),
        (["frontend/src/index.css"], {"frontend", "pipeline-policy"}),
    ],
)
def test_offline_selection_runs_only_owning_groups(paths, expected_groups):
    selected = select_offline_groups(paths, load_manifest())

    assert {group["name"] for group in selected} == expected_groups


@pytest.mark.parametrize(
    "path", ["unknown/new_surface.txt", "ci/quality.json", "backend/config.py"]
)
def test_offline_selection_falls_back_to_every_group_for_risky_changes(path):
    manifest = load_manifest()

    selected = select_offline_groups([path], manifest)

    assert [group["name"] for group in selected] == [
        group["name"] for group in manifest["offline_groups"]
    ]


def test_ci_workflow_selects_groups_from_the_checked_out_event_range():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert (
        './scripts/ci groups --event-file "$GITHUB_EVENT_PATH" --github-output'
        in workflow
    )


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (
            ["README.md", "docs/current-architecture.md"],
            {"docs_only": True, "ai_impact": False},
        ),
        (["frontend/src/index.css"], {"visual_only": True, "ai_impact": False}),
        (["backend/agent/graph.py"], {"ai_impact": True}),
        (["backend/db/migrations/versions/next.py"], {"ai_impact": True}),
        (["unknown/new_surface.txt"], {"ai_impact": True}),
    ],
)
def test_change_classification_is_fail_safe(paths, expected):
    actual = classify_paths(paths, load_manifest())

    for key, value in expected.items():
        assert actual[key] is value


def test_same_repository_pr_is_trusted(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    event = {
        "pull_request": {
            "head": {"repo": {"full_name": "owner/repo"}},
            "base": {"repo": {"full_name": "owner/repo"}},
        }
    }

    assert trust_for_event(event) == (True, "same-repository pull request")


def test_fork_pr_is_not_trusted(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    event = {
        "pull_request": {
            "head": {"repo": {"full_name": "contributor/repo"}},
            "base": {"repo": {"full_name": "owner/repo"}},
        }
    }

    assert trust_for_event(event) == (False, "fork pull request")


def test_merge_queue_is_trusted(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")

    assert trust_for_event({"merge_group": {}}) == (True, "trusted merge_group event")


def test_workflows_do_not_use_pull_request_target():
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github/workflows").glob("*.yml")
    )

    assert "pull_request_target" not in workflow_text


def test_browser_workflows_use_the_websocket_allowlisted_dev_origin():
    workflow_paths = [
        ROOT / ".github/workflows/scheduled-eval.yml",
        ROOT / ".github/workflows/live-eval.yml",
        ROOT / ".github/workflows/deploy-production.yml",
    ]
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8") for path in workflow_paths
    )
    dev_origin = "http://localhost:5173"

    assert "http://127.0.0.1:4173" not in workflow_text
    assert dev_origin in Settings(_env_file=None).cors_allowed_origins
    assert workflow_text.count(f"--target {dev_origin}") == len(workflow_paths)
    assert workflow_text.count("--host localhost --port 5173 --strictPort") == len(
        workflow_paths
    )


def test_workflow_dispatch_inputs_are_never_interpolated_into_shell_scripts():
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        in_run_block = False
        run_indent = 0
        for line in workflow.read_text(encoding="utf-8").splitlines():
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if in_run_block and stripped and indent <= run_indent:
                in_run_block = False
            if stripped.startswith("run:"):
                assert "${{ inputs." not in stripped, workflow
                in_run_block = stripped.removeprefix("run:").strip() in {"|", ">"}
                run_indent = indent
            elif in_run_block:
                assert "${{ inputs." not in line, workflow


def test_gcp_federation_separates_staging_and_production_credentials():
    terraform = ROOT / "infra/terraform/gcp"
    iam = (terraform / "iam.tf").read_text(encoding="utf-8")
    federation = (terraform / "workload_identity.tf").read_text(encoding="utf-8")

    staging_secrets = iam.split("staging_ci_secret_ids = toset([", 1)[1].split("])", 1)[
        0
    ]
    production_secrets = iam.split("production_ci_secret_ids = toset([", 1)[1].split(
        "])", 1
    )[0]
    assert "staging-supabase-db-url" in staging_secrets
    assert "production-migration-db-url" not in staging_secrets
    assert "production-migration-db-url" in production_secrets
    assert "staging-supabase-db-url" not in production_secrets
    assert "environment:staging-eval" in federation
    assert "environment:production" in federation
    assert "legacy_ci_wif_binding" in federation
    assert "count              = var.retain_legacy_ci_access ? 1 : 0" in federation
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    transition = variables.split('variable "retain_legacy_ci_access"', 1)[1].split(
        "}", 1
    )[0]
    assert "default     = false" in transition


def test_staging_allows_control_traffic_without_parallel_schema_mutation():
    cloud_run = (ROOT / "infra/terraform/gcp/cloud_run.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/terraform/gcp/variables.tf").read_text(encoding="utf-8")
    locals_source = (ROOT / "infra/terraform/gcp/locals.tf").read_text(encoding="utf-8")
    staging = cloud_run.split(
        'resource "google_cloud_run_v2_service" "backend_staging"', 1
    )[1]
    staging_template = staging.split("containers {", 1)[0]
    container_concurrency = variables.split('variable "container_concurrency"', 1)[
        1
    ].split("}", 1)[0]

    assert (
        "max_instance_request_concurrency = local.live_budgets.staging_request_concurrency"
        in staging_template
    )
    assert (
        'jsondecode(file("${path.module}/../../../ci/quality.json")).live.budgets'
        in locals_source
    )
    production = cloud_run.split(
        'resource "google_cloud_run_v2_service" "backend_staging"', 1
    )[0]
    assert "max_instance_request_concurrency = var.container_concurrency" in production
    assert "min_instance_count = 0" in staging_template
    assert "max_instance_count = 1" in staging_template
    assert "default     = 4" in container_concurrency


@pytest.mark.parametrize("workflow_name", ["live-eval.yml", "scheduled-eval.yml"])
@pytest.mark.parametrize("concurrency", [16, 24, 7])
def test_staging_deployment_resolves_versioned_request_capacity(
    tmp_path, workflow_name, concurrency
):
    workflow = (ROOT / ".github/workflows" / workflow_name).read_text()
    step = workflow.split("name: Resolve staging request concurrency\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("\n      - ", 1)[0])
    module = tmp_path / "backend/eval"
    module.mkdir(parents=True)
    (module / "runtime_budget.py").write_text(
        (ROOT / "backend/eval/runtime_budget.py").read_text()
    )
    (tmp_path / "ci").mkdir()
    manifest = load_manifest()
    manifest["live"]["budgets"]["staging_request_concurrency"] = concurrency
    (tmp_path / "ci/quality.json").write_text(json.dumps(manifest))
    github_env = tmp_path / "github-env"

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "GITHUB_ENV": str(github_env),
            "STAGING_REQUEST_CONCURRENCY": "4",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if concurrency < 8:
        assert result.returncode != 0
        assert "at least twice browser case concurrency" in result.stderr
        assert not github_env.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert github_env.read_text() == f"STAGING_REQUEST_CONCURRENCY={concurrency}\n"
    assert (
        workflow.index("pip install -r backend/requirements.txt")
        < workflow.index("name: Resolve staging request concurrency")
        < workflow.index("gcloud run deploy")
    )


@pytest.mark.parametrize("workflow_name", ["live-eval.yml", "scheduled-eval.yml"])
@pytest.mark.parametrize("configured_concurrency", ["16", "4", "", "true", "32"])
def test_staging_deploy_verifies_the_returned_request_capacity(
    tmp_path, workflow_name, configured_concurrency
):
    workflow = (ROOT / ".github/workflows" / workflow_name).read_text()
    step_name = (
        "Deploy digest as a no-traffic staging revision"
        if workflow_name == "live-eval.yml"
        else "Deploy evaluation digest to a tagged staging revision"
    )
    step = workflow.split(f"name: {step_name}\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("\n      - ", 1)[0])
    # Stop after deployment verification, before the unrelated traffic lookup.
    separator = (
        "candidate_url="
        if workflow_name == "live-eval.yml"
        else "gcloud run services describe"
    )
    script = script.split(separator, 1)[0]
    script += (
        'printf "%s" "$CONFIGURED_STAGING_REQUEST_CONCURRENCY"\n'
        if workflow_name == "scheduled-eval.yml"
        else ""
    )
    gcloud = tmp_path / "gcloud"
    gcloud.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$GCLOUD_ARGS"\nprintf "%s\\n" "$OBSERVED_CONCURRENCY"\n'
    )
    gcloud.chmod(0o755)
    github_env = tmp_path / "github-env"
    arguments_path = tmp_path / "gcloud-args"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            "PATH": str(tmp_path) + os.pathsep + os.defpath,
            "GCLOUD_ARGS": str(arguments_path),
            "OBSERVED_CONCURRENCY": configured_concurrency,
            "GITHUB_ENV": str(github_env),
            "GITHUB_RUN_ID": "123",
            "STAGING_SERVICE": "agent-backend-staging",
            "PROJECT_ID": "test-project",
            "REGION": "europe-west2",
            "IMAGE": "registry.example.test/agent",
            "IMAGE_DIGEST": "sha256:" + "c" * 64,
            "REVISION_TAG": "eval-123-1",
            "STAGING_REQUEST_CONCURRENCY": "16",
            "EVALUATION_RUN_ID": "123-1",
            "EVALUATION_PROVIDER_ATTEMPT_LIMIT": "64",
            "EVALUATION_FULL_PROVIDER_ATTEMPT_LIMIT": "150",
            "EVALUATION_PR_PROVIDER_ATTEMPT_LIMIT": "64",
            "GRAPH_PIPELINE_MODE": "staged",
            "EVAL_PIPELINE_MODE": "staged",
            "EVAL_SUITE": "full",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    arguments = arguments_path.read_text().splitlines()
    assert arguments[arguments.index("--concurrency") + 1] == "16"
    assert "--format=value(spec.template.spec.containerConcurrency)" in arguments
    assert "--no-traffic" in arguments
    if configured_concurrency == "16":
        assert result.returncode == 0, result.stderr
        if workflow_name == "live-eval.yml":
            assert (
                "CONFIGURED_STAGING_REQUEST_CONCURRENCY=16\n" in github_env.read_text()
            )
        else:
            assert result.stdout == "16"
    else:
        assert result.returncode != 0
        assert "does not match the versioned budget" in result.stderr
        assert (
            not github_env.exists()
            or "CONFIGURED_STAGING_REQUEST_CONCURRENCY" not in github_env.read_text()
        )


def test_required_check_names_are_stable():
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github/workflows").glob("*.yml")
    )

    assert "name: CI required" in workflows
    assert "name: Live eval required" in workflows


def test_feature_pull_requests_do_not_duplicate_required_workflows_on_push():
    for name in ("ci.yml", "live-eval.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        triggers = workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]

        assert "pull_request:\n    branches: [main]" in triggers
        assert "push:\n    branches: [main]" in triggers
        assert "merge_group:" in triggers
        assert "codex/**" not in triggers


def test_live_eval_override_compares_release_content_by_tree_snapshot():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]

    assert "def tree_files(commit_sha):" in verification
    assert "git/trees/{commit['tree']['sha']}?recursive=1" in verification
    assert 'if entry_type not in {"blob", "commit"}:' in verification
    assert (
        'files[item["path"]] = (item["mode"], entry_type, item["sha"])' in verification
    )
    assert "applied_files = tree_files(applied_commit)" in verification
    assert "current_files = tree_files(current_commit)" in verification
    assert "applied_files.keys() | current_files.keys()" in verification
    assert "if applied_files.get(path) != current_files.get(path)" in verification
    assert "/compare/" not in verification


def test_live_eval_override_binds_pr_merge_evidence_to_parent_and_recorded_tree():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]

    assert 'if context_name == "run-context.json":' in verification
    assert 'if run.get("event") == "pull_request":' in verification
    assert 'pull_requests = run.get("pull_requests")' in verification
    assert "len(pull_requests) != 1" in verification
    assert 'head_sha = head.get("sha")' in verification
    assert 'base_sha = base.get("sha")' in verification
    assert "if head_sha != source_commit:" in verification
    assert "expected_pr_parents = {head_sha, base_sha}" in verification
    assert "if len(expected_pr_parents) != 2:" in verification
    assert "if context_commit == source_commit:" in verification
    assert 'tested_parents = tested.get("parents", [])' in verification
    assert "len(tested_parent_shas) != 2" in verification
    assert "len(set(tested_parent_shas)) != 2" in verification
    assert "if set(tested_parent_shas) != expected_pr_parents:" in verification
    assert 'recorded_tree = context.get("tree_sha")' in verification
    assert 'not re.fullmatch(r"[0-9a-f]{40}", recorded_tree)' in verification
    assert 'if recorded_tree != tested["tree"]["sha"]:' in verification
    assert (
        'if run.get("event") == "pull_request" and not deployment_commits:'
        in verification
    )
    assert (
        "tested_commit = next(iter(deployment_commits), source_commit)" in verification
    )
    assert "source_cases = case_map(tested_commit)" in verification
    assert 'context.get("commit_sha") != source_commit' not in verification


def test_live_eval_override_rejects_ambiguous_composite_evidence():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    request_validation = workflow.split(
        "name: Validate authenticated evidence request", 1
    )[1].split("name: Download explicit evidence and source metadata", 1)[0]
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]

    assert "seen_run_ids = set()" in request_validation
    assert "if run_id in seen_run_ids:" in request_validation
    assert "Each evidence source must use a distinct run_id" in request_validation
    assert "def raw_case_results(document, key, label, run_id):" in verification
    assert "len(case_ids) != len(set(case_ids))" in verification
    assert "if replay is None and browser_ids != live_ids:" in verification
    assert 'identity_value(browser, "corpus_sha256")' in verification
    assert 'identity_value(live, "corpus_sha256")' in verification
    assert "if missing_corpus_sha256 and not legacy:" in verification
    assert "if len(present_corpus_sha256) > 1:" in verification
    assert '"corpus_sha256_documents": corpus_sha256_documents' in verification
    assert '("corpus_version", "release_identity", "corpus_sha256")' in verification
    assert 'browser.get("suite") != "diagnostic"' in verification
    assert 'live.get("suite") != "diagnostic"' in verification
    assert 'browser_ids != ["applied-domain"]' in verification
    assert 'live_ids != ["applied-domain"]' in verification


def test_live_eval_override_supports_exact_pr_check_and_production_scopes():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    inputs = workflow.split("workflow_dispatch:", 1)[1].split("\npermissions:", 1)[0]
    validation = workflow.split("name: Validate authenticated evidence request", 1)[
        1
    ].split("name: Download explicit evidence and source metadata", 1)[0]
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]
    publication = workflow.split("- uses: google-github-actions/auth@v2", 1)[1]

    assert "scope:" in inputs
    assert "options: [pr-check, production]" in inputs
    assert "current_commit_sha:" in inputs
    assert "pr_number:" in inputs
    assert "ref: ${{ inputs.current_commit_sha }}" in workflow
    assert "environment: staging-eval" in workflow
    assert "name: Live eval required" in workflow
    assert '[ "$GITHUB_SHA" = "$CURRENT_COMMIT_SHA" ]' in validation
    assert '[ "$GITHUB_REF" = refs/heads/main ]' in validation
    assert 'if approval_scope == "pr-check":' in verification
    assert 'api_json(f"repos/{repository}/pulls/{pr_number}")' in verification
    assert "head_sha != current_commit" in verification
    assert 'base.get("ref") != "main"' in verification
    assert 'os.environ["GITHUB_REF"] != f"refs/heads/{head_ref}"' in verification
    assert 'os.environ["GITHUB_SHA"] != head_sha' in verification
    assert '"head_sha": head_sha' in verification
    assert '"base_sha": base_sha' in verification
    assert publication.count("if: inputs.scope == 'production'") == 3
    assert "gcloud artifacts docker tags add" in publication
    assert "gcloud artifacts docker tags add" not in verification


def test_live_eval_override_authenticates_replay_and_diagnostic_composition():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    request_validation = workflow.split(
        "name: Validate authenticated evidence request", 1
    )[1].split("name: Download explicit evidence and source metadata", 1)[0]
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]

    assert 'source.get("browser_sha256", "")' in request_validation
    assert 'source.get("semantic_sha256", "")' in request_validation
    assert 'source.get("semantic_replay")' in request_validation
    assert "replay_count != 1" in request_validation
    assert "exactly one source-linked semantic replay" in request_validation
    assert "def file_sha256(path):" in verification
    assert "Browser artifact hash mismatch" in verification
    assert "Semantic artifact hash mismatch" in verification
    assert "Semantic replay context hash mismatch" in verification
    assert 'replay_context.get("source_run_id")' in verification
    assert 'replay_context.get("source_commit_sha")' in verification
    assert 'replay_context.get("judge_commit_sha")' in verification
    assert (
        'replay_run.get("path") != ".github/workflows/semantic-review-replay.yml"'
        in verification
    )
    assert 'run.get("path") != ".github/workflows/live-eval.yml"' in verification
    assert 'run.get("path") != ".github/workflows/scheduled-eval.yml"' in verification
    assert 'browser.get("suite") != "pr"' in verification
    assert 'browser.get("suite") != "diagnostic"' in verification
    assert "browser_ids != selected or live_ids != selected" in verification
    assert "assigned != expected_cases" in verification
    assert "Cases assigned more than once" in verification
    assert 'selected != ["applied-domain"]' in verification
    assert 'tested_tree_sha = tested_metadata["tree"]["sha"]' in verification
    assert "logged_digests != {image_digest}" in verification
    assert '"current_commit_sha": current_commit' in verification
    assert '"current_tree_sha": current_tree_sha' in verification


def test_live_eval_override_replay_source_is_the_bounded_failed_pr_lane():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]

    assert 'run.get("path") != ".github/workflows/live-eval.yml"' in verification
    assert 'run.get("event") != "pull_request"' in verification
    assert 'run.get("status") != "completed"' in verification
    assert 'run.get("conclusion") != "failure"' in verification
    assert 'job.get("name") == "Live eval required"' in verification
    assert 'required_jobs[0].get("conclusion") != "failure"' in verification
    assert "set(selected) != replay_expected_cases" in verification
    assert (
        'replay_expected_cases = {"memory", "graph-off", "prompt-injection"}'
        in verification
    )
    assert "source_commit != evidence_commit" in verification
    assert "head_sha != applied_commit" in verification
    assert 'base_sha != pr_identity["base_sha"]' in verification
    assert "set(browser_ids) != expected_cases" in verification
    assert 'browser.get("suite") != "pr"' in verification
    assert 'live_ids != selected or live.get("status") != "pass"' in verification


def test_live_eval_override_replay_selection_has_no_graph_operation_provenance():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]

    assert (
        'application_telemetry = browser.get("application_telemetry")' in verification
    )
    assert 'thread_ids = browser_case.get("thread_ids")' in verification
    assert 'item.get("thread_id") in set(thread_ids)' in verification
    assert 'operation.startswith("graph_")' in verification
    assert "if graph_operations:" in verification
    assert 'replay_provenance["selection"] = selected' in verification
    assert (
        'replay_provenance["case_operations"] = replay_case_operations' in verification
    )
    assert '"graph_operations": graph_operations' in verification


def test_live_eval_override_tree_equality_has_one_bounded_legacy_replay_exception():
    workflow = (ROOT / ".github/workflows/live-eval-override.yml").read_text(
        encoding="utf-8"
    )
    verification = workflow.split(
        "name: Verify complete per-case evidence and exact release identity", 1
    )[1].split("- uses: google-github-actions/auth@v2", 1)[0]
    allowed_paths = {
        "backend/agent/nodes/graph_worker.py",
        "backend/agent/nodes/graph_critic.py",
        "backend/tests/test_graph_patch.py",
        "backend/tests/test_graph_critic.py",
        "backend/tests/test_graph_grounding_prompts.py",
        "backend/eval/evidence_replay.py",
        "backend/tests/test_quality_corpus.py",
        "ci/tests/test_ci_system.py",
        ".github/workflows/semantic-review-replay.yml",
        ".github/workflows/live-eval-override.yml",
        ".github/workflows/scheduled-eval.yml",
        "docs/quality-system.md",
    }

    assert "legacy_replay_allowed_changes = {" in verification
    for path in allowed_paths:
        assert f'"{path}"' in verification
    assert 'tested_tree_sha = tested_metadata["tree"]["sha"]' in verification
    assert "if tested_tree_sha != applied_tree_sha:" in verification
    assert "if replay is None or not legacy:" in verification
    assert "replay_case_operations is None or any(" in verification
    assert (
        'item["graph_operations"] for item in replay_case_operations.values()'
        in verification
    )
    assert (
        "if not replay_tree_changes <= legacy_replay_allowed_changes:" in verification
    )
    assert "replay_tree_changes - legacy_replay_allowed_changes" in verification
    assert verification.index("if graph_operations:") < verification.index(
        "if tested_tree_sha != applied_tree_sha:"
    )
    assert '"legacy_replay_tree_changes": legacy_replay_tree_changes' in verification


def test_scheduled_eval_missing_approval_fails_closed_before_expensive_setup():
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )
    preflight = workflow.split(
        "name: Preflight exact-tree approval before expensive setup", 1
    )[1].split("- uses: actions/setup-python@v5", 1)[0]

    assert "id: approved_image" in workflow
    assert 'commit_sha="$(git rev-parse HEAD)"' in preflight
    assert "tree_sha=\"$(git rev-parse 'HEAD^{tree}')\"" in preflight
    assert 'approval_tag="approved-tree-$tree_sha"' in preflight
    assert '2>"$lookup_error_file"' in preflight
    assert "lookup_status=$?" in preflight
    classifier_pattern = (
        r"^(ERROR: \(gcloud\.artifacts\.docker\.images\.describe\) "
        r"(Docker image .+ not found\.?|Image not found\.)|Image not found\.)$"
    )
    assert f"grep -Eiq '{classifier_pattern}' \"$lookup_error_file\"" in preflight
    classifier = __import__("re").compile(
        classifier_pattern, __import__("re").IGNORECASE
    )
    assert classifier.fullmatch(
        "ERROR: (gcloud.artifacts.docker.images.describe) "
        "Docker image [europe-west2-docker.pkg.dev/p/r/i:approved-tree-deadbeef] not found."
    )
    assert classifier.fullmatch("Image not found.")
    assert classifier.fullmatch(
        "ERROR: (gcloud.artifacts.docker.images.describe) Image not found."
    )
    assert not classifier.fullmatch("Unexpected Image not found.")
    assert not classifier.fullmatch(
        "ERROR: (gcloud.artifacts.docker.images.describe) PERMISSION_DENIED: "
        "Permission artifactregistry.dockerimages.get denied."
    )
    assert not classifier.fullmatch(
        "ERROR: (gcloud.artifacts.docker.images.describe) "
        "ResponseError: status=[503], code=[Unavailable]"
    )
    assert "Exact-tree approval lookup failed:" in preflight
    assert 'exit "$lookup_status"' in preflight
    assert "Exact-tree approval lookup returned no digest:" in preflight
    assert preflight.index('if [ -z "$digest" ]; then') < preflight.index("grep -Eiq")
    assert "2>/dev/null || true" not in preflight
    assert (
        'if [ "$GITHUB_EVENT_NAME" = workflow_dispatch ] '
        '&& { [ "$EVAL_SUITE" = full ] || [ "$EVAL_SUITE" = diagnostic ]; }; then' in preflight
    )
    assert "Missing exact-tree evaluation approval:" in preflight
    assert (
        "commit=$commit_sha tree=$tree_sha image_tag=$IMAGE:$approval_tag" in preflight
    )
    assert "The protected live evaluation must publish this exact-tree tag" in preflight
    assert preflight.rstrip().endswith("exit 1")

    dependency_setup = workflow.index("uses: actions/setup-python@v5")
    assert workflow.index("id: approved_image") < dependency_setup
    assert workflow.index("pip install -r backend/requirements.txt") > dependency_setup
    assert workflow.index("python scripts/staging_database.py reset") > dependency_setup
    assert (
        "APPROVED_IMAGE_DIGEST: ${{ steps.approved_image.outputs.digest }}" in workflow
    )
    assert 'digest="$APPROVED_IMAGE_DIGEST"' in workflow


def test_scheduled_eval_preserves_approval_and_manual_build_boundaries():
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "environment: staging-eval" in workflow
    assert "evaluation-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in workflow
    assert "CORPUS_STATUS" not in workflow
    assert "--require-approved-corpus" not in workflow
    assert "--manual-review-policy report-only" in workflow
    assert workflow.count("docker buildx build") == 1
    assert "Missing exact-tree evaluation approval:" in workflow
    assert (
        'if [ "$GITHUB_EVENT_NAME" != workflow_dispatch ] || '
        '{ [ "$EVAL_SUITE" != full ] && [ "$EVAL_SUITE" != diagnostic ]; }; then' in workflow
    )
    assert "Scheduled evaluation did not pass." in workflow
    assert (
        "An ephemeral candidate requires a manually dispatched full or diagnostic evaluation."
        in workflow
    )
    assert "Diagnostic suite requires one to eight unique case IDs." in workflow
    assert (
        'for case_id in "${selected_cases[@]}"; do case_args+=(--case "$case_id"); done'
        in workflow
    )
    assert (
        'gcloud artifacts docker tags delete "$IMAGE:$EVALUATION_IMAGE_TAG"' in workflow
    )
    assert "docker tags add" not in workflow
    assert 'EVAL_EMAIL="$email" python scripts/staging_database.py reset' in workflow
    assert "artifacts/live-eval/run-context.json" in workflow
    assert "name: Wait for candidate readiness" in workflow
    assert '[ "$frontend_ready" = true ]' in workflow
    assert "VITE_EVAL_AUTH_BOOTSTRAP=true" in workflow

    approval_preflight = workflow.index(
        "name: Preflight exact-tree approval before expensive setup"
    )
    dependency_setup = workflow.index("uses: actions/setup-python@v5")
    candidate_resolution = workflow.index(
        "name: Resolve approved digest or build an ephemeral evaluation candidate"
    )
    candidate_readiness = workflow.index("name: Wait for candidate readiness")
    browser_capture = workflow.index("name: Start frontend and capture journeys")
    assert (
        approval_preflight
        < dependency_setup
        < candidate_resolution
        < candidate_readiness
        < browser_capture
    )
    evaluation_env = workflow.index('echo "EVALUATION_IMAGE_TAG=$evaluation_tag"')
    assert evaluation_env < workflow.index("docker buildx build")
    assert workflow.index('echo "REVISION_TAG=$tag"') < workflow.index(
        "gcloud run deploy"
    )


@pytest.mark.parametrize("suite", ["nightly", "full", "diagnostic"])
@pytest.mark.parametrize(
    ("browser_outcome", "semantic_outcome"),
    [
        ("success", "success"),
        ("failure", "success"),
        ("success", "failure"),
        ("cancelled", "success"),
        ("success", "cancelled"),
        ("skipped", "success"),
        ("success", "skipped"),
        ("", ""),
        ("failure", "failure"),
    ],
)
def test_scheduled_eval_status_preserves_failed_outcomes(
    suite, browser_outcome, semantic_outcome
):
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.split("- name: Enforce scheduled evaluation outcome\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1])

    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        env={
            "EVAL_SUITE": suite,
            "GITHUB_EVENT_NAME": (
                "schedule" if suite == "nightly" else "workflow_dispatch"
            ),
            "BROWSER_OUTCOME": browser_outcome,
            "SEMANTIC_OUTCOME": semantic_outcome,
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    succeeded = browser_outcome == semantic_outcome == "success"
    assert result.returncode == (0 if succeeded else 1)
    if not succeeded:
        assert "Scheduled evaluation did not pass" in result.stderr


@pytest.mark.parametrize(
    "invalid_identity", [None, "digest", "missing_revision", "duplicate_tag"]
)
def test_scheduled_eval_records_exact_deployment_identity(tmp_path, invalid_identity):
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )
    deployment = workflow.split(
        "- name: Deploy evaluation digest to a tagged staging revision\n", 1
    )[1].split("- name: Wait for candidate readiness", 1)[0]
    script = dedent(
        deployment.split("python - <<'PY'\n", 1)[1].split("          PY", 1)[0]
    )
    candidate = {
        "tag": "scheduled-123",
        "url": "https://scheduled-123.example.test",
        "revisionName": "agent-backend-staging-123",
    }
    if invalid_identity == "missing_revision":
        candidate.pop("revisionName")
    traffic = [{"tag": "other", "revisionName": "wrong-revision"}, candidate]
    if invalid_identity == "duplicate_tag":
        traffic.append(candidate)
    (tmp_path / "candidate-traffic.json").write_text(
        json.dumps({"status": {"traffic": traffic}}), encoding="utf-8"
    )
    artifact_dir = tmp_path / "artifacts/live-eval"
    artifact_dir.mkdir(parents=True)
    github_env = tmp_path / "github-env"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ENV": str(github_env),
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
            "COMMIT_SHA": "a" * 40,
            "TREE_SHA": "b" * 40,
            "IMAGE": "registry.example.test/agent",
            "IMAGE_DIGEST": (
                "mutable-tag" if invalid_identity == "digest" else "sha256:" + "c" * 64
            ),
            "EVAL_PIPELINE_MODE": "staged",
            "EVAL_SUITE": "diagnostic",
            "EVAL_CASE_IDS": "graph-expansion",
            "CONFIGURED_STAGING_REQUEST_CONCURRENCY": "16",
            "ANTHROPIC_API_KEY": "must-not-appear-in-evidence",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    evidence_path = artifact_dir / "deployment.json"
    if invalid_identity:
        assert result.returncode != 0
        assert not evidence_path.exists()
        assert not github_env.exists()
        return
    assert result.returncode == 0, result.stderr
    assert json.loads(evidence_path.read_text()) == {
        "run_id": "123",
        "run_attempt": "2",
        "commit_sha": "a" * 40,
        "tree_sha": "b" * 40,
        "image": "registry.example.test/agent",
        "digest": "sha256:" + "c" * 64,
        "revision_name": "agent-backend-staging-123",
        "staging_request_concurrency": 16,
        "pipeline_mode": "staged",
        "suite": "diagnostic",
        "case_ids": ["graph-expansion"],
    }
    assert (
        github_env.read_text() == "CANDIDATE_URL=https://scheduled-123.example.test\n"
    )
    uploads = workflow.split("- uses: actions/upload-artifact@v4")
    assert len(uploads) == 3
    assert "artifacts/live-eval/deployment.json" in uploads[1]
    assert all("retention-days: 90" in upload for upload in uploads[1:])


@pytest.mark.parametrize(
    "workflow_name", ["live-eval.yml", "scheduled-eval.yml", "deploy-production.yml"]
)
@pytest.mark.parametrize("versioned_default", ["legacy", "staged", "unsupported"])
def test_deployment_mode_resolves_versioned_default_despite_stale_environment(
    tmp_path, workflow_name, versioned_default
):
    workflow = (ROOT / ".github/workflows" / workflow_name).read_text()
    step = workflow.split("name: Resolve versioned graph pipeline mode\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("\n      - ", 1)[0])
    backend = tmp_path / "backend"
    backend.mkdir()
    source, replaced = re.subn(
        r'(^    graph_pipeline_mode:.* = )"(?:legacy|staged)"',
        lambda match: match[1] + json.dumps(versioned_default),
        (ROOT / "backend/config.py").read_text(),
        flags=re.MULTILINE,
    )
    assert replaced == 1
    (backend / "config.py").write_text(source)
    github_env = tmp_path / "github-env"

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "GITHUB_ENV": str(github_env),
            "GRAPH_PIPELINE_MODE": "staged"
            if versioned_default == "legacy"
            else "legacy",
            "EVAL_PIPELINE_MODE": "default",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    variable = (
        "EVAL_PIPELINE_MODE"
        if workflow_name == "scheduled-eval.yml"
        else "GRAPH_PIPELINE_MODE"
    )
    if versioned_default == "unsupported":
        assert result.returncode != 0
        assert "Unsupported pipeline mode" in result.stderr
        assert not github_env.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert github_env.read_text() == f"{variable}={versioned_default}\n"
    assert (
        workflow.index("pip install -r backend/requirements.txt")
        < workflow.index("name: Resolve versioned graph pipeline mode")
        < workflow.index("gcloud run deploy")
    )
    assert f"GRAPH_PIPELINE_MODE=${variable}" in workflow


@pytest.mark.parametrize(
    ("event", "suite", "requested", "expected"),
    [
        ("workflow_dispatch", suite, requested, requested)
        for suite in ("diagnostic", "full", "nightly")
        for requested in ("default", "legacy", "staged")
    ]
    + [
        ("schedule", "", "staged", "default"),
        ("workflow_dispatch", "full", "", "default"),
        ("workflow_dispatch", "diagnostic", "unsupported", None),
        ("workflow_dispatch", "full", "unsupported", None),
    ],
)
def test_scheduled_mode_selection_preserves_manual_intent_and_rejects_invalid_modes(
    tmp_path, event, suite, requested, expected
):
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text()
    step = workflow.split("name: Select nightly rotation or weekly full corpus\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("\n      - ", 1)[0])
    github_env = tmp_path / "github-env"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=ROOT,
        env={
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "GITHUB_ENV": str(github_env),
            "GITHUB_EVENT_NAME": event,
            "DISPATCH_SUITE": suite,
            "DISPATCH_CASE_IDS": "graph-expansion" if suite == "diagnostic" else "",
            "DISPATCH_PIPELINE_MODE": requested,
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if expected is None:
        assert result.returncode != 0
        assert "Unsupported pipeline mode" in result.stderr
        assert not github_env.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert f"EVAL_PIPELINE_MODE={expected}\n" in github_env.read_text()
    assert (
        workflow.index("name: Select nightly rotation")
        < workflow.index(
            "name: Preflight exact-tree approval before expensive setup"
        )
        < workflow.index("pip install -r backend/requirements.txt")
    )


@pytest.mark.parametrize("selected", ["legacy", "staged", "unsupported"])
def test_scheduled_explicit_mode_resolution_never_uses_environment_override(
    tmp_path, selected
):
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text()
    step = workflow.split("name: Resolve versioned graph pipeline mode\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("\n      - ", 1)[0])
    github_env = tmp_path / "github-env"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "GITHUB_ENV": str(github_env),
            "EVAL_PIPELINE_MODE": selected,
            "GRAPH_PIPELINE_MODE": "stale-service-value",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    if selected == "unsupported":
        assert result.returncode != 0
        assert "Unsupported pipeline mode" in result.stderr
        assert not github_env.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert github_env.read_text() == f"EVAL_PIPELINE_MODE={selected}\n"


def test_production_deployment_clears_evaluation_quota_pair_and_pins_mode():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text()
    deploy = next(line for line in workflow.splitlines() if "gcloud run deploy" in line)

    assert "GRAPH_PIPELINE_MODE=$GRAPH_PIPELINE_MODE" in deploy
    assert (
        "--remove-env-vars EVALUATION_RUN_ID,EVALUATION_PROVIDER_ATTEMPT_LIMIT"
        in deploy
    )
    assert "--clear-env-vars" not in deploy
    assert "--set-env-vars" not in deploy
    assert '--image "$IMAGE@$IMAGE_DIGEST"' in deploy
    assert "--no-traffic" in deploy


@pytest.mark.parametrize(
    ("workflow_name", "step_name", "artifact_directory"),
    [
        ("live-eval.yml", "Record deployment identity", "live-eval"),
        (
            "deploy-production.yml",
            "Deploy an immutable no-traffic production candidate",
            "production-smoke",
        ),
    ],
)
def test_deployment_manifest_records_resolved_mode_without_environment_secrets(
    tmp_path, workflow_name, step_name, artifact_directory
):
    workflow = (ROOT / ".github/workflows" / workflow_name).read_text()
    step = workflow.split(f"name: {step_name}\n", 1)[1]
    script = dedent(step.split("python - <<'PY'\n", 1)[1].split("          PY", 1)[0])
    artifact_dir = tmp_path / "artifacts" / artifact_directory
    artifact_dir.mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "GITHUB_RUN_ID": "123",
            "COMMIT_SHA": "a" * 40,
            "TREE_SHA": "b" * 40,
            "IMAGE": "registry.example.test/agent",
            "IMAGE_DIGEST": "sha256:" + "c" * 64,
            "GRAPH_PIPELINE_MODE": "staged",
            "CONFIGURED_STAGING_REQUEST_CONCURRENCY": "16",
            "ANTHROPIC_API_KEY": "must-not-appear-in-evidence",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = (artifact_dir / "deployment.json").read_text()
    assert json.loads(manifest)["pipeline_mode"] == "staged"
    if workflow_name == "live-eval.yml":
        assert json.loads(manifest)["staging_request_concurrency"] == 16
    assert "must-not-appear-in-evidence" not in manifest


def test_semantic_review_can_replay_authenticated_browser_evidence_without_app_calls():
    workflow = (ROOT / ".github/workflows/semantic-review-replay.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "environment: staging-eval" in workflow
    assert "actions: read" in workflow
    assert "scheduled-eval-$SOURCE_RUN_ID" in workflow
    assert "scheduled-eval-replay-$SOURCE_RUN_ID" in workflow
    assert "source artifact commit mismatch" in workflow
    assert "./scripts/ci live" in workflow
    assert "./scripts/ci browser" not in workflow
    assert "gcloud " not in workflow
    assert "python -m eval.calibration" not in workflow

    scheduled = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )
    assert "scheduled-eval-replay-${{ github.run_id }}" in scheduled


def test_judge_calibration_uses_immutable_reviewed_evidence():
    calibration = (ROOT / ".github/workflows/judge-calibration.yml").read_text(
        encoding="utf-8"
    )
    promotion = (
        ROOT / ".github/workflows/promote-eval-calibration-evidence.yml"
    ).read_text(encoding="utf-8")
    evidence_tf = (ROOT / "infra/terraform/gcp/eval_evidence.tf").read_text(
        encoding="utf-8"
    )
    iam = (ROOT / "infra/terraform/gcp/iam.tf").read_text(encoding="utf-8")

    assert "schedule:" in calibration
    assert "--capture-replay" in calibration
    assert "python -m eval.calibration" in calibration
    assert "browser-results-$EVIDENCE_SHA.json" in calibration
    assert 'Path("artifacts/calibration/browser-results-replay.json")' in calibration
    assert "--input artifacts/calibration/browser-results-replay.json" in calibration
    assert "--evidence artifacts/calibration/browser-results.json" in calibration
    assert "environment: staging-eval" in calibration
    assert "environment: staging-eval" in promotion
    assert "validate_calibration_capture(capture, current)" in promotion
    assert "validate_calibration_capture(capture, current)" in calibration
    assert "hashlib.sha256(capture_path.read_bytes()).hexdigest()" in promotion
    assert "source evidence digest does not match" in promotion
    assert "ensure_object artifacts/source/browser-results.json" in promotion
    assert "ensure_object artifacts/promotion/promotion.json" in promotion
    assert "--if-generation-match=0" in promotion
    assert 'cmp -s "$source" "$existing"' in promotion
    assert "Existing immutable evidence differs" in promotion
    assert 'public_access_prevention    = "enforced"' in evidence_tf
    assert "retention_period = 31536000" in evidence_tf
    assert 'role   = "roles/storage.objectCreator"' in iam
    assert 'role   = "roles/storage.objectViewer"' in iam


_CALIBRATION_WORKFLOWS = (
    "promote-eval-calibration-evidence.yml",
    "judge-calibration.yml",
)


def _calibration_workflow_python(workflow_name, step_name, *, marker="PY", index=0):
    workflow = (ROOT / ".github/workflows" / workflow_name).read_text()
    step = workflow.split(f"name: {step_name}\n", 1)[1].split("\n      - ", 1)[0]
    blocks = re.findall(
        rf"<<'{marker}'\n(.*?)\n          {marker}(?:\n|$)", step, re.DOTALL
    )
    return dedent(blocks[index])


@pytest.mark.parametrize("workflow_name", (*_CALIBRATION_WORKFLOWS, "semantic-review-replay.yml"))
@pytest.mark.parametrize(
    "change",
    [
        None,
        {"event": "schedule", "conclusion": "success"},
        {"id": 456},
        {"head_sha": "b" * 40},
        {"repository": {"full_name": "other/repository"}},
        {"head_repository": {"full_name": "fork/repository"}},
        {"head_repository": None},
        {"path": ".github/workflows/untrusted.yml"},
        {"event": "pull_request"},
        {"status": "in_progress"},
        {"status": None},
        {"conclusion": "cancelled"},
        {"conclusion": "timed_out"},
        {"conclusion": None},
    ],
)
def test_calibration_source_accepts_only_pinned_completed_repository_runs(
    monkeypatch, workflow_name, change
):
    source = {
        "id": 123,
        "head_sha": "a" * 40,
        "head_branch": "candidate-bootstrap",
        "repository": {"full_name": "owner/repository"},
        "head_repository": {"full_name": "owner/repository"},
        "path": ".github/workflows/scheduled-eval.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "failure",
        **(change or {}),
    }
    monkeypatch.setenv("SOURCE_METADATA", json.dumps(source))
    monkeypatch.setenv("SOURCE_RUN_ID", "123")
    monkeypatch.setenv("SOURCE_COMMIT_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repository")
    step_name = (
        "Download the exact human-reviewed full-suite artifact"
        if workflow_name.startswith("promote-")
        else "Download and authenticate immutable scheduled browser evidence"
        if workflow_name == "semantic-review-replay.yml"
        else "Download and authenticate the fixed evidence bundle"
    )
    script = _calibration_workflow_python(workflow_name, step_name, marker="PY_SOURCE")
    if change is None or change == {"event": "schedule", "conclusion": "success"}:
        exec(compile(script, workflow_name, "exec"), {})
    else:
        with pytest.raises(SystemExit, match="completed same-repository"):
            exec(compile(script, workflow_name, "exec"), {})


@pytest.fixture
def reviewed_calibration_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    corpus = json.loads((ROOT / "backend/eval/corpus/v1/cases.json").read_text())
    corpus["approval"].update(
        status="approved",
        reviewed_by="Reviewer",
        reviewed_at="2026-09-11T12:00:00Z",
        approved_manifest_sha256=None,
    )
    corpus["approval"]["calibration"].update(
        evidence_run_id="123",
        evidence_commit_sha="a" * 40,
        evidence_sha256="b" * 64,
        agreement=0.9,
        critical_false_passes=0,
        evaluated_at="2026-09-11T12:00:00Z",
    )
    for case in corpus["cases"]:
        case["approval"].update(
            status="approved",
            reviewer="Reviewer",
            reviewed_at="2026-09-11T12:00:00Z",
            review_run_id="123",
            reviewed_grades={
                dimension: "pass" for dimension in case["rubric_dimensions"]
            },
        )
    corpus_path = tmp_path / "backend/eval/corpus/v1/cases.json"
    corpus_path.parent.mkdir(parents=True)
    corpus_path.write_text(json.dumps(corpus))
    corpus["approval"]["approved_manifest_sha256"] = approval_manifest_sha256(
        corpus_path
    )
    corpus_path.write_text(json.dumps(corpus))
    behavior_sha = corpus_sha256(corpus_path)
    source = tmp_path / "artifacts/source"
    source.mkdir(parents=True)
    (source / "source-cases.json").write_text(json.dumps(corpus))
    (source / "run-context.json").write_text(
        json.dumps({"run_id": "123", "commit_sha": "a" * 40})
    )
    (tmp_path / "artifacts/calibration").mkdir()
    monkeypatch.setenv("SOURCE_RUN_ID", "123")
    monkeypatch.setenv("SOURCE_COMMIT_SHA", "a" * 40)
    monkeypatch.setenv("CORPUS_SHA", behavior_sha)
    monkeypatch.setenv("JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("JUDGE_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(
        "eval.quality_corpus.load_corpus",
        lambda **kwargs: load_corpus(path=corpus_path, **kwargs),
    )
    return corpus_path, {
        "format_version": 1,
        "kind": "browser_capture",
        "suite": "full",
        "status": "complete",
        "corpus_version": corpus["corpus_version"],
        "release_identity": corpus["release_identity"],
        "corpus_sha256": behavior_sha,
        "case_states": [{"id": case["id"], "state": "completed"} for case in corpus["cases"]],
        "results": [
            {
                "id": case["id"], "passed": True, "deterministic_failures": [],
                "failure_details": [], "execution_state": "completed",
                "turns": [
                    {"turn": index, "prompt": step["prompt"], "answer": "Captured answer."}
                    for index, step in enumerate(case["steps"], 1)
                ],
                "events": [{"type": "done", "eval_turn": index} for index in range(1, len(case["steps"]) + 1)],
                "screenshot": f"screenshots/{case['id']}.png",
                "trace": f"traces/{case['id']}.zip",
            }
            for case in corpus["cases"]
        ],
        "dashboard_smoke": {"passed": True},
    }


@pytest.mark.parametrize("workflow_name", _CALIBRATION_WORKFLOWS)
@pytest.mark.parametrize("change", [None, "mixed_runs", "pending", "missing_grades"])
def test_calibration_promotion_requires_complete_human_review(
    reviewed_calibration_files, workflow_name, change
):
    corpus_path, _capture = reviewed_calibration_files
    corpus = json.loads(corpus_path.read_text())
    if change == "mixed_runs":
        corpus["cases"][0]["approval"]["review_run_id"] = "456"
    elif change == "pending":
        corpus["approval"]["status"] = "pending_human_review"
    elif change == "missing_grades":
        corpus["cases"][0]["approval"]["reviewed_grades"] = {}
    corpus_path.write_text(json.dumps(corpus))
    corpus["approval"]["approved_manifest_sha256"] = approval_manifest_sha256(
        corpus_path
    )
    corpus_path.write_text(json.dumps(corpus))
    script = _calibration_workflow_python(
        workflow_name, "Validate the complete human approval"
    )
    if change is None:
        exec(compile(script, workflow_name, "exec"), {})
    else:
        with pytest.raises((SystemExit, RuntimeError, ValueError)):
            exec(compile(script, workflow_name, "exec"), {})


@pytest.mark.parametrize("workflow_name", _CALIBRATION_WORKFLOWS)
@pytest.mark.parametrize(
    "change",
    [
        None,
        "partial",
        "missing_status",
        "subset",
        "reordered",
        "duplicate",
        "false",
        "nonboolean",
        "deterministic",
        "dashboard",
        "digest",
        "negative",
        "missing_turn",
        "missing_done",
        "wrong_prompt",
        "infrastructure",
        "mixed_failure",
        "missing_answer",
        "missing_artifact",
        "case_state",
        "release_identity",
    ],
)
def test_calibration_evidence_requires_complete_reviewable_browser_capture(
    reviewed_calibration_files, monkeypatch, workflow_name, change
):
    _corpus_path, capture = reviewed_calibration_files
    if change == "partial":
        capture["status"] = "partial"
    elif change == "missing_status":
        capture.pop("status")
    elif change == "subset":
        capture["results"].pop()
    elif change == "reordered":
        capture["results"].reverse()
    elif change == "duplicate":
        capture["results"][-1] = capture["results"][0]
    elif change == "false":
        capture["results"][0]["passed"] = False
    elif change == "nonboolean":
        capture["results"][0]["passed"] = "true"
    elif change == "deterministic":
        capture["results"][0]["deterministic_failures"] = ["graph missing"]
    elif change == "dashboard":
        capture["dashboard_smoke"]["passed"] = False
    elif change in {"negative", "infrastructure", "mixed_failure"}:
        capture["results"][0].update(
            passed=False,
            deterministic_failures=["graph missing"],
            failure_details=[{"kind": "quality", "code": "required_graph_missing", "message": "graph missing"}],
        )
        if change == "infrastructure":
            capture["results"][0]["failure_details"][0]["kind"] = "infrastructure"
        elif change == "mixed_failure":
            capture["results"][0]["failure_details"].append({"kind": "infrastructure"})
    elif change == "missing_turn":
        capture["results"][0]["turns"].pop()
    elif change == "missing_done":
        capture["results"][0]["events"] = []
    elif change == "wrong_prompt":
        capture["results"][0]["turns"][0]["prompt"] = "Different prompt"
    elif change == "missing_answer":
        capture["results"][0]["turns"][0]["answer"] = ""
    elif change == "missing_artifact":
        capture["results"][0].pop("trace")
    elif change == "case_state":
        capture["case_states"][0]["state"] = "cancelled"
    elif change == "release_identity":
        capture["release_identity"] = "different"
    capture_path = Path("artifacts/source/browser-results.json")
    capture_path.write_text(json.dumps(capture))
    evidence_sha = hashlib.sha256(capture_path.read_bytes()).hexdigest()
    for variable in ("EVIDENCE_SHA", "EXPECTED_EVIDENCE_SHA"):
        monkeypatch.setenv(variable, "0" * 64 if change == "digest" else evidence_sha)
    step_name = (
        "Validate and hash the approved evidence"
        if workflow_name.startswith("promote-")
        else "Download and authenticate the fixed evidence bundle"
    )
    script = _calibration_workflow_python(workflow_name, step_name)
    if change in {None, "negative"}:
        exec(compile(script, workflow_name, "exec"), {})
        output_dir = (
            "promotion" if workflow_name.startswith("promote-") else "calibration"
        )
        promotion = json.loads(
            Path(f"artifacts/{output_dir}/promotion.json").read_text()
        )
        assert promotion["evidence_sha256"] == evidence_sha
        assert json.loads(capture_path.read_text()) == capture
    else:
        with pytest.raises((SystemExit, ValueError)):
            exec(compile(script, workflow_name, "exec"), {})


@pytest.mark.parametrize("change", [None, "dashboard", "nonboolean", "partial"])
def test_calibration_revalidates_already_promoted_browser_evidence(
    reviewed_calibration_files, monkeypatch, change
):
    _corpus_path, capture = reviewed_calibration_files
    if change == "dashboard":
        capture["dashboard_smoke"]["passed"] = False
    elif change == "nonboolean":
        capture["results"][0]["passed"] = 1
    elif change == "partial":
        capture["status"] = "partial"
    output = Path("artifacts/calibration")
    (output / "browser-results.json").write_text(json.dumps(capture))
    monkeypatch.setenv("EVIDENCE_SHA", "b" * 64)
    (output / "promotion.json").write_text(
        json.dumps(
            {
                "corpus_sha256": os.environ["CORPUS_SHA"],
                "evidence_sha256": os.environ["EVIDENCE_SHA"],
                "source_run_id": os.environ["SOURCE_RUN_ID"],
                "source_commit_sha": os.environ["SOURCE_COMMIT_SHA"],
            }
        )
    )
    script = _calibration_workflow_python(
        "judge-calibration.yml",
        "Download and authenticate the fixed evidence bundle",
        index=1,
    )
    if change is None:
        exec(compile(script, "judge-calibration.yml", "exec"), {})
        assert (output / "browser-results-replay.json").exists()
    else:
        with pytest.raises((SystemExit, ValueError)):
            exec(compile(script, "judge-calibration.yml", "exec"), {})


@pytest.mark.parametrize("change", [None, "negative", "missing_done", "wrong_commit", "digest"])
def test_full_semantic_replay_preserves_reviewable_negative_evidence(
    reviewed_calibration_files, monkeypatch, change
):
    _corpus_path, capture = reviewed_calibration_files
    source = Path("artifacts/source")
    if change == "negative":
        capture["results"][0].update(
            passed=False,
            deterministic_failures=["graph missing"],
            failure_details=[{"kind": "quality", "code": "required_graph_missing"}],
        )
    elif change == "missing_done":
        capture["results"][0]["events"] = []
    elif change == "wrong_commit":
        (source / "run-context.json").write_text(json.dumps({"run_id": "123", "commit_sha": "c" * 40}))
    elif change == "digest":
        capture["corpus_sha256"] = "0" * 64
    capture_path = source / "browser-results.json"
    capture_path.write_text(json.dumps(capture))
    original = capture_path.read_bytes()
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setenv("GITHUB_ACTOR", "reviewer")
    monkeypatch.setattr("backend.eval.quality_corpus.corpus_sha256", lambda: os.environ["CORPUS_SHA"])
    script = _calibration_workflow_python(
        "semantic-review-replay.yml", "Validate deterministic scheduled source evidence"
    )
    if change in {None, "negative"}:
        exec(compile(script, "semantic-review-replay.yml", "exec"), {})
        context = json.loads(Path("artifacts/semantic-replay/replay-context.json").read_text())
        assert context["source_browser_sha256"] == hashlib.sha256(original).hexdigest()
        assert capture_path.read_bytes() == original
    else:
        with pytest.raises((SystemExit, ValueError)):
            exec(compile(script, "semantic-review-replay.yml", "exec"), {})


@pytest.mark.parametrize("name", ["live-eval.yml", "scheduled-eval.yml", "semantic-review-replay.yml"])
def test_standard_evaluation_has_no_human_corpus_prerequisite(name):
    workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    assert "CORPUS_STATUS" not in workflow
    assert "corpus-status" not in workflow
    assert "corpus-bootstrap-guidance" not in workflow
    assert "--require-approved-corpus" not in workflow
    assert "environment: staging-eval" in workflow
    if name != "semantic-review-replay.yml":
        assert "--manual-review-policy report-only" in workflow


@pytest.fixture
def run_live_eval_status():
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text(encoding="utf-8")
    status_step = workflow.split("- name: Resolve stable live-eval status\n", 1)[1]
    script = dedent(status_step.split("        run: |\n", 1)[1])

    def run(**overrides):
        environment = {
            "AI_IMPACT": "true",
            "TRUSTED": "true",
            "CLASSIFY_RESULT": "success",
            "APPROVAL_RESULT": "success",
            "TREE_APPROVED": "false",
            "EVAL_RESULT": "success",
            **overrides,
        }
        return subprocess.run(
            [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                script,
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    return run


def test_non_ai_live_status_passes_without_approval_or_evaluation(run_live_eval_status):
    result = run_live_eval_status(
        AI_IMPACT="false",
        TRUSTED="false",
        APPROVAL_RESULT="skipped",
        TREE_APPROVED="",
        EVAL_RESULT="skipped",
    )

    assert result.returncode == 0
    assert "No AI-impacting paths changed" in result.stdout


@pytest.mark.parametrize("ai_impact", ["", "invalid"])
def test_invalid_ai_impact_cannot_skip_required_evaluation(
    run_live_eval_status, ai_impact
):
    result = run_live_eval_status(AI_IMPACT=ai_impact, EVAL_RESULT="skipped")

    assert result.returncode == 1
    assert "invalid AI-impact state" in result.stderr


@pytest.mark.parametrize("corpus_status", ["approved", "pending_human_review", "", "invalid"])
def test_corpus_metadata_does_not_block_successful_automated_live_status(
    run_live_eval_status, corpus_status
):
    result = run_live_eval_status(CORPUS_STATUS=corpus_status)
    assert result.returncode == 0
    assert "Protected staging evaluation passed" in result.stdout


@pytest.mark.parametrize("trusted", ["false", ""])
def test_untrusted_ai_change_fails_required_live_status(run_live_eval_status, trusted):
    result = run_live_eval_status(TRUSTED=trusted)

    assert result.returncode == 1
    assert "requires maintainer review and a trusted branch" in result.stderr


@pytest.mark.parametrize("job_result", ["failure", "cancelled", "skipped", ""])
@pytest.mark.parametrize(
    ("job", "diagnostic", "overrides"),
    [
        ("CLASSIFY_RESULT", "Change classification failed", {"AI_IMPACT": "false"}),
        (
            "APPROVAL_RESULT",
            "Exact-tree approval lookup failed",
            {"TREE_APPROVED": "true"},
        ),
        ("EVAL_RESULT", "Protected staging evaluation did not pass", {}),
    ],
)
def test_failed_prerequisite_fails_required_live_status(
    run_live_eval_status, job_result, job, diagnostic, overrides
):
    result = run_live_eval_status(**{**overrides, job: job_result})

    assert result.returncode == 1
    assert diagnostic in result.stderr


@pytest.mark.parametrize("tree_approved", ["", "invalid"])
def test_invalid_tree_approval_fails_required_live_status(
    run_live_eval_status, tree_approved
):
    result = run_live_eval_status(TREE_APPROVED=tree_approved)

    assert result.returncode == 1
    assert "Exact-tree approval lookup returned an invalid state" in result.stderr


@pytest.mark.parametrize("eval_result", ["success", "failure", "cancelled", ""])
def test_approved_tree_requires_skipped_evaluation(run_live_eval_status, eval_result):
    result = run_live_eval_status(TREE_APPROVED="true", EVAL_RESULT=eval_result)

    assert result.returncode == 1
    assert "protected evaluation was not skipped" in result.stderr


def test_approved_tree_passes_required_live_status(run_live_eval_status):
    result = run_live_eval_status(TREE_APPROVED="true", EVAL_RESULT="skipped")

    assert result.returncode == 0
    assert "Exact tree already passed protected live evaluation" in result.stdout


def test_successful_evaluation_passes_required_live_status(run_live_eval_status):
    result = run_live_eval_status()

    assert result.returncode == 0
    assert "Protected staging evaluation passed" in result.stdout


def test_live_eval_job_allows_setup_around_the_bounded_browser_suite():
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text(encoding="utf-8")
    manifest = load_manifest()

    assert "timeout-minutes: 90" in workflow
    budgets = manifest["live"]["budgets"]
    settings = Settings(_env_file=None)
    assert settings.agent_timeout_s == 940
    assert settings.anthropic_max_concurrent_streams == 4
    assert budgets["application_turn_timeout_seconds"] == settings.agent_timeout_s + 30
    assert (
        budgets["browser_case_concurrency"] == settings.anthropic_max_concurrent_streams
    )
    assert budgets["browser_graph_case_concurrency"] == 2
    corpus = json.loads(
        (ROOT / "backend/eval/corpus/v1/cases.json").read_text(encoding="utf-8")
    )
    pr_case_ids = set(manifest["live"]["suites"]["pr"])
    pr_cases = [case for case in corpus["cases"] if case["id"] in pr_case_ids]
    # These are complete per-case path bounds for the current PR corpus. Logical
    # calls assume one provider request. Provider attempts include every adapter
    # retry and the configured Opus fallback. The tagged revision stops before
    # attempt 65, so the 144-attempt failure envelope cannot be spent.
    call_bounds = {
        "rag-grounding": (8, 16),
        "memory": (4, 12),
        "graph-off": (2, 6),
        "research": (9, 27),
        "node-followup": (10, 21),
        "graph-expansion": (18, 38),
        "applied-domain": (9, 18),
        "prompt-injection": (2, 6),
    }
    assert set(call_bounds) == {case["id"] for case in pr_cases}
    logical_call_bound = sum(bound[0] for bound in call_bounds.values())
    provider_attempt_bound = sum(bound[1] for bound in call_bounds.values())
    assert logical_call_bound == 62
    assert provider_attempt_bound == 144
    assert logical_call_bound <= budgets["application_calls"] < provider_attempt_bound
    assert budgets["browser_infrastructure_retry_count"] == 0
    assert budgets["browser_suite_max_timeout_seconds"] <= 60 * 60
    assert budgets["semantic_suite_timeout_seconds"] == 20 * 60
    assert budgets["semantic_full_suite_timeout_seconds"] == 60 * 60
    cost_policy = manifest["live"]["cost_policy"]
    assert cost_policy == {
        "mode": "report-only",
        "suite_limit_usd": None,
        "case_limit_usd": None,
        "baseline_min_runs": 5,
    }

    scheduled = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )
    assert "timeout-minutes: 150" in scheduled
    assert (
        "- id: browser\n        name: Start frontend and capture journeys" in scheduled
    )
    assert (
        "if: always() && hashFiles('artifacts/live-eval/browser-results.json') != ''"
        in scheduled
    )
    assert "BROWSER_OUTCOME: ${{ steps.browser.outcome }}" in scheduled
    assert (
        'if [ "$BROWSER_OUTCOME" != success ] || [ "$SEMANTIC_OUTCOME" != success ]; then'
        in scheduled
    )

    terraform_variables = (ROOT / "infra/terraform/gcp/variables.tf").read_text(
        encoding="utf-8"
    )
    request_timeout = terraform_variables.split(
        'variable "request_timeout_seconds"', 1
    )[1].split("}", 1)[0]
    assert "default     = 1000" in request_timeout
    deploy_workflows = "\n".join(
        (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        for name in ("live-eval.yml", "scheduled-eval.yml", "deploy-production.yml")
    )
    production = (ROOT / ".github/workflows/deploy-production.yml").read_text(
        encoding="utf-8"
    )
    assert "timeout-minutes: 35" in production
    assert deploy_workflows.count("--timeout 1000s") == 3
    assert (
        f"EVALUATION_PROVIDER_ATTEMPT_LIMIT: {budgets['application_calls']}"
        in deploy_workflows
    )
    assert (
        f"EVALUATION_PR_PROVIDER_ATTEMPT_LIMIT: {budgets['application_calls']}"
        in deploy_workflows
    )
    assert (
        f"EVALUATION_FULL_PROVIDER_ATTEMPT_LIMIT: "
        f"{budgets['application_full_calls']}" in deploy_workflows
    )
    assert (
        deploy_workflows.count(
            "EVALUATION_RUN_ID: ${{ github.run_id }}-${{ github.run_attempt }}"
        )
        == 2
    )
    assert (
        deploy_workflows.count("--update-env-vars ANTHROPIC_MAX_CONCURRENT_STREAMS=4")
        == 3
    )
    terraform_locals = (ROOT / "infra/terraform/gcp/locals.tf").read_text(
        encoding="utf-8"
    )
    assert 'ANTHROPIC_MAX_CONCURRENT_STREAMS = "4"' in terraform_locals
    assert 'POSTHOG_API_KEY                   = "posthog-api-key"' in terraform_locals
    assert (
        'POSTHOG_HOST                     = "https://eu.i.posthog.com"'
        in terraform_locals
    )
    env_example = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_MAX_CONCURRENT_STREAMS=4" in env_example
    assert "POSTHOG_API_KEY=" in env_example
    assert "POSTHOG_HOST=https://eu.i.posthog.com" in env_example


def test_browser_workflows_use_development_only_internal_auth_bootstrap():
    for name in ("live-eval.yml", "scheduled-eval.yml", "deploy-production.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "VITE_EVAL_AUTH_BOOTSTRAP=true" in workflow
        assert "./scripts/ci browser" in workflow


def test_production_rollout_requires_passed_main_digest_and_smoke():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text(
        encoding="utf-8"
    )

    assert "corpus-status" not in workflow
    assert "CORPUS_STATUS" not in workflow
    assert "branches: [main]" in workflow
    prepare = workflow.split("  prepare:\n", 1)[1].split("  backend:\n", 1)[0]
    condition = " ".join(prepare.split("    if: >-\n", 1)[1].split("    outputs:", 1)[0].split())
    assert condition == (
        "github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.head_repository.full_name == github.repository && "
        "github.event.workflow_run.head_branch == 'main' && "
        "(github.event.workflow_run.event == 'push' || "
        "github.event.workflow_run.event == 'workflow_dispatch')"
    )
    assert prepare.index("    if: >-") < prepare.index("actions/checkout@v4")
    assert "environment: production" in workflow
    assert '$IMAGE:approved-tree-$TREE_SHA' in workflow
    assert "production will not rebuild or substitute another image" in workflow
    assert "needs.backend.result == 'success' || needs.backend.result == 'skipped'" in workflow
    assert workflow.index("./scripts/ci browser") < workflow.index("--to-tags")


@pytest.mark.parametrize("policy", [None, "report-only", "blocking"])
def test_live_dispatch_preserves_selected_manual_review_policy(monkeypatch, policy):
    from scripts.ci_runner import _dispatch_eval, build_parser

    cli = ["live", "--suite", "pr", "--target", "https://candidate.example"]
    if policy:
        cli += ["--manual-review-policy", policy]
    args = build_parser().parse_args(cli)
    assert args.manual_review_policy == (policy or "report-only")
    commands = []
    monkeypatch.setattr(
        "scripts.ci_runner.subprocess.run", lambda argv, **kwargs: commands.append(argv)
    )
    _dispatch_eval("live", args)
    argv = commands[0]
    assert argv[argv.index("--manual-review-policy") + 1] == (policy or "report-only")


@pytest.mark.parametrize("event,suite,can_build", [
    ("workflow_dispatch", "full", True),
    ("workflow_dispatch", "diagnostic", True),
    ("workflow_dispatch", "nightly", False),
    ("schedule", "nightly", False),
    ("schedule", "full", False),
    ("schedule", "diagnostic", False),
])
@pytest.mark.parametrize("lookup", ["found", "missing", "error", "empty"])
def test_scheduled_image_preflight_authorizes_only_bounded_manual_builds(
    tmp_path, event, suite, can_build, lookup
):
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text()
    step = workflow.split("name: Preflight exact-tree approval before expensive setup\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("      - uses:", 1)[0])
    executable = tmp_path / "gcloud"
    executable.write_text('''#!/bin/bash
case "$LOOKUP" in
  found) echo sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
  missing) echo 'Image not found.' >&2; exit 1 ;;
  error) echo 'PERMISSION_DENIED' >&2; exit 7 ;;
  empty) exit 0 ;;
esac
''')
    executable.chmod(0o755)
    output = tmp_path / "output"
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
             "GITHUB_EVENT_NAME": event, "EVAL_SUITE": suite, "LOOKUP": lookup,
             "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(tmp_path), "IMAGE": "example/image"},
        capture_output=True, text=True, timeout=5, check=False,
    )
    expected = 0 if lookup == "found" or (lookup == "missing" and can_build) else (7 if lookup == "error" else 1)
    assert result.returncode == expected, result.stderr
    assert "commit_sha=" in output.read_text()
    assert "tree_sha=" in output.read_text()
    assert ("digest=sha256:" in output.read_text()) == (lookup == "found")
    if lookup == "error":
        assert "Exact-tree approval lookup failed" in result.stderr
    if lookup == "empty":
        assert "lookup returned no digest" in result.stderr


@pytest.mark.parametrize("event,suite,can_build", [
    ("workflow_dispatch", "full", True),
    ("workflow_dispatch", "diagnostic", True),
    ("workflow_dispatch", "nightly", False),
    ("schedule", "nightly", False),
])
@pytest.mark.parametrize("existing_digest", ["", "sha256:" + "a" * 64])
def test_scheduled_candidate_reuses_digest_or_builds_once(
    tmp_path, event, suite, can_build, existing_digest
):
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text()
    step = workflow.split("- name: Resolve approved digest or build an ephemeral evaluation candidate\n", 1)[1]
    script = dedent(step.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
    calls = tmp_path / "calls"
    for name, body in {
        "docker": 'echo "docker $*" >> "$CALLS"',
        "gcloud": 'echo "gcloud $*" >> "$CALLS"; echo "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
    }.items():
        executable = tmp_path / name
        executable.write_text(f"#!/bin/bash\n{body}\n")
        executable.chmod(0o755)
    output = tmp_path / "environment"
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
             "GITHUB_EVENT_NAME": event, "EVAL_SUITE": suite,
             "APPROVED_IMAGE_DIGEST": existing_digest, "GITHUB_ENV": str(output),
             "IMAGE": "example/image", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
             "EVALUATION_COMMIT_SHA": "c" * 40, "CALLS": str(calls)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == (0 if existing_digest or can_build else 1), result.stderr
    if existing_digest:
        assert not calls.exists()
        assert output.read_text() == f"IMAGE_DIGEST={existing_digest}\n"
    elif can_build:
        invocations = calls.read_text().splitlines()
        assert len(invocations) == 2
        assert invocations[0].startswith("docker buildx build ")
        assert "--tag example/image:evaluation-123-2 --push ." in invocations[0]
        assert f"org.opencontainers.image.revision={'c' * 40}" in invocations[0]
        assert output.read_text() == f"EVALUATION_IMAGE_TAG=evaluation-123-2\nIMAGE_DIGEST=sha256:{'b' * 64}\n"
    else:
        assert not calls.exists()
        assert not output.exists()


@pytest.mark.parametrize("change", [
    "pass", "manual_review", "mixed", "fail", "infrastructure",
    "failed_case", "infrastructure_case", "unknown_case", "missing_decision",
    "blocking_fail", "missing_blocking_status", "reordered", "missing_case",
    "duplicate", "missing_evaluations", "wrong_suite", "wrong_kind",
    "missing_report", "missing_provenance", "missing_subset",
])
def test_selective_replay_requires_exact_automated_passing_evidence(
    tmp_path, monkeypatch, change
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SELECTED_CASES_JSON", '["memory", "long-context"]')
    report = {
        "kind": "live_gate", "suite": "diagnostic", "status": "pass",
        "blocking_status": "pass",
        "evaluations": [
            {"id": "memory", "decision": "pass"},
            {"id": "long-context", "decision": "pass"},
        ],
    }
    if change in {"manual_review", "mixed", "fail", "infrastructure"}:
        report["status"] = "manual_review" if change == "mixed" else change
        report["evaluations"][0]["decision"] = report["status"]
        if change == "manual_review":
            report["evaluations"][1]["decision"] = "manual_review"
    elif change in {"failed_case", "infrastructure_case", "unknown_case"}:
        report["evaluations"][0]["decision"] = {
            "failed_case": "fail", "infrastructure_case": "infrastructure", "unknown_case": "unknown",
        }[change]
    elif change == "missing_decision":
        report["evaluations"][0].pop("decision")
    elif change == "blocking_fail":
        report["blocking_status"] = "fail"
    elif change == "missing_blocking_status":
        report.pop("blocking_status")
    elif change == "reordered":
        report["evaluations"].reverse()
    elif change == "missing_case":
        report["evaluations"].pop()
    elif change == "duplicate":
        report["evaluations"][1]["id"] = "memory"
    elif change == "missing_evaluations":
        report.pop("evaluations")
    elif change == "wrong_suite":
        report["suite"] = "full"
    elif change == "wrong_kind":
        report["kind"] = "browser"
    output = Path("artifacts/selective")
    output.mkdir(parents=True)
    for name, value in {
        "live-results.json": report,
        "replay-provenance.json": {},
        "browser-results.json": {},
    }.items():
        (output / name).write_text(json.dumps(value))
    missing_file = {
        "missing_report": "live-results.json",
        "missing_provenance": "replay-provenance.json",
        "missing_subset": "browser-results.json",
    }.get(change)
    if missing_file:
        (output / missing_file).unlink()
    script = _calibration_workflow_python(
        "semantic-review-replay.yml", "Require selective decisions to pass"
    )
    if change in {"pass", "manual_review", "mixed"}:
        exec(compile(script, "selective outcome", "exec"), {})
    else:
        with pytest.raises(SystemExit):
            exec(compile(script, "selective outcome", "exec"), {})
