"""
Facebook Agent
--------------
Connects to a personal Facebook account using Camoufox to:
  READ  — Scrape rental listings from Facebook Marketplace (Pune)
          Scrape rental posts from popular Pune flat-hunting groups
  WRITE — Send a message to a listing seller via Facebook Messenger

Credentials:
  FB_EMAIL and FB_PASSWORD in .env / GitHub Secrets
  (No tokens or app review needed — just your FB login)

Usage:
  from agents.scrapers.facebook_agent import scrape_facebook, send_message
  listings = scrape_facebook({"budget_min": 10000, "budget_max": 30000})
  send_message("https://www.facebook.com/marketplace/item/123", "Hi, is this available?")
"""

import asyncio
import concurrent.futures
import os
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from agents.scrapers.base import empty_listing, normalize_phone, normalize_furnishing

# ── Config ────────────────────────────────────────────────────────────────────

# Popular Pune rental Facebook groups (public — no join required to view)
PUNE_RENTAL_GROUPS = [
    "https://www.facebook.com/groups/puneflatrentals",
    "https://www.facebook.com/groups/puneflatsforrent",
    "https://www.facebook.com/groups/rentalpuneflatrooms",
    "https://www.facebook.com/groups/PuneAccommodation",
]

PAGE_TIMEOUT_MS   = 30_000
POST_LOAD_WAIT_MS = 4_000
SCROLL_PAUSE_MS   = 1_500
MAX_MP_LISTINGS   = 60    # max from Marketplace per run
MAX_GROUP_POSTS   = 40    # max posts to scan per group

# In-process cookie cache (avoids re-login within same run)
_SESSION_COOKIES: list | None = None


# ── Credential helpers ────────────────────────────────────────────────────────

def _creds() -> tuple[str, str]:
    return (
        os.environ.get("FB_EMAIL", ""),
        os.environ.get("FB_PASSWORD", ""),
    )


# ── Login ─────────────────────────────────────────────────────────────────────

