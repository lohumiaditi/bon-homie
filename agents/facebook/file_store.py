"""
Facebook agent state in a JSON file
-----------------------------------
Drop-in replacement for store.py (the functions fb_groups_agent uses) that
keeps everything for one account in a single file, so the agent can run with
no database — e.g. the daily Claude routine that refreshes the "Pune Flat
Leads" artifact: it downloads the artifact's data.json, runs
  python -m agents.fb_groups_agent run --state data.json
and publishes the updated file back.

File shape (the artifact page reads it as-is):
  {
    "schema": 1,
    "updated_at": iso,
    "groups": {group_key: {group_key, url, name, privacy, member_count, activity,
                           relevance, added_by, membership, enabled,
                           join_requested_at, last_harvested_at, leads_found}},
    "leads":  [newest first: {post_id, group_id (= group_key), url, text, price,
                              area_name, contact, poster_name, poster_url, images,
                              furnishing, gender, occupancy, brokerage, found_at}],
    "runs":   [newest first: the agent's run report]
  }
"""

import json
import os
import tempfile
from datetime import datetime, timezone

from agents.facebook.parsing import group_url
from agents.facebook.store import join_candidate, seed_rows, worth_reading

MAX_LEADS = 1500
MAX_RUNS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state() -> dict:
    return {"schema": 1, "updated_at": None, "groups": {}, "leads": [], "runs": []}


class FileStore:
    def __init__(self, path: str):
        self.path = path
        self.data = empty_state()
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path) as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict) or loaded.get("schema") != 1:
                raise ValueError(f"{path} isn't a Facebook agent state file (schema 1).")
            self.data.update(loaded)

    # ── groups ────────────────────────────────────────────────────────────────

    def upsert_groups(self, groups: list[dict]) -> dict[str, dict]:
        now = _now()
        rows = {}
        for g in groups:
            key = g["group_key"]
            row = self.data["groups"].setdefault(key, {
                "group_key": key, "membership": "unknown", "enabled": True,
                "leads_found": 0, "first_seen_at": now,
            })
            row["url"] = g.get("url") or row.get("url") or group_url(key)
            for field in ("name", "privacy", "member_count", "activity"):
                row[field] = g.get(field) or row.get(field)
            if "relevance" in g:
                row["relevance"] = g["relevance"]
            row["last_seen_at"] = now
            row["id"] = key
            rows[key] = row
        return rows

    def link_groups(self, owner: str, group_ids: list[str], added_by: str) -> int:
        new = 0
        for gid in group_ids:
            row = self.data["groups"].get(gid)
            if row is not None and not row.get("added_by"):
                row["added_by"] = added_by
                new += 1
        return new

    def ensure_seed_groups(self, owner: str, urls: list[str]) -> None:
        missing = [g for g in seed_rows(urls) if g["group_key"] not in self.data["groups"]]
        self.upsert_groups(missing)
        self.link_groups(owner, [g["group_key"] for g in missing], "seed")

    def _groups(self) -> list[dict]:
        groups = [g for g in self.data["groups"].values() if g.get("added_by")]
        return sorted(groups, key=lambda g: g.get("relevance") or 0, reverse=True)

    def groups_for_harvest(self, owner: str, limit: int) -> list[dict]:
        groups = sorted((g for g in self._groups() if worth_reading(g)),
                        key=lambda g: g.get("last_harvested_at") or "")
        return groups[:limit]

    def groups_to_join(self, owner: str, limit: int, min_relevance: float) -> list[dict]:
        return [g for g in self._groups() if join_candidate(g, min_relevance)][:limit]

    def update_user_group(self, owner: str, group_id: str, **fields) -> None:
        if group_id in self.data["groups"]:
            self.data["groups"][group_id].update(fields)

    # ── leads ─────────────────────────────────────────────────────────────────

    def save_leads(self, owner: str, leads: list[dict]) -> int:
        seen = {l["post_id"] for l in self.data["leads"]}
        now = _now()
        fresh = []
        for lead in leads:
            if lead["post_id"] not in seen:
                seen.add(lead["post_id"])
                fresh.append({**lead, "found_at": now})
        self.data["leads"] = (fresh + self.data["leads"])[:MAX_LEADS]
        return len(fresh)

    def save_listings(self, listings: list[dict]) -> int:
        """Also feed the search pipeline, but only when a database is configured."""
        if not os.environ.get("SUPABASE_URL"):
            return 0
        from agents.scrapers.base import save_listings
        return save_listings(listings)

    # ── connection / run bookkeeping ──────────────────────────────────────────

    def get_connection(self, user_id: str) -> dict | None:
        return None

    def update_connection(self, user_id: str, **fields) -> None:
        pass

    def finish_run(self, report: dict) -> None:
        self.data["runs"] = ([report] + self.data["runs"])[:MAX_RUNS]
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = _now()
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.path)
