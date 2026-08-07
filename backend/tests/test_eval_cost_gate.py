from eval.cost_gate import (
    CostPolicy,
    account_application_cost,
    account_judge_cost,
    evaluate_cost_policy,
)


def test_application_cost_is_attributed_by_attempt_thread_and_operation():
    accounting = account_application_cost(
        [
            {
                "id": "graph-expansion",
                "thread_id": "thread-final",
                "thread_ids": ["thread-first", "thread-final"],
            },
            {"id": "graph-off", "thread_id": "thread-light"},
        ],
        [
            {
                "thread_id": "thread-first",
                "operation": "graph_integration",
                "attempts": [
                    {
                        "provider": "anthropic",
                        "model": "claude-opus-5-20260801",
                        "input_tokens": 1_000,
                        "output_tokens": 100,
                        "queue_wait_ms": 30,
                    },
                    {
                        "provider": "openai",
                        "model": "gpt-5.4",
                        "input_tokens": 500,
                        "output_tokens": 50,
                        "queue_wait_ms": 0,
                    },
                ],
            },
            {
                "thread_id": "thread-light",
                "operation": "synthesis",
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "input_tokens": 100,
                "output_tokens": 10,
                "queue_wait_ms": 5,
            },
        ],
    )

    assert accounting["status"] == "pass"
    assert accounting["total"] == {
        "input_tokens": 1_600,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 160,
        "queue_wait_ms": 35,
        "estimated_usd": 0.0098,
    }
    graph = accounting["cases"][0]
    assert graph["input_tokens"] == 1_500
    assert graph["operations"][0]["provider_attempts"] == 2
    assert graph["operations"][0]["estimated_usd"] == 0.0095


def test_application_cost_prices_anthropic_cache_writes_and_reads():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "claude-opus-5",
                "input_tokens": 1_000,
                "cache_creation_input_tokens": 1_000,
                "cache_read_input_tokens": 1_000,
                "output_tokens": 100,
            }
        ],
    )

    assert accounting["status"] == "pass"
    assert accounting["total"] == {
        "input_tokens": 1_000,
        "cache_creation_input_tokens": 1_000,
        "cache_read_input_tokens": 1_000,
        "output_tokens": 100,
        "queue_wait_ms": 0,
        "estimated_usd": 0.01425,
    }


def test_application_cost_prices_kimi_automatic_cache_reads():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [{
            "thread_id": "thread",
            "operation": "graph_worker",
            "provider": "kimi",
            "model": "kimi-k3",
            "input_tokens": 1_000,
            "cache_read_input_tokens": 2_000,
            "output_tokens": 100,
        }],
    )

    assert accounting["status"] == "pass"
    assert accounting["total"]["estimated_usd"] == 0.0051


def test_application_cost_rejects_cache_usage_without_provider_pricing():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "gpt-5.4",
                "cache_read_input_tokens": 1_000,
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "unsupported prompt-cache pricing" in accounting["reason"]
    assert accounting["total"]["estimated_usd"] is None


def test_unpriced_model_is_infrastructure_and_never_zero_cost():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "new-unpriced-model",
                "input_tokens": 10,
                "output_tokens": 2,
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "unpriced model" in accounting["reason"]
    assert accounting["total"]["estimated_usd"] is None
    assert accounting["cases"][0]["estimated_usd"] is None
    assert accounting["cases"][0]["operations"][0]["estimated_usd"] is None
    assert evaluate_cost_policy(accounting)["blocking_status"] == "fail"


def test_specific_model_price_wins_over_a_shared_prefix():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "gpt-5.4-mini-2026-07-01",
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
            }
        ],
    )

    assert accounting["total"]["estimated_usd"] == 5.25


