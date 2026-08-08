# ─────────────────────────────────────────────────────────────────────────────
# File: backend/config.py
# Purpose: All environment-variable-backed configuration for the backend.
#          Single source of truth — nothing else reads os.environ directly.
# Language: Python
# Connects to: every backend module that needs config
# Inputs:  environment variables (set via Cloud Run/Secret Manager or .env locally)
# Outputs: `settings` singleton imported by other modules
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ───────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.ai/v1"

    # General conversation roles retain their independent fallback policy.
    orchestrator_model: str = "claude-opus-5"
    worker_model: str = "claude-opus-5"
    # Applied-design roles are explicit so quality and cost changes cannot drift
    # behind a shared model setting.
    architecture_model: str = "claude-opus-5"
    graph_builder_model: str = "kimi-k3"
    graph_qa_model: str = "claude-sonnet-5"
    # Extended thinking budget per agent call (tokens)
    # Extended reasoning budgets used by prototype and production design paths.
    # max_tokens must leave room for both hidden reasoning and the final answer.
    thinking_budget_tokens: int = 6000
    production_thinking_budget_tokens: int = 9000

    # ── OpenAI fallback ───────────────────────────────────────────────────────
    # Used when Anthropic fails after llm_max_retries attempts.
    openai_api_key: str = ""
    # gpt-5.4 with medium reasoning effort ≈ claude-sonnet-4-6
    orchestrator_fallback_model: str = "gpt-5.4"
    orchestrator_fallback_reasoning_effort: str = "medium"
    worker_fallback_model: str = "gpt-5.4"
    # Retry budget: how many Anthropic attempts before switching to OpenAI
    # Initial provider attempt plus one bounded retry before fallback/failure.
    llm_max_retries: int = 2
    llm_retry_delay_s: float = 1.0
    # CI and protected evaluation revisions opt in. Production app traffic does
    # not pay cache-write premiums for low-reuse prompts.
    anthropic_prompt_cache_enabled: bool = False
    # Bound concurrent Anthropic streams within each application process.
    anthropic_max_concurrent_streams: int = 4
    # Tagged evaluation revisions set both values. Production leaves them off.
    evaluation_run_id: str = ""
    evaluation_provider_attempt_limit: int = 0
    # Ordinary calls use the bounded default. Reasoning-heavy roles may request
    # more room up to the hard cap without changing their visible output contract.
    llm_default_max_tokens: int = 12000
    llm_max_tokens: int = 131072
    architecture_max_completion_tokens: int = 16000
    graph_builder_max_completion_tokens: int = 65536
    graph_qa_max_completion_tokens: int = 16384
    # Hard timeout on the whole agent run (seconds); yields a timeout error event
    agent_timeout_s: int = 910
    # Graph work must leave fixed synthesis, persistence, and transport headroom.
    agent_terminal_headroom_s: float = 30.0
    # Stage admission keeps this time inside the terminal window for orchestration.
    agent_orchestration_reserve_s: float = 30.0
    # Bound the initial Kimi topology build and one typed repair while preserving
    # independent review inside the terminal window.
    graph_design_timeout_s: float = 150.0
    architecture_role_timeout_s: float = 150.0
    graph_critic_timeout_s: float = 90.0
    # Initial editable rejections receive one clean completeness pass before repair.
    # Both reviews share this stage ceiling and may borrow saved upstream time.
    graph_critic_max_timeout_s: float = 195.0
    graph_patch_timeout_s: float = 150.0
    # Kimi may use time saved by earlier stages up to this per-call ceiling.
    # Deadline admission still preserves the complete downstream review path.
    graph_builder_max_timeout_s: float = 240.0
    # Keep removed names visible so stale deployment overrides fail at startup
    # instead of disappearing through `extra="ignore"`.
    architecture_pass_timeout_s: float | None = None
    architecture_review_timeout_s: float | None = None
    graph_critic_initial_timeout_s: float | None = None
    graph_critic_revision_timeout_s: float | None = None
    graph_synthesis_timeout_s: float = 55.0
    graph_finalization_reserve_s: float = 8.0
    # A browser renders candidate graphs off-screen and returns a bounded image
    # plus layout metrics before an applied diagram may be published.
    diagram_evaluation_timeout_s: float = 15.0
    max_diagram_screenshot_bytes: int = 400_000
    # Backend-wide request body guard. Must exceed max_graph_data_bytes plus JSON envelope.
    max_request_body_bytes: int = 600000
    # Sampling controls. Keep top_p / top_k unset unless you have a measured reason.
    # Anthropic extended thinking is incompatible with modified temperature or top_k.
    router_temperature: float = 0.0
    router_top_p: float | None = None
    router_top_k: int | None = None
    synthesis_temperature: float = 0.25
    synthesis_top_p: float | None = None
    synthesis_top_k: int | None = None
    quick_synthesis_temperature: float = 0.1
    quick_synthesis_top_p: float | None = None
    quick_synthesis_top_k: int | None = None
    graph_temperature: float = 0.1
    graph_top_p: float | None = None
    graph_top_k: int | None = None
    node_detail_temperature: float = 0.2
    node_detail_top_p: float | None = None
    node_detail_top_k: int | None = None
    condense_temperature: float = 0.0
    condense_top_p: float | None = None
    condense_top_k: int | None = None
    suggestion_chip_temperature: float = 0.35
    suggestion_chip_top_p: float | None = None
    suggestion_chip_top_k: int | None = None

    # ── Storage ───────────────────────────────────────────────────────────────
    # Locally: defaults to project root /data
    # In production: Cloud Run container filesystem for warm instance lifetime only
    data_dir: Path = Path(__file__).parent.parent / "data"

    @property
    def faiss_dir(self) -> Path:
        return self.data_dir / "faiss"

    @property
    def graph_dir(self) -> Path:
        return self.data_dir / "graph"

    @property
    def graph_schema_dir(self) -> Path:
        return self.data_dir / "graph_schema"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "sessions.db"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_db_url: str = ""
    # Application SQL is unqualified and every Postgres connection pins its
    # search_path to this allowlisted schema. No arbitrary schema names are accepted.
    db_schema: Literal["public", "staging"] = "public"
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    # Required for HS256 projects (most Supabase projects).
    # Find it at: Supabase dashboard → Project Settings → API → JWT Secret
    supabase_jwt_secret: str = ""
    turnstile_secret_key: str = ""
    faiss_artifact_url: str = ""
    faiss_artifact_sha256: str = ""
    faiss_artifact_timeout_s: int = 120
    # Artifact bundles contain pickle files, so downloads are checksum-pinned and
    # bounded before extraction to limit disk/memory exhaustion from a bad host.
    faiss_artifact_max_download_bytes: int = 268435456  # 256 MiB
    faiss_artifact_max_extracted_bytes: int = 536870912  # 512 MiB
    faiss_artifact_max_files: int = 1000

    # ── Internal test access ────────────────────────────────────────────────
    # Explicit internal-only login path for production testing without OTP.
    # This is disabled unless BOTH the password and allowlist are configured.
    internal_test_password: str = ""
    internal_test_email_allowlist_raw: str = ""
    internal_test_session_minutes: int = 30
    internal_test_attempt_window_s: int = 600
    internal_test_attempt_limit: int = 10

    # ── Observability / analytics ────────────────────────────────────────────
    otel_enabled: bool = False
    otel_service_name: str = "ai-engineering-study-agent"
    otel_service_version: str = "0.1.0"
    otel_environment: str = "development"
    # Base OTLP/HTTP endpoint, e.g. https://collector.example.com
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers_raw: str = ""
    internal_dashboard_allowlist_raw: str = ""
    analytics_queue_max_size: int = 1000
    analytics_event_schema_version: int = 1
    telemetry_retention_days: int = 30
    dashboard_query_max_rows: int = 20000

    # ── Dev ───────────────────────────────────────────────────────────────────
    # Cloud Run injects this automatically. Keeping it in Settings preserves
    # the single configuration boundary used by application code.
    k_service: str = ""
    # Set to true in local .env only. NEVER enable in production.
    # Accepts the token "dev-local" as a valid auth token for any request.
    dev_bypass_auth: bool = False

    # ── Security ──────────────────────────────────────────────────────────────
    frontend_origin: str = "http://localhost:5173"
    vercel_origin_regex: str = r"^https://[a-z0-9-]+\.vercel\.app$"
    # Rate limiting (per user_id, sliding window)
    rate_limit_per_minute: int = 20
    rate_limit_per_hour: int = 100
    # Per-user active LLM streams. Enforced through shared storage so Cloud Run
    # instance scaling does not multiply spend limits.
    max_active_chat_streams_per_user: int = 1
    max_active_node_streams_per_user: int = 2
    # Max incoming chat message payload (bytes)
    max_message_bytes: int = 2048
    # Local prompt-injection pattern score rejection threshold (0-1)
    prompt_injection_threshold: float = 0.85
    # Max combined title + description bytes for node follow-up generation
    max_node_text_bytes: int = 4096
    max_thread_title_bytes: int = 160
    auth_session_hours: int = 24
    otp_request_window_s: int = 600
    otp_request_per_email_limit: int = 3
    otp_request_per_ip_limit: int = 10
    otp_verify_failure_limit: int = 3
    otp_verify_failure_per_ip_limit: int = 10
    otp_verify_window_s: int = 600

    # ── Resource limits ───────────────────────────────────────────────────────
    # Max threads stored per user (oldest evicted on overflow)
    max_threads_per_user: int = 5
    # Max messages stored per thread (returns 429 when hit)
    max_messages_per_thread: int = 50
    # Max graph_data size in bytes (500 KB — skips save + notifies user if exceeded)
    max_graph_data_bytes: int = 524288
    # Auto-condense: summarise old history with Haiku when total chars exceeds this
    context_condense_threshold_chars: int = 12000
    # Auto-condense: how many recent turns to keep verbatim (not summarised)
    context_condense_keep_recent: int = 4

    # ── Embedding ─────────────────────────────────────────────────────────────
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # ── RAG ───────────────────────────────────────────────────────────────────
    rag_top_k: int = 5          # child chunks retrieved from FAISS
    # Malformed-output guards for rendering and persistence. These values never
    # appear in design prompts and do not define a preferred diagram size.
    graph_safety_max_nodes: int = 60
    graph_safety_max_edges: int = 180
    # Concept-map enrichment makes one paid call per selected node. Keep its
    # spend boundary independent from applied-architecture topology capacity.
    max_node_detail_nodes: int = 13
    search_tool_decision_timeout_s: float = 3.0
    # Backpressure for the temporary HTTP/SSE compatibility transport.
    max_sse_queue_events: int = 256

    # ── Research worker (DuckDuckGo) ──────────────────────────────────────────
    # Max results fetched per search query (3 queries × this = total raw results)
    research_results_per_query: int = 2
    # Domains whose results are filtered out as low-quality noise
    research_noise_domains: list[str] = [
        "pinterest.com", "quora.com", "reddit.com", "youtube.com",
        "twitter.com", "facebook.com", "instagram.com", "tiktok.com",
    ]

    @model_validator(mode="after")
    def reject_removed_timeout_settings(self):
        removed = {
            "ARCHITECTURE_PASS_TIMEOUT_S": self.architecture_pass_timeout_s,
            "ARCHITECTURE_REVIEW_TIMEOUT_S": self.architecture_review_timeout_s,
            "GRAPH_CRITIC_INITIAL_TIMEOUT_S": self.graph_critic_initial_timeout_s,
            "GRAPH_CRITIC_REVISION_TIMEOUT_S": self.graph_critic_revision_timeout_s,
        }
        configured = sorted(name for name, value in removed.items() if value is not None)
        if configured:
            raise ValueError(
                "Removed timeout settings are configured: "
                + ", ".join(configured)
                + ". Use ARCHITECTURE_ROLE_TIMEOUT_S and GRAPH_CRITIC_TIMEOUT_S."
            )
        return self

    @model_validator(mode="after")
    def validate_evaluation_provider_attempt_limit(self):
        run_id = self.evaluation_run_id.strip()
        limit = self.evaluation_provider_attempt_limit
        if limit < 0 or bool(run_id) != (limit > 0):
            raise ValueError(
                "EVALUATION_RUN_ID and a positive "
                "EVALUATION_PROVIDER_ATTEMPT_LIMIT must be configured together."
            )
        return self

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [self.frontend_origin, "http://localhost:5173"]

    @property
    def use_postgres(self) -> bool:
        return bool(self.supabase_db_url.strip())

    @property
    def effective_supabase_jwt_issuer(self) -> str:
        if self.supabase_jwt_issuer.strip():
            return self.supabase_jwt_issuer.strip()
        if self.supabase_url.strip():
            return self.supabase_url.rstrip("/") + "/auth/v1"
        return ""

    @property
    def effective_supabase_jwt_audience(self) -> str:
        return self.supabase_jwt_audience.strip()

    @property
    def internal_test_email_allowlist(self) -> list[str]:
        raw = self.internal_test_email_allowlist_raw.replace("\n", ",")
        return [email.strip().lower() for email in raw.split(",") if email.strip()]

    @property
    def internal_test_enabled(self) -> bool:
        return bool(
            self.internal_test_password.strip()
            and self.internal_test_email_allowlist
            and self.supabase_jwt_secret.strip()
            and self.effective_supabase_jwt_issuer
        )

    @property
    def otel_exporter_otlp_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        for pair in self.otel_exporter_otlp_headers_raw.split(","):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                headers[key] = value
        return headers

    @property
    def internal_dashboard_allowlist(self) -> list[str]:
        raw = self.internal_dashboard_allowlist_raw.replace("\n", ",")
        return [email.strip().lower() for email in raw.split(",") if email.strip()]

    def validate_for_cloud_run(self) -> None:
        """Fail closed when production starts with unsafe or unusable config."""
        if not self.use_postgres:
            raise RuntimeError("SUPABASE_DB_URL must be configured in Cloud Run; refusing SQLite fallback.")
        if self.dev_bypass_auth:
            raise RuntimeError("DEV_BYPASS_AUTH must be false in Cloud Run.")

        required_strings = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_ANON_KEY": self.supabase_anon_key,
            "SUPABASE_JWT_ISSUER": self.effective_supabase_jwt_issuer,
            "SUPABASE_JWT_AUDIENCE": self.effective_supabase_jwt_audience,
            "TURNSTILE_SECRET_KEY": self.turnstile_secret_key,
        }
        if self.graph_builder_model.startswith("kimi-"):
            required_strings["MOONSHOT_API_KEY"] = self.moonshot_api_key
        missing = sorted(name for name, value in required_strings.items() if not value.strip())
        if missing:
            raise RuntimeError(f"Cloud Run configuration is incomplete: {', '.join(missing)}")
        values_with_surrounding_whitespace = sorted(
            name for name, value in required_strings.items() if value != value.strip()
        )
        if values_with_surrounding_whitespace:
            raise RuntimeError(
                "Cloud Run configuration contains surrounding whitespace: "
                + ", ".join(values_with_surrounding_whitespace)
            )

        if not self.frontend_origin.startswith("https://"):
            raise RuntimeError("FRONTEND_ORIGIN must use HTTPS in Cloud Run.")
        if not self.supabase_url.startswith("https://"):
            raise RuntimeError("SUPABASE_URL must use HTTPS in Cloud Run.")
        if self.internal_test_password and len(self.internal_test_password) < 16:
            raise RuntimeError("INTERNAL_TEST_PASSWORD must be at least 16 characters when enabled.")

        positive_limits = {
            "AGENT_TIMEOUT_S": self.agent_timeout_s,
            "AGENT_TERMINAL_HEADROOM_S": self.agent_terminal_headroom_s,
            "AGENT_ORCHESTRATION_RESERVE_S": self.agent_orchestration_reserve_s,
            "ARCHITECTURE_ROLE_TIMEOUT_S": self.architecture_role_timeout_s,
            "ARCHITECTURE_MAX_COMPLETION_TOKENS": (
                self.architecture_max_completion_tokens
            ),
            "GRAPH_DESIGN_TIMEOUT_S": self.graph_design_timeout_s,
            "GRAPH_BUILDER_MAX_TIMEOUT_S": self.graph_builder_max_timeout_s,
            "GRAPH_BUILDER_MAX_COMPLETION_TOKENS": (
                self.graph_builder_max_completion_tokens
            ),
            "GRAPH_CRITIC_TIMEOUT_S": self.graph_critic_timeout_s,
            "GRAPH_CRITIC_MAX_TIMEOUT_S": self.graph_critic_max_timeout_s,
            "GRAPH_QA_MAX_COMPLETION_TOKENS": self.graph_qa_max_completion_tokens,
            "GRAPH_PATCH_TIMEOUT_S": self.graph_patch_timeout_s,
            "GRAPH_SYNTHESIS_TIMEOUT_S": self.graph_synthesis_timeout_s,
            "GRAPH_FINALIZATION_RESERVE_S": self.graph_finalization_reserve_s,
            "LLM_MAX_RETRIES": self.llm_max_retries,
            "LLM_DEFAULT_MAX_TOKENS": self.llm_default_max_tokens,
            "LLM_MAX_TOKENS": self.llm_max_tokens,
            "THINKING_BUDGET_TOKENS": self.thinking_budget_tokens,
            "PRODUCTION_THINKING_BUDGET_TOKENS": self.production_thinking_budget_tokens,
            "DIAGRAM_EVALUATION_TIMEOUT_S": self.diagram_evaluation_timeout_s,
            "MAX_DIAGRAM_SCREENSHOT_BYTES": self.max_diagram_screenshot_bytes,
            "MAX_REQUEST_BODY_BYTES": self.max_request_body_bytes,
            "MAX_MESSAGE_BYTES": self.max_message_bytes,
            "MAX_THREADS_PER_USER": self.max_threads_per_user,
            "MAX_MESSAGES_PER_THREAD": self.max_messages_per_thread,
            "MAX_SSE_QUEUE_EVENTS": self.max_sse_queue_events,
            "ANALYTICS_QUEUE_MAX_SIZE": self.analytics_queue_max_size,
            "ANTHROPIC_MAX_CONCURRENT_STREAMS": self.anthropic_max_concurrent_streams,
            "RATE_LIMIT_PER_MINUTE": self.rate_limit_per_minute,
            "RATE_LIMIT_PER_HOUR": self.rate_limit_per_hour,
            "MAX_ACTIVE_CHAT_STREAMS_PER_USER": self.max_active_chat_streams_per_user,
            "MAX_ACTIVE_NODE_STREAMS_PER_USER": self.max_active_node_streams_per_user,
            "OTP_REQUEST_WINDOW_S": self.otp_request_window_s,
            "OTP_REQUEST_PER_EMAIL_LIMIT": self.otp_request_per_email_limit,
            "OTP_REQUEST_PER_IP_LIMIT": self.otp_request_per_ip_limit,
            "OTP_VERIFY_FAILURE_LIMIT": self.otp_verify_failure_limit,
            "OTP_VERIFY_FAILURE_PER_IP_LIMIT": self.otp_verify_failure_per_ip_limit,
            "OTP_VERIFY_WINDOW_S": self.otp_verify_window_s,
            "INTERNAL_TEST_ATTEMPT_WINDOW_S": self.internal_test_attempt_window_s,
            "INTERNAL_TEST_ATTEMPT_LIMIT": self.internal_test_attempt_limit,
            "TELEMETRY_RETENTION_DAYS": self.telemetry_retention_days,
            "DASHBOARD_QUERY_MAX_ROWS": self.dashboard_query_max_rows,
            "FAISS_ARTIFACT_MAX_DOWNLOAD_BYTES": self.faiss_artifact_max_download_bytes,
            "FAISS_ARTIFACT_MAX_EXTRACTED_BYTES": self.faiss_artifact_max_extracted_bytes,
            "FAISS_ARTIFACT_MAX_FILES": self.faiss_artifact_max_files,
        }
        invalid = sorted(name for name, value in positive_limits.items() if value <= 0)
        if invalid:
            raise RuntimeError(f"Cloud Run limits must be positive: {', '.join(invalid)}")
        if self.agent_terminal_headroom_s >= self.agent_timeout_s:
            raise RuntimeError("AGENT_TERMINAL_HEADROOM_S must be below AGENT_TIMEOUT_S.")
        if self.graph_builder_max_timeout_s < max(
            self.graph_design_timeout_s,
            self.graph_patch_timeout_s,
        ):
            raise RuntimeError(
                "GRAPH_BUILDER_MAX_TIMEOUT_S cannot be below the reserved design or patch timeout."
            )
        if self.graph_critic_max_timeout_s < self.graph_critic_timeout_s:
            raise RuntimeError(
                "GRAPH_CRITIC_MAX_TIMEOUT_S cannot be below the reserved critic timeout."
            )
        complete_architecture_path_s = (
            2 * self.architecture_role_timeout_s
            + self.graph_design_timeout_s
            + self.graph_critic_timeout_s
            + self.graph_patch_timeout_s
            + self.graph_critic_timeout_s
            + self.graph_synthesis_timeout_s
            + self.graph_finalization_reserve_s
        )
        terminal_window_s = self.agent_timeout_s - self.agent_terminal_headroom_s
        if (
            complete_architecture_path_s + self.agent_orchestration_reserve_s
            > terminal_window_s
        ):
            raise RuntimeError(
                "Agent terminal window cannot fit the complete architecture repair path "
                "and orchestration reserve."
            )
        if self.llm_max_tokens <= self.production_thinking_budget_tokens:
            raise RuntimeError(
                "LLM_MAX_TOKENS must be greater than PRODUCTION_THINKING_BUDGET_TOKENS."
            )
        role_token_limits = {
            "ARCHITECTURE_MAX_COMPLETION_TOKENS": (
                self.architecture_max_completion_tokens
            ),
            "GRAPH_BUILDER_MAX_COMPLETION_TOKENS": (
                self.graph_builder_max_completion_tokens
            ),
            "GRAPH_QA_MAX_COMPLETION_TOKENS": self.graph_qa_max_completion_tokens,
        }
        above_hard_cap = sorted(
            name for name, value in role_token_limits.items() if value > self.llm_max_tokens
        )
        if above_hard_cap:
            raise RuntimeError(
                "Role completion limits exceed LLM_MAX_TOKENS: "
                + ", ".join(above_hard_cap)
            )


# Module-level singleton — import this everywhere
settings = Settings()
