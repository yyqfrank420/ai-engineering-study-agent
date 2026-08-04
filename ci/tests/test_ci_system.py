from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from config import Settings
from eval.browser_runner import _execute_browser, _run_browser_attempt
from scripts.ci_runner import (
    classify_paths,
    load_manifest,
    select_offline_groups,
    trust_for_event,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


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
            {"agent-rag-llm", "static-security", "container", "pipeline-policy"},
        ),
        (
            ["backend/tests/test_quality_corpus.py"],
            {"eval-quality", "static-security", "pipeline-policy"},
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
    variables = (ROOT / "infra/terraform/gcp/variables.tf").read_text(
        encoding="utf-8"
    )
    staging = cloud_run.split(
        'resource "google_cloud_run_v2_service" "backend_staging"', 1
    )[1]
    staging_template = staging.split("containers {", 1)[0]
    container_concurrency = variables.split(
        'variable "container_concurrency"', 1
    )[1].split("}", 1)[0]

    assert (
        "max_instance_request_concurrency = var.container_concurrency"
        in staging_template
    )
    assert "min_instance_count = 0" in staging_template
    assert "max_instance_count = 1" in staging_template
    assert "default     = 4" in container_concurrency


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
    assert 'files[item["path"]] = (item["mode"], entry_type, item["sha"])' in verification
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
    assert "if context_commit == source_commit:" in verification
    assert 'tested_parents = tested.get("parents", [])' in verification
    assert "if len(tested_parents) != 2:" in verification
    assert (
        'parents = {parent["sha"] for parent in tested_parents}'
        in verification
    )
    assert "if source_commit not in parents:" in verification
    assert 'recorded_tree = context.get("tree_sha")' in verification
    assert (
        'not re.fullmatch(r"[0-9a-f]{40}", recorded_tree)'
        in verification
    )
    assert 'if recorded_tree != tested["tree"]["sha"]:' in verification
    assert (
        'if run.get("event") == "pull_request" and not deployment_commits:'
        in verification
    )
    assert "tested_commit = next(iter(deployment_commits), source_commit)" in verification
    assert "source_cases = case_map(tested_commit)" in verification
    assert 'context.get("commit_sha") != source_commit' not in verification


def test_scheduled_eval_missing_approval_fails_closed_before_expensive_setup():
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )
    preflight = workflow.split(
        "name: Preflight exact-tree approval before expensive setup", 1
    )[1].split("- uses: actions/setup-python@v5", 1)[0]

    assert "id: approved_image" in workflow
    assert 'commit_sha="$(git rev-parse HEAD)"' in preflight
    assert 'tree_sha="$(git rev-parse \'HEAD^{tree}\')"' in preflight
    assert 'approval_tag="approved-tree-$tree_sha"' in preflight
    assert '2>"$lookup_error_file"' in preflight
    assert 'lookup_status=$?' in preflight
    assert 'if ! grep -Fq "Image not found" "$lookup_error_file"; then' in preflight
    assert "Exact-tree approval lookup failed:" in preflight
    assert 'exit "$lookup_status"' in preflight
    assert "Exact-tree approval lookup returned no digest:" in preflight
    assert "2>/dev/null || true" not in preflight
    assert (
        'if [ "$GITHUB_EVENT_NAME" = workflow_dispatch ] '
        '&& [ "$EVAL_SUITE" = diagnostic ]; then'
        in preflight
    )
    assert "Missing exact-tree evaluation approval:" in preflight
    assert "commit=$commit_sha tree=$tree_sha image_tag=$IMAGE:$approval_tag" in preflight
    assert (
        "The protected live evaluation must publish this exact-tree tag" in preflight
    )
    assert preflight.rstrip().endswith("exit 1")

    dependency_setup = workflow.index("uses: actions/setup-python@v5")
    assert workflow.index("id: approved_image") < dependency_setup
    assert workflow.index("pip install -r backend/requirements.txt") > dependency_setup
    assert workflow.index("python scripts/staging_database.py reset") > dependency_setup
    assert (
        "APPROVED_IMAGE_DIGEST: ${{ steps.approved_image.outputs.digest }}" in workflow
    )
    assert 'digest="$APPROVED_IMAGE_DIGEST"' in workflow


