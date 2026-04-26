"""
Camoufox Browser Scraper
------------------------
Replaces apify_browser.py. Uses Camoufox (modified Firefox with stealth patches)
to bypass Cloudflare/Akamai bot protection on all 5 real estate sites.

Why Camoufox works where requests fails:
  - Real Firefox browser (not a fake UA string)
  - Solves Cloudflare JS challenges automatically
  - Mimics human fingerprints (canvas, fonts, screen size, WebGL)
  - Runs on Python 3.11+ Linux (GitHub Actions) and Python 3.14+ Windows

Two entry points:
  scrape_all_with_camoufox(prefs)  — called by orchestrator for one area on demand
  run_batch_scrape()               — called by GitHub Actions for all 20 areas

Run standalone (GitHub Actions):
    python agents/scrapers/camoufox_scraper.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import asyncio
import concurrent.futures
import re
import time
import random
import uuid

from bs4 import BeautifulSoup
from agents.scrapers.base import (
    empty_listing, extract_price, normalize_furnishing, save_listings,
    CARD_SELECTORS,
)

# ── All Pune areas for GitHub Actions batch run ───────────────────────────────
from agents.pune_areas import ALL_PUNE_AREAS, TOP_AREAS
TOP_20_AREAS = ALL_PUNE_AREAS   # full list — batch scrapes all ~60 localities

# GitHub Actions batch budget range (broad — covers all listings)
BATCH_BUDGET_MIN = 5_000
BATCH_BUDGET_MAX = 1_20_000

# Browser timing constants (ms)
PAGE_TIMEOUT_MS   = 50_000   # max time to wait for page navigation
POST_LOAD_WAIT_MS = 4_000    # wait after DOMContentLoaded for JS to render
SCROLL_PAUSE_MS   = 900      # pause between each scroll step

# Per-site selectors to wait for before extracting HTML
# (ensures the page has actually loaded listings, not just the shell)
_WAIT_SELECTORS = {
    "nobroker":    ".package-detail, [class*='PropertyCard'], [class*='srp-property']",
    "99acres":     "[class*='srpCard'], [class*='propertyCard'], [class*='listingCard']",
    "magicbricks": "[class*='mb-srp__card'], [class*='PropertyCard']",
    "housing":     "[class*='srpCard'], article[class*='prop'], [class*='listing']",
    "squareyards": "[class*='PropertyCard'], [class*='property-card'], [class*='propCard']",
}

# Longer wait for NoBroker (heavy React app, slow hydration)
_EXTRA_WAIT_MS = {
    "nobroker": 6_000,
    "99acres":  4_000,
}

_PRICE_RE = re.compile(
    r"(?:Rs\.?|INR|[\u20b9])?\s*(\d[\d,]+)\s*(?:/\s*(?:mo|month|pm))?", re.I
)


# ── URL builders ──────────────────────────────────────────────────────────────
def _slug(area: str) -> str:
    return area.lower().replace(" ", "-")


def _build_urls(area: str, lo: int, hi: int) -> list[dict]:
    """Return list of {url, platform} dicts for one area across all 5 sites."""
    s = _slug(area)
    return [
        {
            "platform": "nobroker",
            "url": f"https://www.nobroker.in/property/residential/rent/pune/{s}?budget={lo},{hi}",
        },
        {
            "platform": "99acres",
            "url": f"https://www.99acres.com/property-for-rent-in-{s}-pune-ffid",
        },
        {
            "platform": "housing",
            "url": f"https://housing.com/in/rent/flats-in-{s}-pune",
        },
        {
            "platform": "magicbricks",
            "url": (
                f"https://www.magicbricks.com/property-for-rent/residential-real-estate"
                f"?BudgetMin={lo}&BudgetMax={hi}&City=Pune&Locality={area.title()}"
                f"&proptype=Multistorey-Apartment,Builder-Floor-Apartment,"
                f"Penthouse,Studio-Apartment"
            ),
        },
        {
            "platform": "squareyards",
            "url": (
                f"https://www.squareyards.com/pune/{s}-property-for-rent"
                f"?minBudget={lo}&maxBudget={hi}"
            ),
        },
    ]


# ── Core scraper: one URL → list of listing dicts ────────────────────────────
async def _scrape_url_async(url: str, platform: str) -> list[dict]:
    """Async Camoufox scrape of a single URL. Uses async API to avoid event-loop conflicts."""
    from camoufox.async_api import AsyncCamoufox

    print(f"  [camoufox] {platform}: {url[:70]}...")
    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")

        extra_wait = _EXTRA_WAIT_MS.get(platform, POST_LOAD_WAIT_MS)
        await page.wait_for_timeout(extra_wait)

        if platform in _WAIT_SELECTORS:
            try:
                await page.wait_for_selector(_WAIT_SELECTORS[platform], timeout=15_000)
            except Exception:
                pass

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)
        await page.wait_for_timeout(800)

        html = await page.content()

    listings = _parse_html(html, platform, url)
    print(f"  [camoufox] {platform}: {len(listings)} listings extracted")
    return listings


def _scrape_url(url: str, platform: str) -> list[dict]:
    """
    Open one URL in a fresh Camoufox browser, extract listing cards, close browser.
    Returns raw listing dicts in standard format.

    Runs the async scrape inside a dedicated ThreadPoolExecutor thread so that
    asyncio.run() always gets a clean event-loop state, regardless of whatever
    asyncio machinery GitHub Actions (or any other host) has left running in the
    main thread.  This is the only approach that is 100% safe on all platforms.
    """
    # Guard: skip live browser on Python 3.14 Windows (use cache instead)
    if sys.version_info >= (3, 14) and sys.platform == "win32":
        print(f"  [camoufox] Skipping live scrape on Python 3.14/Windows ({platform}). Use cache.")
        return []

    try:
        from camoufox.async_api import AsyncCamoufox  # noqa: F401
    except ImportError:
        print("  [camoufox] Not installed. Run: pip install 'camoufox[geoip]' && python -m camoufox fetch")
        return []

    def _run():
        return asyncio.run(_scrape_url_async(url, platform))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run).result(timeout=120)
    except concurrent.futures.TimeoutError:
        print(f"  [camoufox] {platform}: timed out after 120s")
        return []
    except Exception as e:
        print(f"  [camoufox] {platform} error: {e}")
        return []


# ── HTML parser: delegates to existing per-site parse_listing_card functions ──
def _parse_html(html: str, platform: str, source_url: str) -> list[dict]:
    """
    Parse full-page HTML into listing dicts.
    Strategy 1: Try 20 known CSS selector patterns from base.CARD_SELECTORS
    Strategy 2: Price-element DOM walk (finds cards by ₹ symbol proximity)
    Then delegates to per-site parse_listing_card() for structured extraction.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # ── Strategy 1: CSS selector patterns ────────────────────────────────────
    cards = []
    for sel in CARD_SELECTORS:
        found = soup.select(sel)
        if len(found) > 1:
            cards = found
            break

    # ── Strategy 2: price-element detection fallback ─────────────────────────
    if not cards:
        price_nodes = [
            el for el in soup.find_all(True)
            if not el.find_all(True, recursive=False)   # leaf nodes only
            and re.search(r"[₹Rs\.\s]{0,4}\s*\d[\d,]{2,}", el.get_text())
            and len(el.get_text(strip=True)) < 60
        ]
        seen = set()
        for pn in price_nodes[:40]:
            node = pn.parent
            for _ in range(10):
                if node is None or node.name == "body":
                    break
                if node.find("img") and node.find("a", href=True):
                    nid = id(node)
                    if nid not in seen:
                        seen.add(nid)
                        cards.append(node)
                    break
                node = node.parent

    if not cards:
        return []

    # ── Delegate to per-site parsers ──────────────────────────────────────────
    parsers = _get_parsers()
    parse_fn = parsers.get(platform)

    from agents.scrapers.base import _is_valid_listing_id

    # Diagnostic: report how many cards the CSS selectors matched
    print(f"  [camoufox] {platform}: {len(cards)} cards matched in HTML (len={len(html)})")
    if cards:
        sample_link = cards[0].find("a", href=True)
        sample_href = sample_link.get("href", "none")[:80] if sample_link else "no-link"
        print(f"  [camoufox] {platform}: first card link = {sample_href}")

    listings = []
    for card in cards[:30]:
        # Try data-attribute IDs first — these are the most reliable source
        data_id = ""
        for attr in ("data-listing-id", "data-property-id", "data-propid", "data-id"):
            val = card.get(attr, "")
            if val and any(c.isdigit() for c in str(val)):
                data_id = str(val)[:64]
                break

        if parse_fn:
            l = parse_fn(card)
            l["city"] = "Pune"
            # Override with data-attribute ID if the parser's URL-based ID looks generic
            if data_id and not _is_valid_listing_id(l.get("listing_id", "")):
                l["listing_id"] = data_id
            # URL-based fallback if parser still has no valid ID
            if not _is_valid_listing_id(l.get("listing_id", "")):
                link = card.find("a", href=True)
                if link:
                    href = link["href"]
                    if href.startswith("/"):
                        base = "/".join(source_url.split("/")[:3])
                        href = base + href
                    l["url"] = l["url"] or href
                    l["listing_id"] = href.rstrip("/").split("/")[-1]
        else:
            l = _generic_extract(card, platform, source_url)
            if data_id and not _is_valid_listing_id(l.get("listing_id", "")):
                l["listing_id"] = data_id

        if l and (l.get("listing_id") or l.get("url")):
            listings.append(l)

    # Diagnostic: show sample listing IDs extracted
    if listings:
        sample_ids = [f"{l.get('platform')}:{l.get('listing_id','?')}" for l in listings[:3]]
        print(f"  [camoufox] {platform}: sample IDs = {sample_ids}")

    return listings


