"""
SquareYards Scraper
-------------------
Scrapes rental listings from squareyards.com for Pune.
Server-renders with Sec-Fetch-* headers. No browser needed.

Confirmed working URL pattern:
    /rent/property-for-rent-in-{area}-pune  → 25-27 real listing cards
    /rent/property-for-rent-in-pune         → city-wide fallback

Selectors (confirmed live):
    Card:        article.listing-card
    ID:          article[propertyid] or data-propertyid
    URL:         [data-href] on .property-label  OR  a[href]
    Price:       .listing-price  (handles "₹ 48,000" and "1.5 L" formats)
    Title:       .heading
    Locality:    data-locality on .favorite-btn
    Images:      data-image on .favorite-btn + img[src*=squareyards]

Run standalone:
    python agents/scrapers/squareyards.py
"""

import sys
import os
import re
import time
import random

try:
    from curl_cffi import requests
    _IMPERSONATE = "chrome"
except ImportError:
    import requests
    _IMPERSONATE = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bs4 import BeautifulSoup
from agents.scrapers.base import (
    RequestsScraper,
    empty_listing, normalize_furnishing,
    extract_price, save_listings,
)

BASE_URL = "https://www.squareyards.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def build_search_url(area: str, page: int = 1) -> str:
    """Build SquareYards rent search URL for a Pune area."""
    area_slug = area.lower().replace(" ", "-")
    url = f"{BASE_URL}/rent/property-for-rent-in-{area_slug}-pune"
    if page > 1:
        url += f"?page={page}"
    return url


def parse_listing_card(card_soup) -> dict:
    listing = empty_listing()
    listing["platform"] = "squareyards"
    try:
        # ID — article[propertyid] is the most reliable
        prop_id = card_soup.get("propertyid", "")
        if not prop_id:
            fav = card_soup.select_one(".favorite-btn, [data-propertyid]")
            if fav:
                prop_id = fav.get("data-propertyid", "")
        if prop_id and any(c.isdigit() for c in str(prop_id)):
            listing["listing_id"] = str(prop_id)[:64]

        # URL — data-href on .property-label list, or first a[href]
        label = card_soup.select_one(".property-label")
        href = label.get("data-href", "") if label else ""
        if not href:
            link = card_soup.select_one("a[href*='squareyards.com'], a[href^='/']")
            href = link.get("href", "") if link else ""
        if href:
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            # Fallback ID from URL tail (numeric)
            if not listing["listing_id"]:
                tail = href.rstrip("/").split("/")[-1]
                if any(c.isdigit() for c in tail):
                    listing["listing_id"] = tail

        # Title
        title_el = card_soup.select_one(".heading, h2, h3, [class*='title']")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        # Price — .listing-price handles both "₹ 48,000" and "1.5 L" formats
        price_el = card_soup.select_one(".listing-price, [class*='price']")
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        # Locality — stored in data-locality on .favorite-btn
        fav_btn = card_soup.select_one("[data-locality]")
        if fav_btn:
            locality_raw = fav_btn.get("data-locality", "")
            listing["area_name"] = locality_raw.split(",")[0].strip()
            listing["address"] = locality_raw

        # Furnishing — scan card text
        card_text = card_soup.get_text(" ", strip=True)
        listing["furnishing"] = normalize_furnishing(card_text) or None

        # Images — data-image on fav btn gives first image; also grab img[src]
        image_urls = []
        fav = card_soup.select_one("[data-image]")
        if fav and fav.get("data-image", "").startswith("http"):
            image_urls.append(fav["data-image"])
        for img in card_soup.select("img[src*='squareyards'], img[data-src*='squareyards']"):
            src = img.get("data-src") or img.get("src", "")
            if src and src.startswith("http") and src not in image_urls:
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))

    except Exception:
        pass
    return listing


class SquareYardsScraper(RequestsScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        areas = prefs.get("areas", [])
        budget_min = prefs.get("budget_min", 5000)
        budget_max = prefs.get("budget_max", 120000)

        if _IMPERSONATE:
            session = requests.Session(impersonate=_IMPERSONATE)
        else:
            session = requests.Session()
        session.headers.update(_HEADERS)
        # DO NOT warm with homepage — SY switches to client-side-only render
        # when it detects a returning-user cookie, producing 0 SSR cards.

        listings = []
        for area in areas:
            for page_num in range(1, max_pages + 1):
                url = build_search_url(area, page=page_num)
                try:
                    print(f"  [squareyards] {area} page {page_num}: {url[:80]}...")
                    r = session.get(url, timeout=20, allow_redirects=True)
                    if r.status_code != 200:
                        print(f"  [squareyards] HTTP {r.status_code}, stopping.")
                        break

                    soup = BeautifulSoup(r.text, "html.parser")
                    cards = soup.select("article.listing-card")

                    if not cards:
                        # Fallback: city-wide URL
                        city_url = f"{BASE_URL}/rent/property-for-rent-in-pune"
                        print(f"  [squareyards] No cards for {area}, trying city-wide URL")
                        r2 = session.get(city_url, timeout=20)
                        soup = BeautifulSoup(r2.text, "html.parser")
                        cards = soup.select("article.listing-card")
                        if not cards:
                            break

                    print(f"  [squareyards] {len(cards)} cards")
                    for card in cards:
                        l = parse_listing_card(card)
                        l["city"] = "Pune"
                        if l["listing_id"] and l["price"]:
                            # Client-side budget filter
                            if budget_min <= l["price"] <= budget_max:
                                listings.append(l)

                    self.random_delay(2.0, 4.0)

                except Exception as e:
                    print(f"  [squareyards] Error: {e}")
                    break

        return listings


if __name__ == "__main__":
    prefs = {
        "areas": ["Kothrud"],
        "budget_min": 8000,
        "budget_max": 60000,
        "furnishing": "any",
    }
    s = SquareYardsScraper()
    listings = s.scrape(prefs, max_pages=1)
    print(f"\nSquareYards: {len(listings)} listings in budget")
    for l in listings[:3]:
        print(f"  [{l['listing_id'][:12]}] Rs.{l['price']:,} | {l['title'][:55]} | {len(l['images'])} imgs")
