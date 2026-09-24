"""
Facebook browser plumbing
-------------------------
One Camoufox browser per run (not one per page), with the session's cookies
loaded. Every navigation checks for the login wall so a dead session fails
fast with FacebookSessionExpired instead of silently scraping a login page.

FB_HEADLESS=0 shows the browser window (useful when debugging selectors).
"""

import asyncio
import os
import random
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from agents.facebook.parsing import is_login_wall
from agents.facebook.session import FacebookSession, FacebookSessionExpired

PAGE_TIMEOUT_MS = 35_000
POST_LOAD_WAIT_MS = 4_500
SCROLL_PAUSE_MS = 1_500

HEADLESS = os.environ.get("FB_HEADLESS", "1") != "0"


def run_sync(coro_factory, timeout: float):
    """
    Run an async job from sync code. Uses a worker thread so it also works when
    the caller is already inside an event loop (FastAPI background tasks).
    On timeout the worker is abandoned rather than waited on.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(lambda: asyncio.run(coro_factory())).result(timeout=timeout)
    finally:
        executor.shutdown(wait=False)


async def pause(min_ms: int, max_ms: int) -> None:
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


@asynccontextmanager
async def open_page(session: FacebookSession):
    """
    A logged-in page. When the block finishes cleanly, session.cookies is
    replaced with the browser's current cookies (Facebook rotates some), so
    callers can save them with session.persist_session(session).
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=HEADLESS, geoip=True) as browser:
        page = await browser.new_page()
        await page.context.add_cookies(session.cookies)
        yield page
        try:
            fresh = [c for c in await page.context.cookies() if "facebook.com" in c.get("domain", "")]
            names = {c["name"] for c in fresh}
            if {"c_user", "xs"} <= names:
                session.cookies = fresh
        except Exception:
            pass


async def goto(page, url: str, wait_ms: int = POST_LOAD_WAIT_MS) -> str:
    """Navigate and return the HTML; raises FacebookSessionExpired on a login wall."""
    await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    await page.wait_for_timeout(wait_ms)
    html = await page.content()
    if is_login_wall(page.url, html):
        raise FacebookSessionExpired(f"redirected to {page.url[:80]}")
    return html


async def scroll(page, times: int, pause_ms: int = SCROLL_PAUSE_MS) -> None:
    for _ in range(times):
        await page.evaluate("window.scrollBy(0, window.innerHeight * (1 + Math.random()))")
        await page.wait_for_timeout(pause_ms + random.randint(0, 800))


async def login_with_password(email: str, password: str) -> list[dict]:
    """Automated email/password login. Returns cookies; raises when Facebook blocks it."""
    from camoufox.async_api import AsyncCamoufox

    print("  [facebook] Logging in to Facebook with FB_EMAIL/FB_PASSWORD...")
    async with AsyncCamoufox(headless=HEADLESS, geoip=True) as browser:
        page = await browser.new_page()
        await page.goto("https://www.facebook.com/login", timeout=PAGE_TIMEOUT_MS,
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(2_500)

        for sel in ("button[data-cookiebanner='accept_button']",
                    "button:has-text('Allow all cookies')"):
            try:
                await page.click(sel, timeout=1_500)
                break
            except Exception:
                pass

        email_sel = None
        for sel in ("#email", "[name='email']", "input[type='email']"):
            try:
                await page.wait_for_selector(sel, timeout=8_000)
                email_sel = sel
                break
            except Exception:
                pass
        if not email_sel:
            raise RuntimeError("Login form not found (captcha, 2FA or IP block).")

        await page.click(email_sel)
        for ch in email:
            await page.keyboard.type(ch)
            await page.wait_for_timeout(random.randint(30, 120))
        await page.wait_for_timeout(random.randint(300, 700))
        await page.click("#pass" if await page.query_selector("#pass") else "[name='pass']")
        for ch in password:
            await page.keyboard.type(ch)
            await page.wait_for_timeout(random.randint(30, 120))
        await page.wait_for_timeout(random.randint(400, 900))
        for btn in ("[name='login']", "button[type='submit']"):
            try:
                await page.click(btn, timeout=3_000)
                break
            except Exception:
                pass
        await page.wait_for_timeout(7_000)

        if is_login_wall(page.url):
            try:
                await page.screenshot(path=os.path.join(
                    os.path.dirname(__file__), "..", "..", ".fb_login_debug.png"))
            except Exception:
                pass
            raise RuntimeError(f"Facebook blocked the login ({page.url[:80]}).")

        print("  [facebook] Login successful.")
        return await page.context.cookies()
