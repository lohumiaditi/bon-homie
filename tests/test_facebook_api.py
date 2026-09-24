"""API tests for /facebook/* with an in-memory store — run: pytest tests/test_facebook_api.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

from fastapi.testclient import TestClient

from agents.auth_agent import create_access_token
from agents.facebook import session as fb_session
from agents.facebook import store


class FakeStore:
    def __init__(self):
        self.connections, self.groups, self.leads = {}, {}, {}

    def get_connection(self, uid):
        return self.connections.get(uid)

    def save_connection(self, uid, cookies, status, detail):
        row = {"user_id": uid, "cookies": cookies, "status": status, "status_detail": detail,
               "fb_user_id": next(c["value"] for c in cookies if c["name"] == "c_user"),
               "auto_join": False, "harvest_enabled": True}
        self.connections[uid] = row
        return row

    def update_connection(self, uid, **fields):
        self.connections[uid].update(fields)

    def delete_connection(self, uid):
        self.connections.pop(uid, None)

    def decrypt_cookies(self, row):
        return row["cookies"]

    def list_user_groups(self, owner):
        return list(self.groups.get(owner, {}).values())

    def add_group_by_url(self, owner, url):
        key = url.rstrip("/").split("/")[-1]
        row = {"id": key, "group_key": key, "url": url, "enabled": True}
        self.groups.setdefault(owner, {})[key] = row
        return row

    def update_user_group(self, owner, gid, **fields):
        self.groups[owner][gid].update(fields)

    LEAD_STATUSES = store.LEAD_STATUSES

    def list_leads(self, owner, status, limit):
        return [l for l in self.leads.values()
                if l["owner_key"] == owner and (not status or l["status"] == status)][:limit]

    def update_lead(self, owner, lead_id, **fields):
        lead = self.leads.get(lead_id)
        if not lead or lead["owner_key"] != owner:
            return None
        lead.update(fields)
        return lead


@pytest.fixture
def fake(monkeypatch):
    fake = FakeStore()
    for name in ("get_connection", "save_connection", "update_connection", "delete_connection",
                 "decrypt_cookies", "list_user_groups", "add_group_by_url", "update_user_group",
                 "list_leads", "update_lead"):
        monkeypatch.setattr(store, name, getattr(fake, name))
    monkeypatch.setattr(fb_session, "verify_cookies", lambda cookies: (True, "Session is logged in."))
    fb_session.clear_cache()
    return fake


@pytest.fixture
def client():
    from api.main import app
    from api import facebook_routes
    facebook_routes._agent_runs.clear()
    c = TestClient(app)
    c.cookies.set("fh_token", create_access_token("user-1", "fb-1"))
    return c


def test_requires_login(fake):
    from api.main import app
    assert TestClient(app).get("/facebook/connection").status_code == 401


def test_connect_flow(fake, client):
    assert client.get("/facebook/connection").json()["connected"] is False

    bad = client.post("/facebook/connect", json={"cookies": "datr=abc"})
    assert bad.status_code == 400 and "c_user" in bad.json()["detail"]

    res = client.post("/facebook/connect", json={"cookies": "c_user=100012345; xs=abc"})
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] and body["status"] == "active" and body["fb_user_id"] == "100012345"

    res = client.patch("/facebook/connection", json={"auto_join": True})
    assert res.json()["auto_join"] is True

    assert client.delete("/facebook/connection").json() == {"connected": False}
    assert "user-1" not in fake.connections


def test_connect_rejects_logged_out_cookies(fake, client, monkeypatch):
    monkeypatch.setattr(fb_session, "verify_cookies", lambda c: (False, "Facebook says these cookies are logged out."))
    res = client.post("/facebook/connect", json={"cookies": "c_user=1; xs=2"})
    assert res.status_code == 400 and "logged out" in res.json()["detail"]
    assert "user-1" not in fake.connections


def test_connect_inconclusive_is_unverified(fake, client, monkeypatch):
    monkeypatch.setattr(fb_session, "verify_cookies", lambda c: (None, "Couldn't confirm"))
    assert client.post("/facebook/connect", json={"cookies": "c_user=1; xs=2"}).json()["status"] == "unverified"


def test_agent_run(fake, client, monkeypatch):
    import agents.fb_groups_agent as agent

    calls = []

    def fake_run(user_id, tasks, prefs):
        calls.append((user_id, tasks, prefs))
        return {"session_expired": False, "leads_new": 3, "errors": []}

    monkeypatch.setattr(agent, "run_agent", fake_run)

    assert client.post("/facebook/agent/run", json={}).status_code == 404     # not connected
    client.post("/facebook/connect", json={"cookies": "c_user=1; xs=2"})

    assert client.post("/facebook/agent/run", json={"tasks": ["nope"]}).status_code == 400
    res = client.post("/facebook/agent/run", json={"tasks": ["discover", "harvest"], "areas": ["Baner"]})
    assert res.status_code == 200
    assert calls == [("user-1", ["discover", "harvest"], {"areas": ["Baner"]})]
    run = client.get("/facebook/connection").json()["run"]
    assert run["status"] == "done" and run["report"]["leads_new"] == 3

    fake.connections["user-1"]["status"] = "expired"
    assert client.post("/facebook/agent/run", json={}).status_code == 409


def test_groups_and_leads(fake, client):
    client.post("/facebook/connect", json={"cookies": "c_user=1; xs=2"})
    res = client.post("/facebook/groups", json={"url": "https://www.facebook.com/groups/puneflats"})
    assert res.json()["group"]["group_key"] == "puneflats"
    client.patch("/facebook/groups/puneflats", json={"enabled": False})
    assert client.get("/facebook/groups").json()["groups"][0]["enabled"] is False

    fake.leads = {
        "l1": {"id": "l1", "owner_key": "user-1", "status": "new"},
        "l2": {"id": "l2", "owner_key": "someone-else", "status": "new"},
    }
    assert [l["id"] for l in client.get("/facebook/leads").json()["leads"]] == ["l1"]
    assert client.get("/facebook/leads?status=bogus").status_code == 400
    assert client.patch("/facebook/leads/l1", json={"status": "shortlisted"}).json()["lead"]["status"] == "shortlisted"
    assert client.patch("/facebook/leads/l2", json={"status": "dismissed"}).status_code == 404
    assert client.patch("/facebook/leads/l1", json={"status": "bogus"}).status_code == 400


def test_search_attaches_user_id(fake, client, monkeypatch):
    import api.main as main

    captured = {}
    monkeypatch.setattr(main, "run_pipeline", lambda sid, prefs: captured.update(prefs))
    res = client.post("/search", json={"areas": ["Baner"], "budget_min": 10000, "budget_max": 30000})
    assert res.status_code == 200
    assert captured["user_id"] == "user-1"
    assert "user_fb_token" not in captured
