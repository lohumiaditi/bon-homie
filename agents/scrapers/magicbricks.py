"""
MagicBricks Scraper
-------------------
Scrapes rental listings from magicbricks.com for Pune.
Server-renders full HTML — no JS needed. Requires Sec-Fetch-* headers to
get past Akamai bot scoring.

Selectors (confirmed live):
  Card:      .mb-srp__card
  Title:     .mb-srp__card--title
  Price:     .mb-srp__card__price
  ID:        &id= param in <a href>

Run standalone:
    python agents/scrapers/magicbricks.py
"""

import sys
import os
import re
import time
import random
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bs4 import BeautifulSoup
from agents.scrapers.base import (
    RequestsScraper,
    empty_listing, normalize_furnishing,
    extract_price, save_listings,
)

BASE_URL = "https://www.magicbricks.com"

# Full browser-like headers — Akamai scores these; Sec-Fetch-* are required
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


def build_search_url(prefs: dict, page: int = 1) -> str:
    areas = prefs.get("areas", [])
    # MagicBricks uses Locality= param for area filtering
    area_slug = "-".join(a.lower().replace(" ", "-") for a in areas[:1])
    budget_min = prefs.get("budget_min", 0)
    budget_max = prefs.get("budget_max", 50000)

    url = (
        f"{BASE_URL}/property-for-rent/residential-real-estate"
        f"?proptype=Multistorey-Apartment,Builder-Floor-Apartment,"
        f"Penthouse,Studio-Apartment,Service-Apartment"
        f"&cityName=Pune"
        f"&BudgetMin={budget_min}&BudgetMax={budget_max}"
    )
    if area_slug:
        url += f"&Locality={area_slug}"
    if page > 1:
        url += f"&page={page}"
    return url


def parse_listing_card(card_soup) -> dict:
    listing = empty_listing()
    listing["platform"] = "magicbricks"
    try:
        # Title
        title_el = card_soup.select_one(".mb-srp__card--title")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        # listing_id: prefer &id= param in link URL (hex-encoded MB property ID)
        link = card_soup.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            m = re.search(r'[?&]id=([A-Za-z0-9_-]{6,})', href)
            if m:
                listing["listing_id"] = m.group(1)[:64]
            else:
                listing["listing_id"] = href.rstrip("/").split("/")[-1]

        # data-* attribute fallback (if present)
        if not listing["listing_id"]:
            for attr in ("data-listing-id", "data-property-id", "data-propid", "data-id"):
                val = card_soup.get(attr, "")
                if val and any(c.isdigit() for c in str(val)):
                    listing["listing_id"] = str(val)[:64]
                    break

        # Price — class confirmed: .mb-srp__card__price
        price_el = card_soup.select_one(".mb-srp__card__price, [class*='price']")
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        # Locality
        loc_el = card_soup.select_one(
            "[class*='locality'], [class*='location'], [class*='address']"
        )
        if loc_el:
            txt = loc_el.get_text(strip=True)
            listing["area_name"] = txt.split(",")[0].strip()
            listing["address"] = txt

        # Furnishing — scan all text nodes
        for el in card_soup.find_all(["span", "div", "li"]):
            furn = normalize_furnishing(el.get_text(strip=True))
            if furn:
                listing["furnishing"] = furn
                break

        # Images
        imgs = card_soup.select(
            "img[src*='staticmb'], img[data-src*='staticmb'], "
            "img[src*='cdn'], img[data-src*='cdn']"
        )
        image_urls = []
        for img in imgs:
            src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith("http") and "placeholder" not in src and "logo" not in src:
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))

    except Exception:
        pass
    return listing


class MagicBricksScraper(RequestsScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        listings = []
        session = requests.Session()
        session.headers.update(_HEADERS)
        # Warm session with homepage
        try:
            session.get(BASE_URL, timeout=10)
            time.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass

        for page_num in range(1, max_pages + 1):
            url = build_search_url(prefs, page=page_num)
            try:
                print(f"  [magicbricks] Page {page_num}: {url[:90]}...")
                r = session.get(url, timeout=20, allow_redirects=True)
                if r.status_code != 200:
                    print(f"  [magicbricks] HTTP {r.status_code} on page {page_num}, stopping.")
                    break

                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select(".mb-srp__card")

                if not cards:
                    print(f"  [magicbricks] No cards page {page_num}. HTML: {len(r.text)} chars")
                    break

                print(f"  [magicbricks] {len(cards)} listings on page {page_num}")
                for card in cards:
                    l = parse_listing_card(card)
                    l["city"] = "Pune"
                    if l["listing_id"]:
                        listings.append(l)

                self.random_delay(1.5, 3.0)

            except Exception as e:
                print(f"  [magicbricks] Error page {page_num}: {e}")
                break

            if page_num < max_pages:
                self.random_delay(3.0, 5.0)

        return listings


if __name__ == "__main__":
    prefs = {
        "areas": ["Kothrud"],
        "budget_min": 8000,
        "budget_max": 35000,
        "furnishing": "any",
    }
    s = MagicBricksScraper()
    listings = s.scrape(prefs, max_pages=1)
    print(f"MagicBricks: {len(listings)} listings, "
          f"{sum(1 for l in listings if len(l['images']) >= 1)} with images")
    for l in listings[:3]:
        print(f"  [{l['listing_id'][:16]}] Rs.{l['price']} | {l['title'][:60]}")
