# ─────────────────────────────────────────────────────────────────────────────
# File: backend/tests/test_mode_controls.py
# Purpose: Tests for the new mode-control features:
#            - ChatRequest field validation (complexity, graph_mode, research_enabled)
#            - research_worker _format_results (noise filtering, dedup, bullet format)
#            - research_worker explicit degradation when DDG raises
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import uuid

import pytest


# ── ChatRequest field validation ──────────────────────────────────────────────

class TestChatRequestValidation:
    """Validates that new mode-control fields accept valid values and
    coerce invalid values to sensible defaults rather than raising 422."""

    def _request(self, **kwargs) -> dict:
        """Build a minimal valid request payload."""
        return {
            "thread_id": str(uuid.uuid4()),
            "content": "test",
            **kwargs,
        }

    def test_valid_complexity_values(self):
        from api.sse_handler import ChatRequest

        for value in ("auto", "low", "prototype", "production"):
            req = ChatRequest(**self._request(complexity=value))
            assert req.complexity == value

    def test_invalid_complexity_coerces_to_auto(self):
        from api.sse_handler import ChatRequest

        req = ChatRequest(**self._request(complexity="extreme"))
        assert req.complexity == "auto"

    def test_valid_graph_mode_values(self):
        from api.sse_handler import ChatRequest

        for value in ("auto", "on", "off"):
            req = ChatRequest(**self._request(graph_mode=value))
            assert req.graph_mode == value

    def test_invalid_graph_mode_coerces_to_auto(self):
        from api.sse_handler import ChatRequest

        req = ChatRequest(**self._request(graph_mode="force"))
        assert req.graph_mode == "auto"

    def test_research_enabled_defaults_to_false(self):
        from api.sse_handler import ChatRequest

        req = ChatRequest(**self._request())
        assert req.research_enabled is False

    def test_research_enabled_accepts_true(self):
        from api.sse_handler import ChatRequest

        req = ChatRequest(**self._request(research_enabled=True))
        assert req.research_enabled is True

    def test_defaults_applied_when_fields_omitted(self):
        from api.sse_handler import ChatRequest

        req = ChatRequest(**self._request())
        assert req.complexity == "auto"
        assert req.graph_mode == "auto"
        assert req.research_enabled is False


@pytest.mark.parametrize(
    "query",
    [
        "growth marketing AI agent system that evaluates campaigns and adjusts targeting",
        "multi-agent customer support chatbot architecture",
        "Describe a production model serving stack",
        "self-improving AI system for performance marketing",
    ],
)
def test_applied_system_design_detection(query):
    from agent.complexity import is_applied_system_design_request

    assert is_applied_system_design_request(query)


@pytest.mark.parametrize(
    "query",
    [
        "Explain retrieval augmented generation",
        "What is agent planning?",
        "Create a concise summary of the last answer",
        "What is a machine learning pipeline?",
    ],
)
def test_concept_questions_do_not_trigger_applied_design(query):
    from agent.complexity import is_applied_system_design_request

    assert not is_applied_system_design_request(query)


@pytest.mark.parametrize(
    "query",
    [
        "customer support chatbot",
        "fraud detection copilot",
        "personal finance assistant",
        "clinical intake automation",
        "invoice reconciliation agent",
        "growth marketing multi-agent system",
        "Design customer support chatbot",
    ],
)
def test_terse_product_seeds_trigger_applied_design_enrichment(query):
    from agent.complexity import is_applied_system_design_request, resolve_complexity

    assert is_applied_system_design_request(query)
    assert resolve_complexity("auto", query).resolved == "production"


@pytest.mark.parametrize(
    "query",
    [
        "What is a customer support chatbot?",
        "How does an invoice reconciliation agent work?",
        "Explain a fraud detection copilot",
        "AI assistant",
        "agent",
    ],
)
def test_concepts_and_domain_free_product_nouns_do_not_invent_a_system(query):
    from agent.complexity import is_applied_system_design_request

    assert not is_applied_system_design_request(query)


@pytest.mark.parametrize(
    ("requested", "expected_range"),
    [
        ("low", (5, 7)),
        ("prototype", (7, 9)),
        ("production", (9, 10)),
    ],
)
def test_complexity_profiles_keep_diagrams_within_the_ui_node_cap(requested, expected_range):
    from agent.complexity import resolve_complexity
    from config import settings

    profile = resolve_complexity(requested, "Design a production AI system")

    assert (profile.min_graph_nodes, profile.max_graph_nodes) == expected_range
    assert profile.max_graph_nodes <= settings.max_graph_nodes


