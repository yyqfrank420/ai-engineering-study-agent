import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from adapters.supabase_auth_adapter import request_email_otp, verify_email_otp, verify_turnstile
from config import settings
from storage.profile_store import upsert_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])

_otp_request_by_email: dict[str, list[float]] = defaultdict(list)
_otp_request_by_ip: dict[str, list[float]] = defaultdict(list)
_otp_verify_failures: dict[str, list[float]] = defaultdict(list)


class OTPRequest(BaseModel):
    email: str
    captcha_token: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email")
        return email


class OTPVerifyRequest(BaseModel):
    email: str
    token: str
    captcha_token: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email")
        return email


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
