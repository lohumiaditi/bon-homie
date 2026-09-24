"""Unit tests for agents/facebook/parsing.py — run: pytest tests/test_facebook_parsing.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agents.facebook.parsing import (
    classify_post,
    detect_membership,
    extract_area,
    extract_phone,
    extract_price,
    group_key_from_url,
    is_login_wall,
    parse_feed_posts,
    parse_group_search,
    parse_marketplace,
    parse_member_count,
    post_to_listing,
    score_group,
    RELEVANCE_THRESHOLD,
)


# ── Text extraction ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("2BHK in Baner, rent 18000", "Baner"),
    ("Flat near Viman Nagar Road", "Viman Nagar"),
    ("room on NIBM Road available", "NIBM Road"),
    ("vimannagar 1rk", "Viman Nagar"),
    ("Account suspended, contact support", ""),       # "Sus" is a word match only
    ("near the college campus", ""),                   # not "Camp"
    ("PG in Camp area", "Camp"),
])
def test_extract_area(text, expected):
    assert extract_area(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Rent: 18,000 per month", 18000),
    ("Rent 22000/- deposit 50000", 22000),
    ("Deposit ₹60,000. Rent ₹25,000", 25000),
    ("₹15,000 / month  2 beds", 15000),
    ("Rs.12500 pm", 12500),
    ("2BHK 15k rent Baner", 15000),
    ("rent 22.5k", 22500),
    ("1,20,000 per month penthouse", 120000),
    ("Call 9876543210 for details", None),            # phone, not price
    ("3 BHK flat, 2 bathrooms", None),
    ("Deposit 50000 only", None),
])
def test_extract_price(text, expected):
    assert extract_price(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Call 9876543210", "+919876543210"),
    ("WhatsApp +91 98765 43210", "+919876543210"),
    ("contact 987-654-3210 anytime", "+919876543210"),
    ("ph: 09876543210", "+919876543210"),
    ("Rent 65000 deposit 200000", ""),
    ("posted 12345678901234", ""),
])
def test_extract_phone(text, expected):
    assert extract_phone(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("2BHK flat available for rent in Baner. Rent 20000. Call 9876543210", "offer"),
    ("Looking for a flatmate for my 2BHK in Kothrud, rent 9000 per head", "offer"),
    ("Room available in Wakad, fully furnished", "offer"),
    ("Looking for a 1BHK flat in Baner, budget 15k, need from 1st Oct", "seek"),
    ("Need a room near Hinjewadi phase 1 urgently", "seek"),
    ("Anyone selling a used bike?", "other"),
    ("Happy Diwali everyone!", "other"),
])
def test_classify_post(text, expected):
    assert classify_post(text) == expected


# ── Page state ────────────────────────────────────────────────────────────────

def test_is_login_wall():
    assert is_login_wall("https://www.facebook.com/login/?next=x")
    assert is_login_wall("https://www.facebook.com/checkpoint/123")
    assert is_login_wall("https://www.facebook.com/groups/x", '<form id="login_form">')
    assert not is_login_wall("https://www.facebook.com/groups/x", "<div>feed</div>")


@pytest.mark.parametrize("html, expected", [
    ('<div aria-label="Join group" role="button">Join group</div>', "not_member"),
    ('<div aria-label="Cancel request" role="button"></div>', "pending"),
    ('<div role="button" aria-label="Joined"></div><span>Write something...</span>', "member"),
    ("<div>nothing here</div>", "unknown"),
])
def test_detect_membership(html, expected):
    assert detect_membership(html) == expected


def test_group_key_from_url():
    assert group_key_from_url("https://www.facebook.com/groups/puneflatrentals/?ref=share") == "puneflatrentals"
    assert group_key_from_url("/groups/123456789/posts/987/") == "123456789"
    assert group_key_from_url("https://www.facebook.com/groups/feed/") == ""
    assert group_key_from_url("https://example.com/x") == ""


# ── Feed parsing ──────────────────────────────────────────────────────────────

FEED_HTML = """
<div role="feed">
  <div role="article">
    <h3><a href="https://www.facebook.com/groups/puneflats/user/100012345/">Asha K</a></h3>
    <a href="https://www.facebook.com/groups/puneflats/posts/1234567890123/?__cft__[0]=x">2h</a>
    <div data-ad-preview="message">2BHK flat available for rent in Baner. Rent: 22,000. Semi furnished,
      family preferred. Call 98765 43210 … See more</div>
    <img src="https://scontent.xx.fbcdn.net/v/photo1.jpg" width="500" height="400">
    <img src="https://static.xx.fbcdn.net/images/emoji.php/v9/smile.png" width="16" height="16">
    <div role="article">
      <a href="https://www.facebook.com/someone">Commenter</a>
      Is it still available? Looking for a flat for rent in Baner
    </div>
  </div>
  <div role="article">
    <a href="https://www.facebook.com/rahul.m">Rahul M</a>
    <a href="#">1h</a>
    <a href="https://www.facebook.com/photo/?fbid=555&set=gm.2222222222">photo</a>
    <div data-ad-preview="message">Looking for a 1BHK in Kothrud, budget 15k</div>
  </div>
  <div role="article">
    <a href="https://www.facebook.com/priya.s">Priya S</a>
    <div data-ad-preview="message">Room available in Wakad for working women, 9000 per month</div>
  </div>
