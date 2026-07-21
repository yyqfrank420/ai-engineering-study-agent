from fastapi import Header, HTTPException

from adapters.supabase_auth_adapter import get_current_user
from config import settings


def get_optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return get_current_user(authorization)


def get_internal_dashboard_user(authorization: str | None = Header(default=None)) -> dict:
    user = get_current_user(authorization)
    if settings.dev_bypass_auth and authorization == "Bearer dev-local":
        return user
    email = (user.get("email") or "").strip().lower()
    if email not in settings.internal_dashboard_allowlist:
        raise HTTPException(status_code=403, detail="Internal dashboard access denied")
    return user
