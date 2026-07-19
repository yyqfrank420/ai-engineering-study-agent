from __future__ import annotations

import inspect
from pathlib import Path
import time

import pytest

from eval.browser_runner import _session_expires_soon, run_browser
from scripts.ci_runner import classify_paths, load_manifest, trust_for_event, validate_manifest


ROOT = Path(__file__).resolve().parents[2]


def test_manifest_tracks_every_backend_test():
    validate_manifest(load_manifest())


def test_browser_navigation_does_not_wait_for_long_lived_connections_to_close():
    source = inspect.getsource(run_browser)

    assert 'wait_until="networkidle"' not in source
    assert source.count('wait_until="domcontentloaded"') == 2
    assert source.count("_wait_for_composer_ready(page)") == 2


def test_internal_session_is_renewed_before_its_expiry_buffer():
    now = time.time()

    assert _session_expires_soon({"expires_at": now + 599})
    assert not _session_expires_soon({"expires_at": now + 601})
    assert _session_expires_soon({})


def test_manifest_validation_fails_when_a_tracked_test_is_omitted():
    manifest = load_manifest()
    for group in manifest["offline_groups"]:
        for command in group["commands"]:
            if "backend/tests/test_api_security.py" in command["argv"]:
                command["argv"].remove("backend/tests/test_api_security.py")

    with pytest.raises(ValueError, match="unassigned tests: backend/tests/test_api_security.py"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["README.md", "docs/current-architecture.md"], {"docs_only": True, "ai_impact": False}),
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
    workflow_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / ".github/workflows").glob("*.yml"))

    assert "pull_request_target" not in workflow_text


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

    staging_secrets = iam.split("staging_ci_secret_ids = toset([", 1)[1].split("])" , 1)[0]
    production_secrets = iam.split("production_ci_secret_ids = toset([", 1)[1].split("])" , 1)[0]
    assert "staging-supabase-db-url" in staging_secrets
    assert "production-migration-db-url" not in staging_secrets
    assert "production-migration-db-url" in production_secrets
    assert "staging-supabase-db-url" not in production_secrets
    assert "environment:staging-eval" in federation
    assert "environment:production" in federation
    assert "legacy_ci_wif_binding" in federation
    assert "count              = var.retain_legacy_ci_access ? 1 : 0" in federation
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    transition = variables.split('variable "retain_legacy_ci_access"', 1)[1].split("}", 1)[0]
    assert "default     = false" in transition


def test_required_check_names_are_stable():
    workflows = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / ".github/workflows").glob("*.yml"))

    assert "name: CI required" in workflows
    assert "name: Live eval required" in workflows


def test_pending_corpus_has_a_trusted_full_suite_bootstrap_path():
    workflow = (ROOT / ".github/workflows/scheduled-eval.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "environment: staging-eval" in workflow
    assert "corpus-bootstrap-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in workflow
    assert 'if [ "$CORPUS_STATUS" = approved ]; then' in workflow
    assert "Approved corpus requires an existing exact-tree image approval." in workflow
    assert "A pending corpus can be bootstrapped only by a manually dispatched full-suite run." in workflow
    assert 'gcloud artifacts docker tags delete "$IMAGE:$BOOTSTRAP_IMAGE_TAG"' in workflow
    assert 'EVAL_EMAIL="$email" python scripts/staging_database.py reset' in workflow
    assert "artifacts/live-eval/run-context.json" in workflow
    assert "name: Wait for candidate readiness" in workflow
    assert '[ "$frontend_ready" = true ]' in workflow
    assert "VITE_EVAL_AUTH_BOOTSTRAP=true" in workflow

    approval_state = workflow.index("name: Resolve corpus approval state without installing dependencies")
    dependency_setup = workflow.index("uses: actions/setup-python@v5")
    candidate_resolution = workflow.index("name: Resolve approved digest or build the one-time corpus candidate")
    candidate_readiness = workflow.index("name: Wait for candidate readiness")
    browser_capture = workflow.index("name: Start frontend and capture journeys")
    assert approval_state < dependency_setup < candidate_resolution < candidate_readiness < browser_capture
    assert workflow.index('echo "BOOTSTRAP_IMAGE_TAG=$bootstrap_tag"') < workflow.index("docker buildx build")
    assert workflow.index('echo "REVISION_TAG=$tag"') < workflow.index("gcloud run deploy")


def test_pending_corpus_pr_skips_expensive_live_work_successfully():
    workflow = (ROOT / ".github/workflows/live-eval.yml").read_text(encoding="utf-8")

    assert "name: Pending corpus bootstrap guidance" in workflow
    assert "needs.classify.outputs.corpus-status == 'approved'" in workflow
    assert 'if [ "$CORPUS_STATUS" != approved ]; then' in workflow
    corpus_state = workflow.index("name: Resolve corpus approval state without installing dependencies")
    dependency_setup = workflow.index("uses: actions/setup-python@v5")
    assert corpus_state < dependency_setup


def test_browser_workflows_use_development_only_internal_auth_bootstrap():
    for name in ("live-eval.yml", "scheduled-eval.yml", "deploy-production.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "VITE_EVAL_AUTH_BOOTSTRAP=true" in workflow
        assert "./scripts/ci browser" in workflow


def test_pending_corpus_does_not_trigger_production_rollout():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "needs.prepare.outputs.corpus-status == 'approved'" in workflow
