"""
Scraper Orchestrator
--------------------
Runs all site scrapers in parallel using threads (sync Playwright).
Deduplicates results across platforms.

Run standalone:
    python agents/scraper_orchestrator.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import fuzz
from agents.scrapers.ninetynineacres import NinetyNineAcresScraper
from agents.scrapers.nobroker import NoBrokerScraper
from agents.scrapers.housing import HousingScraper
from agents.scrapers.magicbricks import MagicBricksScraper
from agents.scrapers.squareyards import SquareYardsScraper
from agents.scrapers.facebook import scrape_facebook
from agents.scrapers.base import save_listings

DEDUP_THRESHOLD = 85


def deduplicate(listings: list[dict]) -> list[dict]:
    """Remove near-duplicate listings across platforms."""
    unique = []
    for listing in listings:
        addr = (listing.get("address") or listing.get("area_name") or "").lower()
        price = listing.get("price") or 0
        is_dup = False
        for existing in unique:
            ex_addr = (existing.get("address") or existing.get("area_name") or "").lower()
            ex_price = existing.get("price") or 0
            if fuzz.ratio(addr, ex_addr) > DEDUP_THRESHOLD:
                if price and ex_price and abs(price - ex_price) / max(price, ex_price) < 0.10:
                    is_dup = True
                    break
        if not is_dup:
            unique.append(listing)
    return unique


def _run_scraper(scraper_cls, prefs: dict, max_pages: int = 2) -> list[dict]:
    """Run one scraper in a thread, catch errors."""
    try:
        scraper = scraper_cls(headless=True)
        return scraper.scrape(prefs, max_pages=max_pages)
    except Exception as e:
        print(f"  [orchestrator] {scraper_cls.__name__} failed: {e}")
        return []


def orchestrate(prefs: dict) -> list[dict]:
    """
    Run all scrapers in parallel threads and return deduplicated listings.
    """
    print("\n[Orchestrator] Starting all scrapers in parallel...")

    scraper_classes = [
        NinetyNineAcresScraper,
        NoBrokerScraper,
        HousingScraper,
        MagicBricksScraper,
        SquareYardsScraper,
    ]

    all_listings = []

    # Run Playwright scrapers in parallel threads
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_run_scraper, cls, prefs): cls.__name__
            for cls in scraper_classes
        }
        for future in as_completed(futures):
            name = futures[future]
            result = future.result()
            print(f"  [orchestrator] {name}: {len(result)} listings")
            all_listings.extend(result)

    # Facebook (Apify — sync HTTP call, run in main thread)
    fb_listings = scrape_facebook(prefs)
    all_listings.extend(fb_listings)

    print(f"\n[Orchestrator] Total raw: {len(all_listings)}")
    unique = deduplicate(all_listings)
    print(f"[Orchestrator] After dedup: {len(unique)} unique listings")
    return unique


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    test_prefs = {
        "city": "Pune",
        "areas": ["Kothrud"],
        "budget_min": 10000,
        "budget_max": 22000,
        "furnishing": "any",
    }

    listings = orchestrate(test_prefs)
    print(f"\n=== FINAL: {len(listings)} unique listings ===")
    print(f"With 3+ images: {sum(1 for l in listings if len(l.get('images') or []) >= 3)}")

    save_choice = input("\nSave all to Supabase? (y/n) [n]: ").strip().lower()
    if save_choice == "y":
        count = save_listings(listings)
        print(f"Saved {count} new listings.")
