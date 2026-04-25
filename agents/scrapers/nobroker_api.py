"""
NoBroker Internal API Scraper
------------------------------
Calls NoBroker's internal JSON REST API directly — no browser, no Playwright,
no Apify needed. Works because the API returns JSON with standard HTTP headers;
Cloudflare/bot-detection only blocks HTML page requests.

API endpoint:
    GET https://www.nobroker.in/api/v3/multi/property/RENT/filter
    Params: latitude, longitude, radius, city, pageSize, pageNo, budgetMin, budgetMax

Run standalone:
    python agents/scrapers/nobroker_api.py
"""

import sys
import os
import time
import random
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.scrapers.base import (
    empty_listing,
    normalize_furnishing,
    save_listings,
)

# ---------------------------------------------------------------------------
# Geocoding — resolves any area name → (lat, lng) via OpenStreetMap Nominatim.
# Free, no API key required. Results cached in-process.
# ---------------------------------------------------------------------------
_GEOCODE_CACHE: dict[str, tuple[float, float] | None] = {}


def geocode_area(area: str, city: str = "Pune") -> tuple[float, float] | None:
    """
    Return (lat, lng) for `area, city`. Checks hardcoded AREA_COORDS first;
    falls back to Nominatim (OpenStreetMap) for unknown areas.
    Returns None if geocoding fails.
    """
    key = f"{area}|{city}".lower()
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]

    # Check hardcoded dict (populated below after AREA_COORDS is defined)
    coords = AREA_COORDS.get(area)
    if coords:
        _GEOCODE_CACHE[key] = coords
        return coords

    # Google Maps Geocoding API (primary — uses GOOGLE_MAPS_KEY from .env)
    gmaps_key = os.getenv("GOOGLE_MAPS_KEY")
    if gmaps_key:
        try:
            query = f"{area}, {city}, Maharashtra, India"
            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": gmaps_key},
                timeout=10,
            )
            data = r.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                lat, lng = loc["lat"], loc["lng"]
                print(f"  [geocode] {area} = ({lat:.4f}, {lng:.4f}) via Google Maps")
                _GEOCODE_CACHE[key] = (lat, lng)
                return (lat, lng)
        except Exception as e:
            print(f"  [geocode] Google Maps failed for '{area}': {e}")

    # Nominatim fallback (free, no key needed)
    try:
        query = f"{area}, {city}, Maharashtra, India"
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "bon-homie-flat-finder/1.0 (educational project)"},
            timeout=10,
        )
        if r.status_code == 200:
            results = r.json()
            if results:
                lat = float(results[0]["lat"])
                lng = float(results[0]["lon"])
                print(f"  [geocode] {area} = ({lat:.4f}, {lng:.4f}) via Nominatim")
                _GEOCODE_CACHE[key] = (lat, lng)
                return (lat, lng)
    except Exception as e:
        print(f"  [geocode] Nominatim failed for '{area}': {e}")

    _GEOCODE_CACHE[key] = None
    return None

BASE_URL = "https://www.nobroker.in"
API_URL = f"{BASE_URL}/api/v3/multi/property/RENT/filter"
ASSETS_URL = "https://assets.nobroker.in/images"

# Import comprehensive coords from shared module
from agents.pune_areas import AREA_COORDS

PAGE_SIZE = 20        # items per page (NoBroker API max)
SEARCH_RADIUS = 4500  # metres — wider radius catches more listings
MAX_PAGES = 10        # cap: 200 results/area max (uses total_count to stop early)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": BASE_URL + "/",
    "Origin": BASE_URL,
}

_FURNISH_MAP = {
    "FULLY_FURNISHED":  "furnished",
    "SEMI_FURNISHED":   "semi-furnished",
    "SEMI FURNISHED":   "semi-furnished",
    "UN_FURNISHED":     "unfurnished",
    "UNFURNISHED":      "unfurnished",
    "NOT_FURNISHED":    "unfurnished",
}


