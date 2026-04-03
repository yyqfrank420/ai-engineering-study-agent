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


def test_verify_access_token_accepts_google_oauth_token(monkeypatch):
    # Supabase issues HS256 tokens for Google OAuth users with the same
    # audience/issuer as OTP users. The app_metadata.provider field is
    # present in the payload but not used for verification — both paths
    # must be accepted identically.
    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")

    google_token = jwt.encode(
        {
            "sub": "user-google-456",
            "email": "friend@example.com",
            "aud": "authenticated",
            "iss": settings.effective_supabase_jwt_issuer,
            # Supabase includes app_metadata for OAuth users
            "app_metadata": {"provider": "google", "providers": ["google"]},
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )

    payload = verify_access_token(google_token)

    assert payload["sub"] == "user-google-456"
    assert payload["email"] == "friend@example.com"
    assert payload["app_metadata"]["provider"] == "google"
