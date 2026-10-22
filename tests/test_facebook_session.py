"""Unit tests for agents/facebook/session.py — run: pytest tests/test_facebook_session.py"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agents.facebook import session as fb_session
from agents.facebook.session import parse_cookie_input

EDITOR_EXPORT = json.dumps([
    {"domain": ".facebook.com", "expirationDate": 1790000000.5, "httpOnly": False, "name": "c_user",
     "path": "/", "sameSite": "no_restriction", "secure": True, "value": "100012345"},
    {"domain": ".facebook.com", "expirationDate": 1790000000, "httpOnly": True, "name": "xs",
     "path": "/", "sameSite": "no_restriction", "secure": True, "value": "12%3Aabc%3A2"},
    {"domain": ".facebook.com", "httpOnly": True, "name": "datr", "path": "/",
     "sameSite": "unspecified", "value": "d1"},
    {"domain": ".instagram.com", "name": "sessionid", "value": "ignored"},
])


def test_parse_cookie_editor_export():
    cookies = {c["name"]: c for c in parse_cookie_input(EDITOR_EXPORT)}
    assert set(cookies) == {"c_user", "xs", "datr"}
    assert cookies["c_user"]["value"] == "100012345"
    assert cookies["c_user"]["expires"] == 1790000000.5
    assert cookies["xs"]["httpOnly"] is True
    assert cookies["xs"]["sameSite"] == "None"
    assert cookies["datr"]["sameSite"] == "Lax"
    assert "expires" not in cookies["datr"]
    assert all(c["domain"] == ".facebook.com" and c["secure"] for c in cookies.values())


@pytest.mark.parametrize("raw", [
    "c_user=100012345; xs=12%3Aabc; datr=d1",
    '{"c_user": "100012345", "xs": "12%3Aabc"}',
    '{"cookies": [{"name": "c_user", "value": "100012345", "domain": ".facebook.com"},'
    ' {"name": "xs", "value": "12%3Aabc", "domain": ".facebook.com"}]}',
    "c_user\t100012345\t.facebook.com\t/\nxs\t12%3Aabc\t.facebook.com\t/",
])
def test_parse_other_formats(raw):
    names = {c["name"]: c["value"] for c in parse_cookie_input(raw)}
    assert names["c_user"] == "100012345"
    assert names["xs"] == "12%3Aabc"


@pytest.mark.parametrize("raw, message", [
    ("", "Paste your Facebook cookies"),
    ("[not json", "couldn't be read"),
    ("datr=abc", "Missing the c_user and xs cookies"),
    ("c_user=100012345", "Missing the xs cookie"),
    ("c_user=abc; xs=1", "numeric Facebook ID"),
    ("42", "Missing the c_user and xs cookies"),
])
def test_parse_cookie_errors(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_cookie_input(raw)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for var in ("FB_COOKIES_JSON", "FB_EMAIL", "FB_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(fb_session, "FB_COOKIES_PATH", str(tmp_path / "cookies.json"))
    fb_session.clear_cache()
    yield tmp_path
    fb_session.clear_cache()


def test_system_session_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("FB_COOKIES_JSON", "c_user=100012345; xs=abc")
    s = fb_session.load_session()
    assert s.source == "env" and s.owner == "system" and s.fb_user_id == "100012345"


def test_system_session_from_file_without_password(clean_env):
    (clean_env / "cookies.json").write_text(EDITOR_EXPORT)
    s = fb_session.load_session()
    assert s is not None and s.source == "file"


def test_no_session_configured(clean_env):
    assert fb_session.load_session() is None


def test_user_session_preferred_then_fallback(clean_env, monkeypatch):
    from agents.facebook import store

    user_cookies = parse_cookie_input("c_user=200099999; xs=u")
    rows = {"u1": {"status": "active", "cookies": user_cookies},
            "u2": {"status": "expired", "cookies": user_cookies}}
    monkeypatch.setattr(store, "get_connection", lambda uid: rows.get(uid))
    monkeypatch.setattr(store, "decrypt_cookies", lambda row: row["cookies"])
    monkeypatch.setenv("FB_COOKIES_JSON", "c_user=100012345; xs=abc")

    s = fb_session.load_session(user_id="u1")
    assert s.source == "user" and s.owner == "u1" and s.fb_user_id == "200099999"

    fallback = fb_session.load_session(user_id="u2")
    assert fallback.owner == "system"
    assert fb_session.load_session(user_id="u2", allow_system=False) is None


def test_invalidate_user_session_marks_expired(clean_env, monkeypatch):
    from agents.facebook import store

    updates = {}
    monkeypatch.setattr(store, "update_connection", lambda uid, **f: updates.update({uid: f}))
    s = fb_session.FacebookSession(parse_cookie_input("c_user=1; xs=2"), owner="u1", source="user")
    fb_session._cache["u1"] = s
    fb_session.invalidate_session(s, "redirected to login")
    assert updates["u1"]["status"] == "expired"
    assert "u1" not in fb_session._cache
