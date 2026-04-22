"""
Base Scraper
------------
Two scraper bases are provided:

  RequestsScraper  — uses requests + BeautifulSoup.
                     No browser needed. Works on Python 3.14+ / Windows.
                     ALL current scrapers inherit this.

  BaseScraper      — uses Playwright sync API (kept for future use).
                     Only used if Playwright is correctly installed.

Helper functions (empty_listing, extract_price, etc.) are shared.
"""

import hashlib
import random
import re
import time
import uuid
import requests
from typing import Optional


# ── Standard listing schema ───────────────────────────────────────────────────
def empty_listing() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "platform": "",
        "listing_id": "",
        "url": "",
        "title": "",
        "price": None,           # int, monthly rent in INR
        "area_name": "",
        "address": "",
        "city": "Pune",
        "furnishing": None,      # 'furnished' | 'semi-furnished' | 'unfurnished'
        "renter_type": None,     # 'family' | 'bachelor'
        "gender": None,          # 'male' | 'female'
        "occupancy": None,       # 'single' | 'double'
        "brokerage": None,       # True | False
        "images": [],            # list of image URLs
        "contact_raw": "",
        "contact": "",
        "lat": None,
        "lng": None,
    }


# ── User agents (rotated per request) ────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

# ── Card CSS selectors shared across scrapers ────────────────────────────────
# Used by both camoufox_scraper.py (Strategy 1) and individual BeautifulSoup scrapers.
CARD_SELECTORS = [
    ".package-detail",                 # NoBroker
    "[class*='PropertyCard']",
    "[class*='propertyCard']",
    "[class*='property-card']",
    "[class*='property_card']",
    "[class*='srpCard']",
    "[class*='SrpCard']",
    "[class*='srp-card']",
    "[class*='mb-srp__card']",         # MagicBricks
    "[class*='listing-card']",
    "[class*='listingCard']",
    "[class*='Listing_card']",
    "[class*='prop-card']",
    "[class*='propCard']",
    "[class*='result-card']",
    "[class*='resultCard']",
    "li[class*='property']",
    "article[class*='prop']",
    "[data-listing-id]",
    "[data-property-id]",
    "[data-id][class*='prop']",
]

# Browser-like headers sent with every request
_HEADERS_BASE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
    "DNT": "1",
}


# ── Phone number normalizer ───────────────────────────────────────────────────
_PHONE_RE = re.compile(r"(?:\+91|0)?([6-9]\d{9})")