def test_self_improving_applied_system_defaults_to_production_depth():
    from agent.complexity import resolve_complexity

    profile = resolve_complexity("auto", "self-improving AI system for performance marketing")

    assert profile.resolved == "production"
    assert (profile.min_graph_nodes, profile.max_graph_nodes) == (9, 10)


def test_terse_graph_followup_restores_the_original_design_context():
    from agent.complexity import resolve_design_query

    query = resolve_design_query(
        "expand the approval path",
        history=[
            {"role": "user", "content": "growth marketing multi-agent system"},
            {"role": "assistant", "content": "Here is the first design."},
        ],
        graph_data={
            "title": "Campaign Optimisation Loop",
            "graph_type": "architecture",
            "nodes": [{"label": "Channel Executor"}, {"label": "Outcome Attribution"}],
        },
    )

    assert "growth marketing multi-agent system" in query
    assert "Campaign Optimisation Loop" in query
    assert "Channel Executor" in query
    assert query.endswith("expand the approval path")


# ── research_worker._format_results ──────────────────────────────────────────

class TestFormatResults:
    """Unit-tests the result formatting logic in isolation — no network calls."""

    def _make_result(self, href: str, title: str, body: str) -> dict:
        return {"href": href, "title": title, "body": body}

    def test_returns_empty_string_when_no_results(self):
        from agent.nodes.research_worker import _format_results

        result = _format_results([], noise_domains=[])
        assert result == ""

    def test_returns_empty_string_when_all_noise(self):
        from agent.nodes.research_worker import _format_results

        raw = [
            self._make_result("https://reddit.com/r/ml", "ML post", "some body"),
            self._make_result("https://youtube.com/watch?v=x", "Video", "content"),
        ]
        result = _format_results(raw, noise_domains=["reddit.com", "youtube.com"])
        assert result == ""

    def test_filters_noise_domains(self):
        from agent.nodes.research_worker import _format_results

        raw = [
            self._make_result("https://reddit.com/r/ml", "Noise", "noise body"),
            self._make_result("https://aws.amazon.com/blogs/ml", "AWS Blog", "useful content"),
        ]
        result = _format_results(raw, noise_domains=["reddit.com"])
        assert "reddit.com" not in result
        assert "aws.amazon.com" in result

    def test_deduplicates_same_url(self):
        from agent.nodes.research_worker import _format_results

        raw = [
            self._make_result("https://example.com/post", "Title A", "Body one"),
            self._make_result("https://example.com/post", "Title A", "Body one"),
        ]
        result = _format_results(raw, noise_domains=[])
        # Only one bullet should appear
        assert result.count("example.com") == 1

    def test_caps_at_six_bullets(self):
        from agent.nodes.research_worker import _format_results

        raw = [
            self._make_result(f"https://example.com/{i}", f"Title {i}", f"Body {i}")
            for i in range(10)
        ]
        result = _format_results(raw, noise_domains=[])
        assert result.count("\n- ") == 5  # 6 bullets = 5 internal newlines + 1 leading

    def test_skips_items_with_no_body(self):
        from agent.nodes.research_worker import _format_results

        raw = [
            self._make_result("https://no-body.example.com/a", "Title", ""),
            self._make_result("https://has-body.example.com/b", "Title B", "Has body"),
        ]
        result = _format_results(raw, noise_domains=[])
        assert "no-body.example.com" not in result
        assert "has-body.example.com" in result

    def test_truncates_long_title_and_body(self):
        from agent.nodes.research_worker import _format_results

        long_title = "X" * 200
        long_body  = "Y" * 200
        raw = [self._make_result("https://example.com", long_title, long_body)]
        result = _format_results(raw, noise_domains=[])
        # Ellipsis markers should appear
        assert "…" in result
        # Bullet should be a single line
        assert result.count("\n") == 0

    def test_bullet_format_has_domain_title_body(self):
        from agent.nodes.research_worker import _format_results

        raw = [self._make_result("https://docs.anthropic.com/guide", "Claude Docs", "Helpful text")]
        result = _format_results(raw, noise_domains=[])
        assert result.startswith("- Claude Docs — <https://docs.anthropic.com/guide>")
        assert "Claude Docs" in result
        assert "Helpful text" in result

    def test_extracts_exact_formatted_source_urls(self):
        from agent.nodes.research_worker import _source_urls

        context = "- Source — <https://example.com/report?q=agent>: body"

        assert _source_urls(context) == ["https://example.com/report?q=agent"]

    def test_rejects_non_http_and_credential_bearing_source_urls(self):
        from agent.nodes.research_worker import _format_results

        raw = [
            self._make_result("javascript:alert(1)", "Unsafe", "body"),
            self._make_result("https://user@example.com/private", "Credentials", "body"),
            self._make_result("https://example.com/public", "Public", "body"),
        ]

        assert _format_results(raw, noise_domains=[]) == "- Public — <https://example.com/public>: body"


