"""Probe 99acres page for embedded JSON / XHR API endpoints."""
import sys, os, re, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from curl_cffi import requests
    session = requests.Session(impersonate="chrome")
    print("curl_cffi ok")
except ImportError:
    import requests
    session = requests.Session()
    print("WARNING: using plain requests")

session.headers.update({
    "accept-language": "en-IN,en-GB;q=0.9,en;q=0.8",
    "referer": "https://www.99acres.com/",
})

url = "https://www.99acres.com/property-for-rent-in-kothrud-pune-ffid"
print(f"GET {url}")
r = session.get(url, timeout=25, allow_redirects=True)
print(f"HTTP {r.status_code}  len={len(r.text)}")

html = r.text

# 1. Look for embedded JSON blobs (window.__*, __INITIAL_STATE__, etc.)
json_vars = re.findall(r'window\.__([A-Z_]+)\s*=\s*(\{.*?\});', html, re.S)
print(f"\nEmbedded window.__ vars: {[v[0] for v in json_vars]}")
for name, blob in json_vars[:3]:
    try:
        data = json.loads(blob)
        print(f"  window.__{name}: keys={list(data.keys())[:8]}")
    except Exception:
        print(f"  window.__{name}: not valid JSON ({len(blob)} chars)")

# 2. Look for <script id="__NEXT_DATA__">
next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
if next_data:
    print("\n__NEXT_DATA__ found!")
    try:
        nd = json.loads(next_data.group(1))
        print(f"  keys: {list(nd.keys())}")
    except Exception as e:
        print(f"  parse error: {e}")
else:
    print("\nNo __NEXT_DATA__")

# 3. Look for API endpoint strings in scripts
api_hits = re.findall(r'["\']((?:https?://[^"\']+)?/api/v\d+/[^"\']{5,80})["\']', html)
api_hits = list(dict.fromkeys(api_hits))[:20]
print(f"\nAPI endpoints in HTML ({len(api_hits)}):")
for h in api_hits:
    print(f"  {h}")

# 4. Count FSL_TUPLE cards
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, "html.parser")
cards = soup.select('[data-label^="FSL_TUPLE"]')
print(f"\nFSL_TUPLE cards in SSR HTML: {len(cards)}")

# 5. Look for any JSON blob containing 'listing' or 'property' keys
script_blobs = re.findall(r'<script[^>]*>(\{.*?\})</script>', html, re.S)
for blob in script_blobs[:5]:
    if any(k in blob for k in ['"listing"', '"property"', '"price"', '"locality"']):
        try:
            d = json.loads(blob)
            print(f"\nListing JSON in <script>: keys={list(d.keys())[:10]}")
        except Exception:
            pass

# 6. Check if there's a JSON endpoint for this area
# Try common 99acres API patterns
print("\n\n--- Probing known API patterns ---")
test_urls = [
    "https://www.99acres.com/api/v2/GNB_SEARCH_RESULTS?city=6&category=1&res_com=R",
    "https://www.99acres.com/api/v1/listings?city=6&locality=kothrud&purpose=rent",
    "https://www.99acres.com/api/v3/user/propertyListing?city=6&locality_id=kothrud",
]
for tu in test_urls:
    try:
        tr = session.get(tu, timeout=10)
        print(f"  {tr.status_code} {tu[:70]}")
        if tr.status_code == 200 and tr.headers.get("content-type","").startswith("application/json"):
            d = tr.json()
            print(f"    JSON keys: {list(d.keys())[:5]}")
    except Exception as e:
        print(f"  ERR {tu[:60]}: {e}")
