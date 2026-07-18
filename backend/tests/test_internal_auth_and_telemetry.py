from types import SimpleNamespace
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.database_adapter import fetchall
from adapters.llm_adapter import stream_response
from config import settings
from storage.profile_store import upsert_profile
from storage.analytics_event_store import list_recent_analytics_events
from storage.telemetry_store import list_recent_http_request_logs, list_recent_llm_telemetry


def test_internal_login_returns_bearer_token_without_touching_otp(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "correct horse battery staple")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "friend@example.com")
    monkeypatch.setattr(settings, "internal_test_session_minutes", 15)

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "correct horse battery staple"},
        )

        assert response.status_code == 200
        session = response.json()["session"]
        assert session["token_type"] == "bearer"
        assert session["user"]["email"] == "friend@example.com"

        authed = client.get(
            "/api/threads",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )

    assert authed.status_code == 200
    assert authed.json() == {"threads": []}


def test_internal_login_rejects_wrong_password(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "expected-secret")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "friend@example.com")

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "wrong-secret"},
        )

    assert response.status_code == 401
    assert "Invalid internal login credentials" in response.text


def test_internal_login_can_be_disabled(monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "internal_test_password", "")
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "anything"},
        )

    assert response.status_code == 404


def test_internal_login_rate_limits_after_failures(monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_attempt_limit", 1)
    monkeypatch.setattr(settings, "internal_test_attempt_window_s", 60)
    monkeypatch.setattr(settings, "internal_test_password", "expected-secret")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "friend@example.com")
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        first = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "wrong-secret"},
        )
        second = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "expected-secret"},
        )

    assert first.status_code == 401
    assert second.status_code == 429


def test_auth_rate_limit_storage_hashes_identifiers(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "internal_test_password", "expected-secret")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "friend@example.com")
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "wrong-secret"},
        )

    rows = fetchall(
        "SELECT key_hash, event_type, created_at_epoch, expires_at_epoch "
        "FROM rate_limit_events"
    )
    assert response.status_code == 401
    assert len(rows) == 1
    assert rows[0]["event_type"] == "internal_login_failure"
    assert "friend@example.com" not in rows[0]["key_hash"]
    assert rows[0]["expires_at_epoch"] > rows[0]["created_at_epoch"]


def test_internal_login_requires_jwt_secret(monkeypatch):
    from fastapi import HTTPException
    from api import auth_route

    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")

    with pytest.raises(HTTPException) as exc_info:
        auth_route._mint_internal_session("friend@example.com")

    assert exc_info.value.status_code == 500
    assert "not configured" in exc_info.value.detail


def test_internal_login_requires_existing_postgres_profile(monkeypatch):
    from fastapi import HTTPException
    from api import auth_route

    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://example")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(auth_route, "get_profile_by_email", lambda _email: None)

    with pytest.raises(HTTPException) as exc_info:
        auth_route._mint_internal_session("friend@example.com")

    assert exc_info.value.status_code == 503
    assert "normal sign-in" in exc_info.value.detail


def test_internal_login_uses_generic_error_for_unlisted_email(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "expected-secret")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "friend@example.com")

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/internal-login",
            json={"email": "outsider@example.com", "password": "expected-secret"},
        )

    assert response.status_code == 401
    assert "Invalid internal login credentials" in response.text


