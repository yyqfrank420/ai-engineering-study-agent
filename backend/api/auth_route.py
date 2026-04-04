import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hmac
import uuid

import jwt

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from adapters.supabase_auth_adapter import request_email_otp, verify_email_otp, verify_turnstile
from config import settings
from storage.profile_store import get_profile_by_email, upsert_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])

_otp_request_by_email: dict[str, list[float]] = defaultdict(list)
_otp_request_by_ip: dict[str, list[float]] = defaultdict(list)
_otp_verify_failures: dict[str, list[float]] = defaultdict(list)
_internal_login_failures: dict[str, list[float]] = defaultdict(list)
_INTERNAL_TEST_USER_NAMESPACE = uuid.UUID("db57f8ae-e7ce-4f62-9779-6337ed49f1f6")


def _normalise_email(value: str) -> str:
    email = value.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Invalid email")
    return email


class OTPRequest(BaseModel):
    email: str
    captcha_token: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


class OTPVerifyRequest(BaseModel):
    email: str
    token: str
    captcha_token: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


class InternalLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


def _mint_internal_session(email: str) -> dict:
    if not settings.supabase_jwt_secret:
        raise HTTPException(status_code=500, detail="Internal test auth is not configured")

    existing_profile = get_profile_by_email(email)
    user_id = existing_profile["id"] if existing_profile else str(uuid.uuid5(_INTERNAL_TEST_USER_NAMESPACE, email))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.internal_test_session_minutes)
    payload = {
        "sub": user_id,
        "email": email,
        "aud": settings.effective_supabase_jwt_audience,
        "iss": settings.effective_supabase_jwt_issuer,
        "role": "authenticated",
        "aal": "aal1",
        "app_metadata": {"provider": "internal_test", "providers": ["internal_test"]},
        "user_metadata": {"email": email},
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    access_token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")
    return {
        "access_token": access_token,
        "refresh_token": "",
        "expires_in": int((expires_at - now).total_seconds()),
        "token_type": "bearer",
        "user": {"id": user_id, "email": email},
    }


def _prune(bucket: dict[str, list[float]], key: str, window_s: int) -> list[float]:
    now = time.time()
    bucket[key] = [ts for ts in bucket[key] if now - ts < window_s]
    return bucket[key]


def _is_request_suspicious(email: str, ip: str) -> bool:
    email_hits = _prune(_otp_request_by_email, email, settings.otp_request_window_s)
    ip_hits = _prune(_otp_request_by_ip, ip, settings.otp_request_window_s)
    return (
        len(email_hits) >= settings.otp_request_per_email_limit
        or len(ip_hits) >= settings.otp_request_per_ip_limit
    )


def _is_verify_suspicious(email: str) -> bool:
    failures = _prune(_otp_verify_failures, email, settings.otp_verify_window_s)
    return len(failures) >= settings.otp_verify_failure_limit


def _record_request(email: str, ip: str) -> None:
    now = time.time()
    _otp_request_by_email[email].append(now)
    _otp_request_by_ip[ip].append(now)


def _record_failure(email: str) -> None:
    _otp_verify_failures[email].append(time.time())


def _record_internal_failure(key: str) -> None:
    _internal_login_failures[key].append(time.time())


def _is_internal_login_rate_limited(key: str) -> bool:
    failures = _prune(_internal_login_failures, key, settings.internal_test_attempt_window_s)
    return len(failures) >= settings.internal_test_attempt_limit


@router.post("/request-otp")
async def request_otp(body: OTPRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    suspicious = _is_request_suspicious(body.email, ip)
    if suspicious:
        if not body.captcha_token or not await verify_turnstile(body.captcha_token, ip):
            return {"ok": False, "captcha_required": True}

    await request_email_otp(body.email)
    _record_request(body.email, ip)
    return {"ok": True, "captcha_required": False}


@router.post("/verify-otp")
async def verify_otp(body: OTPVerifyRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    suspicious = _is_verify_suspicious(body.email)
    if suspicious:
        if not body.captcha_token or not await verify_turnstile(body.captcha_token, ip):
            return {"ok": False, "captcha_required": True}

    try:
        session = await verify_email_otp(body.email, body.token)
    except HTTPException:
        _record_failure(body.email)
        raise

    user = session.get("user") or {}
    user_id = user.get("id")
    email = user.get("email") or body.email
    if not user_id:
        raise HTTPException(status_code=400, detail="Supabase did not return a user")

    upsert_profile(user_id, email)
    _otp_verify_failures.pop(body.email, None)
    return {
        "ok": True,
        "session": {
            "access_token": session.get("access_token"),
            "refresh_token": session.get("refresh_token"),
            "expires_in": session.get("expires_in"),
            "token_type": session.get("token_type", "bearer"),
            "user": {
                "id": user_id,
                "email": email,
            },
        },
    }


@router.post("/internal-login")
async def internal_login(body: InternalLoginRequest, request: Request):
    if not settings.internal_test_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    ip = request.client.host if request.client else "unknown"
    limiter_key = f"{body.email}:{ip}"
    if _is_internal_login_rate_limited(limiter_key):
        raise HTTPException(status_code=429, detail="Too many internal login attempts")

    if body.email not in settings.internal_test_email_allowlist:
        _record_internal_failure(limiter_key)
        raise HTTPException(status_code=403, detail="Email is not allowed for internal login")

    if not hmac.compare_digest(body.password, settings.internal_test_password):
        _record_internal_failure(limiter_key)
        raise HTTPException(status_code=401, detail="Invalid internal login password")

    session = _mint_internal_session(body.email)
    upsert_profile(session["user"]["id"], body.email)
    _internal_login_failures.pop(limiter_key, None)
    return {"ok": True, "session": session}