async def _login_async(email: str, password: str) -> list:
    """Log into Facebook with Camoufox and return session cookies."""
    from camoufox.async_api import AsyncCamoufox
    print("  [facebook] Logging in to Facebook...")

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()

        await page.goto(
            "https://www.facebook.com/login",
            timeout=PAGE_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(2_000)

        # Dismiss cookie consent banner if present
        for btn_sel in [
            "button[data-cookiebanner='accept_button']",
            "[aria-label='Allow all cookies']",
            "button[title='Allow all cookies']",
        ]:
            try:
                await page.click(btn_sel, timeout=2_000)
                await page.wait_for_timeout(800)
                break
            except Exception:
                pass

        # Fill credentials
        await page.fill("#email", email)
        await page.wait_for_timeout(400)
        await page.fill("#pass", password)
        await page.wait_for_timeout(400)
        await page.click("[name='login']")
        await page.wait_for_timeout(6_000)

        url = page.url
        if any(kw in url for kw in ("login", "checkpoint", "two_step", "recover")):
            raise RuntimeError(
                f"Facebook login failed or requires 2FA. Current URL: {url}\n"
                "Fix: (1) Disable 2FA on your FB account, OR "
                "(2) Log in once from the GitHub Actions IP to whitelist it."
            )

        print("  [facebook] Login successful.")
        return await page.context.cookies()


def _get_session() -> list:
    """Return cached cookies, logging in fresh if needed."""
    global _SESSION_COOKIES
    if _SESSION_COOKIES:
        return _SESSION_COOKIES

    email, password = _creds()
    if not email or not password:
        raise RuntimeError("FB_EMAIL and FB_PASSWORD must be set in .env or GitHub Secrets.")

    def _run():
        return asyncio.run(_login_async(email, password))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        _SESSION_COOKIES = ex.submit(_run).result(timeout=90)
    return _SESSION_COOKIES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_price(text: str) -> int | None:
    """Extract monthly rent price from any text."""
    # ₹15,000 / Rs 15000 / 15000/month / 15k
    for pattern in [
        r"[₹Rs\.]+\s*([\d,]+)",
        r"([\d,]{4,6})\s*/\s*(?:mo|month|pm)\b",
        r"rent\s*[:\-]?\s*([\d,]{4,6})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
                if 2_000 <= val <= 3_00_000:
                    return val
            except ValueError:
                pass
    return None


def _is_rental_post(text: str) -> bool:
    text_l = text.lower()
    return any(kw in text_l for kw in [
        "rent", "rental", "bhk", "flat", "apartment", "pg", "room for rent",
        "available", "1rk", "2rk", "studio", "bachelorette",
    ])


def _parse_post_text(text: str, post_id: str, post_url: str, source: str) -> dict | None:
    """Convert raw post text + metadata to a standard listing dict."""
    if not _is_rental_post(text):
        return None
    price = _extract_price(text)
    if not price:
        return None

    listing = empty_listing()
    listing["platform"]   = "facebook"
    listing["listing_id"] = post_id
    listing["title"]      = text[:200]
    listing["price"]      = price
    listing["city"]       = "Pune"
    listing["url"]        = post_url
    listing["furnishing"] = normalize_furnishing(text)
    listing["source"]     = source  # "marketplace" or group name

    # Area detection
    try:
        from agents.input_agent import PUNE_AREAS
        text_lower = text.lower()
        for area in PUNE_AREAS:
            if area.lower() in text_lower:
                listing["area_name"] = area
                listing["address"]   = f"{area}, Pune"
                break
    except Exception:
        pass
    if not listing["area_name"]:
        listing["area_name"] = "Pune"
        listing["address"]   = "Pune"

    # Phone number
    phone_m = re.search(r"(?:\+91[\s\-]?)?[6-9]\d{9}", re.sub(r"[^\d+]", "", text))
    if phone_m:
        listing["contact"] = normalize_phone(phone_m.group())

    # Occupancy / gender hints
    text_l = text.lower()
    if "double" in text_l or "sharing" in text_l:
        listing["occupancy"] = "double"
    elif "single" in text_l:
        listing["occupancy"] = "single"
    if "ladies" in text_l or "female" in text_l or "girls" in text_l:
        listing["gender"] = "female"
    elif "bachelors" in text_l or "male" in text_l:
        listing["gender"] = "male"

    return listing


# ── Marketplace scraper ───────────────────────────────────────────────────────

async def _scrape_marketplace_async(lo: int, hi: int, cookies: list) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    from bs4 import BeautifulSoup

    url = (
        f"https://www.facebook.com/marketplace/pune/propertyrentals"
        f"?minPrice={lo}&maxPrice={hi}&daysSinceListed=7"
    )

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(POST_LOAD_WAIT_MS)

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, window.innerHeight * 1.5)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)

        html = await page.content()

    soup = BeautifulSoup(html, "html.parser")
    listings: list[dict] = []
    seen_ids: set[str] = set()

    # Primary: find all marketplace item links
    for link in soup.find_all("a", href=re.compile(r"/marketplace/item/\d+")):
        href = link.get("href", "")
        id_m = re.search(r"/marketplace/item/(\d+)", href)
        if not id_m:
            continue
        pid = f"mp_{id_m.group(1)}"
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        container = link.find_parent("div") or link
        text = container.get_text(" ", strip=True)
        full_url = f"https://www.facebook.com{href}" if href.startswith("/") else href

        listing = _parse_post_text(text, pid, full_url, "marketplace")
        if listing:
            # Images from marketplace card
            imgs = [
                img.get("src", "") for img in container.find_all("img")
                if img.get("src", "").startswith("http")
            ]
            listing["images"] = imgs
            listings.append(listing)

        if len(listings) >= MAX_MP_LISTINGS:
            break

    print(f"  [facebook] Marketplace: {len(listings)} listings extracted")
    return listings


# ── Group scraper ─────────────────────────────────────────────────────────────

async def _scrape_group_async(group_url: str, cookies: list) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    from bs4 import BeautifulSoup

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(group_url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(POST_LOAD_WAIT_MS)

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)

        html = await page.content()

    soup = BeautifulSoup(html, "html.parser")
    listings: list[dict] = []
    seen_ids: set[str] = set()

    # Find posts by role=article or permalink links
    posts = soup.find_all("div", attrs={"role": "article"})
    if not posts:
        posts = [
            a.find_parent("div")
            for a in soup.find_all("a", href=re.compile(r"/(permalink|posts)/\d+"))
            if a.find_parent("div")
        ]

    group_name = group_url.rstrip("/").split("/")[-1]

    for post in posts[:MAX_GROUP_POSTS]:
        text = post.get_text(" ", strip=True)
        link = post.find("a", href=re.compile(r"/(permalink|posts)/\d+"))
        if not link:
            continue
        href = link["href"]
        id_m = re.search(r"/(permalink|posts)/(\d+)", href)
        if not id_m:
            continue
        pid = f"grp_{id_m.group(2)}"
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        post_url = f"https://www.facebook.com{href}" if href.startswith("/") else href
        listing = _parse_post_text(text, pid, post_url, f"group:{group_name}")
        if listing:
            imgs = [
                img.get("src", "") for img in post.find_all("img")
                if img.get("src", "").startswith("http")
            ]
            listing["images"] = imgs
            listings.append(listing)

    return listings


