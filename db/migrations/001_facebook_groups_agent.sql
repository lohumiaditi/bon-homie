-- ============================================================
-- Facebook connect + groups agent
-- Run once in the Supabase SQL Editor (safe to re-run).
-- Also included at the end of db/schema.sql for fresh installs.
-- ============================================================

-- One per user: their Facebook session cookies (Fernet-encrypted with
-- ENCRYPTION_KEY) and agent settings.
CREATE TABLE IF NOT EXISTS fb_connections (
    user_id           UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    fb_user_id        TEXT,                              -- c_user cookie (numeric FB id)
    cookies_enc       TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'unverified', -- unverified | active | expired
    status_detail     TEXT,
    auto_join         BOOLEAN NOT NULL DEFAULT false,    -- let the agent request to join groups
    harvest_enabled   BOOLEAN NOT NULL DEFAULT true,     -- include in scheduled agent runs
    connected_at      TIMESTAMPTZ DEFAULT now(),
    verified_at       TIMESTAMPTZ,
    last_run_at       TIMESTAMPTZ,
    last_run_summary  JSONB
);

-- Shared catalog of rental groups anyone's agent has found.
CREATE TABLE IF NOT EXISTS fb_groups (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_key      TEXT NOT NULL UNIQUE,   -- slug or numeric id from facebook.com/groups/<key>
    url            TEXT NOT NULL,
    name           TEXT,
    privacy        TEXT,                   -- public | private
    member_count   INTEGER,
    activity       TEXT,                   -- e.g. "10+ posts a day"
    relevance      FLOAT NOT NULL DEFAULT 0,
    first_seen_at  TIMESTAMPTZ DEFAULT now(),
    last_seen_at   TIMESTAMPTZ DEFAULT now()
);

-- A group as seen by one account. owner_key = users.id, or 'system' for the
-- shared FB_COOKIES_JSON / .fb_cookies.json session.
CREATE TABLE IF NOT EXISTS fb_user_groups (
    owner_key          TEXT NOT NULL,
    group_id           UUID NOT NULL REFERENCES fb_groups(id) ON DELETE CASCADE,
    added_by           TEXT NOT NULL DEFAULT 'discovered',  -- seed | discovered | user
    membership         TEXT NOT NULL DEFAULT 'unknown',     -- member | pending | not_member | unknown
    enabled            BOOLEAN NOT NULL DEFAULT true,
    join_requested_at  TIMESTAMPTZ,
    last_harvested_at  TIMESTAMPTZ,
    leads_found        INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (owner_key, group_id)
);

-- Rental offers pulled from group posts (kept even without a price).
CREATE TABLE IF NOT EXISTS fb_leads (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key    TEXT NOT NULL,
    post_id      TEXT NOT NULL,
    group_id     UUID REFERENCES fb_groups(id) ON DELETE SET NULL,
    source       TEXT NOT NULL DEFAULT 'group',
    url          TEXT,
    text         TEXT,
    price        INTEGER,
    area_name    TEXT,
    contact      TEXT,
    poster_name  TEXT,
    poster_url   TEXT,
    images       TEXT[],
    furnishing   TEXT,
    gender       TEXT,
    occupancy    TEXT,
    brokerage    BOOLEAN,
    status       TEXT NOT NULL DEFAULT 'new',  -- new | shortlisted | contacted | dismissed
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (owner_key, post_id)
);

CREATE INDEX IF NOT EXISTS idx_fb_user_groups_owner ON fb_user_groups(owner_key);
CREATE INDEX IF NOT EXISTS idx_fb_leads_owner       ON fb_leads(owner_key, status, created_at DESC);

-- Backend-only (service_role bypasses RLS; anon gets nothing).
ALTER TABLE fb_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE fb_groups      ENABLE ROW LEVEL SECURITY;
ALTER TABLE fb_user_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE fb_leads       ENABLE ROW LEVEL SECURITY;
