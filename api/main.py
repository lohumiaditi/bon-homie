"""
FastAPI Backend
---------------
Orchestrates the full pipeline and serves results to the frontend.

Endpoints:
  POST /search              → start pipeline, returns session_id
  GET  /status/{session_id} → pipeline progress
  GET  /results/{session_id}→ ranked listings JSON
  GET  /enquire/{listing_id}→ WhatsApp link for a listing
  GET  /health              → health check

Run:
    uvicorn api.main:app --reload --port 8000
"""

import asyncio
import os
import sys
import uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response, Cookie, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import quote
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Flat Hunter API", version="1.0.0")

# Allow local React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session status (resets on server restart — fine for MVP)
session_status: dict[str, dict] = {}


# ── Request/Response models ───────────────────────────────────────────────────
class SearchRequest(BaseModel):
    areas: list[str]
    budget_min: int
    budget_max: int
    furnishing: str = "any"
    renter_type: str = "any"
    gender: str = "any"
    occupancy: str = "any"
    brokerage: str = "any"
    destination_address: Optional[str] = None
    # New fields from redesigned form
    flat_type: str = "whole"          # 'whole' | 'preoccupied'
    flatmate_gender: str = "any"      # 'any' | 'male' | 'female' | 'same'


class StatusResponse(BaseModel):
    session_id: str
    status: str       # queued | scraping | filtering | ranking | done | error
    message: str
    progress: int     # 0–100


# ── Pipeline runner ───────────────────────────────────────────────────────────
def run_pipeline(session_id: str, prefs: dict):
    """Full pipeline: scrape → filter → match → metro → contact → rank → save."""
    try:
        # 1. Save preferences
        session_status[session_id] = {"status": "scraping", "message": "Scraping listings...", "progress": 10}
        from agents.input_agent import UserPreferences
        from db.client import db
        client = db()
        client.table("user_preferences").insert({
            "id": session_id,
            "city": "Pune",
            "areas": prefs["areas"],
            "budget_min": prefs["budget_min"],
            "budget_max": prefs["budget_max"],
            "furnishing": prefs["furnishing"],
            "renter_type": prefs["renter_type"],
            "gender": prefs["gender"],
            "occupancy": prefs["occupancy"],
            "brokerage": prefs["brokerage"],
            "destination_address": prefs.get("destination_address"),
            "flat_type": prefs.get("flat_type", "whole"),
            "flatmate_gender": prefs.get("flatmate_gender", "any"),
        }).execute()

        # 2. Scrape
        from agents.scraper_orchestrator import orchestrate
        raw_listings = orchestrate(prefs)
        session_status[session_id] = {"status": "filtering", "message": f"Scraped {len(raw_listings)} listings. Filtering...", "progress": 40}

        # 3. Save raw listings to DB
        from agents.scrapers.base import save_listings
        save_listings(raw_listings)

        # 4. Image filter
        from agents.image_filter_agent import filter_by_images
        image_passed = filter_by_images(session_id, raw_listings)
        session_status[session_id] = {"status": "filtering", "message": f"{len(image_passed)} passed image filter. Matching...", "progress": 55}

        # 5. Matching
        from agents.matching_agent import match_listings, save_filtered
        matched = match_listings(image_passed, prefs)
        save_filtered(session_id, matched)
        session_status[session_id] = {"status": "ranking", "message": f"{len(matched)} matched. Finding metro stations...", "progress": 70}

        # 6. Contact extraction
        from agents.contact_agent import extract_contacts_bulk
        matched = extract_contacts_bulk(matched)

        # 7. Metro enrichment
        from agents.metro_agent import enrich_listings_with_metro
        destination_station = _nearest_destination_station(prefs.get("destination_address"))
        matched = enrich_listings_with_metro(matched, destination_station)
        session_status[session_id] = {"status": "ranking", "message": "Ranking results...", "progress": 85}

        # 8. Rank
        from agents.ranking_agent import rank_listings, save_ranked_results
        ranked = rank_listings(matched, prefs)
        save_ranked_results(session_id, ranked)

        session_status[session_id] = {
            "status": "done",
            "message": f"Found {len(ranked)} listings for you!",
            "progress": 100,
        }
        print(f"[pipeline] Session {session_id} done — {len(ranked)} results")

    except Exception as e:
        session_status[session_id] = {
            "status": "error",
            "message": f"Error: {str(e)}",
            "progress": 0,
        }
        print(f"[pipeline] Session {session_id} error: {e}")
        import traceback; traceback.print_exc()