# ── WRITE: send a message to a seller ────────────────────────────────────────

async def _send_message_async(listing_url: str, message: str, cookies: list) -> bool:
    """
    Navigate to a Marketplace listing and send a message to the seller.
    Returns True on success, False on failure.
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(listing_url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(3_000)

        # Click "Message Seller" button
        for btn_text in ["Message Seller", "Message seller", "Send Message"]:
            try:
                await page.click(f"text={btn_text}", timeout=4_000)
                await page.wait_for_timeout(2_000)
                break
            except Exception:
                pass
        else:
            return False  # button not found

        # Find message input and type
        try:
            await page.click("[aria-label='Message']", timeout=4_000)
            await page.keyboard.type(message, delay=40)
            await page.wait_for_timeout(500)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1_500)
            print(f"  [facebook] Message sent to {listing_url[:60]}...")
            return True
        except Exception as e:
            print(f"  [facebook] Could not send message: {e}")
            return False


def send_message(listing_url: str, message: str) -> bool:
    """
    WRITE: Send a message to a Facebook Marketplace listing seller.
    Requires the user to be logged in (FB_EMAIL + FB_PASSWORD in .env).

    ⚠️  Use responsibly. Keep messages natural, space them out.
        Facebook may flag automated messaging patterns.
    """
    try:
        cookies = _get_session()
    except Exception as e:
        print(f"  [facebook] Cannot send message — login error: {e}")
        return False

    def _run():
        return asyncio.run(_send_message_async(listing_url, message, cookies))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run).result(timeout=60)


# ── Public READ entry point ───────────────────────────────────────────────────

def scrape_facebook(prefs: dict) -> list[dict]:
    """
    Main READ entry point called by scraper_orchestrator and run_batch_scrape.

    Scrapes:
      1. Facebook Marketplace → Pune property rentals (budget-filtered)
      2. Top Pune rental Facebook groups

    Returns [] silently if FB_EMAIL / FB_PASSWORD are not configured.
    """
    email, password = _creds()
    if not email or not password:
        print("  [facebook] Skipping — FB_EMAIL / FB_PASSWORD not configured.")
        return []

    lo = prefs.get("budget_min", 5_000)
    hi = prefs.get("budget_max", 1_20_000)

    try:
        cookies = _get_session()
    except Exception as e:
        print(f"  [facebook] Login error: {e}")
        return []

    all_listings: list[dict] = []

    # 1. Marketplace
    def _run_mp():
        return asyncio.run(_scrape_marketplace_async(lo, hi, cookies))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            mp = ex.submit(_run_mp).result(timeout=120)
        all_listings.extend(mp)
    except Exception as e:
        print(f"  [facebook] Marketplace error: {e}")

    # 2. Groups (top 2 to stay within time budget)
    for group_url in PUNE_RENTAL_GROUPS[:2]:
        def _run_grp(url=group_url):
            return asyncio.run(_scrape_group_async(url, cookies))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                grp = ex.submit(_run_grp).result(timeout=90)
            name = group_url.rstrip("/").split("/")[-1]
            print(f"  [facebook] Group '{name}': {len(grp)} listings")
            all_listings.extend(grp)
        except Exception as e:
            print(f"  [facebook] Group error: {e}")

    print(f"  [facebook] Total: {len(all_listings)} listings")
    return all_listings


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = scrape_facebook({"budget_min": 10_000, "budget_max": 30_000})
    print(f"\nFacebook listings found: {len(results)}")
    for r in results[:5]:
        print(f"  ₹{r['price']} | {r['area_name']} | {r['title'][:60]} | {r['listing_id']}")