def _parse_item(item: dict, area_name: str) -> dict:
    listing = empty_listing()
    listing["platform"] = "nobroker"
    listing["city"] = "Pune"
    listing["brokerage"] = False  # NoBroker is always zero-brokerage

    # ID
    listing["listing_id"] = str(item.get("id", ""))[:64]

    # Title
    listing["title"] = item.get("title") or item.get("typeDesc") or ""

    # Price — API gives integer rent in Rs
    rent = item.get("rent")
    if rent:
        try:
            listing["price"] = int(rent)
        except (ValueError, TypeError):
            pass

    # URL
    detail = item.get("detailUrl", "")
    if detail:
        listing["url"] = BASE_URL + detail if detail.startswith("/") else detail
    else:
        listing["url"] = item.get("shortUrl", "")

    # Location
    listing["area_name"] = item.get("locality") or area_name
    listing["address"] = item.get("address") or item.get("completeStreetName") or ""

    # Furnishing
    raw_furn = item.get("furnishing") or item.get("furnishingDesc") or ""
    listing["furnishing"] = (
        _FURNISH_MAP.get(raw_furn.upper().replace(" ", "_"))
        or normalize_furnishing(raw_furn)
        or None
    )

    # Images — photos list, each has imagesMap.thumbnail / imagesMap.original
    prop_id = item.get("id", "")
    image_urls = []
    for photo in item.get("photos", []):
        img_map = photo.get("imagesMap", {})
        fname = img_map.get("original") or img_map.get("thumbnail") or ""
        if fname and prop_id:
            image_urls.append(f"{ASSETS_URL}/{prop_id}/{fname}")
    # Fallback: thumbnailImage already a full URL
    if not image_urls and item.get("thumbnailImage"):
        image_urls.append(item["thumbnailImage"])
    listing["images"] = list(dict.fromkeys(image_urls))

    # Extra fields
    listing["latitude"] = item.get("latitude")
    listing["longitude"] = item.get("longitude")

    return listing


def scrape_area(
    area: str,
    budget_min: int = 5000,
    budget_max: int = 120000,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """Fetch all NoBroker listings for one area via internal API."""
    coords = geocode_area(area)
    if not coords:
        print(f"  [nobroker_api] Could not geocode '{area}', skipping.")
        return []

    lat, lng = coords
    listings = []
    session = requests.Session()
    session.headers.update(_HEADERS)

    for page in range(1, max_pages + 1):
        params = {
            "latitude":  lat,
            "longitude": lng,
            "radius":    SEARCH_RADIUS,
            "city":      "pune",
            "pageSize":  PAGE_SIZE,
            "pageNo":    page,
        }
        try:
            r = session.get(API_URL, params=params, timeout=20)
            if r.status_code != 200:
                print(f"  [nobroker_api] {area} page {page}: HTTP {r.status_code}")
                break

            data = r.json()
            items = data.get("data", [])
            if not items:
                break  # no more results

            print(f"  [nobroker_api] {area} page {page}: {len(items)} listings")

            for item in items:
                rent = item.get("rent")
                # Client-side budget filter (API filter param unreliable)
                if rent:
                    try:
                        rent_int = int(rent)
                        if rent_int < budget_min or rent_int > budget_max:
                            continue
                    except (ValueError, TypeError):
                        pass

                listing = _parse_item(item, area)
                if listing["listing_id"] and listing["price"]:
                    listings.append(listing)

            # Check if there are more pages
            other = data.get("otherParams", {})
            total = other.get("total_count", 0)
            fetched = page * PAGE_SIZE
            if fetched >= total:
                break

        except Exception as e:
            print(f"  [nobroker_api] {area} page {page}: ERROR {e}")
            break

        if page < max_pages:
            time.sleep(random.uniform(0.8, 1.8))

    print(f"  [nobroker_api] {area}: {len(listings)} listings in budget range")
    return listings


class NoBrokerApiScraper:
    """Drop-in replacement for NoBrokerScraper using internal JSON API."""

    def scrape(self, prefs: dict, max_pages: int = MAX_PAGES) -> list[dict]:
        areas = prefs.get("areas", [])
        budget_min = prefs.get("budget_min", 5000)
        budget_max = prefs.get("budget_max", 120000)

        all_listings = []
        for area in areas:
            listings = scrape_area(area, budget_min, budget_max, max_pages)
            all_listings.extend(listings)
        return all_listings


if __name__ == "__main__":
    # Quick smoke test — single area
    test_area = "Baner"
    prefs = {
        "areas": [test_area],
        "budget_min": 8000,
        "budget_max": 35000,
    }
    scraper = NoBrokerApiScraper()
    results = scraper.scrape(prefs, max_pages=2)
    print(f"\nNoBroker API: {len(results)} listings from {test_area}")
    for r in results[:3]:
        print(f"  [{r['listing_id'][:12]}] Rs.{r['price']:,} | {r['title'][:60]} | {len(r['images'])} imgs")

    if results:
        saved = save_listings(results)
        print(f"Saved {saved} to Supabase")
