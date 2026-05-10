from fastapi import Header, HTTPException

from adapters.supabase_auth_adapter import get_current_user, verify_access_token
from config import settings


def get_optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    payload = verify_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        return None
    return {
        "id": user_id,
        "email": payload.get("email", ""),
        "token": token,
        "claims": payload,
    }


def get_internal_dashboard_user(authorization: str | None = Header(default=None)) -> dict:
    user = get_current_user(authorization)
    email = (user.get("email") or "").strip().lower()
    if email not in settings.internal_dashboard_allowlist:
        raise HTTPException(status_code=403, detail="Internal dashboard access denied")
    return user
