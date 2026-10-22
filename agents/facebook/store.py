"""
Facebook persistence (Supabase)
-------------------------------
Tables (db/migrations/001_facebook_groups_agent.sql):
  fb_connections  one per user: encrypted session cookies + agent settings
  fb_groups       shared catalog of rental groups anyone has discovered
  fb_user_groups  per-account view of a group: membership, enabled, last harvest
  fb_leads        rental offers pulled from group posts, per account

"owner" is a users.id, or "system" for the shared FB_COOKIES_JSON / file session.
"""

import json
from datetime import datetime, timezone

from agents.facebook.parsing import RELEVANCE_THRESHOLD, group_key_from_url, group_url, score_group


def _db():
    from db.client import db
    return db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Connections ───────────────────────────────────────────────────────────────

def get_connection(user_id: str) -> dict | None:
    rows = _db().table("fb_connections").select("*").eq("user_id", user_id).execute().data
    return rows[0] if rows else None


def decrypt_cookies(row: dict) -> list[dict] | None:
    from agents.auth_agent import decrypt
    try:
        cookies = json.loads(decrypt(row.get("cookies_enc", "")))
    except (ValueError, TypeError):
        return None
    return cookies if isinstance(cookies, list) and cookies else None


def save_connection(user_id: str, cookies: list[dict], status: str, status_detail: str) -> dict:
    from agents.auth_agent import encrypt
    now = _now()
    row = {
        "user_id": user_id,
        "fb_user_id": next((c["value"] for c in cookies if c["name"] == "c_user"), None),
        "cookies_enc": encrypt(json.dumps(cookies)),
        "status": status,
        "status_detail": status_detail,
        "connected_at": now,
        "verified_at": now if status == "active" else None,
    }
    result = _db().table("fb_connections").upsert(row, on_conflict="user_id").execute()
    return result.data[0] if result.data else row


def update_connection(user_id: str, **fields) -> None:
    _db().table("fb_connections").update(fields).eq("user_id", user_id).execute()


def mark_connection_healthy(user_id: str, cookies: list[dict]) -> None:
    from agents.auth_agent import encrypt
    update_connection(
        user_id,
        cookies_enc=encrypt(json.dumps(cookies)),
        status="active",
        status_detail="Session is logged in.",
        verified_at=_now(),
    )


def delete_connection(user_id: str) -> None:
    client = _db()
    client.table("fb_user_groups").delete().eq("owner_key", user_id).execute()
    client.table("fb_connections").delete().eq("user_id", user_id).execute()


def list_connections(statuses=("active", "unverified")) -> list[dict]:
    return (
        _db().table("fb_connections")
        .select("user_id,status,auto_join,harvest_enabled")
        .in_("status", list(statuses))
        .execute()
        .data
        or []
    )


# ── Group catalog ─────────────────────────────────────────────────────────────

_GROUP_FIELDS = ("name", "privacy", "member_count", "activity")


def upsert_groups(groups: list[dict]) -> dict[str, dict]:
    """Add/refresh catalog rows. Returns {group_key: row} for every input group."""
    if not groups:
        return {}
    client = _db()
    keys = list({g["group_key"] for g in groups})
    existing = {
        r["group_key"]: r
        for r in client.table("fb_groups").select("*").in_("group_key", keys).execute().data or []
    }
    now = _now()
    rows = {}
    for g in groups:
        old = existing.get(g["group_key"], {})
        row = {
            "group_key": g["group_key"],
            "url": g.get("url") or group_url(g["group_key"]),
            "last_seen_at": now,
        }
        for field in _GROUP_FIELDS:
            row[field] = g.get(field) or old.get(field)
        row["relevance"] = g.get("relevance", old.get("relevance") or 0)
        rows[g["group_key"]] = row
    result = client.table("fb_groups").upsert(list(rows.values()), on_conflict="group_key").execute()
    return {r["group_key"]: r for r in result.data or []}


def link_groups(owner: str, group_ids: list[str], added_by: str) -> int:
    """Put catalog groups on an account's list (existing links are left alone). Returns # new."""
    if not group_ids:
        return 0
    client = _db()
    already = {
        r["group_id"]
        for r in client.table("fb_user_groups").select("group_id")
        .eq("owner_key", owner).in_("group_id", group_ids).execute().data or []
    }
    new_ids = [gid for gid in group_ids if gid not in already]
    if new_ids:
        client.table("fb_user_groups").insert(
            [{"owner_key": owner, "group_id": gid, "added_by": added_by} for gid in new_ids]
        ).execute()
    return len(new_ids)