# ── research_worker_node error resilience ─────────────────────────────────────

class TestResearchWorkerResilience:
    """Verifies that DDG failures don't crash the pipeline."""

    def _make_state(self) -> dict:
        events = []

        async def send(event):
            events.append(event)

        return {
            "user_message":      "RAG pipeline architecture",
            "research_context":  "",
            "complexity":        "auto",
            "graph_mode":        "auto",
            "research_enabled":  True,
            "send":              send,
            "_events":           events,
        }

    def test_ddg_exception_returns_empty_context(self, monkeypatch):
        """When DDG raises, the pipeline degrades explicitly to book evidence."""
        import agent.nodes.research_worker as rw

        def raise_on_search(queries, results_per_query):
            raise RuntimeError("DDG unavailable")

        monkeypatch.setattr(rw, "_run_ddg_searches", raise_on_search)

        state = self._make_state()
        result = asyncio.new_event_loop().run_until_complete(
            rw.research_worker_node(state)
        )

        assert result["research_context"] == ""
        assert result["research_status"] == "unavailable"
        assert any("unavailable" in event.get("status", "").lower() for event in state["_events"])

    def test_worker_emits_status_event(self, monkeypatch):
        """A worker_status event is always sent, even before the search runs."""
        import agent.nodes.research_worker as rw

        monkeypatch.setattr(rw, "_run_ddg_searches", lambda *_: [])

        state = self._make_state()
        asyncio.new_event_loop().run_until_complete(rw.research_worker_node(state))

        events = state["_events"]
        assert any(e.get("type") == "worker_status" and e.get("worker") == "research"
                   for e in events)

    def test_empty_ddg_results_returns_empty_context(self, monkeypatch):
        """Empty search results produce an empty research_context."""
        import agent.nodes.research_worker as rw

        monkeypatch.setattr(rw, "_run_ddg_searches", lambda *_: [])

        state = self._make_state()
        result = asyncio.new_event_loop().run_until_complete(
            rw.research_worker_node(state)
        )

        assert result["research_context"] == ""
        assert result["research_status"] == "unavailable"

    def test_success_status_exposes_source_provenance(self, monkeypatch):
        import agent.nodes.research_worker as rw

        monkeypatch.setattr(
            rw,
            "_run_ddg_searches",
            lambda _queries, _limit: [{
                "href": "https://example.com/report",
                "title": "Report",
                "body": "Current evidence",
            }],
        )
        state = self._make_state()

        result = asyncio.run(rw.research_worker_node(state))

        assert result["research_status"] == "ready"
        assert state["_events"][-1]["sources"] == ["https://example.com/report"]

    def test_success_emits_bounded_research_evidence_for_allowlisted_internal_identity(self, monkeypatch):
        import agent.nodes.research_worker as rw

        monkeypatch.setattr(rw.settings, "db_schema", "public")
        monkeypatch.setattr(
            rw.settings,
            "internal_test_email_allowlist_raw",
            "eval@example.com",
        )
        monkeypatch.setattr(
            rw,
            "_run_ddg_searches",
            lambda _queries, _limit: [{
                "href": "https://example.com/report",
                "title": "Report",
                "body": "Current external evidence",
            }],
        )
        state = {**self._make_state(), "user_email": "eval@example.com"}

        asyncio.run(rw.research_worker_node(state))

        evidence = state["_events"][-1]
        assert evidence == {
            "type": "research_evidence",
            "query": "RAG pipeline architecture",
            "results": [
                "- Report — <https://example.com/report>: Current external evidence"
            ],
        }

    def test_success_does_not_emit_research_evidence_for_non_allowlisted_identity(self, monkeypatch):
        import agent.nodes.research_worker as rw

        monkeypatch.setattr(rw.settings, "internal_test_email_allowlist_raw", "eval@example.com")
        monkeypatch.setattr(
            rw,
            "_run_ddg_searches",
            lambda _queries, _limit: [{
                "href": "https://example.com/report",
                "title": "Report",
                "body": "Current external evidence",
            }],
        )
        state = {**self._make_state(), "user_email": "customer@example.com"}

        asyncio.run(rw.research_worker_node(state))

        assert [event["type"] for event in state["_events"]] == ["worker_status", "worker_status"]

    def test_build_queries_uses_current_year_instead_of_hard_coded_year(self, monkeypatch):
        from datetime import datetime

        import agent.nodes.research_worker as rw

        class _FrozenDateTime:
            @classmethod
            def now(cls, tz=None):
                return datetime(2032, 1, 1, tzinfo=tz)

        monkeypatch.setattr(rw, "datetime", _FrozenDateTime)

        queries = rw._build_queries("RAG pipeline")

        assert queries[0] == "RAG pipeline reference architecture reliability security"
        assert queries[1] == "RAG operating model workflow decision points KPIs"
        assert queries[2] == "RAG best practices failure modes 2032"

    def test_build_queries_researches_the_domain_function_behind_a_terse_design_seed(self):
        import agent.nodes.research_worker as rw

        queries = rw._build_queries("growth marketing multi-agent system")

        assert queries[0].startswith("growth marketing multi-agent system reference architecture")
        assert queries[1] == "growth marketing operating model workflow decision points KPIs"
        assert queries[2].startswith("growth marketing best practices failure modes ")

    def test_worker_researches_restored_design_query_for_terse_followup(self, monkeypatch):
        import agent.nodes.research_worker as rw

        captured_queries = []
        monkeypatch.setattr(
            rw,
            "_run_ddg_searches",
            lambda queries, _limit: captured_queries.extend(queries) or [],
        )
        state = {
            **self._make_state(),
            "user_message": "expand this",
            "design_query": "growth marketing multi-agent system expand this",
        }

        asyncio.run(rw.research_worker_node(state))

        assert captured_queries[0].startswith(
            "growth marketing multi-agent system expand this reference architecture"
        )

    def test_topic_truncation_preserves_word_boundaries(self):
        from agent.nodes.research_worker import _normalise_topic

        topic = _normalise_topic("word " * 60)

        assert len(topic) <= 160
        assert topic.endswith("word")

    def test_run_ddg_searches_continues_after_single_query_failure(self, monkeypatch):
        import sys
        import types
        from agent.nodes.research_worker import _run_ddg_searches

        calls = []

        class _DDGS:
            def __init__(self, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def text(self, query, max_results):
                calls.append((query, max_results))
                if query == "bad":
                    raise RuntimeError("search failed")
                return [{"href": f"https://example.com/{query}", "title": query, "body": "body"}]

        monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=_DDGS))

        assert _run_ddg_searches(["good", "bad", "later"], 2) == [
            {"href": "https://example.com/good", "title": "good", "body": "body"},
            {"href": "https://example.com/later", "title": "later", "body": "body"},
        ]
        assert calls == [("good", 2), ("bad", 2), ("later", 2)]

    def test_run_ddg_searches_retries_one_empty_provider_session(self, monkeypatch):
        import sys
        import types
        from agent.nodes.research_worker import _run_ddg_searches

        sessions = []

        class _DDGS:
            def __init__(self, timeout):
                sessions.append(self)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def text(self, query, max_results):
                if len(sessions) == 1:
                    return []
                return [{
                    "href": "https://example.com/recovered",
                    "title": query,
                    "body": "recovered",
                }]

        monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=_DDGS))
        monkeypatch.setattr("agent.nodes.research_worker.time.sleep", lambda _seconds: None)

        results = _run_ddg_searches(["first", "second"], 2)

        assert len(sessions) == 2
        assert results[0]["href"] == "https://example.com/recovered"