def _nearest_destination_station(destination_address: str | None) -> str | None:
    """Find the nearest metro station to the user's destination."""
    if not destination_address:
        return None
    try:
        from agents.metro_agent import geocode_address, nearest_station_haversine
        coords = geocode_address(destination_address)
        if coords:
            station, _ = nearest_station_haversine(*coords)
            return station
    except Exception:
        pass
    return None


# ── Auth dependency ───────────────────────────────────────────────────────────

def get_current_user(fh_token: Optional[str] = Cookie(default=None)) -> dict:
    """
    FastAPI dependency. Reads the HTTP-only JWT cookie and returns the user dict.
    Raises 401 if missing or invalid. Use as: user = Depends(get_current_user)
    """
    if not fh_token:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    try:
        from agents.auth_agent import verify_token
        payload = verify_token(fh_token, expected_type="access")
        return {"user_id": payload["sub"], "fb_id": payload["fb_id"]}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Session expired or invalid: {e}")


# ── Facebook OAuth endpoints ──────────────────────────────────────────────────

@app.get("/auth/facebook")
def facebook_login(response: Response):
    """
    Step 1: Redirect user to Facebook OAuth consent screen.
    Sets a short-lived CSRF state cookie before redirecting.
    """
    from agents.auth_agent import generate_oauth_state, get_facebook_oauth_url, COOKIE_STATE
    state    = generate_oauth_state()
    oauth_url = get_facebook_oauth_url(state)

    redirect = RedirectResponse(url=oauth_url)
    # HTTP-only state cookie (expires in 10 min — just for the OAuth round-trip)
    redirect.set_cookie(
        key=COOKIE_STATE, value=state,
        httponly=True, secure=False, samesite="lax", max_age=600,
    )
    return redirect


@app.get("/auth/facebook/callback")
def facebook_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Step 2: Facebook redirects here after user authorises the app.
    Verifies CSRF state, exchanges code for tokens, sets JWT cookies.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")

    if error:
        return RedirectResponse(url=f"{frontend_url}?auth_error={error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter.")

    from agents.auth_agent import (
        complete_facebook_login, COOKIE_ACCESS, COOKIE_REFRESH, COOKIE_STATE
    )
    stored_state = request.cookies.get(COOKIE_STATE, "")

    try:
        user, access_token, refresh_token = complete_facebook_login(code, state, stored_state)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Facebook auth failed: {e}")

    is_prod = os.environ.get("ENV", "dev") == "prod"

    redirect = RedirectResponse(url=f"{frontend_url}?auth=success")
    # Access token — 24h, HTTP-only (XSS-safe)
    redirect.set_cookie(
        key=COOKIE_ACCESS, value=access_token,
        httponly=True, secure=is_prod, samesite="lax", max_age=86_400,
    )
    # Refresh token — 30d, HTTP-only
    redirect.set_cookie(
        key=COOKIE_REFRESH, value=refresh_token,
        httponly=True, secure=is_prod, samesite="lax", max_age=86_400 * 30,
    )
    # Clear the CSRF state cookie
    redirect.delete_cookie(COOKIE_STATE)
    return redirect


@app.post("/auth/refresh")
def refresh_session(
    response: Response,
    fh_refresh: Optional[str] = Cookie(default=None),
):
    """Issue a new access token using the refresh token (silent re-login)."""
    if not fh_refresh:
        raise HTTPException(status_code=401, detail="No refresh token.")
    try:
        from agents.auth_agent import verify_token, create_access_token, COOKIE_ACCESS
        payload      = verify_token(fh_refresh, expected_type="refresh")
        access_token = create_access_token(payload["sub"], payload["fb_id"])
        response.set_cookie(
            key=COOKIE_ACCESS, value=access_token,
            httponly=True, secure=False, samesite="lax", max_age=86_400,
        )
        return {"ok": True, "message": "Session refreshed."}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/auth/logout")
def logout(response: Response):
    """Clear all auth cookies."""
    from agents.auth_agent import COOKIE_ACCESS, COOKIE_REFRESH
    response.delete_cookie(COOKIE_ACCESS)
    response.delete_cookie(COOKIE_REFRESH)
    return {"ok": True, "message": "Logged out."}


@app.get("/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    """Return the currently logged-in user's public profile."""
    try:
        from db.client import db
        from agents.auth_agent import decrypt
        client = db()
        result = client.table("users").select("*").eq("id", user["user_id"]).execute()
        if not result.data:
            return {"user_id": user["user_id"], "fb_id": user["fb_id"]}
        row = result.data[0]
        return {
            "user_id":     row["id"],
            "fb_id":       row["fb_id"],
            "name":        decrypt(row.get("name_enc", "")),
            "email":       decrypt(row.get("email_enc", "")),
            "picture_url": row.get("picture_url", ""),
        }
    except Exception as e:
        return {"user_id": user["user_id"], "fb_id": user["fb_id"], "error": str(e)}


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "flat-hunter-api"}