def _get_parsers() -> dict:
    """Lazy-import per-site parse_listing_card functions from existing scrapers."""
    try:
        from agents.scrapers.nobroker        import parse_listing_card as nb
        from agents.scrapers.ninetynineacres import parse_listing_card as nna
        from agents.scrapers.housing         import parse_listing_card as hsg
        from agents.scrapers.magicbricks     import parse_listing_card as mb
        from agents.scrapers.squareyards     import parse_listing_card as sy
        return {
            "nobroker":    nb,
            "99acres":     nna,
            "housing":     hsg,
            "magicbricks": mb,
            "squareyards": sy,
        }
    except Exception as e:
        print(f"  [camoufox] Could not import site parsers: {e}")
        return {}


def _generic_extract(card, platform: str, source_url: str) -> dict:
    """Generic fallback extraction for when a per-site parser isn't available."""
    l = empty_listing()
    l["platform"] = platform

    link = card.find("a", href=True)
    if link:
        href = link["href"]
        if href.startswith("/"):
            base = "/".join(source_url.split("/")[:3])
            href = base + href
        l["url"] = href
        l["listing_id"] = href.rstrip("/").split("/")[-1]

    for sel in ["[class*='price']", "[class*='Price']", "[class*='rent']"]:
        el = card.select_one(sel)
        if el:
            l["price"] = extract_price(el.get_text())
            break

    for sel in ["h2", "h3", "[class*='title']", "[class*='bhk']"]:
        el = card.select_one(sel)
        if el:
            l["title"] = el.get_text(strip=True)
            break

    for sel in ["[class*='locality']", "[class*='location']", "[class*='address']"]:
        el = card.select_one(sel)
        if el:
            txt = el.get_text(strip=True)
            l["area_name"] = txt.split(",")[0]
            l["address"] = txt
            break

    l["furnishing"] = normalize_furnishing(card.get_text())

    imgs = []
    for img in card.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy") or img.get("src") or ""
        if src.startswith("http") and not re.search(
            r"logo|placeholder|default|icon|banner|sprite|noimg|blank", src, re.I
        ):
            imgs.append(src)
    l["images"] = list(dict.fromkeys(imgs))
    return l


