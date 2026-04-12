"""
Scraper Orchestrator
--------------------
Runs all site scrapers in parallel and deduplicates results.

Run standalone:
    python agents/scraper_orchestrator.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rapidfuzz import fuzz
from agents.scrapers.ninetynineacres import NinetyNineAcresScraper
from agents.scrapers.nobroker import NoBrokerScraper
from agents.scrapers.housing import HousingScraper
from agents.scrapers.magicbricks import MagicBricksScraper
from agents.scrapers.squareyards import SquareYardsScraper
from agents.scrapers.facebook import scrape_facebook
from agents.scrapers.base import save_listings


DEDUP_THRESHOLD = 85  # fuzzywuzzy ratio — above this = duplicate


def deduplicate(listings: list[dict]) -> list[dict]:
    """
    Remove near-duplicate listings across platforms.
    Two listings are duplicates if their address similarity > DEDUP_THRESHOLD
    AND prices are within 10% of each other.
    """
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


async def run_async_scraper(scraper_cls, prefs: dict, max_pages: int = 2) -> list[dict]:
    """Wrapper to run a single async scraper and catch errors."""
    try:
        scraper = scraper_cls(headless=True)
        return await scraper.scrape(prefs, max_pages=max_pages)
    except Exception as e:
        print(f"  [orchestrator] {scraper_cls.__name__} failed: {e}")
        return []


async def scrape_all(prefs: dict) -> list[dict]:
    """
    Run all scrapers concurrently and return deduplicated listings.
    Facebook is sync (Apify API call) so it runs in a thread.
    """
    print("\n[Orchestrator] Starting all scrapers...")

    # Run Playwright scrapers concurrently
    # Note: Each scraper opens its own browser instance
    playwright_tasks = [
        run_async_scraper(NinetyNineAcresScraper, prefs),
        run_async_scraper(NoBrokerScraper, prefs),
        run_async_scraper(HousingScraper, prefs),
        run_async_scraper(MagicBricksScraper, prefs),
        run_async_scraper(SquareYardsScraper, prefs),
    ]

    # Run Facebook in thread (sync Apify call)
    loop = asyncio.get_event_loop()
    fb_task = loop.run_in_executor(None, scrape_facebook, prefs)

    # Gather all
    results = await asyncio.gather(*playwright_tasks, return_exceptions=True)
    fb_listings = await fb_task

    all_listings = []
    scraper_names = ["99acres", "nobroker", "housing", "magicbricks", "squareyards"]
    for name, result in zip(scraper_names, results):
        if isinstance(result, Exception):
            print(f"  [orchestrator] {name} raised: {result}")
        else:
            print(f"  [orchestrator] {name}: {len(result)} listings")
            all_listings.extend(result)

    all_listings.extend(fb_listings)
    print(f"\n[Orchestrator] Total raw: {len(all_listings)}")

    # Deduplicate
    unique = deduplicate(all_listings)
    print(f"[Orchestrator] After dedup: {len(unique)} unique listings")

    return unique


def orchestrate(prefs: dict) -> list[dict]:
    """Sync wrapper — call this from non-async code."""
    return asyncio.run(scrape_all(prefs))


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
