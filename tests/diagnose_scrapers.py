"""
Scraper Diagnostic
------------------
Tests each site with a warmed session and reports:
  - HTTP status code
  - Final URL after redirects
  - Response size
  - Whether it looks like a real page or a bot-block

Run:
    python tests/diagnose_scrapers.py
"""

import sys, os, time, random, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SITES = [
    {
        "name": "NoBroker",
        "home": "https://www.nobroker.in",
        "search": "https://www.nobroker.in/property/residential/rent/pune/kothrud?budget=10000,25000",
    },
    {
        "name": "Housing",
        "home": "https://housing.com",
        "search": "https://housing.com/in/rent/flats-in-kothrud-pune",
    },
    {
        "name": "MagicBricks",
        "home": "https://www.magicbricks.com",
        "search": "https://www.magicbricks.com/property-for-rent/residential-real-estate?City=Pune",
    },
    {
        "name": "SquareYards",
        "home": "https://www.squareyards.com",
        "search": "https://www.squareyards.com/pune/kothrud-property-for-rent",
    },
    {
        "name": "99Acres",
        "home": "https://www.99acres.com",
        "search": "https://www.99acres.com/property-for-rent-in-kothrud-9",
    },
]

BOT_KEYWORDS = [
    "captcha", "cloudflare", "checking your browser", "enable javascript",
    "access denied", "403 forbidden", "bot", "robot", "verify you are human",
    "please wait", "just a moment", "ddos", "ray id",
]

LISTING_KEYWORDS = [
    "bhk", "rent", "furnish", "bedroom", "bathroom", "sqft", "sq ft",
    "deposit", "monthly", "property", "locality",
]


def diagnose(site: dict):
    name = site["name"]
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")

    session = requests.Session()
    h = {**HEADERS}

    # Step 1: Homepage (session warm)
    try:
        r0 = session.get(site["home"], headers=h, timeout=20, allow_redirects=True)
        print(f"  Homepage :  HTTP {r0.status_code}  |  {len(r0.text)} chars")
        cookies = {c.name: c.value for c in session.cookies}
        print(f"  Cookies  :  {list(cookies.keys()) if cookies else 'none'}")
        h["Referer"] = site["home"]
        time.sleep(random.uniform(1.0, 2.0))
    except Exception as e:
        print(f"  Homepage :  ERROR - {e}")

    # Step 2: Search page
    try:
        r1 = session.get(site["search"], headers=h, timeout=20, allow_redirects=True)
        print(f"  Search   :  HTTP {r1.status_code}  |  {len(r1.text)} chars")
        print(f"  Final URL:  {r1.url[:90]}")

        text_lower = r1.text.lower()

        # Check for bot detection
        bots_found = [kw for kw in BOT_KEYWORDS if kw in text_lower]
        if bots_found:
            print(f"  !! BOT BLOCK detected: {bots_found[:3]}")
        else:
            # Check for real listing content
            listings_found = [kw for kw in LISTING_KEYWORDS if kw in text_lower]
            if listings_found:
                print(f"  LISTING CONTENT found: {listings_found[:5]}")
            else:
                print(f"  No listing content detected")

        # Print a small snippet
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r1.text, "html.parser")
        title = soup.title.string.strip() if soup.title else "(no title)"
        print(f"  Page title: {title[:80]}")

    except Exception as e:
        print(f"  Search   :  ERROR - {e}")


if __name__ == "__main__":
    print("Diagnosing all scrapers (takes ~30s)...\n")
    for site in SITES:
        diagnose(site)
        time.sleep(2)

    print("\n\nDone. Share the output above to determine the fix strategy.")
