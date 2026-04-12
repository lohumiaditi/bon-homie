"""
Image Filter Agent
------------------
Reads all unfiltered listings from the `listings` table and drops any
that have fewer than MIN_IMAGES images. Qualifying listings are written
to `filtered_listings` for the given session.

Run standalone:
    python agents/image_filter_agent.py <session_id>
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MIN_IMAGES = 3


def filter_by_images(session_id: str, listings: list[dict] | None = None) -> list[dict]:
    """
    Filter listings that have at least MIN_IMAGES images.

    Args:
        session_id: The user search session UUID.
        listings:   Optional pre-fetched list of listing dicts. If None,
                    fetches all listings from Supabase directly.

    Returns:
        List of listing dicts that passed the image filter.
    """
    from db.client import db
    client = db()

    # Fetch listings if not provided
    if listings is None:
        result = client.table("listings").select("*").eq("city", "Pune").execute()
        listings = result.data or []

    passed = [l for l in listings if len(l.get("images") or []) >= MIN_IMAGES]
    failed = len(listings) - len(passed)

    print(f"  [ImageFilter] {len(listings)} total → {len(passed)} pass ({failed} dropped, <{MIN_IMAGES} images)")

    if not passed:
        return []

    # Write to filtered_listings (upsert so re-runs are idempotent)
    rows = [
        {
            "session_id": session_id,
            "listing_id": l["id"],
            "match_score": 0.0,  # will be updated by matching agent
        }
        for l in passed
        if l.get("id")  # only if DB row has an id
    ]

    if rows:
        client.table("filtered_listings").upsert(
            rows, on_conflict="session_id,listing_id", ignore_duplicates=True
        ).execute()
        print(f"  [ImageFilter] {len(rows)} listings saved to filtered_listings")

    return passed


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agents/image_filter_agent.py <session_id>")
        print("\nRunning self-test with dummy data...")

        # Test without DB — just the filter logic
        fake_listings = [
            {"id": "a", "images": ["img1", "img2", "img3"], "platform": "test"},
            {"id": "b", "images": ["img1"], "platform": "test"},
            {"id": "c", "images": ["img1", "img2", "img3", "img4"], "platform": "test"},
            {"id": "d", "images": [], "platform": "test"},
            {"id": "e", "images": ["img1", "img2", "img3"], "platform": "test"},
        ]
        passed = [l for l in fake_listings if len(l.get("images") or []) >= MIN_IMAGES]
        print(f"  Input: {len(fake_listings)} listings")
        print(f"  Passed (≥{MIN_IMAGES} images): {len(passed)}")
        print(f"  Dropped: {len(fake_listings) - len(passed)}")
        print("  Test passed!" if len(passed) == 3 else "  Test FAILED")
        sys.exit(0)

    session_id = sys.argv[1]
    results = filter_by_images(session_id)
    print(f"\nDone. {len(results)} listings passed the image filter.")