def test_internal_login_reuses_existing_profile_id_for_same_email(temp_data_dir, monkeypatch):
    from main import create_app

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "internal_test_password", "correct horse battery staple")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "friend@example.com")

    init_db()
    upsert_profile("existing-user-id", "friend@example.com")

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/internal-login",
            json={"email": "friend@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["user"]["id"] == "existing-user-id"


def test_upsert_profile_updates_existing_email_in_place(temp_data_dir):
    init_db()

    first = upsert_profile("existing-user-id", "before@example.com")
    second = upsert_profile("existing-user-id", "after@example.com")

    assert first["id"] == "existing-user-id"
    assert second["id"] == "existing-user-id"
    assert second["email"] == "after@example.com"


def test_internal_login_stringifies_existing_uuid_profile_id(temp_data_dir, monkeypatch):
    from api import auth_route

    monkeypatch.setattr(settings, "supabase_jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "supabase_jwt_issuer", "https://project.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")

    existing_id = uuid.uuid4()
    monkeypatch.setattr(auth_route, "get_profile_by_email", lambda email: {"id": existing_id, "email": email})

    session = auth_route._mint_internal_session("friend@example.com")

    assert session["user"]["id"] == str(existing_id)


def test_request_logging_middleware_records_http_request(temp_data_dir):
    from main import create_app

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.get("/api/prepare")

    logs = list_recent_http_request_logs(since_epoch=0)

    assert response.status_code == 503
    assert logs
    assert logs[0]["path"] == "/api/prepare"
    assert logs[0]["status_code"] == 503


def test_request_logging_middleware_survives_log_write_failure(monkeypatch):
    from main import create_app

    monkeypatch.setattr("main.record_http_request_log", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no log")))
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_auth_routes_validate_email_shape():
    from main import create_app

    app = create_app(load_resources=False)

    with TestClient(app) as client:
        response = client.post("/api/auth/request-otp", json={"email": "bad"})

    assert response.status_code == 422


def test_request_otp_allows_suspicious_request_with_valid_captcha(monkeypatch):
    from main import create_app
    import api.auth_route as auth_route

    monkeypatch.setattr(settings, "otp_request_per_email_limit", 1)
    monkeypatch.setattr(settings, "otp_request_per_ip_limit", 100)
    calls = []

    async def fake_request_email_otp(email):
        calls.append(email)

    async def fake_verify_turnstile(token, ip):
        return token == "pass" and ip

    monkeypatch.setattr(auth_route, "request_email_otp", fake_request_email_otp)
    monkeypatch.setattr(auth_route, "verify_turnstile", fake_verify_turnstile)
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        first = client.post("/api/auth/request-otp", json={"email": "FRIEND@example.com"})
        second = client.post(
            "/api/auth/request-otp",
            json={"email": "friend@example.com", "captcha_token": "pass"},
        )

    assert first.json() == {"ok": True, "captcha_required": False}
    assert second.json() == {"ok": True, "captcha_required": False}
    assert calls == ["friend@example.com", "friend@example.com"]


def test_verify_otp_records_failure_requires_captcha_and_clears_on_success(monkeypatch):
    from fastapi import HTTPException
    from main import create_app
    import api.auth_route as auth_route

    monkeypatch.setattr(settings, "otp_verify_failure_limit", 1)
    monkeypatch.setattr(settings, "otp_verify_window_s", 60)
    attempts = []
    upserts = []

    async def fake_verify_email_otp(email, token):
        attempts.append(token)
        if token == "bad":
            raise HTTPException(status_code=401, detail="bad token")
        if token == "missing-user":
            return {"user": {}, "access_token": "a", "refresh_token": "r", "expires_in": 60}
        return {
            "user": {"id": "user-1", "email": email},
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 60,
            "token_type": "bearer",
        }

    async def fake_verify_turnstile(token, ip):
        return token == "pass" and ip

    monkeypatch.setattr(auth_route, "verify_email_otp", fake_verify_email_otp)
    monkeypatch.setattr(auth_route, "verify_turnstile", fake_verify_turnstile)
    monkeypatch.setattr(auth_route, "upsert_profile", lambda user_id, email: upserts.append((user_id, email)))
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        bad = client.post("/api/auth/verify-otp", json={"email": "friend@example.com", "token": "bad"})
        captcha_required = client.post("/api/auth/verify-otp", json={"email": "friend@example.com", "token": "good"})
        missing_user = client.post(
            "/api/auth/verify-otp",
            json={"email": "friend@example.com", "token": "missing-user", "captcha_token": "pass"},
        )
        good = client.post(
            "/api/auth/verify-otp",
            json={"email": "friend@example.com", "token": "good", "captcha_token": "pass"},
        )

    assert bad.status_code == 401
    assert captcha_required.json() == {"ok": False, "captcha_required": True}
    assert missing_user.status_code == 400
    assert good.json()["session"]["user"] == {"id": "user-1", "email": "friend@example.com"}
    assert upserts == [("user-1", "friend@example.com")]


def test_verify_otp_rate_limits_failures_across_distinct_emails_by_ip(monkeypatch):
    from fastapi import HTTPException
    from main import create_app
    import api.auth_route as auth_route

    monkeypatch.setattr(settings, "otp_verify_failure_limit", 100)
    monkeypatch.setattr(settings, "otp_verify_failure_per_ip_limit", 2)

    async def reject_otp(_email, _token):
        raise HTTPException(status_code=400, detail="bad token")

    monkeypatch.setattr(auth_route, "verify_email_otp", reject_otp)
    app = create_app(load_resources=False)

    with TestClient(app) as client:
        first = client.post(
            "/api/auth/verify-otp",
            json={"email": "first@example.com", "token": "bad"},
        )
        second = client.post(
            "/api/auth/verify-otp",
            json={"email": "second@example.com", "token": "bad"},
        )
        blocked = client.post(
            "/api/auth/verify-otp",
            json={"email": "third@example.com", "token": "bad"},
        )

    assert first.status_code == 400
    assert second.status_code == 400
    assert blocked.json() == {"ok": False, "captcha_required": True}


def test_latest_thread_endpoint_auto_creates_first_thread(temp_data_dir):
    from main import create_app
    from adapters.supabase_auth_adapter import get_current_user

    init_db()

    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1", "email": "friend@example.com"}

    with TestClient(app) as client:
        response = client.get("/api/threads/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread"]["id"]
    assert payload["thread"]["title"] == "New chat"
    assert payload["messages"] == []


class _FakeAnthropicStream:
    def __init__(self, events):
        self._events = iter(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def test_stream_response_records_llm_telemetry(temp_data_dir, monkeypatch):
    init_db()

    fake_events = [
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="Hello")),
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=" world")),
    ]
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **kwargs: _FakeAnthropicStream(fake_events))
    )
    monkeypatch.setattr("adapters.llm_adapter._get_anthropic_client", lambda: fake_client)

    async def _collect():
        chunks: list[str] = []
        async for event_type, content in stream_response(
            model=settings.worker_model,
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            telemetry={
                "operation": "unit_test_llm",
                "user_id": "user-1",
                "thread_id": "thread-1",
            },
        ):
            if event_type == "text":
                chunks.append(content)
        return "".join(chunks)

    text = asyncio.run(_collect())
    rows = list_recent_llm_telemetry(since_epoch=0)
    analytics_rows = list_recent_analytics_events(since_epoch=0, event_category="llm")

    assert text == "Hello world"
    assert rows
    assert rows[0]["operation"] == "unit_test_llm"
    assert rows[0]["provider"] == "anthropic"
    assert rows[0]["status"] == "success"
    assert rows[0]["output_chars"] == len("Hello world")
    assert analytics_rows
    assert analytics_rows[0]["event_name"] == "llm_call_completed"
    assert analytics_rows[0]["properties"]["operation"] == "unit_test_llm"
    assert analytics_rows[0]["properties"]["output_chars"] == len("Hello world")


