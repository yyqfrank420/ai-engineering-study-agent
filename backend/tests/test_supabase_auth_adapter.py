import jwt
import pytest
from fastapi import HTTPException

from adapters.supabase_auth_adapter import verify_access_token
from config import settings


def _make_token(*, audience: str, issuer: str, secret: str) -> str:
    return jwt.encode(
        {
            "sub": "user-123",
            "email": "friend@example.com",
            "aud": audience,
            "iss": issuer,
        },
        secret,
        algorithm="HS256",
    )


def test_verify_access_token_accepts_expected_audience(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")

    token = _make_token(
        audience="authenticated",
        issuer=settings.effective_supabase_jwt_issuer,
        secret=settings.supabase_jwt_secret,
    )

    payload = verify_access_token(token)

    assert payload["sub"] == "user-123"
    assert payload["email"] == "friend@example.com"


def test_verify_access_token_rejects_wrong_audience(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")

    token = _make_token(
        audience="public",
        issuer=settings.effective_supabase_jwt_issuer,
        secret=settings.supabase_jwt_secret,
    )

    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(token)

    assert exc_info.value.status_code == 401
