"""Shared FastAPI dependencies."""

from typing import Optional

from fastapi import Cookie, HTTPException


def get_current_user(fh_token: Optional[str] = Cookie(default=None)) -> dict:
    """
    Reads the HTTP-only JWT cookie and returns {user_id, fb_id}.
    Raises 401 if missing or invalid. Use as: user = Depends(get_current_user)
    """
    if not fh_token:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    try:
        from agents.auth_agent import verify_token
        payload = verify_token(fh_token, expected_type="access")
        return {"user_id": payload["sub"], "fb_id": payload["fb_id"]}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Session expired or invalid: {e}")


def optional_user_id(fh_token: Optional[str] = Cookie(default=None)) -> str | None:
    """users.id when a valid session cookie is present, else None."""
    if not fh_token:
        return None
    try:
        from agents.auth_agent import verify_token
        return verify_token(fh_token, expected_type="access").get("sub") or None
    except Exception:
        return None
