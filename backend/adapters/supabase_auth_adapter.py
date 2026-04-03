import base64
import json
import time
from functools import lru_cache

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from config import settings


def _require_supabase_settings() -> None:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=500, detail="Supabase auth is not configured")


@lru_cache(maxsize=1)
def _get_jwk_client() -> PyJWKClient:
    if not settings.supabase_url:
        raise RuntimeError("Supabase URL not configured")
    return PyJWKClient(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def _jwt_algorithm(token: str) -> str:
    """Read the alg field from the JWT header without verifying the token."""
    try:
        header_b64 = token.split('.')[0]
        # Restore padding that base64url encoding strips
        padding = (4 - len(header_b64) % 4) % 4
        header = json.loads(base64.b64decode(header_b64 + '=' * padding))
        return header.get('alg', 'RS256')
    except Exception:
        return 'RS256'


def verify_access_token(token: str) -> dict:
    if not settings.effective_supabase_jwt_issuer:
        raise HTTPException(status_code=500, detail="Supabase JWT issuer is not configured")
    if not settings.effective_supabase_jwt_audience:
        raise HTTPException(status_code=500, detail="Supabase JWT audience is not configured")

    alg = _jwt_algorithm(token)
    decode_kwargs = {
        "issuer": settings.effective_supabase_jwt_issuer,
        "audience": settings.effective_supabase_jwt_audience,
    }

    try:
        if alg == 'HS256':
            # Supabase projects using symmetric keys — need the JWT secret directly.
            # Set SUPABASE_JWT_SECRET in .env (Project Settings → API → JWT Secret).
            if not settings.supabase_jwt_secret:
                raise HTTPException(
                    status_code=500,
                    detail="SUPABASE_JWT_SECRET is not configured (required for HS256 tokens)",
                )
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                **decode_kwargs,
            )
        else:
            # RS256 / ES256 — verify via JWKS public key (asymmetric)
            signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                **decode_kwargs,
            )
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[auth] JWT verification failed ({alg}): {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc


_DEV_USER = {
    "id": "00000000-0000-0000-0000-000000000dev",
    "email": "dev@local",
    "token": "dev-local",
    "claims": {},
}


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    # Dev bypass — only active when DEV_BYPASS_AUTH=true in .env (never in prod)
    if settings.dev_bypass_auth and authorization == "Bearer dev-local":
        return _DEV_USER

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    payload = verify_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid access token")
    return {
        "id": user_id,
        "email": payload.get("email", ""),
        "token": token,
        "claims": payload,
    }


async def request_email_otp(email: str) -> None:
    _require_supabase_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/otp",
            headers={
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "create_user": True,
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail=response.json().get("msg", "Failed to request OTP"))


async def verify_email_otp(email: str, token: str) -> dict:
    _require_supabase_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/verify",
            headers={
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "token": token,
                "type": "email",
            },
        )
        if response.status_code >= 400:
            detail = response.json()
            raise HTTPException(status_code=400, detail=detail.get("msg", "Invalid verification code"))
        return response.json()


async def verify_turnstile(token: str, remote_ip: str | None) -> bool:
    if not settings.turnstile_secret_key:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": settings.turnstile_secret_key,
                "response": token,
                "remoteip": remote_ip or "",
            },
        )
        if response.status_code >= 400:
            return False
        return bool(response.json().get("success"))