# ── Public API: on-demand scrape for orchestrator ─────────────────────────────
def scrape_all_with_camoufox(prefs: dict, max_pages: int = 1) -> list[dict]:
    """
    Signature matches scrape_all_with_apify(prefs, max_pages).
    Scrapes all 5 sites for the first area in prefs using Camoufox.

    NOTE: On Python 3.14 / Windows, this returns [] immediately — the
    orchestrator's cache-first logic means this is only called when the
    Supabase cache is empty, and GitHub Actions will replenish it.
    """
    areas = prefs.get("areas", ["Kothrud"])
    area  = areas[0] if areas else "Kothrud"
    lo    = prefs.get("budget_min", 5_000)
    hi    = prefs.get("budget_max", 1_20_000)

    print(f"\n  [camoufox] Live scrape: {area} (Rs.{lo}-{hi}) across 5 sites...")
    url_list = _build_urls(area, lo, hi)

    all_listings: list[dict] = []
    for item in url_list:
        listings = _scrape_url(item["url"], item["platform"])
        for l in listings:
            l["city"] = "Pune"
        all_listings.extend(listings)
        # Polite delay between sites (avoids triggering rate limits)
        time.sleep(random.uniform(2.5, 4.5))

    print(f"  [camoufox] On-demand total: {len(all_listings)} listings")
    return all_listings


