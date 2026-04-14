"""
Auth Agent
----------
Handles Facebook OAuth 2.0 login, JWT session tokens, and PII encryption.

Security layers:
  1. CSRF protection      — random `state` param verified on OAuth callback
  2. JWT sessions         — HS256 signed tokens in HTTP-only cookies (XSS-safe)
  3. Short-lived tokens   — 24 h access tokens, 30-day refresh tokens
  4. PII encryption       — Fernet (AES-128-CBC + HMAC) for name/email at rest
  5. No secrets in front  — App Secret never leaves the server

Env vars required:
  FACEBOOK_APP_ID       — from developers.facebook.com
  FACEBOOK_APP_SECRET   — from developers.facebook.com
  JWT_SECRET            — random 64-char string  (generate once, never change)
  ENCRYPTION_KEY        — Fernet key             (python -m agents.auth_agent genkey)
  FRONTEND_URL          — e.g. http://localhost:5173 (for CORS + redirects)
  API_URL               — e.g. http://localhost:8000
"""

import base64
import hashlib
import hmac
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Optional

# ── Lazy imports (avoid crash if packages missing) ────────────────────────────

def _jose():
    try:
        from jose import jwt, JWTError
        return jwt, JWTError
    except ImportError:
        raise ImportError("Run: pip install 'python-jose[cryptography]'")

def _fernet():
    try:
        from cryptography.fernet import Fernet
        return Fernet
    except ImportError:
        raise ImportError("Run: pip install cryptography")

def _httpx():
    try:
        import httpx
        return httpx
    except ImportError:
        raise ImportError("Run: pip install httpx")


# ── Config ────────────────────────────────────────────────────────────────────

FB_API_VERSION    = "v19.0"
FB_OAUTH_BASE     = f"https://www.facebook.com/{FB_API_VERSION}/dialog/oauth"
FB_TOKEN_URL      = f"https://graph.facebook.com/{FB_API_VERSION}/oauth/access_token"
FB_USERINFO_URL   = f"https://graph.facebook.com/me"
FB_SCOPES         = "email,public_profile"

JWT_ALGORITHM     = "HS256"
JWT_ACCESS_EXP    = 60 * 60 * 24        # 24 hours
JWT_REFRESH_EXP   = 60 * 60 * 24 * 30   # 30 days

COOKIE_ACCESS     = "fh_token"          # flat-hunter access token
COOKIE_REFRESH    = "fh_refresh"
COOKIE_STATE      = "fh_oauth_state"    # CSRF state cookie


def _cfg(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"{key} is not set in .env")
    return val


# ── CSRF state ────────────────────────────────────────────────────────────────

def generate_oauth_state() -> str:
    """Generate a cryptographically random CSRF state token."""
    return secrets.token_urlsafe(32)


def verify_oauth_state(received: str, expected: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(received, expected)


# ── Facebook OAuth ────────────────────────────────────────────────────────────

def get_facebook_oauth_url(state: str) -> str:
    """
    Returns the URL to redirect the user to for Facebook login.
    `state` should be a random string stored in a short-lived cookie.
    """
    app_id       = _cfg("FACEBOOK_APP_ID")
    api_url      = os.environ.get("API_URL", "http://localhost:8000")
    redirect_uri = f"{api_url}/auth/facebook/callback"

    params = (
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={FB_SCOPES}"
        f"&state={state}"
        f"&response_type=code"
    )
    return FB_OAUTH_BASE + params


def exchange_code_for_user(code: str) -> dict:
    """
    Exchange the OAuth code for a Facebook access token,
    then fetch the user's profile. Returns:
      {fb_id, name, email, picture_url}
    """
    httpx = _httpx()
    app_id     = _cfg("FACEBOOK_APP_ID")
    app_secret = _cfg("FACEBOOK_APP_SECRET")
    api_url    = os.environ.get("API_URL", "http://localhost:8000")
    redirect_uri = f"{api_url}/auth/facebook/callback"

    # Step 1: exchange code → access token
    token_resp = httpx.get(FB_TOKEN_URL, params={
        "client_id":     app_id,
        "client_secret": app_secret,
        "redirect_uri":  redirect_uri,
        "code":          code,
    }, timeout=15)
    token_resp.raise_for_status()
    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise ValueError(f"No access_token in FB response: {token_resp.text[:200]}")

    # Step 2: fetch user profile (only basic fields, minimal permissions)
    info_resp = httpx.get(FB_USERINFO_URL, params={
        "fields":       "id,name,email,picture.type(large)",
        "access_token": access_token,
    }, timeout=15)
    info_resp.raise_for_status()
    fb_user = info_resp.json()

    return {
        "fb_id":       fb_user.get("id"),
        "name":        fb_user.get("name", ""),
        "email":       fb_user.get("email", ""),
        "picture_url": (
            fb_user.get("picture", {}).get("data", {}).get("url", "")
        ),
    }


# ── PII Encryption (Fernet AES-128-CBC + HMAC-SHA256) ─────────────────────────

def _get_fernet():
    Fernet = _fernet()
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY not set. Generate one with:\n"
            "  python -m agents.auth_agent genkey"
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt PII before storing in the database."""
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt PII when serving to the authenticated user."""
    if not ciphertext:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return "[encrypted]"


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, fb_id: str) -> str:
    """Create a signed 24-hour access JWT."""
    jwt, _ = _jose()
    now = int(time.time())
    payload = {
        "sub":     user_id,          # Supabase UUID
        "fb_id":   fb_id,
        "iat":     now,
        "exp":     now + JWT_ACCESS_EXP,
        "type":    "access",
    }
    return jwt.encode(payload, _cfg("JWT_SECRET"), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, fb_id: str) -> str:
    """Create a signed 30-day refresh JWT."""
    jwt, _ = _jose()
    now = int(time.time())
    payload = {
        "sub":   user_id,
        "fb_id": fb_id,
        "iat":   now,
        "exp":   now + JWT_REFRESH_EXP,
        "type":  "refresh",
    }
    return jwt.encode(payload, _cfg("JWT_SECRET"), algorithm=JWT_ALGORITHM)


