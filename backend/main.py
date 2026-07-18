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
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from analytics.events import enqueue_analytics_event, start_analytics_worker, stop_analytics_worker
from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import verify_access_token
from api.auth_route import router as auth_router
from api.analytics_route import router as analytics_router
from api.health_route import router as health_router
from api.internal_dashboard_route import router as internal_dashboard_router
from api.sse_handler import router as sse_router
from api.chat_websocket import router as websocket_router
from api.thread_route import router as thread_router
from config import settings
from observability import SpanKind, configure_observability, current_trace_context, record_request_metrics, start_span
from storage.telemetry_store import record_http_request_log
from storage.retention import prune_expired_observability_data


_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
logger = logging.getLogger(__name__)


async def _buffer_request_body(request: Request, max_bytes: int) -> tuple[int, bool]:
    """Buffer a request body up to ``max_bytes`` and make it replayable.

    Content-Length is only a hint: HTTP/2 and chunked requests can omit it, and
    clients can lie. Reading the ASGI stream enforces the limit on actual bytes.
    Starlette's request body cache lets downstream FastAPI parsing consume the
    buffered body without reading the socket a second time.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            return total, True
        chunks.append(chunk)
    request._body = b"".join(chunks)  # Starlette's documented body cache behavior.
    return total, False


def create_app(*, load_resources: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Startup: load FAISS index into app.state and initialise the database.
        These are shared across all SSE requests — loaded once, reused always.
        """
        configure_observability()

        if settings.k_service:
            settings.validate_for_cloud_run()

        app.state.startup_step = "database"
        print("[startup] Initialising database…")
        init_db()
        prune_expired_observability_data(
            older_than_epoch=time.time() - (settings.telemetry_retention_days * 86400),
        )
        start_analytics_worker()
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

        await stop_analytics_worker()
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

    def apply_response_headers(
        response,
        request_id: str | None = None,
        request_path: str | None = None,
    ):
        if request_id:
            response.headers["X-Request-Id"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request_path and request_path.startswith("/api"):
            # Auth and thread payloads must never be retained by shared caches.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled request failed: %s", type(exc).__name__)
        return apply_response_headers(
            JSONResponse(status_code=500, content={"detail": "Internal server error"}),
            getattr(request.state, "request_id", None),
            request.url.path,
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
            # This sentinel is accepted only when the production-forbidden dev bypass is enabled.
            if settings.dev_bypass_auth and token == "dev-local":  # nosec B105
                user_id = "00000000-0000-0000-0000-000000000dev"
            else:
                try:
                    payload = verify_access_token(token)
                    user_id = payload.get("sub")
                except Exception:
                    user_id = None

        content_length = request.headers.get("content-length")
        body_size = 0
        if content_length:
            try:
                body_size = max(0, int(content_length))
            except ValueError:
                body_size = 0
            if body_size > settings.max_request_body_bytes:
                enqueue_analytics_event(
                    event_name="request_rejected",
                    event_category="request",
                    request_id=request.state.request_id,
                    properties={
                        "method": request.method,
                        "path": request.url.path,
                        "reason": "body_too_large",
                        "body_size_bytes": body_size,
                    },
                )
                return apply_response_headers(
                    JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    ),
                    request.state.request_id,
                    request.url.path,
                )

        if request.method in _BODY_METHODS:
            body_size, body_too_large = await _buffer_request_body(
                request,
                settings.max_request_body_bytes,
            )
            if body_too_large:
                enqueue_analytics_event(
                    event_name="request_rejected",
                    event_category="request",
                    request_id=request.state.request_id,
                    properties={
                        "method": request.method,
                        "path": request.url.path,
                        "reason": "body_too_large",
                        "body_size_bytes": body_size,
                    },
                )
                return apply_response_headers(
                    JSONResponse(status_code=413, content={"detail": "Request body too large"}),
                    request.state.request_id,
                    request.url.path,
                )

        enqueue_analytics_event(
            event_name="request_started",
            event_category="request",
            request_id=request.state.request_id,
            user_id=user_id,
            properties={
                "method": request.method,
                "path": request.url.path,
                "body_size_bytes": body_size,
            },
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
                        metadata=metadata,
                    )
                except Exception as exc:
                    logger.warning("HTTP request telemetry write failed: %s", type(exc).__name__)
                enqueue_analytics_event(
                    event_name="request_completed",
                    event_category="request",
                    user_id=user_id,
                    request_id=request.state.request_id,
                    trace_id=trace_context.get("trace_id"),
                    client_request_id=getattr(request.state, "client_request_id", None),
                    numeric_value=latency_ms,
                    unit="ms",
                    properties={
                        "method": request.method,
                        "path": request.url.path,
                        "route": route_template,
                        "status_code": status_code,
                        "latency_ms": latency_ms,
                        "thread_id": getattr(request.state, "thread_id", None),
                    },
                )

        return (
            apply_response_headers(response, request.state.request_id, request.url.path)
            if response is not None
            else response
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(analytics_router)
    app.include_router(thread_router)
    app.include_router(internal_dashboard_router)
    app.include_router(sse_router)
    app.include_router(websocket_router)
    return app


app = create_app()
