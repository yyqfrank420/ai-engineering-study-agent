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

    # Orchestrator: high-quality reasoning + synthesis
    orchestrator_model: str = "claude-sonnet-4-6"
    # Workers: fast + cheap for retrieval / generation subtasks
    worker_model: str = "claude-haiku-4-5-20251001"
    # Extended thinking budget per agent call (tokens)
    thinking_budget_tokens: int = 5000

    # ── OpenAI fallback ───────────────────────────────────────────────────────
    # Used when Anthropic fails after llm_max_retries attempts.
    openai_api_key: str = ""
    # gpt-5.4 with medium reasoning effort ≈ claude-sonnet-4-6
    orchestrator_fallback_model: str = "gpt-5.4"
    orchestrator_fallback_reasoning_effort: str = "medium"
    # gpt-5.4-mini ≈ claude-haiku-4-5
    worker_fallback_model: str = "gpt-5.4-mini"
    # Retry budget: how many Anthropic attempts before switching to OpenAI
    llm_max_retries: int = 3
    llm_retry_delay_s: float = 1.0
    # Cap per LLM call — prevents runaway generation eating tokens
    llm_max_tokens: int = 4096
    # Hard timeout on the whole agent run (seconds); yields a timeout error event
    agent_timeout_s: int = 120
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
    def sqlite_path(self) -> Path:
        return self.data_dir / "sessions.db"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_db_url: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    # Required for HS256 projects (most Supabase projects).
    # Find it at: Supabase dashboard → Project Settings → API → JWT Secret
    supabase_jwt_secret: str = ""
    turnstile_secret_key: str = ""
    faiss_artifact_url: str = ""
    faiss_artifact_sha256: str = ""
    faiss_artifact_timeout_s: int = 120

    # ── Internal test access ────────────────────────────────────────────────
    # Explicit internal-only login path for production testing without OTP.
    # This is disabled unless BOTH the password and allowlist are configured.
    internal_test_password: str = ""
    internal_test_email_allowlist_raw: str = ""
    internal_test_session_minutes: int = 30
    internal_test_attempt_window_s: int = 600
    internal_test_attempt_limit: int = 10

    # ── Dev ───────────────────────────────────────────────────────────────────
    # Set to true in local .env only. NEVER enable in production.
    # Accepts the token "dev-local" as a valid auth token for any request.
    dev_bypass_auth: bool = False

    # ── Security ──────────────────────────────────────────────────────────────
    frontend_origin: str = "http://localhost:5173"
    vercel_origin_regex: str = r"^https://[a-z0-9-]+\.vercel\.app$"
    # Rate limiting (per user_id, sliding window)
    rate_limit_per_minute: int = 20
    rate_limit_per_hour: int = 100
    # Max incoming chat message payload (bytes)
    max_message_bytes: int = 2048
    # llm-guard PromptInjection rejection threshold (0–1)
    prompt_injection_threshold: float = 0.85
    # Max combined title + description bytes for node follow-up generation
    max_node_text_bytes: int = 4096
    auth_session_hours: int = 24
    otp_request_window_s: int = 600
    otp_request_per_email_limit: int = 3
    otp_request_per_ip_limit: int = 10
    otp_verify_failure_limit: int = 3
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
    max_graph_nodes: int = 10   # cap on parallel Node Detail Workers
    search_tool_decision_timeout_s: float = 3.0

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


# Module-level singleton — import this everywhere
settings = Settings()
