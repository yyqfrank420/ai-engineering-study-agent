from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.llm_adapter import stream_response
from config import settings
from storage.profile_store import upsert_profile
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
    assert "Invalid internal login password" in response.text


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

    import asyncio

    text = asyncio.run(_collect())
    rows = list_recent_llm_telemetry(since_epoch=0)

    assert text == "Hello world"
    assert rows
    assert rows[0]["operation"] == "unit_test_llm"
    assert rows[0]["provider"] == "anthropic"
    assert rows[0]["status"] == "success"
    assert rows[0]["output_chars"] == len("Hello world")
