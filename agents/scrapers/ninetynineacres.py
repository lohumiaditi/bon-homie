"""
99Acres Scraper
---------------
Scrapes rental listings from 99acres.com for Pune.
Uses requests + BeautifulSoup — no browser or Playwright needed.

Run standalone:
    python agents/scrapers/ninetynineacres.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from urllib.parse import urlencode
from bs4 import BeautifulSoup
from agents.scrapers.base import (
    RequestsScraper, fetch_with_session,
    empty_listing, normalize_phone, normalize_furnishing,
    extract_price, save_listings,
)

BASE_URL = "https://www.99acres.com"


def build_search_url(prefs: dict, page: int = 1) -> str:
    """Build 99Acres search URL from user preferences."""
    params = {
        "search_type": "rent",
        "city": "9",           # Pune city code
        "property_type": "3",  # Residential flat
        "min_budget": prefs.get("budget_min", ""),
        "max_budget": prefs.get("budget_max", ""),
        "page": page,
    }
    furnishing = prefs.get("furnishing", "any")
    if furnishing == "furnished":
        params["furnished_type"] = "1"
    elif furnishing == "semi-furnished":
        params["furnished_type"] = "2"
    elif furnishing == "unfurnished":
        params["furnished_type"] = "3"

    areas = prefs.get("areas", [])
    area_slug = "-".join(a.lower().replace(" ", "-") for a in areas[:2]) if areas else "pune"
    qs = urlencode({k: v for k, v in params.items() if v != ""})
    return f"{BASE_URL}/property-for-rent-in-{area_slug}-9?{qs}"


def parse_listing_card(card_soup) -> dict:
    """Parse one listing card from 99Acres search results HTML."""
    listing = empty_listing()
    listing["platform"] = "99acres"
    try:
        # Title
        title_el = (
            card_soup.select_one("a.srpTitle") or
            card_soup.select_one("[class*='title']") or
            card_soup.select_one("h2")
        )
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        # listing_id: prefer data-* attributes, fall back to URL tail
        for attr in ("data-listing-id", "data-property-id", "data-propid", "data-id"):
            val = card_soup.get(attr, "")
            if val and any(c.isdigit() for c in str(val)):
                listing["listing_id"] = str(val)[:64]
                break

        # URL + listing ID
        link = (
            card_soup.select_one("a[href*='/property/']") or
            card_soup.select_one("a[href*='99acres']") or
            card_soup.select_one("a[href]")
        )
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            if not listing["listing_id"]:
                listing["listing_id"] = href.rstrip("/").split("/")[-1] or href

        # Price
        price_el = (
            card_soup.select_one("[class*='price']") or
            card_soup.select_one("[class*='Price']") or
            card_soup.select_one("[class*='amount']")
        )
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        # Location
        loc_el = (
            card_soup.select_one("[class*='locality']") or
            card_soup.select_one("[class*='location']") or
            card_soup.select_one("[class*='address']")
        )
        if loc_el:
            text = loc_el.get_text(strip=True)
            listing["area_name"] = text.split(",")[0]
            listing["address"] = text

        # Furnishing
        for el in card_soup.find_all(["span", "div", "li"]):
            furn = normalize_furnishing(el.get_text(strip=True))
            if furn:
                listing["furnishing"] = furn
                break

        # Images — grab all img tags, filter out logos/placeholders
        image_urls = []
        for img in card_soup.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy") or img.get("src") or ""
            if (
                src and src.startswith("http")
                and "placeholder" not in src.lower()
                and "logo" not in src.lower()
                and "icon" not in src.lower()
                and "default" not in src.lower()
            ):
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))  # dedupe, preserve order

        # Contact (sometimes visible in card)
        phone_el = card_soup.select_one("[class*='phone'], [class*='contact'], [class*='mobile']")
        if phone_el:
            raw = phone_el.get_text()
            listing["contact_raw"] = raw
            listing["contact"] = normalize_phone(raw)

    except Exception:
        pass  # partial data is fine — image filter handles quality later
    return listing


class NinetyNineAcresScraper(RequestsScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        listings = []

        for page_num in range(1, max_pages + 1):
            url = build_search_url(prefs, page=page_num)
            try:
                print(f"  [99acres] Page {page_num}: {url[:80]}...")
                html = fetch_with_session(BASE_URL, url)
                if not html:
                    print(f"  [99acres] Empty response on page {page_num}, stopping.")
                    break

                self.random_delay(1.0, 2.5)
                soup = BeautifulSoup(html, "html.parser")

                # 99Acres uses several class patterns across redesigns
                cards = (
                    soup.select("div[class*='srpCard']") or
                    soup.select("div[class*='propertyCard']") or
                    soup.select("article[class*='listing']") or
                    soup.select("div[data-label='SRPLISTING']") or
                    soup.select("div[class*='body_noSERP']") or
                    soup.select("div[class*='listingContainer']")
                )

                if not cards:
                    print(f"  [99acres] No listing cards on page {page_num}. HTML length: {len(html)}")
                    break

                print(f"  [99acres] Found {len(cards)} cards on page {page_num}")
                for card in cards:
                    l = parse_listing_card(card)
                    l["city"] = "Pune"
                    if l["listing_id"]:
                        listings.append(l)

            except Exception as e:
                print(f"  [99acres] Error on page {page_num}: {e}")

            if page_num < max_pages:
                self.random_delay(3.0, 5.0)

        return listings


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_prefs = {
        "city": "Pune",
        "areas": ["Kothrud", "Baner"],
        "budget_min": 10000,
        "budget_max": 25000,
        "furnishing": "any",
    }

    print("Scraping 99acres for Pune (Kothrud / Baner, Rs.10k-25k)...")
    scraper = NinetyNineAcresScraper()
    listings = scraper.scrape(test_prefs, max_pages=2)

    print(f"\nTotal listings scraped : {len(listings)}")
    print(f"With 3+ images         : {sum(1 for l in listings if len(l['images']) >= 3)}")

    if listings:
        print("\nSample listing:")
        l = listings[0]
        for k in ["title", "price", "area_name", "furnishing", "url"]:
            print(f"  {k}: {l[k]}")
        print(f"  images: {len(l['images'])} found")
    else:
        print("\nNo listings found.")
        print("Tip: The site may render listings via JavaScript.")
        print("     Check if the HTML contains listing data or is mostly JS.")

    save_choice = input("\nSave to Supabase? (y/n) [n]: ").strip().lower()
    if save_choice == "y":
        count = save_listings(listings)
        print(f"Saved {count} new listings.")
