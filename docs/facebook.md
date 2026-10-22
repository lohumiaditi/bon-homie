# Facebook: connect, scrape, groups agent

Facebook's API no longer exposes group posts, so everything runs through a
logged-in browser session (Camoufox) using an account's cookies.

## Setup

1. Run `db/migrations/001_facebook_groups_agent.sql` in the Supabase SQL editor.
2. Make sure `ENCRYPTION_KEY` and `JWT_SECRET` are set (`python -m agents.auth_agent genkey`).
   Connected sessions are encrypted with `ENCRYPTION_KEY`; changing it disconnects everyone.
3. Optional "system" account for batch runs and users who haven't connected:
   `python setup_fb_cookies.py --print`, then store the printed JSON as the
   `FB_COOKIES_JSON` GitHub secret (and in `.env` for local runs).
4. GitHub secrets for `.github/workflows/facebook-agent.yml`: `SUPABASE_URL`,
   `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`, `FB_COOKIES_JSON`.

## How users connect

In the app: **Facebook leads → Connect Facebook**, paste cookies (Cookie-Editor
JSON export, or `c_user=…; xs=…`). The backend checks they're logged in,
encrypts them into `fb_connections`, and marks the connection `expired`
automatically if Facebook later logs the session out.

## What runs where

| Piece | Code | When |
|---|---|---|
| Search-time scrape (Marketplace, 3 groups, 4 post searches) | `agents/scrapers/facebook_agent.py` | every search; batch scrape |
| Groups agent: discover → (join) → harvest | `agents/fb_groups_agent.py` | "Groups agent" buttons; every 6 h in CI |

Harvest keeps posts **offering** a flat/room (not people looking for one), saves
them to `fb_leads`, and saves priced ones to `listings` so searches pick them up.
Joining is off unless the user enables it (max 2 groups per run). The agent never
posts, comments or sends messages.

## Daily Claude routine → "Pune Flat Leads" artifact

No database or GitHub Actions needed. A Claude routine runs every day at
07:30 IST in the Claude cloud environment and keeps the artifact
https://claude.ai/artifact/1UMBCqKAsZXJYxWRWT9XxV up to date:

1. downloads the artifact's `data.json` (the agent's whole state: groups, leads, run history)
2. runs `python3 -m agents.fb_groups_agent run --state data.json --tasks discover,harvest`
3. republishes `artifacts/flat-leads/index.html` from this repo with the updated `data.json`

The page reads `data.json`; shortlisted / contacted / dismissed marks live in
the artifact's database (`triage/<post_id>`), shared by everyone who can open it.

Setup: add `FB_COOKIES_JSON` (from `python setup_fb_cookies.py --print`) as an
environment variable of the Claude cloud environment the routine runs in.
Cloud sessions can't download Camoufox, so the agent uses the pre-installed
Chromium there (`agents/facebook/browser.py`). Install with
`python3 -m pip install -r requirements-fb-agent.txt`.

## CLI

```
python -m agents.fb_groups_agent discover --dry-run --areas Baner,Wakad   # no DB writes
python -m agents.fb_groups_agent run --user <users.id>
python -m agents.fb_groups_agent run --all --tasks discover,harvest
FB_HEADLESS=0 python -m agents.fb_groups_agent harvest --dry-run           # watch the browser
python -m agents.fb_groups_agent run --state data.json                     # file state, no database
```

## Tests

`pytest tests/test_facebook_parsing.py tests/test_facebook_session.py tests/test_facebook_api.py tests/test_fb_groups_agent.py`
