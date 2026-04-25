"""
Facebook Agent
--------------
Scrapes rental listings from:
  1. Facebook Marketplace — Pune property rentals (public, no group needed)
  2. Facebook Groups — known Pune rental groups (Camoufox browser, logged in)
  3. Facebook Posts Search — elastic keyword search across all public posts
     (searches per area: "pune baner flat rent bhk", etc.)

Outreach strategy:
  - Phone number found   → WhatsApp deep-link generated (wa.me)
  - No phone, Marketplace listing → Messenger DM (send_message)
  - No phone, Group post → comment on the post (post_comment)

Cookie persistence:
  Cookies saved to FB_COOKIES_PATH after login, reloaded on next run.
  Avoids re-login (highest ban-risk action) on every GitHub Actions run.

Note: Facebook Groups Graph API was fully removed by Meta on April 22 2024.
      scrape_groups_with_token() no longer exists — use Camoufox only.

Credentials:
  FB_EMAIL, FB_PASSWORD in .env / GitHub Secrets
  FB_COOKIES_PATH (optional) — path to persist cookies (default: .fb_cookies.json)
"""

import asyncio
import concurrent.futures
import json
import os
import re
import sys
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from agents.scrapers.base import empty_listing, normalize_phone, normalize_furnishing

# ── Config ────────────────────────────────────────────────────────────────────

FB_COOKIES_PATH = os.environ.get(
    "FB_COOKIES_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", ".fb_cookies.json"),
)

PAGE_TIMEOUT_MS   = 35_000
POST_LOAD_WAIT_MS = 4_500
SCROLL_PAUSE_MS   = 1_500
MAX_MP_LISTINGS   = 80     # max marketplace listings per run
MAX_GROUP_POSTS   = 50     # max posts to scan per group
MAX_SEARCH_POSTS  = 40     # max posts per search query

# All known Pune rental Facebook groups
PUNE_RENTAL_GROUPS = [
    "https://www.facebook.com/groups/puneflatrentals",
    "https://www.facebook.com/groups/puneflatsforrent",
    "https://www.facebook.com/groups/rentalpuneflatrooms",
    "https://www.facebook.com/groups/PuneAccommodation",
    "https://www.facebook.com/groups/puneflatmates",
    "https://www.facebook.com/groups/puneflatsandflatmates",
    "https://www.facebook.com/groups/punerentals",
    "https://www.facebook.com/groups/pune.flat.for.rent",
    "https://www.facebook.com/groups/punehomesforrent",
    "https://www.facebook.com/groups/PuneFlatRent",
    "https://www.facebook.com/groups/puneroomrent",
    "https://www.facebook.com/groups/punepgflatmates",
]

# Comprehensive Pune locality list — imported from shared module
from agents.pune_areas import ALL_PUNE_AREAS as PUNE_LOCALITIES

# In-process cookie cache (avoids re-login within same run)
_SESSION_COOKIES: list | None = None


# ── Credential helpers ────────────────────────────────────────────────────────

def _creds() -> tuple[str, str]:
    return (
        os.environ.get("FB_EMAIL", ""),
        os.environ.get("FB_PASSWORD", ""),
    )


# ── Cookie persistence ────────────────────────────────────────────────────────

def _load_cookies_from_disk() -> list | None:
    try:
        if os.path.exists(FB_COOKIES_PATH):
            with open(FB_COOKIES_PATH, "r") as f:
                cookies = json.load(f)
            if cookies:
                print(f"  [facebook] Loaded {len(cookies)} cookies from disk")
                return cookies
    except Exception as e:
        print(f"  [facebook] Cookie load error: {e}")
    return None


def _save_cookies_to_disk(cookies: list) -> None:
    try:
        with open(FB_COOKIES_PATH, "w") as f:
            json.dump(cookies, f)
        print(f"  [facebook] Saved {len(cookies)} cookies to disk")
    except Exception as e:
        print(f"  [facebook] Cookie save error: {e}")


# ── Login ─────────────────────────────────────────────────────────────────────