def test_model_prices_reject_lookalike_future_skus():
    for model in ("gpt-5.40", "gpt-5.4-turbo", "claude-opus-50"):
        accounting = account_application_cost(
            [{"id": "case", "thread_id": "thread"}],
            [
                {
                    "thread_id": "thread",
                    "operation": "synthesis",
                    "model": model,
                    "input_tokens": 10,
                    "output_tokens": 2,
                }
            ],
        )

        assert accounting["status"] == "infrastructure"
        assert f"unpriced model {model!r}" in accounting["reason"]


def test_case_with_a_thread_but_no_telemetry_is_unknown_not_zero_cost():
    accounting = account_application_cost(
        [
            {"id": "observed", "thread_id": "thread-observed"},
            {"id": "missing", "thread_id": "thread-missing"},
        ],
        [
            {
                "thread_id": "thread-observed",
                "operation": "synthesis",
                "model": "claude-opus-5",
                "input_tokens": 10,
                "output_tokens": 2,
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "'missing' has thread attribution but no application telemetry" in accounting[
        "reason"
    ]
    assert accounting["cases"][1]["estimated_usd"] is None
    assert accounting["total"]["estimated_usd"] is None


def test_accepted_attempt_with_incomplete_usage_is_unknown():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "attempts": [
                    {
                        "model": "claude-opus-5",
                        "status": "error_incomplete_usage",
                        "input_tokens": 100,
                        "output_tokens": 0,
                    }
                ],
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "incomplete usage after provider acceptance" in accounting["reason"]
    assert accounting["cases"][0]["input_tokens"] == 100
    assert accounting["cases"][0]["estimated_usd"] is None


def test_cost_policy_can_report_before_it_blocks():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "claude-opus-5",
                "input_tokens": 1_000,
                "output_tokens": 100,
            }
        ],
    )

    report_only = evaluate_cost_policy(
        accounting,
        CostPolicy(mode="report-only", suite_limit_usd=0.001),
    )
    blocking = evaluate_cost_policy(
        accounting,
        CostPolicy(mode="blocking", suite_limit_usd=0.001),
    )

    assert report_only["status"] == "over_budget"
    assert report_only["blocking_status"] == "pass"
    assert report_only["baseline_min_runs"] == 5
    assert blocking["blocking_status"] == "fail"


def test_judge_cost_remains_separate_and_per_case():
    accounting = account_judge_cost(
        [
            {
                "id": "case-a",
                "judgments": [
                    {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "estimated_cost_usd": 0.001,
                    }
                ],
            },
            {"id": "case-b", "judgments": []},
        ]
    )

    assert accounting["total"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "estimated_usd": 0.001,
    }
    assert accounting["cases"][0]["estimated_usd"] == 0.001
    assert accounting["cases"][1]["estimated_usd"] == 0.0


def test_blocking_cost_breach_is_visible_in_junit_and_summary(
    tmp_path, monkeypatch
):
    from eval.live_runner import _exit_code_for_statuses, _write_outputs

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = {
        "status": "fail",
        "blocking_status": "fail",
        "manual_review_policy": "blocking",
        "reason": "suite cost exceeds limit",
        "evaluations": [
            {"id": "case", "decision": "pass", "reason": "passed", "judgments": []}
        ],
        "cost_accounting": {
            "policy": {
                "mode": "blocking",
                "status": "over_budget",
                "blocking_status": "fail",
                "reason": "suite cost exceeds limit",
            },
            "application": {"total": {"estimated_usd": 1.25}},
        },
    }

    _write_outputs(tmp_path / "live-results.json", report)

    junit = (tmp_path / "live-junit.xml").read_text(encoding="utf-8")
    assert 'tests="2"' in junit
    assert 'failures="1"' in junit
    assert 'name="application-cost-policy"' in junit
    assert "suite cost exceeds limit" in junit
    summary_text = summary.read_text(encoding="utf-8")
    assert "Cost policy: `over_budget` (blocking)" in summary_text
    assert "Application cost: `$1.250000`" in summary_text
    assert _exit_code_for_statuses({"fail", "infrastructure"}, "blocking") == 1