def test_stream_response_limits_concurrent_anthropic_streams(temp_data_dir, monkeypatch):
    init_db()

    import adapters.llm_adapter as llm_adapter

    active = 0
    max_active = 0
    gates: dict[str, asyncio.Event] = {}

    class _SlowAnthropicStream:
        def __init__(self):
            self._events = iter([
                SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="ok")),
            ])

        async def __aenter__(self):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            gates["entered"].set()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            nonlocal active
            active -= 1
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            await gates["release"].wait()
            try:
                return next(self._events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    fake_client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **kwargs: _SlowAnthropicStream())
    )
    monkeypatch.setattr(settings, "anthropic_max_concurrent_streams", 1)
    monkeypatch.setattr(llm_adapter, "_anthropic_stream_semaphore", None)
    monkeypatch.setattr(llm_adapter, "_anthropic_stream_limit", None)
    monkeypatch.setattr("adapters.llm_adapter._get_anthropic_client", lambda: fake_client)

    async def _collect_one():
        async for _event_type, _content in stream_response(
            model=settings.worker_model,
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            telemetry={"operation": "unit_test_llm_limit"},
        ):
            pass

    async def _run_concurrently():
        gates["entered"] = asyncio.Event()
        gates["release"] = asyncio.Event()
        tasks = [
            asyncio.create_task(_collect_one()),
            asyncio.create_task(_collect_one()),
            asyncio.create_task(_collect_one()),
        ]

        await asyncio.wait_for(gates["entered"].wait(), timeout=1)
        assert active == 1
        gates["release"].set()
        await asyncio.gather(*tasks)

    asyncio.run(_run_concurrently())

    assert max_active == 1