async def _login_async(email: str, password: str) -> list:
    """Log into Facebook with Camoufox and return session cookies."""
    from camoufox.async_api import AsyncCamoufox
    print("  [facebook] Logging in to Facebook...")

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()

        await page.goto(
            "https://www.facebook.com/",
            timeout=PAGE_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(3_000)

        # Dismiss cookie consent banner
        for btn_sel in [
            "button[data-cookiebanner='accept_button']",
            "[aria-label='Allow all cookies']",
            "button[title='Allow all cookies']",
            "[data-testid='cookie-policy-manage-dialog-accept-button']",
            "button:has-text('Allow all cookies')",
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
        ]:
            try:
                await page.click(btn_sel, timeout=1_500)
                await page.wait_for_timeout(800)
                break
            except Exception:
                pass

        await page.goto(
            "https://www.facebook.com/login",
            timeout=PAGE_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(2_000)

        email_sel = None
        for sel in ("#email", "[name='email']", "input[type='email']", "input[autocomplete='email']"):
            try:
                await page.wait_for_selector(sel, timeout=8_000)
                email_sel = sel
                break
            except Exception:
                pass

        if not email_sel:
            raise RuntimeError(
                "Facebook login form not found. "
                "Likely: captcha, 2FA enabled, or IP blocked."
            )

        # Human-like typing with random delay per character
        await page.click(email_sel)
        for char in email:
            await page.keyboard.type(char)
            await page.wait_for_timeout(random.randint(30, 120))

        await page.wait_for_timeout(random.randint(300, 700))

        pass_sel = "#pass" if await page.query_selector("#pass") else "[name='pass']"
        await page.click(pass_sel)
        for char in password:
            await page.keyboard.type(char)
            await page.wait_for_timeout(random.randint(30, 120))

        await page.wait_for_timeout(random.randint(400, 900))

        for btn in ("[name='login']", "button[type='submit']", "input[type='submit']"):
            try:
                await page.click(btn, timeout=3_000)
                break
            except Exception:
                pass
        await page.wait_for_timeout(7_000)

        url = page.url
        if any(kw in url for kw in ("login", "checkpoint", "two_step", "recover")):
            raise RuntimeError(
                f"Facebook login failed or needs 2FA. URL: {url}\n"
                "Fix: disable 2FA, or log in once manually from this IP."
            )

        print("  [facebook] Login successful.")
        cookies = await page.context.cookies()
        _save_cookies_to_disk(cookies)
        return cookies


def _get_session() -> list:
    """Return cached cookies. Try disk → login fresh if needed."""
    global _SESSION_COOKIES
    if _SESSION_COOKIES:
        return _SESSION_COOKIES

    # Try loading from disk first (avoids login automation)
    disk_cookies = _load_cookies_from_disk()
    if disk_cookies:
        _SESSION_COOKIES = disk_cookies
        return _SESSION_COOKIES

    # Fresh login
    email, password = _creds()
    if not email or not password:
        raise RuntimeError("FB_EMAIL and FB_PASSWORD must be set in .env.")

    def _run():
        return asyncio.run(_login_async(email, password))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        _SESSION_COOKIES = ex.submit(_run).result(timeout=120)
    return _SESSION_COOKIES


# ── Post text extraction helpers ──────────────────────────────────────────────

def _extract_price(text: str) -> int | None:
    for pattern in [
        r"[₹Rs\.]+\s*([\d,]{4,6})",
        r"([\d,]{4,6})\s*/\s*(?:mo|month|pm)\b",
        r"rent\s*[:\-]?\s*([\d,]{4,6})",
        r"([\d]{4,6})\s*(?:per month|pm|\/month)",
        r"\b(\d{1,2})[kK]\b",   # "15k" → 15000
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                raw = m.group(1).replace(",", "")
                val = int(raw)
                # Handle "15k"
                if "k" in m.group(0).lower() and val < 1000:
                    val *= 1000
                if 2_000 <= val <= 3_00_000:
                    return val
            except ValueError:
                pass
    return None


def _is_rental_post(text: str) -> bool:
    text_l = text.lower()
    return any(kw in text_l for kw in [
        "rent", "rental", "bhk", "flat", "apartment", "pg", "room for rent",
        "available", "1rk", "2rk", "studio", "bachelorette", "flatmate",
        "accommodation", "paying guest", "house for rent",
    ])


def _extract_area(text: str) -> str:
    text_l = text.lower()
    for loc in PUNE_LOCALITIES:
        if loc.lower() in text_l:
            return loc
    return ""


def _extract_phone(text: str) -> str:
    """Extract Indian mobile number from post text."""
    # Remove spaces/dashes inside numbers for matching
    cleaned = re.sub(r"[\s\-\.]", "", text)
    m = re.search(r"(?:\+91)?([6-9]\d{9})", cleaned)
    if m:
        return normalize_phone(m.group(0))
    return ""


def _extract_fb_profile_url(post_soup) -> str:
    """Try to find the poster's Facebook profile URL from a post container."""
    for link in post_soup.find_all("a", href=True):
        href = link["href"]
        # Profile links: /profile.php?id=... or /firstname.lastname
        if re.match(r"https?://www\.facebook\.com/(?:profile\.php\?id=\d+|[a-zA-Z0-9\.]+/?$)", href):
            return href
        if href.startswith("/") and not any(x in href for x in [
            "groups", "marketplace", "watch", "events", "pages", "help",
            "login", "settings", "share", "hashtag",
        ]):
            return f"https://www.facebook.com{href}"
    return ""


def _parse_post(text: str, post_id: str, post_url: str, source: str,
                post_soup=None) -> dict | None:
    """Convert raw post text → standard listing dict."""
    if not _is_rental_post(text):
        return None

    price = _extract_price(text)
    # Allow posts without price — we still collect them (price=None)

    listing = empty_listing()
    listing["platform"]   = "facebook"
    listing["listing_id"] = post_id
    listing["title"]      = text[:200].strip()
    listing["price"]      = price
    listing["city"]       = "Pune"
    listing["url"]        = post_url
    listing["furnishing"] = normalize_furnishing(text)

    area = _extract_area(text)
    listing["area_name"] = area or "Pune"
    listing["address"]   = f"{area}, Pune" if area else "Pune"

    phone = _extract_phone(text)
    if phone:
        listing["contact"]     = phone
        listing["contact_raw"] = phone

    # Poster profile URL (used for DM outreach when no phone)
    if post_soup:
        profile_url = _extract_fb_profile_url(post_soup)
        if profile_url:
            listing["fb_poster_url"] = profile_url

    # Occupancy / gender
    text_l = text.lower()
    if "double" in text_l or "sharing" in text_l:
        listing["occupancy"] = "double"
    elif "single" in text_l:
        listing["occupancy"] = "single"
    if any(w in text_l for w in ["ladies", "female", "girls", "women"]):
        listing["gender"] = "female"
    elif any(w in text_l for w in ["bachelors", "male", "gents"]):
        listing["gender"] = "male"

    brokerage_text = text_l
    if "no brokerage" in brokerage_text or "zero brokerage" in brokerage_text:
        listing["brokerage"] = False
    elif "brokerage" in brokerage_text or "broker" in brokerage_text:
        listing["brokerage"] = True

    return listing


def _whatsapp_link(phone: str, listing: dict) -> str:
    """Generate wa.me deep link with pre-filled message."""
    area  = listing.get("area_name") or "Pune"
    price = listing.get("price")
    msg = (
        f"Hi! I saw your rental listing in {area}"
        f"{f' at Rs.{price}/month' if price else ''}. "
        "Is it still available? I'm interested in visiting."
    )
    clean = phone.replace("+", "").replace(" ", "")
    from urllib.parse import quote
    return f"https://wa.me/{clean}?text={quote(msg)}"


# ── Group joining ─────────────────────────────────────────────────────────────

async def _join_group_async(page, group_url: str) -> bool:
    """Click Join on a public group. Returns True if join attempted."""
    try:
        await page.goto(group_url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(3_000)

        join_selectors = [
            "div[aria-label='Join group']",
            "div[aria-label='Join Group']",
            "button:has-text('Join group')",
            "button:has-text('Join Group')",
            "[data-testid='groupJoinButton']",
        ]
        for sel in join_selectors:
            try:
                await page.click(sel, timeout=3_000)
                await page.wait_for_timeout(2_500)
                print(f"  [facebook] Joined group: {group_url.split('/')[-1]}")

                # Handle membership questions modal
                try:
                    dialog = await page.wait_for_selector("div[role='dialog']", timeout=4_000)
                    if dialog:
                        for inp in await page.query_selector_all(
                            "div[role='dialog'] textarea, div[role='dialog'] input[type='text']"
                        ):
                            await inp.fill("Looking for a rental flat in Pune")
                            await page.wait_for_timeout(400)
                        for btn in [
                            "div[role='dialog'] button:has-text('Submit')",
                            "div[role='dialog'] div[aria-label='Submit']",
                        ]:
                            try:
                                await page.click(btn, timeout=2_000)
                                break
                            except Exception:
                                pass
                except Exception:
                    pass  # No questions dialog
                return True
            except Exception:
                pass
    except Exception as e:
        print(f"  [facebook] Join error {group_url}: {e}")
    return False


# ── Marketplace scraper ───────────────────────────────────────────────────────

async def _scrape_marketplace_async(lo: int, hi: int, cookies: list) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    from bs4 import BeautifulSoup

    url = (
        f"https://www.facebook.com/marketplace/pune/propertyrentals"
        f"?minPrice={lo}&maxPrice={hi}&daysSinceListed=7&sortBy=creation_time_descend"
    )
    print(f"  [facebook] Marketplace: {url[:80]}...")

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(POST_LOAD_WAIT_MS)

        # Scroll to load more listings
        for _ in range(6):
            await page.evaluate("window.scrollBy(0, window.innerHeight * 1.5)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)

        html = await page.content()

    soup = BeautifulSoup(html, "html.parser")
    listings: list[dict] = []
    seen_ids: set[str] = set()

    for link in soup.find_all("a", href=re.compile(r"/marketplace/item/\d+")):
        href = link.get("href", "")
        id_m = re.search(r"/marketplace/item/(\d+)", href)
        if not id_m:
            continue
        pid = f"mp_{id_m.group(1)}"
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        # Walk up to find card container
        container = link
        for _ in range(6):
            parent = container.find_parent("div")
            if parent and parent.find("img"):
                container = parent
                break
            if parent:
                container = parent

        text     = container.get_text(" ", strip=True)
        full_url = f"https://www.facebook.com{href}" if href.startswith("/") else href

        l = _parse_post(text, pid, full_url, "marketplace", post_soup=container)
        if l:
            imgs = [img.get("src", "") for img in container.find_all("img")
                    if img.get("src", "").startswith("http")]
            l["images"]    = imgs
            # WhatsApp link if phone known
            if l.get("contact"):
                l["wa_url"] = _whatsapp_link(l["contact"], l)
            listings.append(l)

        if len(listings) >= MAX_MP_LISTINGS:
            break

    print(f"  [facebook] Marketplace: {len(listings)} listings extracted")
    return listings


# ── Group feed scraper ────────────────────────────────────────────────────────

async def _scrape_group_async(group_url: str, cookies: list,
                              join_if_needed: bool = True) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    from bs4 import BeautifulSoup

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(group_url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(POST_LOAD_WAIT_MS)

        # Join if we see a join button and join_if_needed=True
        if join_if_needed:
            await _join_group_async(page, group_url)
            await page.wait_for_timeout(3_000)

        # Scroll to load posts
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)

        html = await page.content()

    soup = BeautifulSoup(html, "html.parser")
    listings: list[dict] = []
    seen_ids: set[str] = set()
    group_name = group_url.rstrip("/").split("/")[-1]

    posts = soup.find_all("div", attrs={"role": "article"})
    if not posts:
        posts = [
            a.find_parent("div")
            for a in soup.find_all("a", href=re.compile(r"/(permalink|posts)/\d+"))
            if a.find_parent("div")
        ]

    for post in posts[:MAX_GROUP_POSTS]:
        text = post.get_text(" ", strip=True)
        link = (
            post.find("a", href=re.compile(r"/(permalink|posts)/\d+")) or
            post.find("a", href=re.compile(r"/groups/\d+/posts/\d+"))
        )
        if not link:
            continue
        href  = link["href"]
        id_m  = re.search(r"/(?:permalink|posts)/(\d+)", href)
        if not id_m:
            id_m = re.search(r"/groups/\d+/posts/(\d+)", href)
        if not id_m:
            continue

        pid = f"grp_{id_m.group(1)}"
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        post_url = f"https://www.facebook.com{href}" if href.startswith("/") else href
        l = _parse_post(text, pid, post_url, f"group:{group_name}", post_soup=post)
        if l:
            imgs = [img.get("src", "") for img in post.find_all("img")
                    if img.get("src", "").startswith("http")]
            l["images"] = imgs
            if l.get("contact"):
                l["wa_url"] = _whatsapp_link(l["contact"], l)
            listings.append(l)

    print(f"  [facebook] Group '{group_name}': {len(listings)} listings")
    return listings


# ── Elastic posts search (cross-group keyword search) ─────────────────────────

async def _scrape_posts_search_async(query: str, cookies: list) -> list[dict]:
    """
    Search Facebook posts for a keyword query.
    URL: facebook.com/search/posts/?q=<query>
    Works while logged in — returns posts from public groups + friends.
    Doesn't require group membership.
    """
    from camoufox.async_api import AsyncCamoufox
    from bs4 import BeautifulSoup
    from urllib.parse import quote

    url = f"https://www.facebook.com/search/posts/?q={quote(query)}&filters=eyJyZWNlbnRseV9jcmVhdGVkIjoie1wibmFtZVwiOlwicmVjZW50bHlfY3JlYXRlZFwiLFwiYXJncFwiOlwiXCJ9In0%3D"
    # filters param = recent posts sort (base64 encoded)

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(POST_LOAD_WAIT_MS)

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)

        html = await page.content()

    soup = BeautifulSoup(html, "html.parser")
    listings: list[dict] = []
    seen_ids: set[str] = set()

    posts = soup.find_all("div", attrs={"role": "article"})

    for post in posts[:MAX_SEARCH_POSTS]:
        text = post.get_text(" ", strip=True)

        # Get post permalink
        link = (
            post.find("a", href=re.compile(r"/(permalink|posts)/\d+")) or
            post.find("a", href=re.compile(r"/groups/\d+/posts/\d+")) or
            post.find("a", href=re.compile(r"/marketplace/item/\d+"))
        )
        if not link:
            continue

        href  = link["href"]
        post_url = f"https://www.facebook.com{href}" if href.startswith("/") else href

        # Build a stable ID from the URL
        id_m = re.search(r"/(\d{10,})", href)
        if not id_m:
            continue
        pid = f"search_{id_m.group(1)}"
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        l = _parse_post(text, pid, post_url, f"search:{query[:30]}", post_soup=post)
        if l:
            imgs = [img.get("src", "") for img in post.find_all("img")
                    if img.get("src", "").startswith("http")]
            l["images"] = imgs
            if l.get("contact"):
                l["wa_url"] = _whatsapp_link(l["contact"], l)
            listings.append(l)

    print(f"  [facebook] Search '{query[:40]}': {len(listings)} listings")
    return listings


def _build_search_queries(prefs: dict) -> list[str]:
    """Build elastic search queries from user preferences."""
    areas  = prefs.get("areas", [])
    queries = []

    # Per-area targeted queries
    for area in areas:
        queries.append(f"pune {area} flat for rent bhk")
        queries.append(f"{area} pune rent available")

    # General Pune queries (always run)
    queries += [
        "pune flat for rent no brokerage",
        "pune 1bhk 2bhk rent available",
        "pune flat rent flatmates",
        "pune room rent pg available",
    ]
    return queries


# ── Outreach functions ────────────────────────────────────────────────────────

async def _send_message_async(listing_url: str, message: str, cookies: list) -> bool:
    """Send Messenger DM to a Marketplace listing seller."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(listing_url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(3_000)

        for btn_text in ["Message Seller", "Message seller", "Send Message"]:
            try:
                await page.click(f"text={btn_text}", timeout=4_000)
                await page.wait_for_timeout(2_000)
                break
            except Exception:
                pass
        else:
            return False

        try:
            await page.click("[aria-label='Message']", timeout=4_000)
            for char in message:
                await page.keyboard.type(char)
                await page.wait_for_timeout(random.randint(20, 80))
            await page.wait_for_timeout(random.randint(400, 800))
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2_000)
            print(f"  [facebook] DM sent to {listing_url[:60]}")
            return True
        except Exception as e:
            print(f"  [facebook] DM failed: {e}")
            return False


async def _post_comment_async(post_url: str, comment: str, cookies: list) -> bool:
    """Comment on a Facebook group post."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(cookies)

        await page.goto(post_url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(4_000)

        comment_box_sels = [
            "[aria-label='Write a comment']",
            "[aria-label='Write a public comment']",
            "[data-testid='UFI2CommentBoxContainer'] [contenteditable='true']",
            "div[role='textbox'][aria-label*='comment']",
        ]
        for sel in comment_box_sels:
            try:
                await page.click(sel, timeout=4_000)
                for char in comment:
                    await page.keyboard.type(char)
                    await page.wait_for_timeout(random.randint(20, 70))
                await page.wait_for_timeout(random.randint(500, 1000))
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2_000)
                print(f"  [facebook] Comment posted on {post_url[:60]}")
                return True
            except Exception:
                pass
    return False


def _craft_outreach_message(listing: dict) -> str:
    """Craft a natural, specific outreach message for a listing."""
    area  = listing.get("area_name") or "Pune"
    price = listing.get("price")
    furnishing = listing.get("furnishing") or ""

    msg = f"Hi! I came across your flat listing in {area}"
    if price:
        msg += f" at Rs.{price:,}/month"
    if furnishing and furnishing != "any":
        msg += f" ({furnishing})"
    msg += ". Is it still available? I'm looking for a flat and would love to know more details or schedule a visit. Thank you!"
    return msg


def send_message(listing_url: str, message: str) -> bool:
    """WRITE: Send Messenger DM for a Marketplace listing."""
    try:
        cookies = _get_session()
    except Exception as e:
        print(f"  [facebook] Login error: {e}")
        return False

    def _run():
        return asyncio.run(_send_message_async(listing_url, message, cookies))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run).result(timeout=60)


def post_comment(post_url: str, comment: str) -> bool:
    """WRITE: Comment on a Facebook group post."""
    try:
        cookies = _get_session()
    except Exception as e:
        print(f"  [facebook] Login error: {e}")
        return False

    def _run():
        return asyncio.run(_post_comment_async(post_url, comment, cookies))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run).result(timeout=60)


def outreach_listing(listing: dict) -> dict:
    """
    Attempt outreach for a listing based on available contact info.
    Returns updated listing with outreach_status.

    Strategy:
      1. Phone found   → generate WhatsApp deep link (wa_url)
      2. Marketplace   → Messenger DM
      3. Group post    → comment on post
    """
    message = _craft_outreach_message(listing)

    if listing.get("contact"):
        # WhatsApp link already generated during scraping
        listing["outreach_status"] = "whatsapp_link_ready"
        return listing

    post_url = listing.get("url", "")
    if "marketplace/item" in post_url:
        success = send_message(post_url, message)
        listing["outreach_status"] = "dm_sent" if success else "dm_failed"
    elif "/groups/" in post_url or "/permalink/" in post_url:
        success = post_comment(post_url, message)
        listing["outreach_status"] = "comment_posted" if success else "comment_failed"
    else:
        listing["outreach_status"] = "no_contact_method"

    return listing


# ── Main READ entry point ─────────────────────────────────────────────────────

def scrape_facebook(prefs: dict) -> list[dict]:
    """
    Main entry point called by scraper_orchestrator.

    Scrapes:
      1. Facebook Marketplace — Pune property rentals (budget-filtered)
      2. Top Pune rental groups (up to 4 groups per run)
      3. Elastic posts search — per-area keyword queries

    Returns [] silently if FB credentials not configured.
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

    def _run(coro):
        def _inner():
            return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_inner).result(timeout=180)

    # 1. Marketplace
    try:
        mp = _run(_scrape_marketplace_async(lo, hi, cookies))
        all_listings.extend(mp)
    except Exception as e:
        print(f"  [facebook] Marketplace error: {e}")

    # 2. Groups (top 4)
    for group_url in PUNE_RENTAL_GROUPS[:4]:
        try:
            grp = _run(_scrape_group_async(group_url, cookies, join_if_needed=True))
            all_listings.extend(grp)
        except Exception as e:
            name = group_url.rstrip("/").split("/")[-1]
            print(f"  [facebook] Group '{name}' error: {e}")
        time.sleep(random.uniform(2.0, 4.0))

    # 3. Elastic posts search (per-area + general)
    queries = _build_search_queries(prefs)
    for query in queries[:6]:  # cap at 6 queries per run
        try:
            results = _run(_scrape_posts_search_async(query, cookies))
            all_listings.extend(results)
        except Exception as e:
            print(f"  [facebook] Search '{query[:40]}' error: {e}")
        time.sleep(random.uniform(1.5, 3.0))

    # Deduplicate by listing_id
    seen: set[str] = set()
    unique: list[dict] = []
    for l in all_listings:
        lid = l.get("listing_id", "")
        if lid and lid not in seen:
            seen.add(lid)
            unique.append(l)

    print(f"  [facebook] Total unique: {len(unique)} listings")
    return unique


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    prefs = {
        "areas": ["Baner", "Kothrud"],
        "budget_min": 10_000,
        "budget_max": 35_000,
    }
    results = scrape_facebook(prefs)
    print(f"\nFacebook: {len(results)} total listings")
    with_phone  = sum(1 for r in results if r.get("contact"))
    with_images = sum(1 for r in results if r.get("images"))
    with_price  = sum(1 for r in results if r.get("price"))
    print(f"  With phone:  {with_phone}")
    print(f"  With images: {with_images}")
    print(f"  With price:  {with_price}")
    for r in results[:5]:
        phone = r.get("contact") or "no phone"
        print(f"  ₹{r.get('price')} | {r.get('area_name')} | {phone} | {r['title'][:50]}")
