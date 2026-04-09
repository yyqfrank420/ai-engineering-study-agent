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
#          {"status": "preparing", "step": str} or
#          {"status": "ready"}
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter, HTTPException, Request

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
        return {"status": "ready"}

    # Return current startup step for frontend progress messaging
    current_step = getattr(request.app.state, "startup_step", "unknown")
    raise HTTPException(
        status_code=503,
        detail={
            "status": "preparing",
            "step": current_step,
        },
    )