# ── Batch entry point for GitHub Actions ─────────────────────────────────────
def run_batch_scrape():
    """
    Scrapes TOP_20_AREAS × 5 sites and saves everything to Supabase.
    Called from GitHub Actions: python agents/scrapers/camoufox_scraper.py

    Strategy:
      1. If APIFY_KEY is set → use Apify (residential proxies, real Chromium, cloud)
         This is the ONLY approach that reliably bypasses Cloudflare/Akamai on all 5 sites.
      2. Otherwise → fall back to local Camoufox (works for testing; sites will bot-block it)
    """
    from dotenv import load_dotenv
    load_dotenv()

    apify_key = os.environ.get("APIFY_KEY") or os.environ.get("APIFY_API_TOKEN", "")

    if apify_key:
        _batch_with_apify()
    else:
        print("[batch] No APIFY_KEY — using per-site scrapers with cloudscraper fallback")
        _batch_with_site_scrapers()


def _batch_with_apify():
    """Run all 20 areas × 5 sites in ONE Apify actor call."""
    from agents.scrapers.apify_browser import scrape_batch_with_apify
    from agents.scrapers.base import save_listings

    print(f"[batch] Apify batch scrape: {len(TOP_20_AREAS)} areas × 5 sites")
    print(f"[batch] Budget range: Rs.{BATCH_BUDGET_MIN} - Rs.{BATCH_BUDGET_MAX}")

    listings = scrape_batch_with_apify(TOP_20_AREAS, BATCH_BUDGET_MIN, BATCH_BUDGET_MAX)

    total_saved = 0
    if listings:
        by_plat = {}
        for l in listings:
            p = l.get("platform", "?")
            by_plat[p] = by_plat.get(p, 0) + 1
        print(f"[batch] By platform: {dict(sorted(by_plat.items()))}")
        saved = save_listings(listings)
        total_saved += saved
        print(f"[batch] {saved} rows written to Supabase")
    else:
        print("[batch] Apify returned 0 listings")

    # Facebook (runs once regardless)
    _batch_facebook(total_saved)


def _batch_with_camoufox():
    """Local Camoufox fallback — area by area (slow, likely bot-blocked on live sites)."""
    from agents.scrapers.base import save_listings

    print(f"[batch] Camoufox batch scrape: {len(TOP_20_AREAS)} areas × 5 sites")
    print(f"[batch] Budget range: Rs.{BATCH_BUDGET_MIN} - Rs.{BATCH_BUDGET_MAX}")

    total_saved = 0
    for i, area in enumerate(TOP_20_AREAS, 1):
        print(f"\n[batch] ── Area {i}/{len(TOP_20_AREAS)}: {area} ──")
        url_list = _build_urls(area, BATCH_BUDGET_MIN, BATCH_BUDGET_MAX)
        area_listings = []

        for item in url_list:
            listings = _scrape_url(item["url"], item["platform"])
            for l in listings:
                l["city"] = "Pune"
            area_listings.extend(listings)
            time.sleep(random.uniform(3.0, 6.0))

        if area_listings:
            by_plat = {}
            for l in area_listings:
                p = l.get("platform", "?")
                by_plat[p] = by_plat.get(p, 0) + 1
            print(f"  [batch] {area}: {len(area_listings)} scraped {dict(sorted(by_plat.items()))}")
            sample = [(l.get("platform"), l.get("listing_id"), l.get("price")) for l in area_listings[:5]]
            print(f"  [batch] {area}: sample = {sample}")
            saved = save_listings(area_listings)
            total_saved += saved
            print(f"  [batch] {area}: {saved} rows written to Supabase")
        else:
            print(f"  [batch] {area}: 0 listings (all sites blocked or no cards)")

        if i < len(TOP_20_AREAS):
            delay = random.uniform(8.0, 15.0)
            print(f"  [batch] Waiting {delay:.1f}s before next area...")
            time.sleep(delay)

    _batch_facebook(total_saved)