</div>
"""


def test_parse_feed_posts_top_level_only():
    posts = parse_feed_posts(FEED_HTML)
    assert len(posts) == 3                                # nested comment article skipped
    first = posts[0]
    assert first["post_id"] == "1234567890123"
    assert first["url"] == "https://www.facebook.com/groups/puneflats/posts/1234567890123/"
    assert first["group_key"] == "puneflats"
    assert first["poster_url"] == "https://www.facebook.com/profile.php?id=100012345"
    assert first["poster_name"] == "Asha K"
    assert first["images"] == ["https://scontent.xx.fbcdn.net/v/photo1.jpg"]
    assert "See more" not in first["text"]
    assert "Commenter" not in first["text"]


def test_parse_feed_posts_fallback_ids():
    posts = parse_feed_posts(FEED_HTML)
    assert posts[1]["post_id"] == "2222222222"            # from the group photo link
    assert posts[1]["url"] == ""
    assert posts[2]["post_id"].startswith("h")            # text hash when no link at all


def test_post_to_listing_offer_vs_seek():
    posts = parse_feed_posts(FEED_HTML)
    offer = post_to_listing(posts[0])
    assert offer["platform"] == "facebook"
    assert offer["listing_id"] == "fbpost_1234567890123"
    assert offer["price"] == 22000
    assert offer["area_name"] == "Baner"
    assert offer["contact"] == "+919876543210"
    assert offer["wa_url"].startswith("https://wa.me/919876543210?text=")
    assert offer["furnishing"] == "semi-furnished"
    assert offer["renter_type"] == "family"
    assert offer["fb_poster_url"].endswith("id=100012345")

    assert post_to_listing(posts[1]) is None              # seeker, not a lead

    women = post_to_listing(posts[2])
    assert women["gender"] == "female"
    assert women["price"] == 9000
    assert women["url"] == ""


def test_parse_marketplace():
    html = """
    <div><div>
      <a href="/marketplace/item/4455667788/?ref=search">
        <img src="https://scontent.xx.fbcdn.net/v/mp1.jpg">
        <span>₹18,000 / month</span><span>2 beds 2 baths Flat</span><span>Baner, Pune</span>
      </a>
    </div></div>
    <a href="/marketplace/item/4455667788/">duplicate link</a>
    """
    listings = parse_marketplace(html)
    assert len(listings) == 1
    l = listings[0]
    assert l["listing_id"] == "fbmp_4455667788"
    assert l["url"] == "https://www.facebook.com/marketplace/item/4455667788/"
    assert l["price"] == 18000
    assert l["area_name"] == "Baner"
    assert l["images"] == ["https://scontent.xx.fbcdn.net/v/mp1.jpg"]


# ── Group search ──────────────────────────────────────────────────────────────

GROUP_SEARCH_HTML = """
<div role="feed">
  <div class="result">
    <a href="https://www.facebook.com/groups/puneflatsnobroker/">Pune Flats &amp; Flatmates - No Brokerage</a>
    <span>Public · 48K members · 10+ posts a day</span>
    <div role="button"><a href="https://www.facebook.com/groups/puneflatsnobroker/">Join</a></div>
  </div>
  <div class="result">
    <a href="https://www.facebook.com/groups/1122334455/">Pune Plots For Sale</a>
    <span>Private · 3.2K members</span>
  </div>
  <div class="result">
    <a href="https://www.facebook.com/groups/bangalorerooms/">Bangalore Rooms</a>
    <span>Public · 900 members</span>
  </div>
  <a href="https://www.facebook.com/groups/feed/">Your feed</a>
</div>
"""


def test_parse_group_search():
    groups = {g["group_key"]: g for g in parse_group_search(GROUP_SEARCH_HTML)}
    assert set(groups) == {"puneflatsnobroker", "1122334455", "bangalorerooms"}
    top = groups["puneflatsnobroker"]
    assert top["name"] == "Pune Flats & Flatmates - No Brokerage"
    assert top["privacy"] == "public"
    assert top["member_count"] == 48_000
    assert top["activity"] == "10+ posts a day"
    assert groups["1122334455"]["privacy"] == "private"
    assert groups["1122334455"]["member_count"] == 3_200


@pytest.mark.parametrize("text, expected", [
    ("48K members", 48_000), ("3.2K members", 3_200), ("1.1M members", 1_100_000),
    ("900 members", 900), ("12,345 members", 12_345), ("no count", None),
])
def test_parse_member_count(text, expected):
    assert parse_member_count(text) == expected


def test_score_group_ranks_rental_groups():
    good = score_group("Pune Flats & Flatmates - No Brokerage", "", 48_000)
    sale = score_group("Pune Plots For Sale", "", 3_200)
    other_city = score_group("Bangalore Rooms", "", 900)
    assert good >= RELEVANCE_THRESHOLD
    assert sale < RELEVANCE_THRESHOLD
    assert other_city < RELEVANCE_THRESHOLD
    assert good > other_city > sale