def verify_token(token: str, expected_type: str = "access") -> dict:
    """
    Verify and decode a JWT. Raises on invalid/expired token.
    Returns payload dict with at least {sub, fb_id, type}.
    """
    jwt, JWTError = _jose()
    try:
        payload = jwt.decode(
            token,
            _cfg("JWT_SECRET"),
            algorithms=[JWT_ALGORITHM],
        )
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")

    if payload.get("type") != expected_type:
        raise ValueError(f"Wrong token type: expected {expected_type}")

    return payload


# ── Supabase user persistence ─────────────────────────────────────────────────

def get_or_create_user(fb_user: dict) -> dict:
    """
    Upsert a Facebook user into the `users` table.
    PII (name, email) is encrypted before storage.
    Returns the DB row dict with decrypted fields.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.client import db
    client = db()

    fb_id = fb_user["fb_id"]
    now   = datetime.now(timezone.utc).isoformat()

    row = {
        "fb_id":       fb_id,
        "name_enc":    encrypt(fb_user.get("name", "")),
        "email_enc":   encrypt(fb_user.get("email", "")),
        "picture_url": fb_user.get("picture_url", ""),
        "last_login":  now,
    }

    # Upsert: insert new user or update last_login
    result = (
        client.table("users")
        .upsert(row, on_conflict="fb_id")
        .execute()
    )
    db_row = result.data[0] if result.data else row

    # Return with decrypted PII for in-memory use
    return {
        "user_id":     db_row.get("id", ""),
        "fb_id":       fb_id,
        "name":        decrypt(db_row.get("name_enc", "")),
        "email":       decrypt(db_row.get("email_enc", "")),
        "picture_url": db_row.get("picture_url", ""),
    }


# ── Full login flow (used by /auth/facebook/callback) ────────────────────────

def complete_facebook_login(code: str, state: str, stored_state: str) -> tuple[dict, str, str]:
    """
    Full OAuth callback handler.
    Returns (user_dict, access_token, refresh_token).
    Raises ValueError on CSRF mismatch or any other failure.
    """
    if not verify_oauth_state(state, stored_state):
        raise ValueError("CSRF state mismatch — possible attack detected. Login rejected.")

    fb_user  = exchange_code_for_user(code)
    db_user  = get_or_create_user(fb_user)

    user_id  = db_user["user_id"]
    fb_id    = db_user["fb_id"]

    access   = create_access_token(user_id, fb_id)
    refresh  = create_refresh_token(user_id, fb_id)

    return db_user, access, refresh


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "genkey":
        Fernet = _fernet()
        key = Fernet.generate_key().decode()
        print(f"\nAdd this to your .env:\nENCRYPTION_KEY={key}\n")
        print("Also add a JWT_SECRET:")
        print(f"JWT_SECRET={secrets.token_urlsafe(64)}\n")
    else:
        print("Usage: python -m agents.auth_agent genkey")