def _batch_with_site_scrapers():
    """
    Use per-site scrapers directly — one area at a time.
    NoBroker: internal JSON API (no bot detection).
    99acres, MagicBricks, SquareYards: curl_cffi / requests with Sec-Fetch headers.
    Housing.com: Camoufox real browser (Cloudflare blocks all HTTP-only approaches).
    Works without Apify.
    """
    from agents.scrapers.base import save_listings
    from agents.scrapers.nobroker_api  import NoBrokerApiScraper   # direct JSON API
    from agents.scrapers.magicbricks   import MagicBricksScraper
    from agents.scrapers.squareyards   import SquareYardsScraper
    # 99acres + Housing.com excluded — SSR renders 1 card max; handled via Camoufox below

    scrapers = [
        NoBrokerApiScraper(),
        MagicBricksScraper(),
        SquareYardsScraper(),
    ]

    print(f"[batch] Batch scrape: {len(TOP_20_AREAS)} areas × {len(scrapers) + 2} sites")
    print(f"[batch] Budget range: Rs.{BATCH_BUDGET_MIN} - Rs.{BATCH_BUDGET_MAX}")

    total_saved = 0
    for i, area in enumerate(TOP_20_AREAS, 1):
        print(f"\n[batch] ── Area {i}/{len(TOP_20_AREAS)}: {area} ──")
        prefs = {
            "areas":      [area],
            "budget_min": BATCH_BUDGET_MIN,
            "budget_max": BATCH_BUDGET_MAX,
            "furnishing": "any",
            "city":       "Pune",
        }
        area_listings = []

        for scraper in scrapers:
            name = scraper.__class__.__name__.replace("Scraper", "").lower()
            try:
                listings = scraper.scrape(prefs, max_pages=2)
                print(f"  [batch] {name}: {len(listings)} listings")
                area_listings.extend(listings)
            except Exception as e:
                print(f"  [batch] {name}: error — {e}")
            time.sleep(random.uniform(1.5, 3.0))

        # 99acres via Camoufox (SSR renders 1 card; needs real browser for full JS)
        try:
            acres_url = f"https://www.99acres.com/property-for-rent-in-{_slug(area)}-pune-ffid"
            acres_listings = _scrape_url(acres_url, "99acres")
            for l in acres_listings:
                l["city"] = "Pune"
            area_listings.extend(acres_listings)
            print(f"  [batch] 99acres: {len(acres_listings)} listings (camoufox)")
        except Exception as e:
            print(f"  [batch] 99acres: error — {e}")

        # Housing.com: BLOCKED — returns HTTP 406 "Security Alert" on all approaches
        # (Camoufox, curl_cffi Chrome impersonation, plain requests all blocked).
        # Requires residential proxy (Apify) to bypass. Skipped to save ~20min/run.
        # TODO: re-enable when APIFY_KEY available and route Housing.com through Apify.

        if area_listings:
            by_plat = {}
            for l in area_listings:
                p = l.get("platform", "?")
                by_plat[p] = by_plat.get(p, 0) + 1
            print(f"  [batch] {area}: {len(area_listings)} total {dict(sorted(by_plat.items()))}")
            saved = save_listings(area_listings)
            total_saved += saved
            print(f"  [batch] {area}: {saved} rows → Supabase")
        else:
            print(f"  [batch] {area}: 0 listings")

        if i < len(TOP_20_AREAS):
            delay = random.uniform(5.0, 10.0)
            print(f"  [batch] Waiting {delay:.1f}s...")
            time.sleep(delay)

    _batch_facebook(total_saved)


def _batch_facebook(total_saved: int):
    """Run Facebook scraper once and print final total."""
    from agents.scrapers.base import save_listings

    print(f"\n[batch] ── Facebook Marketplace + Groups ──")
    try:
        from agents.scrapers.facebook_agent import scrape_facebook
        fb_prefs = {"budget_min": BATCH_BUDGET_MIN, "budget_max": BATCH_BUDGET_MAX}
        fb_listings = scrape_facebook(fb_prefs)
        if fb_listings:
            saved = save_listings(fb_listings)
            total_saved += saved
            print(f"  [batch] Facebook: {len(fb_listings)} scraped, {saved} new → Supabase")
    except Exception as e:
        print(f"  [batch] Facebook error: {e}")

    print(f"\n[batch] COMPLETE. Total new listings saved: {total_saved}")


if __name__ == "__main__":
    run_batch_scrape()
