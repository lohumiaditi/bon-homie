"""
One-time Facebook cookie setup.
Opens a VISIBLE browser window → you log in manually → cookies saved to .fb_cookies.json
After this, the scraper reuses cookies and never needs to log in again.

Run:
    python setup_fb_cookies.py
"""
import sys, os, asyncio, json
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

FB_COOKIES_PATH = os.path.join(os.path.dirname(__file__), ".fb_cookies.json")

async def setup():
    from camoufox.async_api import AsyncCamoufox

    print("Opening visible Firefox browser...")
    print("Log in to Facebook manually. When your feed loads, come back here.")
    print()

    async with AsyncCamoufox(headless=False, geoip=True) as browser:
        page = await browser.new_page()
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

        # Pre-fill credentials if available
        email = os.getenv("FB_EMAIL", "")
        password = os.getenv("FB_PASSWORD", "")
        if email:
            try:
                await page.wait_for_selector("#email", timeout=8000)
                await page.fill("#email", email)
                print(f"Pre-filled email: {email}")
            except Exception:
                pass
        if password:
            try:
                await page.fill("#pass", password)
                print("Pre-filled password.")
            except Exception:
                pass

        print()
        print("Browser is open. If you see a CAPTCHA or 2FA, complete it in the browser.")
        print("Waiting up to 3 minutes for you to reach your Facebook feed...")

        # Wait until not on login/checkpoint page (max 3 min)
        for _ in range(180):
            await asyncio.sleep(1)
            url = page.url
            if url and not any(kw in url for kw in ("login", "checkpoint", "recover", "two_step", "about:blank")):
                print(f"\nFeed detected: {url[:80]}")
                break
        else:
            print("\nTimed out waiting for login. Exiting.")
            return

        # Extra wait for all cookies to be set
        await asyncio.sleep(3)
        cookies = await page.context.cookies()

        with open(FB_COOKIES_PATH, "w") as f:
            json.dump(cookies, f)

        print(f"Saved {len(cookies)} cookies to {FB_COOKIES_PATH}")
        print()
        print("Done. The scraper will now use these cookies automatically.")
        print("Re-run this script if the scraper reports login errors again.")

asyncio.run(setup())