def add_group_by_url(owner: str, url: str, added_by: str = "user") -> dict:
    key = group_key_from_url(url)
    if not key:
        raise ValueError("That isn't a Facebook group link (expected facebook.com/groups/...).")
    rows = upsert_groups([{"group_key": key, "url": group_url(key), "name": key,
                           "relevance": score_group(key.replace(".", " "))}])
    row = rows[key]
    link_groups(owner, [row["id"]], added_by)
    return row


def seed_rows(urls: list[str]) -> list[dict]:
    seeds = []
    for url in urls:
        key = group_key_from_url(url)
        if key:
            seeds.append({"group_key": key, "url": group_url(key), "name": key,
                          "relevance": score_group(key)})
    return seeds


def ensure_seed_groups(owner: str, urls: list[str]) -> None:
    """Add seed groups the catalog doesn't have yet (known ones keep their real names)."""
    seeds = seed_rows(urls)
    if not seeds:
        return
    client = _db()
    known = {
        r["group_key"]: r
        for r in client.table("fb_groups").select("id,group_key")
        .in_("group_key", [g["group_key"] for g in seeds]).execute().data or []
    }
    known.update(upsert_groups([g for g in seeds if g["group_key"] not in known]))
    link_groups(owner, [r["id"] for r in known.values()], "seed")


def list_user_groups(owner: str) -> list[dict]:
    """The account's groups, catalog fields merged in, most relevant first."""
    client = _db()
    links = client.table("fb_user_groups").select("*").eq("owner_key", owner).execute().data or []
    if not links:
        return []
    catalog = {
        g["id"]: g
        for g in client.table("fb_groups").select("*")
        .in_("id", [l["group_id"] for l in links]).execute().data or []
    }
    merged = []
    for link in links:
        group = catalog.get(link["group_id"])
        if group:
            merged.append({**group, **link, "id": group["id"]})
    merged.sort(key=lambda g: (g.get("relevance") or 0), reverse=True)
    return merged


def update_user_group(owner: str, group_id: str, **fields) -> None:
    _db().table("fb_user_groups").update(fields).eq("owner_key", owner).eq("group_id", group_id).execute()


def worth_reading(g: dict) -> bool:
    if not g.get("enabled", True) or g.get("membership") == "pending":
        return False
    if g.get("membership") == "not_member" and g.get("privacy") == "private":
        return False
    return g.get("added_by") in ("seed", "user") or (g.get("relevance") or 0) >= RELEVANCE_THRESHOLD


def groups_for_harvest(owner: str, limit: int) -> list[dict]:
    """Readable groups, least recently harvested first."""
    groups = [g for g in list_user_groups(owner) if worth_reading(g)]
    groups.sort(key=lambda g: g.get("last_harvested_at") or "")
    return groups[:limit]


def join_candidate(g: dict, min_relevance: float) -> bool:
    return (
        g.get("enabled", True)
        and g.get("membership") in ("not_member", "unknown")
        and not g.get("join_requested_at")
        and (g.get("relevance") or 0) >= min_relevance
    )


def groups_to_join(owner: str, limit: int, min_relevance: float) -> list[dict]:
    """Relevant groups the account isn't in and hasn't asked to join yet."""
    return [g for g in list_user_groups(owner) if join_candidate(g, min_relevance)][:limit]


# ── Leads ─────────────────────────────────────────────────────────────────────

LEAD_STATUSES = ("new", "shortlisted", "contacted", "dismissed")


def save_leads(owner: str, leads: list[dict]) -> int:
    """Insert leads not seen before (existing ones keep their status). Returns # new."""
    if not leads:
        return 0
    client = _db()
    post_ids = [l["post_id"] for l in leads]
    seen = {
        r["post_id"]
        for r in client.table("fb_leads").select("post_id")
        .eq("owner_key", owner).in_("post_id", post_ids).execute().data or []
    }
    fresh = {l["post_id"]: {**l, "owner_key": owner} for l in leads if l["post_id"] not in seen}
    if fresh:
        client.table("fb_leads").upsert(
            list(fresh.values()), on_conflict="owner_key,post_id", ignore_duplicates=True
        ).execute()
    return len(fresh)


def list_leads(owner: str, status: str | None = None, limit: int = 100) -> list[dict]:
    query = _db().table("fb_leads").select("*").eq("owner_key", owner)
    if status:
        query = query.eq("status", status)
    return query.order("created_at", desc=True).limit(limit).execute().data or []


def save_listings(listings: list[dict]) -> int:
    """Priced leads also go to the listings table so searches pick them up."""
    from agents.scrapers.base import save_listings as _save
    return _save(listings)


def update_lead(owner: str, lead_id: str, **fields) -> dict | None:
    result = _db().table("fb_leads").update(fields).eq("owner_key", owner).eq("id", lead_id).execute()
    return result.data[0] if result.data else None
