import jwt
import pytest
from fastapi import HTTPException

from adapters.supabase_auth_adapter import (
    _jwt_algorithm,
    _require_supabase_settings,
    get_current_user,
    request_email_otp,
    verify_access_token,
    verify_email_otp,
    verify_turnstile,
)
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


def test_jwt_algorithm_defaults_to_rs256_for_malformed_header():
    assert _jwt_algorithm("not-a-jwt") == "RS256"


def test_require_supabase_settings_rejects_missing_values(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_anon_key", "")

    with pytest.raises(HTTPException) as exc_info:
        _require_supabase_settings()

    assert exc_info.value.status_code == 500


def test_get_current_user_allows_dev_bypass_only_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "dev_bypass_auth", True)

    user = get_current_user("Bearer dev-local")

    assert user["id"].endswith("dev")
    assert user["email"] == "dev@local"


def test_get_current_user_rejects_missing_header(monkeypatch):
    monkeypatch.setattr(settings, "dev_bypass_auth", False)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(None)

    assert exc_info.value.status_code == 401


def test_get_current_user_rejects_token_without_subject(monkeypatch):
    monkeypatch.setattr("adapters.supabase_auth_adapter.verify_access_token", lambda _token: {"email": "friend@example.com"})

    with pytest.raises(HTTPException) as exc_info:
        get_current_user("Bearer token")

    assert exc_info.value.status_code == 401


def test_get_current_user_returns_verified_claims(monkeypatch):
    monkeypatch.setattr(
        "adapters.supabase_auth_adapter.verify_access_token",
        lambda token: {"sub": "user-1", "email": "friend@example.com", "role": "authenticated"},
    )

    user = get_current_user("Bearer token-123")

    assert user == {
        "id": "user-1",
        "email": "friend@example.com",
        "token": "token-123",
        "claims": {"sub": "user-1", "email": "friend@example.com", "role": "authenticated"},
    }


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    calls = []
    response = _FakeResponse()

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None, data=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "data": data,
                "timeout": self.timeout,
            }
        )
        return self.response


@pytest.mark.asyncio
async def test_request_email_otp_posts_expected_supabase_payload(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(200, {})
    monkeypatch.setattr("adapters.supabase_auth_adapter.httpx.AsyncClient", _FakeAsyncClient)

    await request_email_otp("friend@example.com")

    assert _FakeAsyncClient.calls == [
        {
            "url": "https://project.supabase.co/auth/v1/otp",
            "headers": {"apikey": "anon-key", "Content-Type": "application/json"},
            "json": {"email": "friend@example.com", "create_user": True},
            "data": None,
            "timeout": 10,
        }
    ]


@pytest.mark.asyncio
async def test_request_email_otp_maps_supabase_error(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(400, {"msg": "rate limited"})
    monkeypatch.setattr("adapters.supabase_auth_adapter.httpx.AsyncClient", _FakeAsyncClient)

    with pytest.raises(HTTPException) as exc_info:
        await request_email_otp("friend@example.com")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "rate limited"


@pytest.mark.asyncio
async def test_verify_email_otp_returns_supabase_session(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    session = {"access_token": "access", "user": {"id": "user-1"}}
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(200, session)
    monkeypatch.setattr("adapters.supabase_auth_adapter.httpx.AsyncClient", _FakeAsyncClient)

    result = await verify_email_otp("friend@example.com", "123456")

    assert result == session
    assert _FakeAsyncClient.calls[0]["url"] == "https://project.supabase.co/auth/v1/verify"
    assert _FakeAsyncClient.calls[0]["json"] == {
        "email": "friend@example.com",
        "token": "123456",
        "type": "email",
    }


@pytest.mark.asyncio
async def test_verify_email_otp_maps_error(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(400, {"msg": "Invalid code"})
    monkeypatch.setattr("adapters.supabase_auth_adapter.httpx.AsyncClient", _FakeAsyncClient)

    with pytest.raises(HTTPException) as exc_info:
        await verify_email_otp("friend@example.com", "000000")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid code"


@pytest.mark.asyncio
async def test_verify_turnstile_posts_token_and_ip(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret_key", "secret")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(200, {"success": True})
    monkeypatch.setattr("adapters.supabase_auth_adapter.httpx.AsyncClient", _FakeAsyncClient)

    assert await verify_turnstile("token", "127.0.0.1") is True
    assert _FakeAsyncClient.calls == [
        {
            "url": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            "headers": None,
            "json": None,
            "data": {
                "secret": "secret",
                "response": "token",
                "remoteip": "127.0.0.1",
            },
            "timeout": 10,
        }
    ]


@pytest.mark.asyncio
async def test_verify_turnstile_fails_closed_without_secret_or_bad_response(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    assert await verify_turnstile("token", None) is False

    monkeypatch.setattr(settings, "turnstile_secret_key", "secret")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(500, {"success": True})
    monkeypatch.setattr("adapters.supabase_auth_adapter.httpx.AsyncClient", _FakeAsyncClient)

    assert await verify_turnstile("token", None) is False
