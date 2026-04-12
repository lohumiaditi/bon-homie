"""
Base Scraper
------------
Shared Playwright setup, user-agent rotation, rate-limit delays,
and the standard listing dict schema used by all scrapers.
"""

import asyncio
import random
import re
import uuid
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# ── Standard listing schema ───────────────────────────────────────────────────
def empty_listing() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "platform": "",
        "listing_id": "",
        "url": "",
        "title": "",
        "price": None,           # int, monthly rent ₹
        "area_name": "",
        "address": "",
        "city": "Pune",
        "furnishing": None,      # 'furnished'|'semi-furnished'|'unfurnished'
        "renter_type": None,     # 'family'|'bachelor'
        "gender": None,          # 'male'|'female'
        "occupancy": None,       # 'single'|'double'
        "brokerage": None,       # True|False
        "images": [],            # list of image URLs
        "contact_raw": "",
        "contact": "",
        "lat": None,
        "lng": None,
    }


# ── User agents ───────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


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
    """Extract integer rent from strings like '₹12,500/mo' or '12500'."""
    digits = re.sub(r"[^\d]", "", text)
    if digits:
        val = int(digits)
        # Sanity check: rent should be between ₹1,000 and ₹5,00,000
        if 1_000 <= val <= 5_00_000:
            return val
    return None


# ── Base browser context ──────────────────────────────────────────────────────
class BaseScraper:
    """
    Inherit from this. Override `scrape()`.
    Usage:
        async with BaseScraper() as s:
            listings = await s.scrape(prefs)
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def new_context(self) -> BrowserContext:
        """Return a fresh browser context with a random user-agent."""
        ua = random.choice(USER_AGENTS)
        ctx = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 800},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        # Hide webdriver flag
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return ctx

    async def new_page(self) -> tuple[BrowserContext, Page]:
        ctx = await self.new_context()
        page = await ctx.new_page()
        return ctx, page

    async def random_delay(self, min_s: float = 2.0, max_s: float = 5.0):
        """Human-like delay between requests."""
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def scrape(self, prefs: dict) -> list[dict]:
        """Override this in each scraper. Return list of listing dicts."""
        raise NotImplementedError


# ── Supabase persistence ──────────────────────────────────────────────────────
def save_listings(listings: list[dict]) -> int:
    """
    Upsert listings to Supabase. Returns count of new rows inserted.
    Duplicates (same platform + listing_id) are silently skipped.
    """
    if not listings:
        return 0
    from db.client import db
    client = db()
    rows = []
    for l in listings:
        row = {k: v for k, v in l.items() if k != "id"}  # let DB generate id
        rows.append(row)
    # on_conflict: do nothing for duplicate (platform, listing_id)
    result = client.table("listings").upsert(
        rows, on_conflict="platform,listing_id", ignore_duplicates=True
    ).execute()
    return len(result.data) if result.data else 0
