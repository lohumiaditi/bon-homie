"""run_agent() end-to-end with a fake browser page and in-memory store — pytest tests/test_fb_groups_agent.py"""

import os
import sys
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import agents.fb_groups_agent as agent
from agents.facebook import actions, browser, store
from agents.facebook import session as fb_session
from agents.facebook.parsing import parse_feed_posts, parse_group_search
from agents.facebook.session import FacebookSession, FacebookSessionExpired, parse_cookie_input
from tests.test_facebook_parsing import FEED_HTML, GROUP_SEARCH_HTML


class Recorder:
    def __init__(self):
        self.groups, self.links, self.leads, self.listings = {}, [], [], []
        self.group_updates, self.connection = {}, {"auto_join": False}

    def upsert_groups(self, groups):
        for g in groups:
            self.groups[g["group_key"]] = {**g, "id": "id-" + g["group_key"]}
        return {g["group_key"]: self.groups[g["group_key"]] for g in groups}

    def link_groups(self, owner, ids, added_by):
        self.links += [(owner, i, added_by) for i in ids]
        return len(ids)

    def ensure_seed_groups(self, owner, urls):
        pass

    def groups_for_harvest(self, owner, limit):
        return [{"id": "g1", "url": "https://www.facebook.com/groups/puneflats/", "leads_found": 2}]

    def save_leads(self, owner, leads):
        self.leads += leads
        return len(leads)

    def update_user_group(self, owner, gid, **fields):
        self.group_updates[gid] = fields

    def get_connection(self, uid):
        return self.connection

    def update_connection(self, uid, **fields):
        self.connection.update(fields)


@pytest.fixture
def rec(monkeypatch):
    rec = Recorder()
    for name in ("upsert_groups", "link_groups", "ensure_seed_groups", "groups_for_harvest",
                 "save_leads", "update_user_group", "get_connection", "update_connection"):
        monkeypatch.setattr(store, name, getattr(rec, name))

    session = FacebookSession(parse_cookie_input("c_user=1; xs=2"), owner="u1", source="user")
    monkeypatch.setattr(agent, "load_session", lambda **kw: session)
    monkeypatch.setattr(agent, "persist_session", lambda s: None)

    @asynccontextmanager
    async def fake_open_page(s):
        yield object()

    async def no_pause(*a):
        pass

    async def group_search(page, query):
        return parse_group_search(GROUP_SEARCH_HTML)

    async def group_feed(page, url, max_posts):
        return "member", parse_feed_posts(FEED_HTML)

    monkeypatch.setattr(browser, "open_page", fake_open_page)
    monkeypatch.setattr(browser, "pause", no_pause)
    monkeypatch.setattr(actions, "fetch_group_search", group_search)
    monkeypatch.setattr(actions, "fetch_group_feed", group_feed)

    import agents.scrapers.base as base
    monkeypatch.setattr(base, "save_listings", lambda ls: rec.listings.extend(ls) or len(ls))
    return rec


def test_discover_and_harvest(rec):
    report = agent.run_agent("u1", ("discover", "join", "harvest"), {"areas": ["Baner"]})

    assert report["errors"] == []
    assert report["tasks"] == ["discover", "harvest"]            # join dropped: auto_join off
    assert report["groups_found"] == 3
    assert list(rec.groups) == ["puneflatsnobroker"]              # only the relevant group kept
    assert rec.links == [("u1", "id-puneflatsnobroker", "discovered")]

    assert report["posts_seen"] == 3
    assert report["leads_new"] == 2                               # seeker post skipped
    assert {l["post_id"] for l in rec.leads} == {"1234567890123", rec.leads[1]["post_id"]}
    assert rec.leads[0]["group_id"] == "g1" and rec.leads[0]["contact"] == "+919876543210"
    assert report["listings_saved"] == 2                          # both leads have a price
    assert rec.group_updates["g1"]["membership"] == "member"
    assert rec.group_updates["g1"]["leads_found"] == 4
    assert rec.connection["last_run_summary"]["leads_new"] == 2


def test_expired_session_is_reported(rec, monkeypatch):
    async def expired(page, url, max_posts):
        raise FacebookSessionExpired("redirected to login")

    invalidated = []
    monkeypatch.setattr(actions, "fetch_group_feed", expired)
    monkeypatch.setattr(agent, "invalidate_session", lambda s, reason: invalidated.append(reason))

    report = agent.run_agent("u1", ("harvest",))
    assert report["session_expired"] is True
    assert invalidated == ["redirected to login"]
    assert "Reconnect" in report["errors"][0]
