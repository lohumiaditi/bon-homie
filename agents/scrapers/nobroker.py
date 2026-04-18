"""
NoBroker Scraper
----------------
Scrapes rental listings from nobroker.in for Pune.
Uses requests + BeautifulSoup — no browser or Playwright needed.

Note: NoBroker has bot detection. We use rotating User-Agent + delays.
      Some requests may be blocked; the scraper retries automatically.

Run standalone:
    python agents/scrapers/nobroker.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bs4 import BeautifulSoup
from agents.scrapers.base import (
    RequestsScraper, fetch_with_session,
    empty_listing, normalize_phone, normalize_furnishing,
    extract_price, save_listings,
)

BASE_URL = "https://www.nobroker.in"


def build_search_url(prefs: dict, page: int = 1) -> str:
    city = "pune"
    areas = prefs.get("areas", [])
    area_slug = "-".join(a.lower().replace(" ", "-") for a in areas[:1])
    budget_min = prefs.get("budget_min", 0)
    budget_max = prefs.get("budget_max", 50000)

    furnishing_map = {
        "furnished": "furnished",
        "semi-furnished": "semifurnished",
        "unfurnished": "unfurnished",
        "any": "",
    }
    ftype = furnishing_map.get(prefs.get("furnishing", "any"), "")

    url = f"{BASE_URL}/property/residential/rent/{city}"
    if area_slug:
        url += f"/{area_slug}"
    params = f"?budget={budget_min},{budget_max}"
    if ftype:
        params += f"&furnishType={ftype}"
    if page > 1:
        params += f"&pageNo={page}"
    return url + params


def parse_listing_card(card_soup) -> dict:
    listing = empty_listing()
    listing["platform"] = "nobroker"
    try:
        # Title / BHK info
        title_el = card_soup.select_one("h3, [class*='title'], [class*='bhk']")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        # listing_id: prefer data-* attributes (most reliable), fall back to URL tail
        for attr in ("data-listing-id", "data-property-id", "data-propid", "data-id"):
            val = card_soup.get(attr, "")
            if val and any(c.isdigit() for c in str(val)):
                listing["listing_id"] = str(val)[:64]
                break

        # URL
        link = card_soup.select_one("a[href*='/property/'], a[href*='nobroker']")
        if not link:
            link = card_soup.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            if not listing["listing_id"]:
                listing["listing_id"] = href.rstrip("/").split("/")[-1]

        # Price
        price_el = card_soup.select_one("[class*='price'], [class*='rent'], [class*='amount']")
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        # Location
        loc_el = card_soup.select_one("[class*='locality'], [class*='location'], [class*='area']")
        if loc_el:
            listing["area_name"] = loc_el.get_text(strip=True).split(",")[0]
            listing["address"] = loc_el.get_text(strip=True)

        # Furnishing
        for el in card_soup.find_all(["span", "div", "li"]):
            furn = normalize_furnishing(el.get_text(strip=True))
            if furn:
                listing["furnishing"] = furn
                break

        # NoBroker is always zero-brokerage
        listing["brokerage"] = False

        # Images
        imgs = card_soup.select("img[src*='http'], img[data-src*='http']")
        image_urls = []
        for img in imgs:
            src = img.get("data-src") or img.get("src") or ""
            if (
                src and src.startswith("http")
                and "placeholder" not in src
                and "logo" not in src
            ):
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))

    except Exception:
        pass
    return listing


class NoBrokerScraper(RequestsScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        listings = []

        for page_num in range(1, max_pages + 1):
            url = build_search_url(prefs, page=page_num)
            try:
                print(f"  [nobroker] Page {page_num}: {url[:80]}...")
                html = fetch_with_session(BASE_URL, url)
                if not html:
                    print(f"  [nobroker] Empty response on page {page_num}, stopping.")
                    break

                self.random_delay(1.5, 3.0)
                soup = BeautifulSoup(html, "html.parser")

                cards = (
                    soup.select("div[class*='PropertyCard']") or
                    soup.select("div[class*='srp-property-card']") or
                    soup.select("div.package-detail") or
                    soup.select("div[data-id]")
                )

                if not cards:
                    print(f"  [nobroker] No cards on page {page_num}. HTML length: {len(html)}")
                    break

                print(f"  [nobroker] Found {len(cards)} listings on page {page_num}")
                for card in cards:
                    l = parse_listing_card(card)
                    l["city"] = "Pune"
                    if l["listing_id"]:
                        listings.append(l)

            except Exception as e:
                print(f"  [nobroker] Error on page {page_num}: {e}")

            if page_num < max_pages:
                self.random_delay(3.0, 5.5)

        return listings


if __name__ == "__main__":
    prefs = {
        "areas": ["Kothrud"],
        "budget_min": 8000,
        "budget_max": 20000,
        "furnishing": "any",
    }
    s = NoBrokerScraper()
    listings = s.scrape(prefs, max_pages=1)
    print(f"NoBroker: {len(listings)} listings, "
          f"{sum(1 for l in listings if len(l['images']) >= 3)} with 3+ images")
