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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adapters.database_adapter import init_db
from api.auth_route import router as auth_router
from api.health_route import router as health_router
from api.sse_handler import router as sse_router
from api.thread_route import router as thread_router
from config import settings


def create_app(*, load_resources: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Startup: load FAISS index into app.state and initialise the database.
        These are shared across all SSE requests — loaded once, reused always.
        """
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
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(thread_router)
    app.include_router(sse_router)
    return app


app = create_app()
