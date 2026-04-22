"""Quick pipeline test: 1 area, 4 sites, no Supabase."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.scrapers.nobroker_api import NoBrokerApiScraper
from agents.scrapers.ninetynineacres import NinetyNineAcresScraper
from agents.scrapers.magicbricks import MagicBricksScraper
from agents.scrapers.squareyards import SquareYardsScraper

prefs = {"areas": ["Baner"], "budget_min": 5000, "budget_max": 120000,
         "furnishing": "any", "city": "Pune"}

all_listings = []
for ScraperCls in [NoBrokerApiScraper, MagicBricksScraper, SquareYardsScraper, NinetyNineAcresScraper]:
    name = ScraperCls.__name__
    try:
        s = ScraperCls()
        listings = s.scrape(prefs, max_pages=1)
        print(f"{name}: {len(listings)} listings")
        all_listings.extend(listings)
    except Exception as e:
        print(f"{name}: ERROR {e}")
    time.sleep(1)

by_id = {}
for l in all_listings:
    lid = l.get("listing_id", "")
    if lid and lid not in by_id:
        by_id[lid] = l

print(f"\nUnique listings from Baner x 4 sites: {len(by_id)}")
by_plat = {}
for l in by_id.values():
    p = l.get("platform", "?")
    by_plat[p] = by_plat.get(p, 0) + 1
print(f"By platform: {by_plat}")

if by_id:
    sample = list(by_id.values())[0]
    print(f"\nSample: [{sample['platform']}] Rs.{sample['price']} | {sample['title'][:50]} | {len(sample['images'])} imgs")
