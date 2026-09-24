"""
Facebook scraper (search pipeline)
----------------------------------
Called per search by scraper_orchestrator and once per batch by camoufox_scraper.
In one browser session it reads:
  1. Marketplace   Pune property rentals within the budget
  2. Groups        the account's harvest-enabled rental groups (seed list if none)
  3. Post search   area keyword search across posts the account can see

Which account (agents/facebook/session.py): prefs["user_id"]'s connected
account when there is one, else FB_COOKIES_JSON / .fb_cookies.json /
FB_EMAIL+FB_PASSWORD. Returns [] when none is configured.

Finding new groups and collecting leads is agents/fb_groups_agent.py.

Outreach (send_message / post_comment / outreach_listing) is kept for manual
use only — nothing calls it automatically. Automated DMs and comments are the
fastest way to get an account restricted.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from agents.facebook.parsing import build_post_queries, post_to_listing
from agents.facebook.session import (
    FacebookSessionError,
    FacebookSessionExpired,
    invalidate_session,
    load_session,
    persist_session,
)

MAX_GROUPS_PER_SEARCH = 3
MAX_SEARCH_QUERIES = 4
MAX_POSTS_PER_PAGE = 40
SEARCH_TIMEOUT_S = 240

# Seed groups: every account starts with these on its list.
PUNE_RENTAL_GROUPS = [
    "https://www.facebook.com/groups/puneflatrentals",
    "https://www.facebook.com/groups/puneflatsforrent",
    "https://www.facebook.com/groups/rentalpuneflatrooms",
    "https://www.facebook.com/groups/PuneAccommodation",
    "https://www.facebook.com/groups/puneflatmates",
    "https://www.facebook.com/groups/puneflatsandflatmates",
    "https://www.facebook.com/groups/punerentals",
    "https://www.facebook.com/groups/pune.flat.for.rent",
    "https://www.facebook.com/groups/punehomesforrent",
    "https://www.facebook.com/groups/PuneFlatRent",
    "https://www.facebook.com/groups/puneroomrent",
    "https://www.facebook.com/groups/punepgflatmates",
]


def _groups_to_scan(owner: str) -> list[str]:
    try:
        from agents.facebook import store
        urls = [g["url"] for g in store.groups_for_harvest(owner, MAX_GROUPS_PER_SEARCH)]
        if urls:
            return urls
    except Exception as e:
        print(f"  [facebook] Group list unavailable ({e}); using seed groups.")
    return PUNE_RENTAL_GROUPS[:MAX_GROUPS_PER_SEARCH]


def scrape_facebook(prefs: dict, session=None) -> list[dict]:
    """Listings from Marketplace, groups and post search. [] when no session."""
    from agents.facebook.actions import fetch_group_feed, fetch_marketplace, fetch_post_search
    from agents.facebook.browser import open_page, pause, run_sync

    session = session or load_session(user_id=prefs.get("user_id"))
    if session is None:
        return []

    budget_min = prefs.get("budget_min", 5_000)
    budget_max = prefs.get("budget_max", 1_20_000)
    group_urls = _groups_to_scan(session.owner)
    queries = build_post_queries(prefs)[:MAX_SEARCH_QUERIES]

    async def _scrape() -> list[dict]:
        found: list[dict] = []
        async with open_page(session) as page:
            try:
                found += await fetch_marketplace(page, budget_min, budget_max)
            except FacebookSessionError:
                raise
            except Exception as e:
                print(f"  [facebook] Marketplace error: {e}")

            for url in group_urls:
                try:
                    _, posts = await fetch_group_feed(page, url, MAX_POSTS_PER_PAGE)
                    found += [l for p in posts if (l := post_to_listing(p))]
                except FacebookSessionError:
                    raise
                except Exception as e:
                    print(f"  [facebook] Group error {url}: {e}")
                await pause(2_000, 4_000)

            for query in queries:
                try:
                    posts = await fetch_post_search(page, query, MAX_POSTS_PER_PAGE)
                    found += [l for p in posts if (l := post_to_listing(p))]
                except FacebookSessionError:
                    raise
                except Exception as e:
                    print(f"  [facebook] Search error '{query[:40]}': {e}")
                await pause(1_500, 3_000)
        return found

    try:
        listings = run_sync(_scrape, timeout=SEARCH_TIMEOUT_S)
    except FacebookSessionExpired as e:
        invalidate_session(session, str(e))
        return []
    except Exception as e:
        print(f"  [facebook] Scrape failed: {e!r}")
        return []
    persist_session(session)

    unique: dict[str, dict] = {}
    for listing in listings:
        unique.setdefault(listing["listing_id"], listing)
    print(f"  [facebook] Total unique: {len(unique)} listings")
    return list(unique.values())


# ── Manual outreach ───────────────────────────────────────────────────────────

def craft_outreach_message(listing: dict) -> str:
    area = listing.get("area_name") or "Pune"
    price = listing.get("price")
    furnishing = listing.get("furnishing") or ""
    msg = f"Hi! I came across your flat listing in {area}"
    if price:
        msg += f" at Rs.{price:,}/month"
    if furnishing and furnishing != "any":
        msg += f" ({furnishing})"
    return msg + ". Is it still available? I'd love to know more or schedule a visit. Thank you!"


def _with_page(user_id, action) -> bool:
    from agents.facebook.browser import open_page, run_sync

    session = load_session(user_id=user_id)
    if session is None:
        return False

    async def _run():
        async with open_page(session) as page:
            return await action(page)

    try:
        return bool(run_sync(_run, timeout=90))
    except FacebookSessionExpired as e:
        invalidate_session(session, str(e))
    except Exception as e:
        print(f"  [facebook] Outreach error: {e!r}")
    return False


def send_message(listing_url: str, message: str, user_id: str | None = None) -> bool:
    """Messenger DM to a Marketplace seller."""
    from agents.facebook import actions
    return _with_page(user_id, lambda page: actions.send_message(page, listing_url, message))


def post_comment(post_url: str, comment: str, user_id: str | None = None) -> bool:
    """Comment on a group post."""
    from agents.facebook import actions
    return _with_page(user_id, lambda page: actions.post_comment(page, post_url, comment))


def outreach_listing(listing: dict, user_id: str | None = None) -> dict:
    """Phone → WhatsApp link; Marketplace → DM; group post → comment."""
    if listing.get("contact"):
        listing["outreach_status"] = "whatsapp_link_ready"
        return listing
    message = craft_outreach_message(listing)
    url = listing.get("url", "")
    if "marketplace/item" in url:
        ok = send_message(url, message, user_id)
        listing["outreach_status"] = "dm_sent" if ok else "dm_failed"
    elif "/groups/" in url or "/permalink" in url:
        ok = post_comment(url, message, user_id)
        listing["outreach_status"] = "comment_posted" if ok else "comment_failed"
    else:
        listing["outreach_status"] = "no_contact_method"
    return listing


if __name__ == "__main__":
    results = scrape_facebook({"areas": ["Baner", "Kothrud"], "budget_min": 10_000, "budget_max": 35_000})
    print(f"\nFacebook: {len(results)} listings")
    print(f"  With phone:  {sum(1 for r in results if r.get('contact'))}")
    print(f"  With images: {sum(1 for r in results if r.get('images'))}")
    print(f"  With price:  {sum(1 for r in results if r.get('price'))}")
    for r in results[:5]:
        print(f"  Rs.{r.get('price')} | {r.get('area_name')} | {r.get('contact') or 'no phone'} | {r['title'][:50]}")
