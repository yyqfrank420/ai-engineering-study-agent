# ─────────────────────────────────────────────────────────────────────────────
# File: backend/api/health_route.py
# Purpose: Health/readiness endpoints.
#          GET /health       — liveness + whether the knowledge base is loaded
#          GET /api/prepare  — user-facing readiness check for warm-up UX
#          "ready" means both the FAISS vectorstore and its parent-doc metadata
#          are loaded into memory.
# Language: Python
# Connects to: main.py (router registration), app.state (startup_step tracking)
# Inputs:  HTTP GET /health
# Outputs: {"status": "ok", "faiss_loaded": bool} or
#          {"status": "preparing", "step": str, "detail": str} or
#          {"status": "ready", "faiss_loaded": true}
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _knowledge_base_ready(request: Request) -> bool:
    vectorstore = getattr(request.app.state, "vectorstore", None)
    parent_docs = getattr(request.app.state, "parent_docs", None)
    return vectorstore is not None and bool(parent_docs)


@router.get("/health")
async def health(request: Request):
    return {"status": "ok", "faiss_loaded": _knowledge_base_ready(request)}


@router.get("/api/prepare")
async def prepare(request: Request):
    if _knowledge_base_ready(request):
        return {"status": "ready", "faiss_loaded": True}

    # Return current startup step for frontend progress messaging
    current_step = getattr(request.app.state, "startup_step", "unknown")
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Backend is still warming up.",
            "status": "preparing",
            "step": current_step,
            "faiss_loaded": False,
        },
    )
