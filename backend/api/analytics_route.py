from __future__ import annotations

from collections import defaultdict
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from analytics.events import enqueue_analytics_event
from api.internal_access import get_optional_user
from storage.product_analytics_store import record_product_analytics_event
from storage.profile_store import upsert_profile

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_ALLOWED_EVENTS = {
    "auth_viewed",
    "otp_requested",
    "otp_verified",
    "google_signin_started",
    "prepare_clicked",
    "prepare_succeeded",
    "prepare_failed",
    "thread_created",
    "thread_selected",
    "thread_deleted",
    "chat_sent",
    "chat_stream_started",
    "chat_stream_completed",
    "chat_stream_failed",
    "chat_stopped",
    "node_selected",
    "expand_graph_clicked",
    "search_tool_requested",
    "mode_changed",
}

_PUBLIC_EVENTS = {
    "auth_viewed",
    "otp_requested",
    "otp_verified",
    "google_signin_started",
}

_ALLOWED_PROPERTIES = {
    "thread_id",
    "client_request_id",
    "complexity",
    "graph_mode",
    "research_enabled",
    "backend_readiness_state",
    "has_selected_text_context",
    "provider_notice_shown",
    "error_code",
    "node_id",
    "node_label",
    "mode",
    "value",
    "request_id",
}

_CAPTURE_WINDOW_S = 600
_CAPTURE_LIMIT_PER_KEY = 120
_capture_attempts: dict[str, list[float]] = defaultdict(list)


def _prune_attempts(key: str, *, now: float) -> list[float]:
    _capture_attempts[key] = [ts for ts in _capture_attempts[key] if now - ts < _CAPTURE_WINDOW_S]
    return _capture_attempts[key]


def _capture_key(body: "AnalyticsCaptureRequest", request: Request, user: dict | None) -> str:
    if user and user.get("id"):
        return f"user:{user['id']}"
    client_ip = request.client.host if request.client else "unknown"
    return f"anon:{client_ip}"


def _sanitize_properties(properties: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in properties.items():
        if key not in _ALLOWED_PROPERTIES or value is None:
            continue
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (int, float)):
            clean[key] = value
        else:
            clean[key] = str(value)[:120]
    return clean


class AnalyticsCaptureRequest(BaseModel):
    anonymous_id: str
    event_type: str
    properties: dict[str, Any] = {}

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("anonymous_id")
    @classmethod
    def validate_anonymous_id(cls, value: str) -> str:
        if not value:
            raise ValueError("anonymous_id is required")
        return value[:128]

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in _ALLOWED_EVENTS:
            raise ValueError("Unsupported analytics event")
        return value


@router.post("/capture")
async def capture_analytics_event(
    body: AnalyticsCaptureRequest,
    request: Request,
    user=Depends(get_optional_user),
):
    if len(body.model_dump_json()) > 4096:
        raise HTTPException(status_code=413, detail="Analytics event payload too large")

    if body.event_type not in _PUBLIC_EVENTS and not user:
        raise HTTPException(status_code=401, detail="Authentication required for this analytics event")

    now = time.time()
    key = _capture_key(body, request, user)
    attempts = _prune_attempts(key, now=now)
    if len(attempts) >= _CAPTURE_LIMIT_PER_KEY:
        raise HTTPException(status_code=429, detail="Too many analytics events")
    attempts.append(now)

    try:
        if user:
            upsert_profile(user["id"], user.get("email") or f"{user['id']}@unknown.local")
        record_product_analytics_event(
            anonymous_id=body.anonymous_id,
            user_id=user["id"] if user else None,
            event_type=body.event_type,
            properties=_sanitize_properties(body.properties),
            created_at_epoch=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        print(f"[analytics] Product analytics write failed: {type(exc).__name__}: {exc}")
    enqueue_analytics_event(
        event_name=body.event_type,
        event_category="product",
        user_id=user["id"] if user else None,
        anonymous_id=body.anonymous_id,
        request_id=(body.properties or {}).get("request_id"),
        client_request_id=(body.properties or {}).get("client_request_id"),
        properties=_sanitize_properties(body.properties),
        created_at_epoch=now,
    )
    return {"ok": True}
