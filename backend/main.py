# ─────────────────────────────────────────────────────────────────────────────
# File: backend/main.py
# Purpose: FastAPI application entry point. Handles startup (init DB adapter,
#          load FAISS index), mounts routes, configures CORS for the frontend.
# Language: Python
# Connects to: api/sse_handler.py, api/health_route.py,
#              rag/faiss_loader.py, adapters/database_adapter.py, config.py
# Inputs:  none (started via uvicorn)
# Outputs: running FastAPI application on port 8000
# ─────────────────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import verify_access_token
from api.auth_route import router as auth_router
from api.health_route import router as health_router
from api.sse_handler import router as sse_router
from api.thread_route import router as thread_router
from config import settings
from storage.telemetry_store import record_http_request_log


def create_app(*, load_resources: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Startup: load FAISS index into app.state and initialise the database.
        These are shared across all SSE requests — loaded once, reused always.
        """
        if os.getenv("K_SERVICE") and not settings.use_postgres:
            raise RuntimeError("SUPABASE_DB_URL must be configured in Cloud Run; refusing SQLite fallback.")
        print("[startup] Initialising database…")
        init_db()
        if not hasattr(app.state, "vectorstore"):
            app.state.vectorstore = None
        if not hasattr(app.state, "parent_docs"):
            app.state.parent_docs = []

        if load_resources:
            from rag.faiss_artifact import ensure_faiss_artifacts
            from rag.faiss_loader import load_faiss

            print("[startup] Ensuring FAISS artifacts…")
            ensure_faiss_artifacts()
            print("[startup] Loading FAISS index…")
            vectorstore, parent_docs = load_faiss()
            app.state.vectorstore = vectorstore
            app.state.parent_docs = parent_docs
            print(f"[startup] FAISS loaded — {len(parent_docs)} parent docs")

        yield

        print("[shutdown] Goodbye.")

    app = FastAPI(
        title="AI Engineering Study Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Allow the configured frontend origin and Vercel preview URLs.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=settings.vercel_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started_at = time.perf_counter()
        user_id: str | None = None
        status_code = 500

        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1].strip()
            if settings.dev_bypass_auth and token == "dev-local":
                user_id = "00000000-0000-0000-0000-000000000dev"
            else:
                try:
                    payload = verify_access_token(token)
                    user_id = payload.get("sub")
                except Exception:
                    user_id = None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            try:
                record_http_request_log(
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    latency_ms=max(1, int((time.perf_counter() - started_at) * 1000)),
                    user_id=user_id,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
            except Exception as exc:
                print(f"[telemetry] HTTP request log failed: {type(exc).__name__}: {exc}")

        return response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(thread_router)
    app.include_router(sse_router)
    return app


app = create_app()
