# ─────────────────────────────────────────────────────────────────────────────
# File: backend/tests/test_mode_controls.py
# Purpose: Tests for the new mode-control features:
#            - ChatRequest field validation (complexity, graph_mode, research_enabled)
#            - research_worker _format_results (noise filtering, dedup, bullet format)
#            - research_worker silent failure when DDG raises
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
        assert result.startswith("- [docs.anthropic.com]")
        assert "Claude Docs" in result
        assert "Helpful text" in result


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
        """When DDG raises any exception, research_context is empty string."""
        import agent.nodes.research_worker as rw

        def raise_on_search(queries, results_per_query):
            raise RuntimeError("DDG unavailable")

        monkeypatch.setattr(rw, "_run_ddg_searches", raise_on_search)

        state = self._make_state()
        result = asyncio.new_event_loop().run_until_complete(
            rw.research_worker_node(state)
        )

        assert result["research_context"] == ""

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

    def test_build_queries_uses_current_year_instead_of_hard_coded_year(self):
        from datetime import datetime, timezone

        from agent.nodes.research_worker import _build_queries

        queries = _build_queries("RAG pipeline")

        assert queries[0] == "RAG pipeline architecture"
        assert queries[1] == "RAG pipeline best practices"
        assert queries[2] == f"RAG pipeline implementation {datetime.now(timezone.utc).year}"
