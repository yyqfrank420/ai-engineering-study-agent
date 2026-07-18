from datetime import datetime, timedelta, timezone
import hmac
import uuid

import jwt

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from adapters.supabase_auth_adapter import request_email_otp, verify_email_otp, verify_turnstile
from config import settings
from storage.rate_limit_store import (
    RateLimitDimension,
    release_rate_limit,
    reserve_rate_limit,
)
from storage.profile_store import get_profile_by_email, upsert_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])

_INTERNAL_TEST_USER_NAMESPACE = uuid.UUID("db57f8ae-e7ce-4f62-9779-6337ed49f1f6")


def _normalise_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320:
        raise ValueError("Invalid email")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Invalid email")
    return email


class OTPRequest(BaseModel):
    email: str
    captcha_token: str | None = Field(default=None, max_length=4096)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


class OTPVerifyRequest(BaseModel):
    email: str
    token: str = Field(min_length=1, max_length=2048)
    captcha_token: str | None = Field(default=None, max_length=4096)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


class InternalLoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


def _mint_internal_session(email: str) -> dict:
    if not settings.supabase_jwt_secret:
        raise HTTPException(status_code=500, detail="Internal test auth is not configured")

    existing_profile = get_profile_by_email(email)
    if settings.use_postgres and existing_profile is None:
        raise HTTPException(
            status_code=503,
            detail="Internal test user is not provisioned; complete one normal sign-in first",
        )
    user_id = str(existing_profile["id"]) if existing_profile else str(uuid.uuid5(_INTERNAL_TEST_USER_NAMESPACE, email))
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
    # Internal sessions intentionally have no refresh credential; "bearer" is
    # the OAuth token type rather than a password.
    return {
        "access_token": access_token,
        "refresh_token": "",
        "expires_in": int((expires_at - now).total_seconds()),
        "token_type": "bearer",
        "user": {"id": user_id, "email": email},
    }


def _otp_request_dimensions(email: str, ip: str) -> tuple[RateLimitDimension, ...]:
    return (
        RateLimitDimension(
            scope="otp-request-email",
            identifier=email,
            event_type="otp_request_email",
            limit=settings.otp_request_per_email_limit,
            window_s=settings.otp_request_window_s,
        ),
        RateLimitDimension(
            scope="otp-request-ip",
            identifier=ip,
            event_type="otp_request_ip",
            limit=settings.otp_request_per_ip_limit,
            window_s=settings.otp_request_window_s,
        ),
    )


def _otp_verify_dimensions(email: str, ip: str) -> tuple[RateLimitDimension, ...]:
    return (
        RateLimitDimension(
            scope="otp-verify-email",
            identifier=email,
            event_type="otp_verify_email",
            limit=settings.otp_verify_failure_limit,
            window_s=settings.otp_verify_window_s,
        ),
        RateLimitDimension(
            scope="otp-verify-ip",
            identifier=ip,
            event_type="otp_verify_ip",
            limit=settings.otp_verify_failure_per_ip_limit,
            window_s=settings.otp_verify_window_s,
        ),
    )


def _internal_login_dimensions(ip: str) -> tuple[RateLimitDimension, ...]:
    return (
        RateLimitDimension(
            scope="internal-login-ip",
            identifier=ip,
            event_type="internal_login_failure",
            limit=settings.internal_test_attempt_limit,
            window_s=settings.internal_test_attempt_window_s,
        ),
    )


async def _reserve_otp_attempt(
    dimensions: tuple[RateLimitDimension, ...],
    captcha_token: str | None,
    ip: str,
) -> tuple[str, ...] | None:
    reservation = reserve_rate_limit(dimensions)
    if reservation is not None:
        return reservation
    if not captcha_token or not await verify_turnstile(captcha_token, ip):
        return None
    return reserve_rate_limit(dimensions, bypass_limits=True)


@router.post("/request-otp")
async def request_otp(body: OTPRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    reservation = await _reserve_otp_attempt(
        _otp_request_dimensions(body.email, ip), body.captcha_token, ip
    )
    if reservation is None:
        return {"ok": False, "captcha_required": True}

    try:
        await request_email_otp(body.email)
    except Exception:
        release_rate_limit(reservation)
        raise
    return {"ok": True, "captcha_required": False}


@router.post("/verify-otp")
async def verify_otp(body: OTPVerifyRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    reservation = await _reserve_otp_attempt(
        _otp_verify_dimensions(body.email, ip), body.captcha_token, ip
    )
    if reservation is None:
        return {"ok": False, "captcha_required": True}

    try:
        session = await verify_email_otp(body.email, body.token)
    except HTTPException as exc:
        if exc.status_code >= 500:
            release_rate_limit(reservation)
        raise
    except Exception:
        release_rate_limit(reservation)
        raise

    user = session.get("user") or {}
    user_id = user.get("id")
    email = user.get("email") or body.email
    if not user_id:
        release_rate_limit(reservation)
        raise HTTPException(status_code=400, detail="Supabase did not return a user")

    upsert_profile(user_id, email)
    release_rate_limit(reservation)
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
    reservation = reserve_rate_limit(_internal_login_dimensions(ip))
    if reservation is None:
        raise HTTPException(status_code=429, detail="Too many internal login attempts")

    email_allowed = body.email in settings.internal_test_email_allowlist
    password_valid = hmac.compare_digest(body.password, settings.internal_test_password)
    if not email_allowed or not password_valid:
        raise HTTPException(status_code=401, detail="Invalid internal login credentials")

    try:
        session = _mint_internal_session(body.email)
        upsert_profile(session["user"]["id"], body.email)
    except Exception:
        release_rate_limit(reservation)
        raise
    release_rate_limit(reservation)
    return {"ok": True, "session": session}
