"""
99Acres Scraper
---------------
Scrapes rental listings from 99acres.com for Pune.
Uses curl_cffi Chrome impersonation to bypass TLS fingerprint detection.
Standard requests/httpx are blocked; curl_cffi is required.

Working URL format (confirmed 2026):
    /property-for-rent-in-{area}-pune-ffid   (area-specific)
    /property-for-rent-in-pune-ffid          (city-wide fallback)

Working card selector (confirmed 2026):
    [data-label^="FSL_TUPLE"]  — top-level listing cards
    .tupleNew__priceValWrap    — price
    .tupleNew__propType        — title

Run standalone:
    python agents/scrapers/ninetynineacres.py
"""

import sys
import os
import re
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    _HAS_CURL_CFFI = False
    print("  [99acres] WARNING: curl_cffi not installed — requests will likely be blocked")

from bs4 import BeautifulSoup
from agents.scrapers.base import (
    RequestsScraper,
    empty_listing, normalize_furnishing,
    extract_price, save_listings,
)

BASE_URL = "https://www.99acres.com"

_HEADERS = {
    "accept-language": "en-IN,en-GB;q=0.9,en;q=0.8,hi;q=0.7",
    "referer": BASE_URL + "/",
}


def build_search_url(area: str, page: int = 1) -> str:
    """Build 99acres rent search URL. Confirmed format: -ffid suffix."""
    area_slug = area.lower().replace(" ", "-")
    url = f"{BASE_URL}/property-for-rent-in-{area_slug}-pune-ffid"
    if page > 1:
        url += f"?page={page}"
    return url


def parse_listing_card(card_soup) -> dict:
    listing = empty_listing()
    listing["platform"] = "99acres"
    try:
        # Title — confirmed class
        title_el = (
            card_soup.select_one(".tupleNew__propType") or
            card_soup.select_one(".tupleNew__propertyHeading") or
            card_soup.select_one("[class*='propType']") or
            card_soup.select_one("[class*='propertyHeading']")
        )
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        # URL and listing_id
        link = card_soup.select_one("a[href*='99acres']") or card_soup.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            # ID from URL slug tail (alphanumeric + hyphens)
            listing["listing_id"] = href.rstrip("/").split("/")[-1]

        # data-* attribute ID override if available and numeric
        for attr in ("data-listing-id", "data-property-id", "data-propid", "data-id"):
            val = card_soup.get(attr, "")
            if val and any(c.isdigit() for c in str(val)):
                listing["listing_id"] = str(val)[:64]
                break

        # Price — confirmed class: .tupleNew__priceValWrap
        price_el = (
            card_soup.select_one(".tupleNew__priceValWrap") or
            card_soup.select_one("[class*='priceValWrap']") or
            card_soup.select_one("[class*='price']")
        )
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        # Location — extract from title text: "2 BHK ... in {Area}, Pune"
        if listing["title"]:
            in_match = re.search(r'\bin\s+([\w\s]+),\s*Pune', listing["title"], re.I)
            if in_match:
                listing["area_name"] = in_match.group(1).strip()
                listing["address"] = listing["area_name"] + ", Pune"

        # Furnishing
        card_text = card_soup.get_text(" ", strip=True)
        listing["furnishing"] = normalize_furnishing(card_text) or None

        # Images
        image_urls = []
        for img in card_soup.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy") or img.get("src") or ""
            if (
                src and src.startswith("http")
                and "placeholder" not in src.lower()
                and "logo" not in src.lower()
                and "icon" not in src.lower()
                and "default" not in src.lower()
                and "Featured.png" not in src
                and "Shortlist.png" not in src
            ):
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))

    except Exception:
        pass
    return listing


class NinetyNineAcresScraper(RequestsScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        areas = prefs.get("areas", [])
        budget_min = prefs.get("budget_min", 5000)
        budget_max = prefs.get("budget_max", 120000)

        if _HAS_CURL_CFFI:
            session = cffi_requests.Session(impersonate="chrome")
        else:
            import requests
            session = requests.Session()

        session.headers.update(_HEADERS)
        listings = []

        for area in areas:
            for page_num in range(1, max_pages + 1):
                url = build_search_url(area, page=page_num)
                try:
                    print(f"  [99acres] {area} page {page_num}: {url[:80]}...")
                    r = session.get(url, timeout=20, allow_redirects=True)
                    if r.status_code != 200:
                        print(f"  [99acres] HTTP {r.status_code}, stopping.")
                        break

                    soup = BeautifulSoup(r.text, "html.parser")

                    # Primary selector: data-label^="FSL_TUPLE" (confirmed gives top-level cards)
                    cards = soup.select('[data-label^="FSL_TUPLE"]')
                    if not cards:
                        cards = soup.select('[class*="Tuple"]')
                        # Remove nested elements
                        outer = []
                        for c in cards:
                            if not any(p in cards for p in c.parents):
                                outer.append(c)
                        cards = outer

                    if not cards:
                        print(f"  [99acres] No cards on {area} page {page_num}. HTML: {len(r.text)} chars")
                        # Try city-wide URL as fallback on first page
                        if page_num == 1:
                            fallback = f"{BASE_URL}/property-for-rent-in-pune-ffid"
                            print(f"  [99acres] Fallback: {fallback}")
                            r2 = session.get(fallback, timeout=20, allow_redirects=True)
                            soup = BeautifulSoup(r2.text, "html.parser")
                            cards = soup.select('[data-label^="FSL_TUPLE"]')
                        if not cards:
                            break

                    print(f"  [99acres] {len(cards)} cards")
                    for card in cards:
                        l = parse_listing_card(card)
                        l["city"] = "Pune"
                        if not l["area_name"]:
                            l["area_name"] = area
                        if l["listing_id"] and l["price"]:
                            if budget_min <= l["price"] <= budget_max:
                                listings.append(l)

                    self.random_delay(2.5, 4.5)

                except Exception as e:
                    print(f"  [99acres] Error: {e}")
                    break

        return listings


if __name__ == "__main__":
    prefs = {
        "areas": ["Kothrud"],
        "budget_min": 8000,
        "budget_max": 60000,
        "furnishing": "any",
    }
    s = NinetyNineAcresScraper()
    listings = s.scrape(prefs, max_pages=1)
    print(f"\n99acres: {len(listings)} listings in budget")
    for l in listings[:3]:
        print(f"  [{l['listing_id'][:20]}] Rs.{l['price']:,} | {l['title'][:55]} | {len(l['images'])} imgs")
