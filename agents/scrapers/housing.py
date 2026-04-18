"""
Housing.com Scraper
-------------------
Scrapes rental listings from housing.com for Pune.
Uses requests + BeautifulSoup — no browser or Playwright needed.

Run standalone:
    python agents/scrapers/housing.py
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

BASE_URL = "https://housing.com"


def build_search_url(prefs: dict, page: int = 1) -> str:
    areas = prefs.get("areas", ["pune"])
    area_slug = "-".join(a.lower().replace(" ", "-") for a in areas[:1])
    budget_min = prefs.get("budget_min", 0)
    budget_max = prefs.get("budget_max", 50000)
    url = (
        f"{BASE_URL}/in/rent/flats-in-{area_slug}-pune"
        f"?f=price%3D{budget_min}%2C{budget_max}"
    )
    if page > 1:
        url += f"&page={page}"
    return url


def parse_listing_card(card_soup) -> dict:
    listing = empty_listing()
    listing["platform"] = "housing"
    try:
        title_el = card_soup.select_one("h2, h3, [class*='title'], [class*='heading']")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        for attr in ("data-listing-id", "data-property-id", "data-propid", "data-id"):
            val = card_soup.get(attr, "")
            if val and any(c.isdigit() for c in str(val)):
                listing["listing_id"] = str(val)[:64]
                break

        link = card_soup.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            if not listing["listing_id"]:
                listing["listing_id"] = href.rstrip("/").split("/")[-1]

        price_el = card_soup.select_one("[class*='price'], [class*='rent']")
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        loc_el = card_soup.select_one("[class*='location'], [class*='locality'], [class*='address']")
        if loc_el:
            listing["area_name"] = loc_el.get_text(strip=True).split(",")[0]
            listing["address"] = loc_el.get_text(strip=True)

        for el in card_soup.find_all(["span", "div", "li"]):
            furn = normalize_furnishing(el.get_text(strip=True))
            if furn:
                listing["furnishing"] = furn
                break

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


class HousingScraper(RequestsScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        listings = []

        for page_num in range(1, max_pages + 1):
            url = build_search_url(prefs, page=page_num)
            try:
                print(f"  [housing] Page {page_num}: {url[:80]}...")
                html = fetch_with_session(BASE_URL, url)
                if not html:
                    print(f"  [housing] Empty response on page {page_num}, stopping.")
                    break

                self.random_delay(1.0, 2.5)
                soup = BeautifulSoup(html, "html.parser")

                cards = (
                    soup.select("div[class*='srpCard']") or
                    soup.select("article") or
                    soup.select("div[class*='listing']") or
                    soup.select("li[class*='property']")
                )

                if not cards:
                    print(f"  [housing] No cards on page {page_num}. HTML length: {len(html)}")
                    break

                print(f"  [housing] Found {len(cards)} listings")
                for card in cards:
                    l = parse_listing_card(card)
                    l["city"] = "Pune"
                    if l["listing_id"]:
                        listings.append(l)

            except Exception as e:
                print(f"  [housing] Error on page {page_num}: {e}")

            if page_num < max_pages:
                self.random_delay(3.0, 5.0)

        return listings


if __name__ == "__main__":
    prefs = {
        "areas": ["Baner"],
        "budget_min": 10000,
        "budget_max": 25000,
        "furnishing": "any",
    }
    s = HousingScraper()
    listings = s.scrape(prefs, max_pages=1)
    print(f"Housing: {len(listings)} listings, "
          f"{sum(1 for l in listings if len(l['images']) >= 3)} with 3+ images")
