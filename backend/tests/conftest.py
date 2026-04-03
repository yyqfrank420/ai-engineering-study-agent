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
    # Force SQLite mode for unit tests that call init_db() directly.
    # Without this, a SUPABASE_DB_URL env var (e.g. in CI) flips use_postgres=True
    # and the legacy/unit tests that expect a fresh SQLite DB break.
    monkeypatch.setattr(settings, "supabase_db_url", "")
    return tmp_path


@pytest.fixture(autouse=True)
def clear_rate_limits():
    from api.auth_route import _otp_request_by_email, _otp_request_by_ip, _otp_verify_failures
    from adapters.database_adapter import execute

    _otp_request_by_email.clear()
    _otp_request_by_ip.clear()
    _otp_verify_failures.clear()
    try:
        execute("DELETE FROM request_events")
        execute("DELETE FROM search_tool_requests")
    except Exception:
        pass
    yield
    _otp_request_by_email.clear()
    _otp_request_by_ip.clear()
    _otp_verify_failures.clear()
    try:
        execute("DELETE FROM request_events")
        execute("DELETE FROM search_tool_requests")
    except Exception:
        pass