@app.post("/search")
def start_search(req: SearchRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    prefs = req.model_dump()
    prefs["city"] = "Pune"

    session_status[session_id] = {
        "status": "queued",
        "message": "Search queued...",
        "progress": 0,
    }

    # Run pipeline in background thread so endpoint returns immediately
    background_tasks.add_task(
        lambda: asyncio.run(asyncio.get_event_loop().run_in_executor(None, run_pipeline, session_id, prefs))
        if False else run_pipeline(session_id, prefs)
    )

    return {"session_id": session_id, "message": "Search started"}


@app.get("/status/{session_id}", response_model=StatusResponse)
def get_status(session_id: str):
    status = session_status.get(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
    return StatusResponse(session_id=session_id, **status)


@app.get("/results/{session_id}")
def get_results(session_id: str):
    from db.client import db
    client = db()

    # Fetch ranked results joined with listing details
    ranked = client.table("ranked_results")\
        .select("rank, metro_station, walking_distance_m, metro_travel_min, total_score, listing_id")\
        .eq("session_id", session_id)\
        .order("rank")\
        .execute()

    if not ranked.data:
        raise HTTPException(status_code=404, detail="No results yet. Check /status first.")

    listing_ids = [r["listing_id"] for r in ranked.data]
    listings = client.table("listings")\
        .select("*")\
        .in_("id", listing_ids)\
        .execute()

    listings_by_id = {l["id"]: l for l in (listings.data or [])}

    results = []
    for r in ranked.data:
        l = listings_by_id.get(r["listing_id"], {})
        results.append({
            "rank": r["rank"],
            "id": r["listing_id"],
            "title": l.get("title"),
            "price": l.get("price"),
            "area": l.get("area_name"),
            "address": l.get("address"),
            "furnishing": l.get("furnishing"),
            "occupancy": l.get("occupancy"),
            "brokerage": l.get("brokerage"),
            "images": l.get("images", []),
            "contact": l.get("contact"),
            "platform": l.get("platform"),
            "url": l.get("url"),
            "metro_station": r["metro_station"],
            "walking_distance_m": r["walking_distance_m"],
            "metro_travel_min": r["metro_travel_min"],
            "score": r["total_score"],
        })

    return {"session_id": session_id, "count": len(results), "listings": results}


@app.post("/trigger-scrape")
def trigger_scrape():
    """
    Dispatches the GitHub Actions 'Scrape Pune Listings' workflow on demand.
    Requires GITHUB_TOKEN and GITHUB_REPO in .env.
    Returns {"dispatched": true} on success or raises 503 on failure.
    """
    import requests as _req

    token = os.environ.get("GITHUB_TOKEN", "")
    repo  = os.environ.get("GITHUB_REPO", "")   # e.g. "tj17a/bon-homie"

    if not token or not repo:
        raise HTTPException(
            status_code=503,
            detail="GITHUB_TOKEN or GITHUB_REPO not configured in .env",
        )

    url = f"https://api.github.com/repos/{repo}/actions/workflows/scrape.yml/dispatches"
    resp = _req.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": "main"},
        timeout=15,
    )

    if resp.status_code == 204:
        return {
            "dispatched": True,
            "message": "Scrape job triggered. New listings will appear in ~45 minutes.",
        }

    raise HTTPException(
        status_code=503,
        detail=f"GitHub API returned {resp.status_code}: {resp.text[:200]}",
    )


@app.get("/enquire/{listing_id}")
def enquire(listing_id: str):
    """Returns a pre-filled WhatsApp wa.me link for the listing."""
    from db.client import db
    client = db()
    result = client.table("listings").select("*").eq("id", listing_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Listing not found")

    l = result.data[0]
    contact = l.get("contact", "").replace("+", "").replace(" ", "")
    if not contact:
        raise HTTPException(status_code=400, detail="No contact number available for this listing")

    area = l.get("area_name") or l.get("address") or "the listed area"
    price = l.get("price")
    property_type = "flat"

    message = (
        f"Hi, I came across your {property_type} listing in {area}"
        f"{f' at ₹{price}/month' if price else ''}. "
        f"Is it still available? I am interested in visiting."
    )
    wa_url = f"https://wa.me/{contact}?text={quote(message)}"
    return {"wa_url": wa_url, "contact": l.get("contact"), "message": message}
