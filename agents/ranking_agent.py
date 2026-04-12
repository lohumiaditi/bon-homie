"""
Ranking Agent
-------------
Scores and sorts filtered listings. Lower score = better match.

Score formula:
  score = (walking_distance_m / 100) × 0.5
        + (price / budget_max) × 100 × 0.3
        + (1 - match_score) × 20 × 0.2

Returns top MAX_RESULTS listings, ranked ascending by score.

Run standalone:
    python agents/ranking_agent.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MAX_RESULTS = 20


def compute_score(listing: dict, prefs: dict) -> float:
    """Compute ranking score for a single listing. Lower = better."""
    budget_max = prefs.get("budget_max", 1) or 1
    price = listing.get("price") or budget_max
    walking_m = listing.get("walking_distance_m") or 1000  # default 1km if unknown
    match_score = listing.get("match_score", 0.5)

    metro_component = (walking_m / 100) * 0.5
    price_component = (price / budget_max) * 100 * 0.3
    match_component = (1 - match_score) * 20 * 0.2

    return metro_component + price_component + match_component


def rank_listings(listings: list[dict], prefs: dict) -> list[dict]:
    """
    Score and sort listings. Adds `total_score` and `rank` fields.
    Returns top MAX_RESULTS sorted ascending by score.
    """
    if not listings:
        return []

    for l in listings:
        l["total_score"] = compute_score(l, prefs)

    sorted_listings = sorted(listings, key=lambda x: x["total_score"])
    top = sorted_listings[:MAX_RESULTS]

    for i, l in enumerate(top, start=1):
        l["rank"] = i

    return top


def save_ranked_results(session_id: str, ranked: list[dict]):
    """Write ranked results to Supabase ranked_results table."""
    if not ranked:
        return
    from db.client import db
    client = db()
    rows = [
        {
            "session_id": session_id,
            "listing_id": l["id"],
            "rank": l["rank"],
            "metro_station": l.get("metro_station"),
            "walking_distance_m": l.get("walking_distance_m"),
            "metro_travel_min": l.get("metro_travel_min"),
            "total_score": l["total_score"],
        }
        for l in ranked
        if l.get("id")
    ]
    client.table("ranked_results").upsert(
        rows, on_conflict="session_id,listing_id", ignore_duplicates=False
    ).execute()
    print(f"  [ranking] Saved {len(rows)} ranked results to Supabase")


if __name__ == "__main__":
    # Self-test
    fake_prefs = {"budget_max": 20000, "budget_min": 10000}
    fake_listings = [
        {"id": "a", "price": 15000, "walking_distance_m": 200, "match_score": 0.9, "metro_station": "Kothrud"},
        {"id": "b", "price": 19000, "walking_distance_m": 800, "match_score": 0.7, "metro_station": "Deccan Gymkhana"},
        {"id": "c", "price": 12000, "walking_distance_m": 1500, "match_score": 0.6, "metro_station": "Nal Stop"},
        {"id": "d", "price": 18000, "walking_distance_m": 300, "match_score": 0.85, "metro_station": "Shivajinagar"},
    ]

    ranked = rank_listings(fake_listings, fake_prefs)
    print("Ranking Agent — self-test:")
    for l in ranked:
        print(f"  Rank {l['rank']}: id={l['id']} | Rs.{l['price']} | {l['walking_distance_m']}m walk | score={l['total_score']:.2f}")

    assert ranked[0]["id"] == "a", "Rank 1 should be listing 'a'"
    print("\nTest passed!")
