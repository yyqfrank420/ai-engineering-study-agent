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
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import verify_access_token
from api.auth_route import router as auth_router
from api.analytics_route import router as analytics_router
from api.health_route import router as health_router
from api.internal_dashboard_route import router as internal_dashboard_router
from api.sse_handler import router as sse_router
from api.thread_route import router as thread_router
from config import settings
from observability import SpanKind, configure_observability, current_trace_context, record_request_metrics, start_span
from storage.telemetry_store import record_http_request_log


def create_app(*, load_resources: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Startup: load FAISS index into app.state and initialise the database.
        These are shared across all SSE requests — loaded once, reused always.
        """
        configure_observability()

        if os.getenv("K_SERVICE"):
            if not settings.use_postgres:
                raise RuntimeError("SUPABASE_DB_URL must be configured in Cloud Run; refusing SQLite fallback.")
            if settings.dev_bypass_auth:
                raise RuntimeError("DEV_BYPASS_AUTH must be false in Cloud Run.")

        app.state.startup_step = "database"
        print("[startup] Initialising database…")
        init_db()
        if not hasattr(app.state, "vectorstore"):
            app.state.vectorstore = None
        if not hasattr(app.state, "parent_docs"):
            app.state.parent_docs = []

        if load_resources:
            from rag.faiss_artifact import ensure_faiss_artifacts
            from rag.faiss_loader import load_faiss

            app.state.startup_step = "artifacts"
            print("[startup] Ensuring FAISS artifacts…")
            ensure_faiss_artifacts()

            app.state.startup_step = "index"
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
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    def apply_response_headers(response, request_id: str | None = None):
        if request_id:
            response.headers["X-Request-Id"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        print(f"[error] Unhandled request failed: {type(exc).__name__}: {exc}")
        return apply_response_headers(
            JSONResponse(status_code=500, content={"detail": "Internal server error"}),
            getattr(request.state, "request_id", None),
        )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started_at = time.perf_counter()
        request.state.request_id = str(uuid.uuid4())
        user_id: str | None = None
        status_code = 500
        response = None

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

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                body_size = 0
            if body_size > settings.max_request_body_bytes:
                return apply_response_headers(
                    JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    ),
                    request.state.request_id,
                )

        with start_span(
            f"{request.method} {request.url.path}",
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "app.request_id": request.state.request_id,
                "app.user.authenticated": bool(user_id),
            },
        ) as span:
            try:
                response = await call_next(request)
                status_code = response.status_code
            except Exception:
                status_code = 500
                if span is not None:
                    span.set_attribute("http.response.status_code", status_code)
                raise
            finally:
                latency_ms = max(1, int((time.perf_counter() - started_at) * 1000))
                route_template = getattr(request.scope.get("route"), "path", request.url.path)
                trace_context = current_trace_context()
                metadata = {
                    "request_id": request.state.request_id,
                    "trace_id": trace_context.get("trace_id"),
                    "span_id": trace_context.get("span_id"),
                    "thread_id": getattr(request.state, "thread_id", None),
                    "client_request_id": getattr(request.state, "client_request_id", None),
                }
                if span is not None:
                    span.set_attribute("http.route", route_template)
                    span.set_attribute("http.response.status_code", status_code)
                    if getattr(request.state, "thread_id", None):
                        span.set_attribute("app.thread_id", request.state.thread_id)
                    if getattr(request.state, "client_request_id", None):
                        span.set_attribute("app.client_request_id", request.state.client_request_id)
                record_request_metrics(
                    route=route_template,
                    method=request.method,
                    status_code=status_code,
                    latency_ms=latency_ms,
                )
                try:
                    record_http_request_log(
                        method=request.method,
                        path=request.url.path,
                        status_code=status_code,
                        latency_ms=latency_ms,
                        user_id=user_id,
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                        metadata=metadata,
                    )
                except Exception as exc:
                    print(f"[telemetry] HTTP request log failed: {type(exc).__name__}: {exc}")

        return apply_response_headers(response, request.state.request_id) if response is not None else response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(analytics_router)
    app.include_router(thread_router)
    app.include_router(internal_dashboard_router)
    app.include_router(sse_router)
    return app


app = create_app()
