"""
Facebook sessions
-----------------
Facebook's API no longer exposes group content, so every read goes through a
real logged-in browser session: the account's cookies (c_user + xs are the
ones that matter).

Where a session comes from, in order:
  1. A user's connected account  (fb_connections row, cookies Fernet-encrypted)
  2. FB_COOKIES_JSON env var      (the "system" account, e.g. a GitHub secret)
  3. FB_COOKIES_PATH file         (default .fb_cookies.json, from setup_fb_cookies.py)
  4. FB_EMAIL + FB_PASSWORD       (automated login — most likely to trip a checkpoint)

Users connect by pasting cookies in any common export format — see
parse_cookie_input().
"""

import json
import os
import re
from dataclasses import dataclass

from agents.facebook.parsing import is_login_wall

SYSTEM_OWNER = "system"

FB_COOKIES_PATH = os.environ.get(
    "FB_COOKIES_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", ".fb_cookies.json"),
)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
)


class FacebookSessionError(RuntimeError):
    """No usable Facebook session."""


class FacebookSessionExpired(FacebookSessionError):
    """Facebook bounced a request to login/checkpoint — the cookies are dead."""


@dataclass
class FacebookSession:
    cookies: list[dict]
    owner: str = SYSTEM_OWNER      # users.id, or "system"
    source: str = "file"           # user | env | file | login

    @property
    def fb_user_id(self) -> str:
        return next((c["value"] for c in self.cookies if c["name"] == "c_user"), "")


# ── Cookie input ──────────────────────────────────────────────────────────────

_SAMESITE = {
    "strict": "Strict", "lax": "Lax", "none": "None",
    "no_restriction": "None", "unspecified": "Lax",
}


def _parse_cookie_text(text: str) -> list[dict]:
    """'c_user=1; xs=abc' header strings, or tab-separated rows copied from DevTools."""
    if "\t" in text:
        rows = [line.split("\t") for line in text.splitlines() if "\t" in line]
        return [{"name": r[0].strip(), "value": r[1].strip()} for r in rows if len(r) >= 2]
    cookies = []
    for part in re.split(r"[;\n]", text):
        if "=" in part:
            name, value = part.split("=", 1)
            cookies.append({"name": name.strip(), "value": value.strip()})
    return cookies


def parse_cookie_input(raw) -> list[dict]:
    """
    Normalise pasted cookies to Playwright's add_cookies() format.

    Accepts: a JSON array (Cookie-Editor / EditThisCookie export, Playwright
    cookies), a JSON object ({"c_user": "...", "xs": "..."} or a Playwright
    storage_state with a "cookies" key), a "name=value; ..." header string, or
    rows copied from the DevTools cookie table. Raises ValueError with a
    message fit to show the user.
    """
    data = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("Paste your Facebook cookies first.")
        if text[0] in "[{":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(f"That looks like JSON but couldn't be read ({e.msg}).") from None
        else:
            data = _parse_cookie_text(text)

    if isinstance(data, dict):
        if isinstance(data.get("cookies"), list):
            data = data["cookies"]
        else:
            data = [{"name": k, "value": v} for k, v in data.items()]
    if not isinstance(data, list):
        raise ValueError("Unrecognised cookie format.")

    by_name: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        value = str(item.get("value", "")).strip()
        domain = str(item.get("domain") or ".facebook.com")
        if not name or not value or "facebook.com" not in domain:
            continue
        cookie = {
            "name": name,
            "value": value,
            "domain": ".facebook.com",
            "path": item.get("path") or "/",
            "secure": True,
            "httpOnly": bool(item.get("httpOnly", False)),
            "sameSite": _SAMESITE.get(str(item.get("sameSite", "none")).lower(), "None"),
        }
        expires = item.get("expires", item.get("expirationDate"))
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        by_name[name] = cookie

    cookies = list(by_name.values())
    missing = [n for n in ("c_user", "xs") if n not in by_name]
    if missing:
        raise ValueError(
            f"Missing the {' and '.join(missing)} cookie{'s' if len(missing) > 1 else ''}. "
            "Copy them from facebook.com while you're logged in."
        )
    if not by_name["c_user"]["value"].isdigit():
        raise ValueError("The c_user cookie should be your numeric Facebook ID.")
    return cookies


def verify_cookies(cookies: list[dict], timeout: float = 15.0) -> tuple[bool | None, str]:
    """
    Quick HTTP check that the cookies are logged in.
    (True, msg) logged in · (False, msg) logged out / checkpoint · (None, msg) inconclusive
    """
    import httpx

    fb_id = next((c["value"] for c in cookies if c["name"] == "c_user"), "")
    try:
        with httpx.Client(
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-IN,en;q=0.9",
            },
            cookies={c["name"]: c["value"] for c in cookies},
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            resp = client.get("https://www.facebook.com/settings/")
    except httpx.HTTPError as e:
        return None, f"Couldn't reach Facebook to check the session ({e.__class__.__name__})."

    final_url = str(resp.url)
    if "checkpoint" in final_url:
        return False, (
            "Facebook wants a security check on this account. Open facebook.com, "
            "complete it, then connect again with fresh cookies."
        )
    if is_login_wall(final_url, resp.text):
        return False, "Facebook says these cookies are logged out. Copy them again while logged in."
    if resp.status_code >= 400:
        return None, f"Facebook returned HTTP {resp.status_code}; the session will be checked on the first run."
    if fb_id and fb_id in resp.text:
        return True, "Session is logged in."
    return None, "Couldn't confirm the login yet; the session will be checked on the first run."


