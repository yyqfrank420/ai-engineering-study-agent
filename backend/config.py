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

    # Sonnet 5 is the single runtime model. Role-specific ``effort`` settings,
    # rather than a weaker worker model, control latency and spend per node.
    orchestrator_model: str = "claude-sonnet-5"
    worker_model: str = "claude-sonnet-5"
    # Used only after the combined architecture/render gate requests a repair.
    graph_repair_model: str = "claude-opus-4-8"
    # Extended thinking budget per agent call (tokens)
    # Extended reasoning budgets used by prototype and production design paths.
    # max_tokens must leave room for both hidden reasoning and the final answer.
    thinking_budget_tokens: int = 6000
    production_thinking_budget_tokens: int = 9000
    graph_critic_thinking_budget_tokens: int = 2000
    graph_revision_critic_thinking_budget_tokens: int = 1200

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
    # Anthropic enforces a low concurrent streaming connection cap on smaller plans.
    # Queue locally instead of letting bursty evals/users turn into 429 errors.
    anthropic_max_concurrent_streams: int = 2
    # Cap per LLM call — prevents runaway generation eating tokens
    llm_max_tokens: int = 12000
    # Hard timeout on the whole agent run (seconds); yields a timeout error event
    agent_timeout_s: int = 240
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
    max_graph_nodes: int = 13   # bounded production map; deeper detail belongs in node drill-downs
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
        missing = sorted(name for name, value in required_strings.items() if not value.strip())
        if missing:
            raise RuntimeError(f"Cloud Run configuration is incomplete: {', '.join(missing)}")

        if not self.frontend_origin.startswith("https://"):
            raise RuntimeError("FRONTEND_ORIGIN must use HTTPS in Cloud Run.")
        if not self.supabase_url.startswith("https://"):
            raise RuntimeError("SUPABASE_URL must use HTTPS in Cloud Run.")
        if self.internal_test_password and len(self.internal_test_password) < 16:
            raise RuntimeError("INTERNAL_TEST_PASSWORD must be at least 16 characters when enabled.")

        positive_limits = {
            "AGENT_TIMEOUT_S": self.agent_timeout_s,
            "LLM_MAX_RETRIES": self.llm_max_retries,
            "LLM_MAX_TOKENS": self.llm_max_tokens,
            "THINKING_BUDGET_TOKENS": self.thinking_budget_tokens,
            "PRODUCTION_THINKING_BUDGET_TOKENS": self.production_thinking_budget_tokens,
            "GRAPH_CRITIC_THINKING_BUDGET_TOKENS": self.graph_critic_thinking_budget_tokens,
            "GRAPH_REVISION_CRITIC_THINKING_BUDGET_TOKENS": (
                self.graph_revision_critic_thinking_budget_tokens
            ),
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
        if self.llm_max_tokens <= self.production_thinking_budget_tokens:
            raise RuntimeError(
                "LLM_MAX_TOKENS must be greater than PRODUCTION_THINKING_BUDGET_TOKENS."
            )


# Module-level singleton — import this everywhere
settings = Settings()
