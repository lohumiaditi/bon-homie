"""
Facebook Group Scraper
----------------------
Uses Apify's Facebook Posts Scraper actor (free $5/month credits).
No local browser login needed — Apify handles it server-side.

Apify actor used: apify/facebook-posts-scraper
Free tier: $5/month in credits (renews monthly)

Run standalone:
    python agents/scrapers/facebook.py
"""

import asyncio
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
from agents.scrapers.base import (
    empty_listing, normalize_phone, normalize_furnishing, extract_price
)
from dotenv import load_dotenv
load_dotenv()

# Facebook groups commonly used for Pune flat hunting
PUNE_FLAT_GROUPS = [
    "https://www.facebook.com/groups/puneflatrentals",
    "https://www.facebook.com/groups/puneflatsforrent",
    "https://www.facebook.com/groups/rentalpuneflatrooms",
]

APIFY_BASE = "https://api.apify.com/v2"


def run_facebook_scrape(group_urls: list[str], max_posts: int = 50) -> list[dict]:
    """
    Trigger Apify Facebook scraper and wait for results.
    Returns list of raw post dicts from Apify.
    """
    api_key = os.environ.get("APIFY_KEY")
    if not api_key:
        print("  [facebook] APIFY_KEY not set — skipping Facebook scrape")
        return []

    actor_id = "apify~facebook-posts-scraper"
    run_url = f"{APIFY_BASE}/acts/{actor_id}/runs?token={api_key}"

    payload = {
        "startUrls": [{"url": u} for u in group_urls],
        "maxPosts": max_posts,
        "maxPostComments": 0,
        "maxReviews": 0,
        "maxRetries": 3,
    }

    print(f"  [facebook] Triggering Apify scrape for {len(group_urls)} groups...")
    resp = requests.post(run_url, json=payload, timeout=30)

    if resp.status_code not in (200, 201):
        print(f"  [facebook] Apify error {resp.status_code}: {resp.text[:200]}")
        return []

    run_id = resp.json()["data"]["id"]
    print(f"  [facebook] Apify run started: {run_id}")

    # Poll until done (max 5 minutes)
    status_url = f"{APIFY_BASE}/actor-runs/{run_id}?token={api_key}"
    for attempt in range(30):
        time.sleep(10)
        status_resp = requests.get(status_url, timeout=15)
        status = status_resp.json()["data"]["status"]
        print(f"  [facebook] Status: {status} ({attempt * 10}s elapsed)")
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break

    if status != "SUCCEEDED":
        print(f"  [facebook] Apify run did not succeed: {status}")
        return []

    # Fetch results
    dataset_id = status_resp.json()["data"]["defaultDatasetId"]
    data_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={api_key}&format=json"
    data_resp = requests.get(data_url, timeout=30)
    return data_resp.json() if data_resp.status_code == 200 else []


def parse_facebook_post(post: dict) -> dict:
    """Convert a raw Apify Facebook post to our standard listing dict."""
    listing = empty_listing()
    listing["platform"] = "facebook"

    text = post.get("text") or post.get("postText") or ""
    listing["listing_id"] = post.get("postId") or post.get("id") or ""
    listing["url"] = post.get("url") or post.get("postUrl") or ""
    listing["title"] = text[:100] if text else "Facebook listing"

    # Price extraction from post text — look for patterns like ₹15000 or 15,000/month
    import re as _re
    price_match = _re.search(
        r"(?:rs\.?|inr|rent[:\s]+)?[\u20b9]?\s*(\d{4,6})\s*(?:/\s*(?:mo|month|pm))?",
        text, _re.IGNORECASE
    )
    if price_match:
        val = int(price_match.group(1))
        listing["price"] = val if 1_000 <= val <= 5_00_000 else None

    # Area extraction — look for common Pune area names in the text
    from agents.input_agent import PUNE_AREAS
    text_lower = text.lower()
    for area in PUNE_AREAS:
        if area.lower() in text_lower:
            listing["area_name"] = area
            break
    listing["address"] = listing["area_name"]

    # Furnishing
    listing["furnishing"] = normalize_furnishing(text)

    # Images from post
    photos = post.get("media") or post.get("photos") or []
    image_urls = []
    for photo in photos:
        if isinstance(photo, dict):
            url = photo.get("url") or photo.get("src") or ""
        elif isinstance(photo, str):
            url = photo
        else:
            url = ""
        if url and url.startswith("http"):
            image_urls.append(url)
    listing["images"] = image_urls

    # Occupancy hints
    text_lower = text.lower()
    if "double" in text_lower or "sharing" in text_lower:
        listing["occupancy"] = "double"
    elif "single" in text_lower:
        listing["occupancy"] = "single"

    # Gender hints
    if "male" in text_lower and "female" not in text_lower:
        listing["gender"] = "male"
    elif "female" in text_lower or "ladies" in text_lower or "girls" in text_lower:
        listing["gender"] = "female"

    # Contact from post text
    import re
    phone_match = re.search(r"(?:\+91|0)?[6-9]\d{9}", re.sub(r"\D", "", text))
    if phone_match:
        listing["contact_raw"] = phone_match.group()
        listing["contact"] = normalize_phone(phone_match.group())
    else:
        author = post.get("user") or {}
        listing["contact_raw"] = author.get("name", "")

    listing["city"] = "Pune"
    return listing


def scrape_facebook(prefs: dict) -> list[dict]:
    """Main entry point for Facebook scraping."""
    raw_posts = run_facebook_scrape(PUNE_FLAT_GROUPS, max_posts=60)
    if not raw_posts:
        return []

    listings = []
    for post in raw_posts:
        l = parse_facebook_post(post)
        if l["listing_id"]:
            listings.append(l)

    print(f"  [facebook] {len(listings)} posts parsed, {sum(1 for l in listings if len(l['images']) >= 3)} with 3+ images")
    return listings


if __name__ == "__main__":
    # Test without actual Apify call
    test_post = {
        "postId": "test123",
        "url": "https://facebook.com/groups/test/posts/test123",
        "text": "2BHK flat for rent in Kothrud Pune. ₹15000/month. Fully furnished. Contact: 9876543210",
        "media": [{"url": "https://example.com/img1.jpg"},
                  {"url": "https://example.com/img2.jpg"},
                  {"url": "https://example.com/img3.jpg"}],
    }
    result = parse_facebook_post(test_post)
    print("Facebook post parse test:")
    for k in ["title", "price", "area_name", "furnishing", "contact"]:
        print(f"  {k}: {result[k]}")
    print(f"  images: {len(result['images'])} found")
    ok = result["price"] == 15000 and len(result["images"]) == 3
    print("Test passed!" if ok else "Check results above")
