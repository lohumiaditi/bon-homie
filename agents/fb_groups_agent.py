"""
Facebook Groups Agent
---------------------
Keeps a Facebook account's rental-group pipeline fed:

  discover  search Facebook for Pune rental groups, score them for relevance
            and add the good ones to the account's group list
  join      ask to join the most relevant groups the account isn't in yet.
            Opt-in (fb_connections.auto_join, or FB_AUTO_JOIN=1 for the
            system account) and capped at MAX_JOINS_PER_RUN per run
  harvest   read the newest posts in the account's groups, keep the ones
            offering a flat/room (not people looking for one), save them as
            leads, and save priced ones as listings for the search pipeline

It never posts, comments or messages anyone.

Where state lives: Supabase (agents/facebook/store.py) by default, or one
JSON file with --state (agents/facebook/file_store.py) — no database needed.

Run:
  python -m agents.fb_groups_agent run                   # system account
  python -m agents.fb_groups_agent run --user <uuid>     # one connected user
  python -m agents.fb_groups_agent run --all             # system + every connected user
  python -m agents.fb_groups_agent run --state data.json # system account, file state
  python -m agents.fb_groups_agent discover --dry-run --areas Baner,Wakad
  (--tasks discover,join,harvest picks tasks for "run"; --dry-run writes nothing)
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from agents.facebook.parsing import (
    RELEVANCE_THRESHOLD,
    build_group_queries,
    group_key_from_url,
    post_to_listing,
    score_group,
)
from agents.facebook.session import (
    SYSTEM_OWNER,
    FacebookSessionError,
    FacebookSessionExpired,
    invalidate_session,
    load_session,
    persist_session,
)

TASKS = ("discover", "join", "harvest")
DEFAULT_TASKS = ("discover", "harvest")

MAX_DISCOVERY_QUERIES = 6
MAX_JOINS_PER_RUN = 2
JOIN_MIN_RELEVANCE = 6.0
MAX_GROUPS_PER_HARVEST = 8
MAX_POSTS_PER_GROUP = 40
RUN_TIMEOUT_S = 20 * 60
JOIN_ANSWER = "Looking for a rental flat in Pune for myself."


@dataclass
class RunReport:
    owner: str
    tasks: list[str]
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    groups_found: int = 0
    groups_added: int = 0
    joins_requested: list[str] = field(default_factory=list)
    groups_harvested: int = 0
    posts_seen: int = 0
    leads_new: int = 0
    listings_saved: int = 0
    session_expired: bool = False
    errors: list[str] = field(default_factory=list)


def lead_from_listing(listing: dict, post: dict, group: dict | None, source: str) -> dict:
    return {
        "post_id": post["post_id"],
        "group_id": (group or {}).get("id"),
        "source": source,
        "url": listing.get("url") or "",
        "text": listing.get("fb_post_text", "")[:2000],
        "price": listing.get("price"),
        "area_name": listing.get("area_name"),
        "contact": listing.get("contact") or None,
        "poster_name": listing.get("fb_poster_name") or None,
        "poster_url": listing.get("fb_poster_url") or None,
        "images": listing.get("images") or [],
        "furnishing": listing.get("furnishing"),
        "gender": listing.get("gender"),
        "occupancy": listing.get("occupancy"),
        "brokerage": listing.get("brokerage"),
    }


# ── Tasks ─────────────────────────────────────────────────────────────────────
# `st` is the state store (store module or FileStore); None means dry run.

async def _discover(page, st, owner: str, prefs: dict, report: RunReport) -> None:
    from agents.facebook.actions import fetch_group_search
    from agents.facebook.browser import pause

    found: dict[str, dict] = {}
    for query in build_group_queries(prefs)[:MAX_DISCOVERY_QUERIES]:
        try:
            groups = await fetch_group_search(page, query)
        except FacebookSessionError:
            raise
        except Exception as e:
            report.errors.append(f"group search '{query}': {e}")
            continue
        for g in groups:
            g["relevance"] = score_group(g["name"], g.get("description", ""), g.get("member_count"))
            if g["group_key"] not in found or (g.get("member_count") or 0) > (found[g["group_key"]].get("member_count") or 0):
                found[g["group_key"]] = g
        await pause(2_500, 5_000)

    relevant = sorted(
        (g for g in found.values() if g["relevance"] >= RELEVANCE_THRESHOLD),
        key=lambda g: g["relevance"], reverse=True,
    )
    report.groups_found = len(found)
    if st is None:
        for g in relevant:
            print(f"    {g['relevance']:>5}  {g['name'][:60]:60}  {g.get('member_count') or '?':>8}  {g['url']}")
        report.groups_added = len(relevant)
        return

    rows = st.upsert_groups(relevant)
    report.groups_added = st.link_groups(owner, [r["id"] for r in rows.values()], "discovered")


async def _join(page, st, owner: str, report: RunReport) -> None:
    from agents.facebook.actions import join_group
    from agents.facebook.browser import pause

    if st is None:
        return
    for g in st.groups_to_join(owner, MAX_JOINS_PER_RUN, JOIN_MIN_RELEVANCE):
        try:
            state = await join_group(page, g["url"], JOIN_ANSWER)
        except FacebookSessionError:
            raise
        except Exception as e:
            report.errors.append(f"join {g['url']}: {e}")
            continue
        fields = {"membership": state}
        if state != "member":
            fields["join_requested_at"] = datetime.now(timezone.utc).isoformat()
            report.joins_requested.append(g.get("name") or g["group_key"])
        st.update_user_group(owner, g["id"], **fields)
        await pause(20_000, 45_000)


async def _harvest(page, st, owner: str, report: RunReport) -> None:
    from agents.facebook.actions import fetch_group_feed
    from agents.facebook.browser import pause
    from agents.scrapers.facebook_agent import PUNE_RENTAL_GROUPS

    if st is None:
        groups = [{"id": None, "url": u, "group_key": group_key_from_url(u)} for u in PUNE_RENTAL_GROUPS[:3]]
    else:
        st.ensure_seed_groups(owner, PUNE_RENTAL_GROUPS)
        groups = st.groups_for_harvest(owner, MAX_GROUPS_PER_HARVEST)

    for g in groups:
        try:
            membership, posts = await fetch_group_feed(page, g["url"], MAX_POSTS_PER_GROUP)
        except FacebookSessionError:
            raise
        except Exception as e:
            report.errors.append(f"harvest {g['url']}: {e}")
            continue

        report.groups_harvested += 1
        report.posts_seen += len(posts)
        leads, listings = [], []
        for post in posts:
            listing = post_to_listing(post)
            if listing is None:
                continue
            leads.append(lead_from_listing(listing, post, g, "group"))
            if listing.get("price"):
                listings.append(listing)

        if st is None:
            for lead in leads:
                print(f"    Rs.{lead['price'] or '?':>7}  {lead['area_name'] or '':15}  "
                      f"{lead['contact'] or '':14}  {lead['text'][:60]}")
            report.leads_new += len(leads)
        else:
            new = st.save_leads(owner, leads)
            report.leads_new += new
            if listings:
                report.listings_saved += st.save_listings(listings)
            fields = {
                "last_harvested_at": datetime.now(timezone.utc).isoformat(),
                "leads_found": (g.get("leads_found") or 0) + new,
            }
            if membership != "unknown":
                fields["membership"] = membership
            st.update_user_group(owner, g["id"], **fields)
        await pause(3_000, 7_000)


# ── Runner ────────────────────────────────────────────────────────────────────

def _join_allowed(st, user_id: str | None) -> bool:
    if st is None:
        return False
    if user_id is None:
        return os.environ.get("FB_AUTO_JOIN") == "1"
    return bool((st.get_connection(user_id) or {}).get("auto_join"))


def run_agent(
    user_id: str | None = None,
    tasks=DEFAULT_TASKS,
    prefs: dict | None = None,
    dry_run: bool = False,
    store=None,
) -> dict:
    """
    Run the agent for one account. Returns the run report as a dict.
    `store` defaults to Supabase (agents.facebook.store); pass a FileStore to
    keep state in a file. dry_run reads Facebook but writes nothing.
    """
    from agents.facebook.browser import open_page, run_sync

    if dry_run:
        st = None
    elif store is not None:
        st = store
    else:
        from agents.facebook import store as st

    tasks = [t for t in TASKS if t in tasks]
    owner = user_id or SYSTEM_OWNER
    report = RunReport(owner=owner, tasks=tasks)
    session = load_session(user_id=user_id, allow_system=user_id is None)

    if session is None:
        report.errors.append("No Facebook session for this account. Connect Facebook first.")
    else:
        if "join" in tasks and not _join_allowed(st, user_id):
            tasks.remove("join")
            report.tasks = tasks

        async def _run():
            async with open_page(session) as page:
                if "discover" in tasks:
                    await _discover(page, st, owner, prefs or {}, report)
                if "join" in tasks:
                    await _join(page, st, owner, report)
                if "harvest" in tasks:
                    await _harvest(page, st, owner, report)

        try:
            run_sync(_run, timeout=RUN_TIMEOUT_S)
            persist_session(session)
        except FacebookSessionExpired as e:
            invalidate_session(session, str(e))
            report.session_expired = True
            report.errors.append("Facebook logged this session out. Reconnect with fresh cookies.")
        except TimeoutError:
            report.errors.append(f"Run stopped after {RUN_TIMEOUT_S // 60} minutes.")
        except Exception as e:
            report.errors.append(f"Run failed: {e!r}")

    report.finished_at = datetime.now(timezone.utc).isoformat()
    result = asdict(report)
    if st is not None:
        try:
            if hasattr(st, "finish_run"):
                st.finish_run(result)
            elif user_id:
                st.update_connection(user_id, last_run_at=report.finished_at, last_run_summary=result)
        except Exception as e:
            print(f"  [fb-agent] Couldn't save run summary: {e}")
    return result


def run_all(tasks=DEFAULT_TASKS) -> list[dict]:
    """System account (if configured) plus every connected user with harvesting on."""
    from agents.facebook import store

    results = []
    if load_session(allow_password_login=False) is not None:
        results.append(run_agent(None, tasks))
    for conn in store.list_connections():
        if conn.get("harvest_enabled", True):
            results.append(run_agent(conn["user_id"], tasks))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Facebook rental-groups agent")
    parser.add_argument("command", choices=("run",) + TASKS)
    parser.add_argument("--user", help="users.id of a connected account")
    parser.add_argument("--all", action="store_true", help="system account + every connected user")
    parser.add_argument("--tasks", default=",".join(DEFAULT_TASKS), help="for 'run': comma-separated tasks")
    parser.add_argument("--areas", default="", help="comma-separated areas to focus discovery on")
    parser.add_argument("--state", help="keep state in this JSON file instead of Supabase (system account)")
    parser.add_argument("--dry-run", action="store_true", help="print results, write nothing")
    args = parser.parse_args(argv)

    tasks = tuple(t.strip() for t in args.tasks.split(",")) if args.command == "run" else (args.command,)
    unknown = set(tasks) - set(TASKS)
    if unknown:
        parser.error(f"unknown task(s): {', '.join(sorted(unknown))}")
    prefs = {"areas": [a.strip() for a in args.areas.split(",") if a.strip()]}

    if args.state and (args.all or args.user):
        parser.error("--state runs the system account only; don't combine it with --all or --user")
    if args.all:
        results = run_all(tasks)
    elif args.state:
        from agents.facebook.file_store import FileStore
        results = [run_agent(None, tasks, prefs, dry_run=args.dry_run, store=FileStore(args.state))]
    else:
        results = [run_agent(args.user, tasks, prefs, dry_run=args.dry_run)]
    print(json.dumps(results, indent=2))
    return 1 if any(r["session_expired"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
