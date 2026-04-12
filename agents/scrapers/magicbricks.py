"""
MagicBricks Scraper
-------------------
Scrapes rental listings from magicbricks.com for Pune.

Run standalone:
    python agents/scrapers/magicbricks.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bs4 import BeautifulSoup
from agents.scrapers.base import (
    BaseScraper, empty_listing, normalize_phone,
    normalize_furnishing, extract_price, save_listings
)

BASE_URL = "https://www.magicbricks.com"


def build_search_url(prefs: dict) -> str:
    areas = prefs.get("areas", ["Pune"])
    area_slug = "-".join(a.lower().replace(" ", "-") for a in areas[:2])
    budget_min = prefs.get("budget_min", 0)
    budget_max = prefs.get("budget_max", 50000)
    furnishing_map = {"furnished": "Furnished", "semi-furnished": "Semi-Furnished",
                      "unfurnished": "Unfurnished", "any": ""}
    ftype = furnishing_map.get(prefs.get("furnishing", "any"), "")
    url = f"{BASE_URL}/property-for-rent/residential-real-estate?BudgetMin={budget_min}&BudgetMax={budget_max}&City=Pune&Locality={area_slug}&proptype=Multistorey-Apartment,Builder-Floor-Apartment,Penthouse,Studio-Apartment"
    if ftype:
        url += f"&FurnishedStatus={ftype}"
    return url


def parse_listing_card(card_soup) -> dict:
    listing = empty_listing()
    listing["platform"] = "magicbricks"
    try:
        title_el = card_soup.select_one("h2, h3, [class*='mb-srp__card--title'], [class*='title']")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)

        link = card_soup.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = BASE_URL + href
            listing["url"] = href
            listing["listing_id"] = href.rstrip("/").split("/")[-1]

        price_el = card_soup.select_one("[class*='mb-srp__card__price'], [class*='price']")
        if price_el:
            listing["price"] = extract_price(price_el.get_text())

        loc_el = card_soup.select_one("[class*='mb-srp__card__locality'], [class*='locality']")
        if loc_el:
            listing["area_name"] = loc_el.get_text(strip=True).split(",")[0]
            listing["address"] = loc_el.get_text(strip=True)

        for el in card_soup.find_all(["span", "div"]):
            furn = normalize_furnishing(el.get_text(strip=True))
            if furn:
                listing["furnishing"] = furn
                break

        imgs = card_soup.select("img[src*='http'], img[data-src*='http']")
        image_urls = []
        for img in imgs:
            src = img.get("data-src") or img.get("src") or ""
            if src and "placeholder" not in src and "logo" not in src and src.startswith("http"):
                image_urls.append(src)
        listing["images"] = list(dict.fromkeys(image_urls))

    except Exception:
        pass
    return listing


class MagicBricksScraper(BaseScraper):

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        listings = []

        with self as scraper:
            for page_num in range(1, max_pages + 1):
                url = build_search_url(prefs)
                if page_num > 1:
                    url += f"&page={page_num}"

                ctx, page = scraper.new_page()
                try:
                    print(f"  [magicbricks] Page {page_num}: {url[:80]}...")
                    page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    scraper.random_delay(2.5, 5.0)

                    for _ in range(4):
                        page.evaluate("window.scrollBy(0, 600)")
                        scraper.random_delay(0.4, 0.8)

                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    cards = (
                        soup.select("div.mb-srp__card") or
                        soup.select("div[class*='PropertyCard']") or
                        soup.select("div[class*='listing']")
                    )

                    if not cards:
                        print(f"  [magicbricks] No cards on page {page_num}")
                        break

                    print(f"  [magicbricks] Found {len(cards)} listings")
                    for card in cards:
                        l = parse_listing_card(card)
                        l["city"] = "Pune"
                        if l["listing_id"]:
                            listings.append(l)

                except Exception as e:
                    print(f"  [magicbricks] Error page {page_num}: {e}")
                finally:
                    ctx.close()

                if page_num < max_pages:
                    scraper.random_delay(4.0, 7.0)

        return listings


if __name__ == "__main__":
    prefs = {"areas": ["Kothrud"], "budget_min": 10000, "budget_max": 25000, "furnishing": "any"}
    s = MagicBricksScraper(headless=True)
    listings = s.scrape(prefs, max_pages=1)
    print(f"MagicBricks: {len(listings)} listings")