def normalize_phone(raw: str) -> str:
    """Extract and normalize an Indian mobile number to +91XXXXXXXXXX."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    m = _PHONE_RE.search(digits)
    if m:
        return "+91" + m.group(1)
    return ""


# ── Furnishing normalizer ─────────────────────────────────────────────────────
def normalize_furnishing(text: str) -> Optional[str]:
    t = text.lower()
    if "semi" in t:
        return "semi-furnished"
    if "unfurnish" in t or "un-furnish" in t:
        return "unfurnished"
    if "furnish" in t:
        return "furnished"
    return None


# ── Price extractor ───────────────────────────────────────────────────────────
def extract_price(text: str) -> Optional[int]:
    """
    Extract integer rent from price strings.
    Handles: '12,500/month', 'Rs.12500', '1.5 L', '2.7 Lakh', '₹48,000'.
    Returns None if outside plausible rent range (1k – 10L).
    """
    t = text.strip()
    # Lakh notation: "1.5 L", "2.7 Lakh", "1.5L/month"
    lakh_m = re.search(r'(\d+\.?\d*)\s*[Ll](?:akh|ac)?\b', t)
    if lakh_m:
        val = int(round(float(lakh_m.group(1)) * 100_000))
        if 1_000 <= val <= 10_00_000:
            return val
    # Cr notation (skip — crore rents are not residential)
    if re.search(r'\d\s*[Cc]r', t):
        return None
    # Plain digits (strip all non-digit chars)
    digits = re.sub(r"[^\d]", "", t)
    if digits:
        val = int(digits)
        if 1_000 <= val <= 10_00_000:
            return val
    return None


# ── Requests-based page fetcher ───────────────────────────────────────────────
def _do_get(session: requests.Session, url: str, headers: dict,
            retries: int, base_delay: float) -> str:
    """Internal helper: GET with retry/backoff. Returns HTML or ''."""
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=headers, timeout=30, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 403:
                wait = base_delay * (2 ** attempt)
                print(f"    [fetch] 403 on attempt {attempt + 1}. Waiting {wait:.0f}s...")
                time.sleep(wait)
            elif resp.status_code == 429:
                print(f"    [fetch] 429 rate-limited. Sleeping 30s...")
                time.sleep(30)
            else:
                print(f"    [fetch] HTTP {resp.status_code} on attempt {attempt + 1}: {url[:60]}")
                time.sleep(base_delay)
        except requests.exceptions.Timeout:
            print(f"    [fetch] Timeout on attempt {attempt + 1}: {url[:60]}")
            time.sleep(base_delay * (attempt + 1))
        except Exception as e:
            print(f"    [fetch] Error on attempt {attempt + 1}: {e}")
            time.sleep(base_delay)
    print(f"    [fetch] All {retries} attempts failed for: {url[:70]}")
    return ""


def fetch_with_requests(
    url: str,
    retries: int = 3,
    base_delay: float = 2.0,
    extra_headers: Optional[dict] = None,
) -> str:
    """
    Fetch a page's HTML using requests (no browser required).
    Rotates User-Agent, retries with backoff on 403/429/timeout.
    """
    headers = {**_HEADERS_BASE, "User-Agent": random.choice(USER_AGENTS)}
    if extra_headers:
        headers.update(extra_headers)
    return _do_get(requests.Session(), url, headers, retries, base_delay)


def fetch_with_session(
    base_url: str,
    search_url: str,
    retries: int = 3,
    base_delay: float = 2.0,
    extra_headers: Optional[dict] = None,
) -> str:
    """
    Two-step fetch with automatic cloudscraper fallback.
      1. Visit the site homepage first to collect cookies + session tokens.
      2. Fetch the actual search URL with those cookies + a Referer header.
      3. If that returns empty/blocked HTML, fall back to cloudscraper (handles CF JS challenges).
    """
    ua = random.choice(USER_AGENTS)
    headers = {**_HEADERS_BASE, "User-Agent": ua}
    if extra_headers:
        headers.update(extra_headers)

    session = requests.Session()

    # Step 1 — warm the session (homepage visit establishes cookies)
    try:
        session.get(base_url, headers=headers, timeout=15, allow_redirects=True)
        time.sleep(random.uniform(0.8, 1.8))
        headers["Referer"] = base_url
    except Exception as e:
        print(f"    [fetch] Session warm failed ({e}). Trying direct fetch...")

    # Step 2 — fetch the actual search page with warmed session
    result = _do_get(session, search_url, headers, retries, base_delay)

    # Step 3 — cloudscraper fallback (handles Cloudflare JS challenges)
    if not result:
        result = fetch_with_cloudscraper(search_url, base_url, extra_headers)

    return result


def fetch_with_cloudscraper(
    url: str,
    base_url: Optional[str] = None,
    extra_headers: Optional[dict] = None,
) -> str:
    """
    Fetch a page using cloudscraper, which solves Cloudflare JS challenges automatically.
    Falls back to empty string if cloudscraper is not installed or the request fails.
    Works for Cloudflare-protected sites (NoBroker, 99acres, MagicBricks, SquareYards).
    Does NOT work for Akamai-protected sites (Housing.com).
    """
    try:
        import cloudscraper
    except ImportError:
        print("    [cloudscraper] Not installed. Run: pip install cloudscraper")
        return ""

    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "linux", "mobile": False},
            delay=5,
        )
        headers = {**_HEADERS_BASE, "User-Agent": random.choice(USER_AGENTS)}
        if extra_headers:
            headers.update(extra_headers)
        scraper.headers.update(headers)

        if base_url:
            try:
                scraper.get(base_url, timeout=20)
                time.sleep(random.uniform(0.8, 1.5))
                scraper.headers.update({"Referer": base_url})
            except Exception:
                pass

        resp = scraper.get(url, timeout=30)
        if resp.status_code == 200:
            print(f"    [cloudscraper] OK: {url[:60]}")
            return resp.text
        print(f"    [cloudscraper] HTTP {resp.status_code}: {url[:60]}")
        return ""
    except Exception as e:
        print(f"    [cloudscraper] Error: {e}")
        return ""


# ── Requests-based scraper base class ────────────────────────────────────────
class RequestsScraper:
    """
    Base class for all scrapers.
    Uses requests + BeautifulSoup — no browser, no Playwright.
    Works on Python 3.14+ / Windows out of the box.

    Usage:
        scraper = MyScraper()
        listings = scraper.scrape(prefs, max_pages=2)
    """

    def __init__(self, headless: bool = True):
        # headless param accepted for API compatibility with orchestrator
        pass

    def random_delay(self, min_s: float = 1.5, max_s: float = 4.0):
        """Human-like delay between requests."""
        time.sleep(random.uniform(min_s, max_s))

    def scrape(self, prefs: dict, max_pages: int = 3) -> list[dict]:
        """Override in subclass. Return list of listing dicts."""
        raise NotImplementedError


# ── Playwright-based scraper base (optional) ──────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

    class BaseScraper:
        """
        Sync Playwright scraper. Requires a working Playwright installation.
        Use RequestsScraper (above) for everyday scraping on Python 3.14.
        """

        def __init__(self, headless: bool = True):
            self.headless = headless
            self._pw = None
            self._browser: Optional[Browser] = None

        def __enter__(self):
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            return self

        def __exit__(self, *args):
            try:
                if self._browser:
                    self._browser.close()
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

        def new_context(self) -> "BrowserContext":
            ua = random.choice(USER_AGENTS)
            ctx = self._browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return ctx

        def new_page(self) -> "tuple[BrowserContext, Page]":
            ctx = self.new_context()
            page = ctx.new_page()
            return ctx, page

        def random_delay(self, min_s: float = 2.0, max_s: float = 5.0):
            time.sleep(random.uniform(min_s, max_s))

        def scrape(self, prefs: dict) -> list[dict]:
            raise NotImplementedError

except ImportError:
    # Playwright not installed — BaseScraper falls back to RequestsScraper
    class BaseScraper(RequestsScraper):  # type: ignore
        """Playwright unavailable — BaseScraper delegates to RequestsScraper."""
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass


# ── Supabase persistence ──────────────────────────────────────────────────────

# Exact columns that exist in the Supabase `listings` table.
# Any extra keys on listing dicts (e.g. "source", "id") are silently stripped
# before the upsert so schema-mismatches never kill a whole scrape run.
_SAVE_COLUMNS = {
    "platform", "listing_id", "url", "title", "price", "area_name", "address",
    "city", "furnishing", "renter_type", "gender", "occupancy", "brokerage",
    "images", "contact_raw", "contact", "lat", "lng", "last_scraped_at",
}

# Generic URL slugs that are NOT property-specific IDs.
# These appear as the last URL segment on search/category pages.
_GENERIC_SLUGS = {
    "pune", "rent", "residential", "property", "flats", "apartment",
    "residential-real-estate", "search", "index", "listing", "results",
}


def _is_valid_listing_id(lid: str) -> bool:
    """Real property IDs always contain digits (e.g. '12345678', 'prop-9876543-baner').
    Generic search-page slugs like 'flats-in-kothrud-pune' or 'pune' are not valid."""
    if not lid or len(lid) < 4:
        return False
    if lid.lower() in _GENERIC_SLUGS:
        return False
    return any(c.isdigit() for c in lid)


def _content_hash_id(row: dict) -> str:
    """Stable 16-char hex ID derived from listing content (platform+title+price+area).
    Used as last-resort fallback when no URL-based property ID is available."""
    parts = "|".join([
        str(row.get("platform", "")),
        str(row.get("title", "")),
        str(row.get("price", "")),
        str(row.get("area_name", "")),
    ])
    return hashlib.md5(parts.encode()).hexdigest()[:16]


def save_listings(listings: list[dict]) -> int:
    """
    Upsert listings to Supabase one row at a time.

    listing_id validation order:
      1. Use the scraper-supplied listing_id if it passes _is_valid_listing_id()
      2. Try the last URL path segment
      3. Fall back to a content-hash of (platform, title, price, area_name)
      4. Skip the row if we still have nothing (no price AND no title)

    This prevents generic slugs like 'flats-in-kothrud-pune' from collapsing
    all area searches into a handful of fake unique rows.
    """
    if not listings:
        return 0
    from db.client import db
    from datetime import datetime, timezone
    client = db()
    ts = datetime.now(timezone.utc).isoformat()

    seen: dict = {}
    skipped_no_id = 0
    skipped_no_content = 0

    for l in listings:
        row = {k: v for k, v in l.items() if k in _SAVE_COLUMNS}
        row["last_scraped_at"] = ts

        # Quality gate: price is required — priceless listings are useless
        if not row.get("price"):
            skipped_no_content += 1
            continue

        # Resolve listing_id
        lid = row.get("listing_id", "")
        if not _is_valid_listing_id(lid):
            # Try URL tail
            url_tail = (row.get("url") or "").rstrip("/").split("/")[-1][:64]
            if _is_valid_listing_id(url_tail):
                lid = url_tail
            else:
                # Content-hash fallback (requires at least price or title — guaranteed above)
                lid = _content_hash_id(row)

        if not lid:
            skipped_no_id += 1
            continue

        row["listing_id"] = lid
        key = (row.get("platform"), lid)
        seen[key] = row

    if skipped_no_content:
        print(f"  [save] skipped {skipped_no_content} empty rows (no price + no title)")
    if skipped_no_id:
        print(f"  [save] skipped {skipped_no_id} rows with no usable listing_id")

    saved = 0
    for row in seen.values():
        try:
            result = (
                client.table("listings")
                .upsert([row], on_conflict="platform,listing_id")
                .execute()
            )
            if result.data:
                saved += len(result.data)
        except Exception as e:
            print(f"  [save] skipped ({row.get('platform')}, {row.get('listing_id')}): {e}")
    return saved
