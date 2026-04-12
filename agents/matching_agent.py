"""
Matching Agent
--------------
Two-pass filter of scraped listings against user preferences:
  Pass 1 — Hard filter (Python): price, furnishing, brokerage, occupancy, renter_type
  Pass 2 — Soft filter (Groq LLM): fuzzy area name matching

LLM fallback order: Groq → Gemini Flash-Lite → skip LLM (use rapidfuzz only)

Run standalone:
    python agents/matching_agent.py
"""

import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rapidfuzz import fuzz
from dotenv import load_dotenv
load_dotenv()


# ── LLM client setup ──────────────────────────────────────────────────────────
def _get_groq():
    from groq import Groq
    key = os.environ.get("GROQ_API_KEY")
    return Groq(api_key=key) if key else None


def _get_gemini():
    import google.generativeai as genai
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        genai.configure(api_key=key)
        return genai.GenerativeModel("gemini-2.0-flash-lite")
    return None


def llm_area_match(listing_area: str, user_areas: list[str], retries: int = 3) -> bool:
    """
    Ask LLM: does listing_area match any of user_areas?
    Falls back: Groq → Gemini → rapidfuzz.
    """
    if not listing_area:
        return False

    # Fast path: rapidfuzz check first (saves LLM calls)
    for user_area in user_areas:
        if fuzz.partial_ratio(listing_area.lower(), user_area.lower()) >= 70:
            return True

    # LLM path: handles abbreviations, typos, alternate names
    prompt = (
        f"Does the locality '{listing_area}' refer to or overlap with any of these areas: "
        f"{', '.join(user_areas)}? Answer only 'yes' or 'no'."
    )

    # Try Groq
    groq_client = _get_groq()
    if groq_client:
        for attempt in range(retries):
            try:
                resp = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=5,
                    temperature=0,
                )
                answer = resp.choices[0].message.content.strip().lower()
                return answer.startswith("yes")
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate_limit" in err_str.lower():
                    print(f"  [matching] Groq rate limit, waiting 60s...")
                    time.sleep(60)
                else:
                    print(f"  [matching] Groq error: {e}")
                    break

    # Fallback: Gemini
    try:
        gemini = _get_gemini()
        if gemini:
            resp = gemini.generate_content(prompt)
            answer = resp.text.strip().lower()
            return answer.startswith("yes")
    except Exception as e:
        print(f"  [matching] Gemini error: {e}")

    # Final fallback: pure rapidfuzz (already checked above, return False)
    return False


# ── Hard filter ───────────────────────────────────────────────────────────────
def hard_filter(listing: dict, prefs: dict) -> bool:
    """Return True if listing passes all strict filters."""

    # Price range
    price = listing.get("price")
    if price:
        if price < prefs.get("budget_min", 0):
            return False
        if price > prefs.get("budget_max", 999999):
            return False

    # Furnishing
    pref_furn = prefs.get("furnishing", "any")
    if pref_furn != "any" and listing.get("furnishing"):
        if listing["furnishing"] != pref_furn:
            return False

    # Brokerage
    pref_brok = prefs.get("brokerage", "any")
    if pref_brok != "any" and listing.get("brokerage") is not None:
        want_no_broker = (pref_brok == "no")
        listing_has_broker = listing["brokerage"]
        if want_no_broker and listing_has_broker:
            return False

    # Occupancy
    pref_occ = prefs.get("occupancy", "any")
    if pref_occ != "any" and listing.get("occupancy"):
        if listing["occupancy"] != pref_occ:
            return False

    # Renter type
    pref_renter = prefs.get("renter_type", "any")
    if pref_renter != "any" and listing.get("renter_type"):
        if listing["renter_type"] != pref_renter:
            return False

    return True


def compute_match_score(listing: dict, prefs: dict) -> float:
    """
    0.0–1.0 score of how well this listing matches preferences.
    Used by the Ranking Agent.
    """
    score = 0.5  # baseline

    # Price closeness
    price = listing.get("price")
    if price:
        mid = (prefs["budget_min"] + prefs["budget_max"]) / 2
        spread = prefs["budget_max"] - prefs["budget_min"] or 1
        price_score = max(0, 1 - abs(price - mid) / spread)
        score += price_score * 0.3

    # Furnishing exact match
    if prefs.get("furnishing") != "any" and listing.get("furnishing") == prefs.get("furnishing"):
        score += 0.2

    return min(score, 1.0)


# ── Main match function ───────────────────────────────────────────────────────
def match_listings(listings: list[dict], prefs: dict) -> list[dict]:
    """
    Filter and score listings. Returns list of listings that match prefs,
    with a `match_score` field added.
    """
    user_areas = prefs.get("areas", [])
    passed = []

    for l in listings:
        # Pass 1: hard filter
        if not hard_filter(l, prefs):
            continue

        # Pass 2: area match
        listing_area = l.get("area_name") or l.get("address") or ""
        if user_areas and not llm_area_match(listing_area, user_areas):
            continue

        l["match_score"] = compute_match_score(l, prefs)
        passed.append(l)

    return passed


def save_filtered(session_id: str, matched: list[dict]):
    """Update match_score in filtered_listings table."""
    if not matched:
        return
    from db.client import db
    client = db()
    for l in matched:
        lid = l.get("id")
        if lid:
            client.table("filtered_listings").update(
                {"match_score": l.get("match_score", 0)}
            ).eq("session_id", session_id).eq("listing_id", lid).execute()


if __name__ == "__main__":
    # Offline test — no DB or LLM needed
    fake_listings = [
        {"id": "1", "price": 15000, "furnishing": "furnished", "area_name": "Kothrud", "images": ["a","b","c"], "brokerage": False},
        {"id": "2", "price": 30000, "furnishing": "furnished", "area_name": "Baner", "images": ["a","b","c"], "brokerage": False},
        {"id": "3", "price": 18000, "furnishing": "semi-furnished", "area_name": "KP", "images": ["a","b","c"], "brokerage": False},
        {"id": "4", "price": 14000, "furnishing": "unfurnished", "area_name": "Kothrud", "images": ["a","b","c"], "brokerage": False},
    ]
    test_prefs = {
        "areas": ["Kothrud", "Koregaon Park"],
        "budget_min": 10000, "budget_max": 20000,
        "furnishing": "any", "brokerage": "any",
        "renter_type": "any", "occupancy": "any",
    }
    results = match_listings(fake_listings, test_prefs)
    print(f"Matched {len(results)} / {len(fake_listings)} listings")
    for r in results:
        print(f"  {r['area_name']} | Rs.{r['price']} | score={r.get('match_score', 0):.2f}")
