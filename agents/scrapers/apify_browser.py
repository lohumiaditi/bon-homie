"""
Apify Browser Scraper
---------------------
Runs ONE Apify playwright-scraper actor that visits all 5 real estate sites
simultaneously. Handles Cloudflare, Akamai, and any other bot protection because
it runs a real Chromium browser through Apify's residential proxy network.

Why one run for all sites:
  - Cheaper (single actor startup cost)
  - Faster (sites loaded in parallel inside Apify)
  - Simpler to manage

Run standalone:
    python agents/scrapers/apify_browser.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import re
import time
import uuid

import requests as _req

from agents.scrapers.base import empty_listing, extract_price, normalize_furnishing

# ── Config ────────────────────────────────────────────────────────────────────
ACTOR_ID = "apify~playwright-scraper"
POLL_INTERVAL = 10      # seconds between status-check calls
MAX_WAIT_SECS  = 420    # 7 minutes max (Apify cold-starts ~30s + crawl time)


# ── Apify Playwright page function (JavaScript, runs inside the browser) ──────
# Two-strategy extraction:
#   1. Try 20 known CSS selector patterns for property cards
#   2. Fallback: detect cards by finding price-bearing elements (₹ symbol)
#      then walking up the DOM to find the container that also has an img + link
# This means the function works even when sites change their class names.
_PAGE_FUNCTION = r"""
async function pageFunction(context) {
    const { page, request, log } = context;
    const platform = (request.userData && request.userData.platform) || 'unknown';

    // Wait for JS-rendered content
    await page.waitForTimeout(4000);

    // Scroll 3× to trigger lazy-loaded images and infinite scroll
    for (let i = 0; i < 3; i++) {
        await page.evaluate(() => window.scrollBy(0, window.innerHeight));
        await page.waitForTimeout(700);
    }
    await page.waitForTimeout(1000);

    const items = await page.evaluate((plat) => {

        /* ---- helpers ---- */
        function getText(root, sels) {
            for (const sel of sels) {
                const el = root.querySelector(sel);
                if (el && el.innerText.trim()) return el.innerText.trim();
            }
            return '';
        }

        function getUrl(root) {
            const a = root.querySelector('a[href]');
            if (!a) return '';
            const href = a.getAttribute('href') || '';
            if (!href || href === '#') return '';
            return href.startsWith('http') ? href : (location.origin + href);
        }

        function getImages(root) {
            return [...root.querySelectorAll('img')]
                .map(i =>
                    i.getAttribute('data-src') ||
                    i.getAttribute('data-lazy') ||
                    i.getAttribute('data-original') ||
                    i.getAttribute('data-url') ||
                    i.src || ''
                )
                .filter(s =>
                    s && s.startsWith('http') &&
                    !/logo|placeholder|default|icon|banner|sprite|noimg|no-image|blank/i.test(s)
                );
        }

        /* ---- Strategy 1: known CSS patterns ---- */
        const CARD_SELECTORS = [
            '.package-detail',                    // NoBroker
            '[class*="PropertyCard"]',
            '[class*="propertyCard"]',
            '[class*="property-card"]',
            '[class*="property_card"]',
            '[class*="srpCard"]',
            '[class*="SrpCard"]',
            '[class*="srp-card"]',
            '[class*="mb-srp__card"]',             // MagicBricks
            '[class*="listing-card"]',
            '[class*="listingCard"]',
            '[class*="Listing_card"]',
            '[class*="prop-card"]',
            '[class*="propCard"]',
            '[class*="result-card"]',
            '[class*="resultCard"]',
            'li[class*="property"]',
            'article[class*="prop"]',
            '[data-listing-id]',
            '[data-property-id]',
            '[data-id][class*="prop"]',
        ];

        let cards = [];
        for (const sel of CARD_SELECTORS) {
            const els = [...document.querySelectorAll(sel)];
            if (els.length > 1) { cards = els; break; }
        }

        /* ---- Strategy 2: price-element detection ---- */
        if (cards.length === 0) {
            // Find all leaf nodes that contain a price pattern
            const priceNodes = [...document.querySelectorAll('*')].filter(el => {
                if (el.children.length > 0) return false;        // leaf only
                const t = el.innerText || '';
                return /[₹Rs\.\s]{0,4}\s*\d[\d,]{2,}/.test(t) && t.length < 60;
            });

            const seen = new Set();
            for (const pn of priceNodes.slice(0, 40)) {
                let node = pn.parentElement;
                for (let depth = 0; depth < 10 && node && node !== document.body; depth++) {
                    const hasImg  = node.querySelector('img') !== null;
                    const hasLink = node.querySelector('a[href]') !== null;
                    const hasLoc  = /locality|location|address|area/i.test(node.className || '');
                    if (hasImg && hasLink) {
                        if (!seen.has(node)) { seen.add(node); cards.push(node); }
                        break;
                    }
                    node = node.parentElement;
                }
            }
        }

        /* ---- Extract data from each card ---- */
        const results = [];
        for (const card of cards.slice(0, 30)) {
            const url    = getUrl(card);
            const images = getImages(card);

            const title = getText(card, [
                'h2', 'h3', 'h4',
                '[class*="title"]', '[class*="Title"]',
                '[class*="bhk"]',   '[class*="BHK"]',
                '[class*="name"]',  '[class*="heading"]',
                '[class*="config"]',
            ]);

            const priceText = getText(card, [
                '[class*="price"]',  '[class*="Price"]',
                '[class*="rent"]',   '[class*="Rent"]',
                '[class*="amount"]', '[class*="Amount"]',
                '[class*="rate"]',   '[class*="Rate"]',
                '[class*="cost"]',   '[class*="Cost"]',
            ]);

            const location = getText(card, [
                '[class*="locality"]', '[class*="Locality"]',
                '[class*="location"]', '[class*="Location"]',
                '[class*="address"]',  '[class*="Address"]',
                '[class*="area"]',     '[class*="Area"]',
                '[class*="suburb"]',   '[class*="zone"]',
            ]);

            if (url || title) {
                results.push({
                    platform:   plat,
                    title:      title,
                    price_text: priceText,
                    location:   location,
                    url:        url,
                    images:     [...new Set(images)],
                    raw_text:   (card.innerText || '').slice(0, 500),
                });
            }
        }
        return results;
    }, platform);

    log.info('[' + platform + '] extracted ' + items.length + ' cards');
    return items;
}
"""


# ── Build start-URL list for all 5 sites ─────────────────────────────────────
def _urls_for_area(area: str, lo: int, hi: int) -> list[dict]:
    """Return 5 start-URL dicts (one per site) for a single area."""
    s = area.lower().replace(" ", "-")
    return [
        {
            "url": f"https://www.nobroker.in/property/residential/rent/pune/{s}?budget={lo},{hi}",
            "userData": {"platform": "nobroker", "area": area},
        },
        {
            "url": (
                f"https://www.99acres.com/property-for-rent-in-{s}-9"
                f"?search_type=rent&city=9&min_budget={lo}&max_budget={hi}"
            ),
            "userData": {"platform": "99acres", "area": area},
        },
        {
            "url": f"https://housing.com/in/rent/flats-in-{s}-pune",
            "userData": {"platform": "housing", "area": area},
        },
        {
            "url": (
                f"https://www.magicbricks.com/property-for-rent/residential-real-estate"
                f"?BudgetMin={lo}&BudgetMax={hi}&City=Pune&Locality={area.title()}"
                f"&proptype=Multistorey-Apartment,Builder-Floor-Apartment,Penthouse,Studio-Apartment"
            ),
            "userData": {"platform": "magicbricks", "area": area},
        },
        {
            "url": f"https://www.squareyards.com/pune/{s}-property-for-rent?minBudget={lo}&maxBudget={hi}",
            "userData": {"platform": "squareyards", "area": area},
        },
    ]


def build_start_urls(prefs: dict) -> list[dict]:
    """Return Apify startUrls for the first area in prefs (on-demand use)."""
    areas = prefs.get("areas", ["kothrud"])
    area  = areas[0] if areas else "kothrud"
    lo    = prefs.get("budget_min", 0)
    hi    = prefs.get("budget_max", 50000)
    return _urls_for_area(area, lo, hi)


def build_all_start_urls(areas: list[str], lo: int, hi: int) -> list[dict]:
    """Return Apify startUrls for ALL areas × 5 sites (batch use, up to 100 URLs)."""
    all_urls = []
    for area in areas:
        all_urls.extend(_urls_for_area(area, lo, hi))
    return all_urls


# ── Apify API helpers ─────────────────────────────────────────────────────────
def _apify_token() -> str:
    # Support both env var names (APIFY_KEY is used throughout this project)
    from dotenv import load_dotenv
    load_dotenv()
    return (
        os.environ.get("APIFY_KEY") or
        os.environ.get("APIFY_API_TOKEN") or
        ""
    )


def _start_run(token: str, start_urls: list[dict], max_pages: int) -> str | None:
    """Start an Apify playwright-scraper run. Returns run ID or None."""
    payload = {
        "startUrls": start_urls,
        "pageFunction": _PAGE_FUNCTION,
        "maxPagesPerCrawl": max_pages * len(start_urls),
        "navigationTimeoutSecs": 60,
        "pageFunctionTimeoutSecs": 90,
        "proxyConfiguration": {
            "useApifyProxy": True,
        },
    }
    try:
        resp = _req.post(
            f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs?token={token}",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        run_id = resp.json()["data"]["id"]
        print(f"  [apify-browser] Run started: {run_id}")
        return run_id
    except Exception as e:
        print(f"  [apify-browser] Could not start run: {e}")
        return None


def _wait_for_run(token: str, run_id: str) -> str | None:
    """Poll until run succeeds. Returns datasetId or None."""
    elapsed = 0
    while elapsed < MAX_WAIT_SECS:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        try:
            data = _req.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}",
                timeout=15,
            ).json()["data"]
            status = data["status"]
            items_count = data.get("stats", {}).get("datasetItemsCount", "?")
            print(f"  [apify-browser] {status} — {items_count} items — {elapsed}s elapsed")
            if status == "SUCCEEDED":
                return data["defaultDatasetId"]
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"  [apify-browser] Run ended with status: {status}")
                return None
        except Exception as e:
            print(f"  [apify-browser] Status check error: {e}")
    print("  [apify-browser] Timed out waiting for run")
    return None


def _fetch_items(token: str, dataset_id: str) -> list[dict]:
    """Fetch all items from an Apify dataset."""
    try:
        resp = _req.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={token}",
            timeout=30,
        )
        items = resp.json()
        if isinstance(items, list):
            return items
        # Apify sometimes returns {"items": [...]}
        if isinstance(items, dict):
            return items.get("items", [])
    except Exception as e:
        print(f"  [apify-browser] Could not fetch items: {e}")
    return []


# ── Parse Apify items → standard listing dicts ────────────────────────────────
_PRICE_RE = re.compile(r"(?:Rs\.?|INR|[\u20b9])?\s*(\d[\d,]+)\s*(?:/\s*(?:mo|month|pm))?", re.I)


def _parse_price(text: str):
    """Extract rent from text like '₹12,500/mo' or 'Rs. 18000 per month'."""
    if not text:
        return None
    for m in _PRICE_RE.finditer(text):
        val = int(m.group(1).replace(",", ""))
        if 1_000 <= val <= 5_00_000:
            return val
    return None


def apify_items_to_listings(raw_items: list[dict]) -> list[dict]:
    """Convert raw Apify-extracted items to our standard listing format."""
    listings = []
    for item in raw_items:
        # Each item IS one listing (returned directly by the page function)
        # but Apify also wraps items in its own metadata — handle both cases
        if isinstance(item, list):
            # page function returned a list; Apify flattens these
            for sub in item:
                listings += apify_items_to_listings([sub])
            continue

        l = empty_listing()
        l["platform"] = item.get("platform", "unknown")

        url = item.get("url", "").strip()
        l["url"] = url
        l["listing_id"] = url.rstrip("/").split("/")[-1] if url else str(uuid.uuid4())[:8]

        l["title"]     = item.get("title", "").strip()
        l["price"]     = _parse_price(item.get("price_text", ""))
        l["city"]      = "Pune"

        loc = item.get("location", "").strip()
        if loc:
            l["area_name"] = loc.split(",")[0].strip()
            l["address"]   = loc

        furn = normalize_furnishing(item.get("raw_text", ""))
        if furn:
            l["furnishing"] = furn

        l["images"] = item.get("images", [])

        if l["listing_id"] and (l["title"] or l["price"] or l["url"]):
            listings.append(l)

    return listings


# ── Batch entry point (GitHub Actions: all areas × 5 sites in one run) ────────
def scrape_batch_with_apify(areas: list[str], lo: int, hi: int) -> list[dict]:
    """
    Run ONE Apify actor covering all areas × 5 sites.
    Apify handles all URLs in parallel via its worker pool — much faster and
    cheaper than separate runs per area.
    Returns all listings in standard format.
    """
    token = _apify_token()
    if not token:
        print("  [apify-browser] No APIFY_KEY — cannot run batch scrape")
        return []

    start_urls = build_all_start_urls(areas, lo, hi)
    print(f"  [apify-browser] Batch: {len(start_urls)} URLs ({len(areas)} areas × 5 sites)")

    run_id = _start_run(token, start_urls, max_pages=3)
    if not run_id:
        return []

    dataset_id = _wait_for_run(token, run_id)
    if not dataset_id:
        return []

    raw = _fetch_items(token, dataset_id)
    print(f"  [apify-browser] {len(raw)} raw items received")

    listings = apify_items_to_listings(raw)
    print(f"  [apify-browser] {len(listings)} listings parsed")
    return listings


# ── On-demand entry point (orchestrator: single area) ─────────────────────────
def scrape_all_with_apify(prefs: dict, max_pages: int = 2) -> list[dict]:
    """
    Scrape all 5 real estate sites in ONE Apify playwright run.
    Returns listings in standard format. Falls back to [] if anything fails.
    """
    token = _apify_token()
    if not token:
        print("  [apify-browser] No APIFY_KEY found in .env — skipping browser scrape")
        return []

    print(f"\n  [apify-browser] Starting browser scrape for all 5 sites...")
    start_urls = build_start_urls(prefs)

    run_id = _start_run(token, start_urls, max_pages)
    if not run_id:
        return []

    dataset_id = _wait_for_run(token, run_id)
    if not dataset_id:
        return []

    raw = _fetch_items(token, dataset_id)
    print(f"  [apify-browser] {len(raw)} raw items received")

    listings = apify_items_to_listings(raw)
    print(f"  [apify-browser] {len(listings)} listings parsed")
    return listings


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    prefs = {
        "city": "Pune",
        "areas": ["Kothrud"],
        "budget_min": 10000,
        "budget_max": 25000,
        "furnishing": "any",
    }

    print("Running Apify browser scrape for Kothrud, Rs.10k-25k...")
    listings = scrape_all_with_apify(prefs, max_pages=1)

    print(f"\nTotal listings : {len(listings)}")
    print(f"With 3+ images : {sum(1 for l in listings if len(l['images']) >= 3)}")

    by_platform = {}
    for l in listings:
        by_platform[l['platform']] = by_platform.get(l['platform'], 0) + 1
    for p, c in sorted(by_platform.items()):
        print(f"  {p:15} {c} listings")

    if listings:
        print("\nSample listing:")
        s = listings[0]
        for k in ["platform", "title", "price", "area_name", "url"]:
            print(f"  {k}: {s[k]}")
        print(f"  images: {len(s['images'])}")
