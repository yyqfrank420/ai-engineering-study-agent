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


def _progress_payload(request: Request) -> dict[str, int]:
    completed = max(0, int(getattr(request.app.state, "startup_completed_units", 0)))
    total = max(1, int(getattr(request.app.state, "startup_total_units", 3)))
    return {
        "completed_units": min(completed, total),
        "total_units": total,
        "percent": min(100, round((completed / total) * 100)),
    }


@router.get("/health")
async def health(request: Request):
    return {"status": "ok", "faiss_loaded": _knowledge_base_ready(request)}


@router.get("/api/prepare")
async def prepare(request: Request):
    if _knowledge_base_ready(request):
        return {
            "status": "ready",
            "step": "ready",
            "detail": "Knowledge base ready",
            "progress": {"completed_units": 3, "total_units": 3, "percent": 100},
            "faiss_loaded": True,
        }

    current_step = getattr(request.app.state, "startup_step", "unknown")
    startup_failed = current_step == "failed" or bool(
        getattr(request.app.state, "startup_error", None)
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": getattr(
                request.app.state,
                "startup_detail",
                "Backend is still warming up.",
            ),
            "status": "error" if startup_failed else "preparing",
            "step": current_step,
            "progress": _progress_payload(request),
            "faiss_loaded": False,
        },
    )
