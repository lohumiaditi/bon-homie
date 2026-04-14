"""
Scraper Orchestrator
--------------------
Cache-first pipeline:
  1. Query Supabase for listings scraped in the last 6 hours (fast, ~100ms)
  2. If cache is warm (≥10 listings) → use cache, run Facebook scraper concurrently
  3. If cache is empty/stale → run live Camoufox scrape + Facebook concurrently

The Supabase cache is kept warm by GitHub Actions running every 4 hours.
On Python 3.14/Windows, Camoufox skips live scraping automatically, so the
local machine only ever reads from cache — no browser required locally.

Run standalone:
    python agents/scraper_orchestrator.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from rapidfuzz import fuzz
from agents.scrapers.camoufox_scraper import scrape_all_with_camoufox
from agents.scrapers.facebook import scrape_facebook
from agents.scrapers.base import save_listings

DEDUP_THRESHOLD   = 85
CACHE_MAX_AGE_H   = 6    # accept listings scraped within this many hours
CACHE_MIN_COUNT   = 10   # if fewer than this, treat cache as empty


# ── Supabase cache query ──────────────────────────────────────────────────────
def query_supabase_listings(prefs: dict, max_age_hours: int = CACHE_MAX_AGE_H) -> list[dict]:
    """
    Query Supabase for fresh cached listings matching user prefs.

    Filters:
    - city = 'Pune'
    - price BETWEEN budget_min AND budget_max
    - last_scraped_at >= now - max_age_hours  (freshness)
    - area fuzzy-matched in Python (Supabase doesn't support pg_trgm in free tier)

    Returns [] if cache is empty, stale, or query fails.
    """
    try:
        from db.client import db
        client = db()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        lo = prefs.get("budget_min", 0)
        hi = prefs.get("budget_max", 2_00_000)

        result = (
            client.table("listings")
            .select("*")
            .eq("city", "Pune")
            .gte("price", lo)
            .lte("price", hi)
            .gte("last_scraped_at", cutoff)
            .execute()
        )
        rows = result.data or []

        if not rows:
            print(f"  [orchestrator] Cache empty (cutoff: {cutoff[:16]} UTC)")
            return []

        # Post-filter by area with fuzzy matching
        user_areas = [a.lower() for a in prefs.get("areas", [])]
        if user_areas:
            matched = []
            for row in rows:
                area_text = (row.get("area_name") or row.get("address") or "").lower()
                if any(fuzz.partial_ratio(area_text, ua) >= 65 for ua in user_areas):
                    matched.append(row)
            rows = matched

        print(f"  [orchestrator] Cache hit: {len(rows)} listings (age <= {max_age_hours}h)")
        return rows

    except Exception as e:
        print(f"  [orchestrator] Cache query failed: {e}")
        return []


# ── Deduplication ─────────────────────────────────────────────────────────────
def deduplicate(listings: list[dict]) -> list[dict]:
    """Remove near-duplicate listings (same area + price within 10%)."""
    unique = []
    for listing in listings:
        addr  = (listing.get("address") or listing.get("area_name") or "").lower()
        price = listing.get("price") or 0
        is_dup = False
        for existing in unique:
            ex_addr  = (existing.get("address") or existing.get("area_name") or "").lower()
            ex_price = existing.get("price") or 0
            if fuzz.ratio(addr, ex_addr) > DEDUP_THRESHOLD:
                if price and ex_price:
                    if abs(price - ex_price) / max(price, ex_price) < 0.10:
                        is_dup = True
                        break
        if not is_dup:
            unique.append(listing)
    return unique


# ── Main pipeline entry point ─────────────────────────────────────────────────
def orchestrate(prefs: dict) -> list[dict]:
    """
    Cache-first orchestration. Called by api/main.py's run_pipeline().
    """
    print("\n[Orchestrator] Starting (cache-first)...")
    all_listings = []

    cached = query_supabase_listings(prefs)
    cache_ok = len(cached) >= CACHE_MIN_COUNT

    if cache_ok:
        print(f"  [orchestrator] Cache warm ({len(cached)} listings). Running Facebook only.")
        all_listings.extend(cached)
        try:
            fb = scrape_facebook(prefs)
            all_listings.extend(fb)
            print(f"  [orchestrator] Facebook: {len(fb)} listings")
        except Exception as e:
            print(f"  [orchestrator] Facebook failed: {e}")

    else:
        print("  [orchestrator] Cache miss. Running live Camoufox + Facebook.")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(scrape_all_with_camoufox, prefs, 1): "Camoufox",
                executor.submit(scrape_facebook, prefs):              "Facebook",
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    print(f"  [orchestrator] {name}: {len(result)} listings")
                    all_listings.extend(result)
                except Exception as e:
                    print(f"  [orchestrator] {name} failed: {e}")

    print(f"\n[Orchestrator] Raw total    : {len(all_listings)}")
    unique = deduplicate(all_listings)
    print(f"[Orchestrator] After dedup  : {len(unique)}")

    by_platform = {}
    for l in unique:
        by_platform[l.get("platform", "?")] = by_platform.get(l.get("platform", "?"), 0) + 1
    for p, c in sorted(by_platform.items()):
        print(f"  {p:15} {c}")

    return unique


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    test_prefs = {
        "city": "Pune",
        "areas": ["Kothrud"],
        "budget_min": 10000,
        "budget_max": 25000,
        "furnishing": "any",
    }
    listings = orchestrate(test_prefs)
    print(f"\n=== FINAL: {len(listings)} unique listings ===")
    print(f"With 3+ images: {sum(1 for l in listings if len(l.get('images') or []) >= 3)}")

    save_choice = input("\nSave to Supabase? (y/n) [n]: ").strip().lower()
    if save_choice == "y":
        count = save_listings(listings)
        print(f"Saved {count} listings.")
