import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def force_sqlite_mode(monkeypatch):
    from config import settings

    # Unit tests default to SQLite even when CI exports SUPABASE_DB_URL.
    # Tests that need Postgres behavior can override this per-test.
    monkeypatch.setattr(settings, "supabase_db_url", "")


@pytest.fixture(autouse=True)
def block_live_llm_credentials(monkeypatch):
    from config import settings

    # Test code must use fakes/mocks for model calls. This prevents a local
    # shell with real API keys from leaking paid credentials into pytest.
    monkeypatch.setattr(settings, "anthropic_api_key", "test-disabled")
    monkeypatch.setattr(settings, "openai_api_key", "")


@pytest.fixture(autouse=True)
def skip_prompt_injection_model(monkeypatch):
    # Most chat tests do not exercise the prompt guard; dedicated tests reload
    # the module when they need real scanner behavior.
    monkeypatch.setattr("api.chat_guards.check_prompt_injection", lambda _text: True)
    monkeypatch.setattr("api.sse_handler.check_prompt_injection", lambda _text: True)


@pytest.fixture(autouse=True)
def clear_rate_limits():
    from api.auth_route import (
        _internal_login_failures,
        _otp_request_by_email,
        _otp_request_by_ip,
        _otp_verify_failures,
    )
    from api.analytics_route import _capture_attempts
    from adapters.database_adapter import execute

    _capture_attempts.clear()
    _otp_request_by_email.clear()
    _otp_request_by_ip.clear()
    _otp_verify_failures.clear()
    _internal_login_failures.clear()
    try:
        execute("DELETE FROM request_events")
        execute("DELETE FROM product_analytics_events")
        execute("DELETE FROM search_tool_requests")
        execute("DELETE FROM active_streams")
        execute("DELETE FROM http_request_logs")
        execute("DELETE FROM llm_telemetry")
        execute("DELETE FROM analytics_events")
    except Exception:
        pass
    yield
    _capture_attempts.clear()
    _otp_request_by_email.clear()
    _otp_request_by_ip.clear()
    _otp_verify_failures.clear()
    _internal_login_failures.clear()
    try:
        execute("DELETE FROM request_events")
        execute("DELETE FROM product_analytics_events")
        execute("DELETE FROM search_tool_requests")
        execute("DELETE FROM active_streams")
        execute("DELETE FROM http_request_logs")
        execute("DELETE FROM llm_telemetry")
        execute("DELETE FROM analytics_events")
    except Exception:
        pass