def test_scheduled_eval_preserves_approval_and_diagnostic_build_boundaries():
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "environment: staging-eval" in workflow
    assert "corpus-bootstrap-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in workflow
    assert "diagnostic-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in workflow
    assert 'if [ "$CORPUS_STATUS" = approved ]; then' in workflow
    assert "Missing exact-tree evaluation approval:" in workflow
    assert (
        'if [ "$GITHUB_EVENT_NAME" != workflow_dispatch ] || '
        '[ "$EVAL_SUITE" != diagnostic ]; then'
        in workflow
    )
    assert (
        "A pending corpus can be bootstrapped only by a manually dispatched full or diagnostic run."
        in workflow
    )
    assert "Diagnostic suite requires one to eight unique case IDs." in workflow
    assert (
        'for case_id in "${selected_cases[@]}"; do case_args+=(--case "$case_id"); done'
        in workflow
    )
    assert (
        'gcloud artifacts docker tags delete "$IMAGE:$BOOTSTRAP_IMAGE_TAG"' in workflow
    )
    assert (
        'gcloud artifacts docker tags delete "$IMAGE:$DIAGNOSTIC_IMAGE_TAG"'
        in workflow
    )
    assert "docker tags add" not in workflow
    assert 'EVAL_EMAIL="$email" python scripts/staging_database.py reset' in workflow
    assert "artifacts/live-eval/run-context.json" in workflow
    assert "name: Wait for candidate readiness" in workflow
    assert '[ "$frontend_ready" = true ]' in workflow
    assert "VITE_EVAL_AUTH_BOOTSTRAP=true" in workflow

    approval_state = workflow.index(
        "name: Resolve corpus approval state without installing dependencies"
    )
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
        approval_state
        < approval_preflight
        < dependency_setup
        < candidate_resolution
        < candidate_readiness
        < browser_capture
    )
    diagnostic_env = workflow.index('echo "DIAGNOSTIC_IMAGE_TAG=$diagnostic_tag"')
    diagnostic_build = workflow.index("docker buildx build", diagnostic_env)
    bootstrap_env = workflow.index('echo "BOOTSTRAP_IMAGE_TAG=$bootstrap_tag"')
    bootstrap_build = workflow.index("docker buildx build", bootstrap_env)
    assert diagnostic_env < diagnostic_build
    assert bootstrap_env < bootstrap_build
    assert workflow.index('echo "REVISION_TAG=$tag"') < workflow.index(
        "gcloud run deploy"
    )


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
    assert "source browser evidence is incomplete" in promotion
    assert "actual_ids != expected_ids" in promotion
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


def test_pending_corpus_pr_skips_expensive_live_work_successfully():
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text(encoding="utf-8")

    assert "name: Pending corpus bootstrap guidance" in workflow
    assert "needs.classify.outputs.corpus-status == 'approved'" in workflow
    assert 'if [ "$CORPUS_STATUS" != approved ]; then' in workflow
    corpus_state = workflow.index(
        "name: Resolve corpus approval state without installing dependencies"
    )
    dependency_setup = workflow.index("uses: actions/setup-python@v5")
    assert corpus_state < dependency_setup


def test_live_eval_job_allows_setup_around_the_bounded_browser_suite():
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text(encoding="utf-8")
    manifest = load_manifest()

    assert "timeout-minutes: 90" in workflow
    budgets = manifest["live"]["budgets"]
    settings = Settings(_env_file=None)
    assert settings.agent_timeout_s == 360
    assert settings.anthropic_max_concurrent_streams == 4
    assert budgets["application_turn_timeout_seconds"] == settings.agent_timeout_s + 30
    assert (
        budgets["browser_case_concurrency"] == settings.anthropic_max_concurrent_streams
    )
    assert budgets["browser_graph_case_concurrency"] == 2
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
    assert "timeout-minutes: 130" in scheduled
    assert "- id: browser\n        name: Start frontend and capture journeys" in scheduled
    assert "if: always() && hashFiles('artifacts/live-eval/browser-results.json') != ''" in scheduled
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
    assert "default     = 420" in request_timeout
    deploy_workflows = "\n".join(
        (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        for name in ("live-eval.yml", "scheduled-eval.yml", "deploy-production.yml")
    )
    assert deploy_workflows.count("--timeout 420s") == 3
    assert (
        deploy_workflows.count(
            "--update-env-vars ANTHROPIC_MAX_CONCURRENT_STREAMS=4"
        )
        == 3
    )
    terraform_locals = (ROOT / "infra/terraform/gcp/locals.tf").read_text(
        encoding="utf-8"
    )
    assert 'ANTHROPIC_MAX_CONCURRENT_STREAMS = "4"' in terraform_locals
    env_example = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_MAX_CONCURRENT_STREAMS=4" in env_example


def test_browser_workflows_use_development_only_internal_auth_bootstrap():
    for name in ("live-eval.yml", "scheduled-eval.yml", "deploy-production.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "VITE_EVAL_AUTH_BOOTSTRAP=true" in workflow
        assert "./scripts/ci browser" in workflow


def test_pending_corpus_does_not_trigger_production_rollout():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text(
        encoding="utf-8"
    )

    assert "needs.prepare.outputs.corpus-status == 'approved'" in workflow
