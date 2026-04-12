"""
99Acres Scraper
---------------
Scrapes rental listings from 99acres.com for Pune.

Run standalone:
    python agents/scrapers/ninetynineacres.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from urllib.parse import urlencode, quote_plus
from bs4 import BeautifulSoup
from agents.scrapers.base import (
    BaseScraper, empty_listing, normalize_phone,
    normalize_furnishing, extract_price, save_listings
)

# 99Acres city slug for Pune
CITY_SLUG = "pune-9"
BASE_URL = "https://www.99acres.com"


def build_search_url(prefs: dict, page: int = 1) -> str:
    """Build 99Acres search URL from user preferences."""
    areas = prefs.get("areas", [])
    # 99Acres uses locality names in the URL path
    area_slug = "-".join(a.lower().replace(" ", "-") for a in areas[:2])

    params = {
        "search_type": "rent",
        "city": "9",  # Pune = 9
        "property_type": "3",  # Residential flat
        "bedroom": "",
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

    query_string = urlencode({k: v for k, v in params.items() if v != ""})
    return f"{BASE_URL}/property-for-rent-in-{CITY_SLUG}?{query_string}"


def parse_listing_card(card_soup) -> dict:
    """Parse a single listing card from 99Acres search results HTML."""
    listing = empty_listing()
    listing["platform"] = "99acres"

    try:
        # Title
        title_el = card_soup.select_one("a.srpTitle, h2.title, [class*='title']")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        # URL and listing ID
        link = card_soup.select_one("a[href*='/property/']")
        if not link:
            link = card_soup.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            # Extract ID from URL slug
            parts = href.rstrip("/").split("/")
            listing["listing_id"] = parts[-1] if parts else href

        # Price
        price_el = card_soup.select_one(
            "[class*='price'], [class*='Price'], .priceBox, span[class*='amount']"
        )
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        # Area / locality
        loc_el = card_soup.select_one(
            "[class*='locality'], [class*='location'], [class*='address']"
        )
        if loc_el:
            listing["area_name"] = loc_el.get_text(strip=True).split(",")[0]
            listing["address"] = loc_el.get_text(strip=True)

        # Furnishing
        for span in card_soup.find_all(["span", "div", "li"]):
            text = span.get_text(strip=True)
            furn = normalize_furnishing(text)
            if furn:
                listing["furnishing"] = furn
                break

        # Images
        imgs = card_soup.select("img[src*='99acres'], img[data-src*='99acres'], img[src*='img.']")
        if not imgs:
            imgs = card_soup.select("img[src*='http']")
        image_urls = []
        for img in imgs:
            src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith("http") and "placeholder" not in src and "logo" not in src:
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))  # dedupe

        # Contact (sometimes visible on search page)
        phone_el = card_soup.select_one("[class*='phone'], [class*='contact'], [class*='mobile']")
        if phone_el:
            raw = phone_el.get_text()
            listing["contact_raw"] = raw
            listing["contact"] = normalize_phone(raw)

    except Exception as e:
        pass  # Partial data is fine; image filter will drop bad listings

    return listing


class NinetyNineAcresScraper(BaseScraper):

    async def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        listings = []

        async with self as scraper:
            for page_num in range(1, max_pages + 1):
                url = build_search_url(prefs, page=page_num)
                ctx, page = await scraper.new_page()

                try:
                    print(f"  [99acres] Page {page_num}: {url[:80]}...")
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await scraper.random_delay(2.0, 4.0)

                    # Scroll to trigger lazy-loaded images
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    await asyncio.sleep(1.5)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.0)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Find listing cards — 99Acres uses several class patterns
                    cards = (
                        soup.select("div[class*='srpCard']") or
                        soup.select("div[class*='propertyCard']") or
                        soup.select("article[class*='listing']") or
                        soup.select("div[data-label='SRPLISTING']")
                    )

                    if not cards:
                        print(f"  [99acres] No cards found on page {page_num}. Site may have changed.")
                        break

                    print(f"  [99acres] Found {len(cards)} listings on page {page_num}")
                    for card in cards:
                        l = parse_listing_card(card)
                        l["city"] = "Pune"
                        if l["listing_id"]:  # Only keep if we got an ID
                            listings.append(l)

                except Exception as e:
                    print(f"  [99acres] Error on page {page_num}: {e}")
                finally:
                    await ctx.close()

                if page_num < max_pages:
                    await scraper.random_delay(3.0, 6.0)

        return listings


# ── Standalone test ───────────────────────────────────────────────────────────
async def _test():
    test_prefs = {
        "city": "Pune",
        "areas": ["Kothrud", "Baner"],
        "budget_min": 10000,
        "budget_max": 25000,
        "furnishing": "any",
    }
    scraper = NinetyNineAcresScraper(headless=True)
    print("Scraping 99acres for Pune (Kothrud / Baner, ₹10k–25k)...")
    listings = await scraper.scrape(test_prefs, max_pages=2)
    print(f"\nTotal listings scraped: {len(listings)}")
    print(f"With 3+ images: {sum(1 for l in listings if len(l['images']) >= 3)}")

    if listings:
        print("\nSample listing:")
        l = listings[0]
        for k in ["title", "price", "area_name", "furnishing", "url"]:
            print(f"  {k}: {l[k]}")
        print(f"  images: {len(l['images'])} found")

    save_choice = input("\nSave to Supabase? (y/n) [n]: ").strip().lower()
    if save_choice == "y":
        count = save_listings(listings)
        print(f"Saved {count} new listings to Supabase.")


if __name__ == "__main__":
    asyncio.run(_test())