# ── Loading ───────────────────────────────────────────────────────────────────

_cache: dict[str, FacebookSession] = {}


def load_session(
    user_id: str | None = None,
    *,
    allow_system: bool = True,
    allow_password_login: bool = True,
) -> FacebookSession | None:
    """The session to scrape with, or None when nothing is configured."""
    if user_id:
        session = _load_user_session(user_id)
        if session or not allow_system:
            return session
    return load_system_session(allow_password_login=allow_password_login)


def _load_user_session(user_id: str) -> FacebookSession | None:
    if user_id in _cache:
        return _cache[user_id]
    try:
        from agents.facebook import store
        row = store.get_connection(user_id)
    except Exception as e:
        print(f"  [facebook] Couldn't load connection for {user_id[:8]}: {e}")
        return None
    if not row or row.get("status") not in ("active", "unverified"):
        return None
    cookies = store.decrypt_cookies(row)
    if not cookies:
        print(f"  [facebook] Stored cookies for {user_id[:8]} can't be decrypted (ENCRYPTION_KEY changed?)")
        return None
    session = FacebookSession(cookies=cookies, owner=user_id, source="user")
    _cache[user_id] = session
    return session


def load_system_session(allow_password_login: bool = True) -> FacebookSession | None:
    if SYSTEM_OWNER in _cache:
        return _cache[SYSTEM_OWNER]

    session = None
    env_value = os.environ.get("FB_COOKIES_JSON", "").strip()
    if env_value:
        try:
            session = FacebookSession(parse_cookie_input(env_value), source="env")
        except ValueError as e:
            print(f"  [facebook] FB_COOKIES_JSON ignored: {e}")

    if session is None:
        cookies = _load_cookies_file()
        if cookies:
            session = FacebookSession(cookies, source="file")

    if session is None and allow_password_login:
        email = os.environ.get("FB_EMAIL", "")
        password = os.environ.get("FB_PASSWORD", "")
        if email and password:
            try:
                from agents.facebook.browser import login_with_password, run_sync
                cookies = run_sync(lambda: login_with_password(email, password), timeout=120)
                save_cookies_file(cookies)
                session = FacebookSession(cookies, source="login")
            except Exception as e:
                print(f"  [facebook] Login failed: {e}")
                print("  [facebook] Run  python setup_fb_cookies.py  to log in manually once.")

    if session is None:
        print("  [facebook] No Facebook session configured (connect an account, "
              "set FB_COOKIES_JSON, or run setup_fb_cookies.py).")
        return None
    _cache[SYSTEM_OWNER] = session
    return session


def _load_cookies_file() -> list[dict] | None:
    if not os.path.exists(FB_COOKIES_PATH):
        return None
    try:
        with open(FB_COOKIES_PATH) as f:
            return parse_cookie_input(json.load(f))
    except (OSError, ValueError) as e:
        print(f"  [facebook] {FB_COOKIES_PATH} ignored: {e}")
        return None


def save_cookies_file(cookies: list[dict]) -> None:
    try:
        with open(FB_COOKIES_PATH, "w") as f:
            json.dump(cookies, f)
    except OSError as e:
        print(f"  [facebook] Couldn't save cookies: {e}")


# ── After a run ───────────────────────────────────────────────────────────────

def persist_session(session: FacebookSession) -> None:
    """Store the (possibly refreshed) cookies after a successful browser run."""
    try:
        if session.source == "user":
            from agents.facebook import store
            store.mark_connection_healthy(session.owner, session.cookies)
        elif session.source in ("file", "login"):
            save_cookies_file(session.cookies)
    except Exception as e:
        print(f"  [facebook] Couldn't persist refreshed cookies: {e}")


def invalidate_session(session: FacebookSession, reason: str) -> None:
    """Forget a session Facebook rejected; flag a user's connection as expired."""
    _cache.pop(session.owner, None)
    print(f"  [facebook] Session for {session.owner[:8]} rejected: {reason}")
    if session.source == "user":
        try:
            from agents.facebook import store
            store.update_connection(
                session.owner,
                status="expired",
                status_detail="Facebook logged this session out. Reconnect with fresh cookies.",
            )
        except Exception as e:
            print(f"  [facebook] Couldn't mark connection expired: {e}")
    elif session.source in ("file", "login"):
        print("  [facebook] Run  python setup_fb_cookies.py  to refresh .fb_cookies.json")
    elif session.source == "env":
        print("  [facebook] Refresh the FB_COOKIES_JSON secret with new cookies.")


def clear_cache(owner: str | None = None) -> None:
    if owner is None:
        _cache.clear()
    else:
        _cache.pop(owner, None)
