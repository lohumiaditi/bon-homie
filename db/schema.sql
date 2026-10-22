-- ============================================================
-- Flat Hunter — Supabase Schema
-- Run this entire file once in Supabase SQL Editor
-- ============================================================

-- 0. Users (authenticated via Facebook OAuth)
--    PII (name, email) stored Fernet-encrypted — only decryptable server-side.
--    fb_token_enc / fb_token_expires_at: unused since Meta removed group access
--    from the Graph API (April 2024). Facebook sessions live in fb_connections.
CREATE TABLE IF NOT EXISTS users (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fb_id                TEXT NOT NULL UNIQUE,         -- Facebook user ID (not PII)
    name_enc             TEXT,                          -- Fernet-encrypted display name
    email_enc            TEXT,                          -- Fernet-encrypted email
    picture_url          TEXT,                          -- FB profile photo URL (public)
    fb_token_enc         TEXT,                          -- Fernet-encrypted long-lived FB token
    fb_token_expires_at  TIMESTAMPTZ,                  -- when the long-lived token expires
    last_login           TIMESTAMPTZ DEFAULT now(),
    created_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_fb_id ON users(fb_id);

-- ── Row Level Security ─────────────────────────────────────────────────────
-- Backend uses SUPABASE_SERVICE_KEY (service_role) which bypasses RLS.
-- Anon key (used by frontend if ever needed) cannot touch users at all.
-- RLS on users: only service_role can read/write. Anon = zero access.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- No policies → anon key has zero access. service_role bypasses RLS entirely.

-- listings: service_role writes (scraper). Anon can only SELECT (public data).
ALTER TABLE listings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "listings_anon_select" ON listings;
CREATE POLICY "listings_anon_select"
    ON listings FOR SELECT TO anon USING (true);

-- user_preferences: service_role manages. Anon cannot access.
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;

-- filtered_listings, ranked_results: service_role only.
ALTER TABLE filtered_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE ranked_results    ENABLE ROW LEVEL SECURITY;


-- 1. User Preferences
--    One row per search session
CREATE TABLE IF NOT EXISTS user_preferences (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ DEFAULT now(),

    city        TEXT NOT NULL DEFAULT 'Pune',
    areas       TEXT[] NOT NULL,           -- e.g. ['Kothrud', 'Baner']
    budget_min  INTEGER NOT NULL,          -- monthly rent in ₹
    budget_max  INTEGER NOT NULL,

    furnishing  TEXT NOT NULL,             -- 'furnished' | 'semi-furnished' | 'unfurnished' | 'any'
    renter_type TEXT NOT NULL DEFAULT 'any', -- 'family' | 'bachelor' | 'any'
    gender      TEXT NOT NULL DEFAULT 'any', -- 'male' | 'female' | 'any'
    occupancy   TEXT NOT NULL DEFAULT 'any', -- 'single' | 'double' | 'any'
    brokerage   TEXT NOT NULL DEFAULT 'any', -- 'yes' | 'no' | 'any'

    destination_address TEXT,             -- workplace / college / visit place
    destination_lat     FLOAT,
    destination_lng     FLOAT,

    flat_type       TEXT NOT NULL DEFAULT 'whole',  -- 'whole' | 'preoccupied'
    flatmate_gender TEXT NOT NULL DEFAULT 'any'     -- 'any' | 'male' | 'female' | 'same'
);

-- 2. Raw Listings (all scraped, before filtering)
CREATE TABLE IF NOT EXISTS listings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ DEFAULT now(),

    platform    TEXT NOT NULL,            -- '99acres' | 'nobroker' | 'housing' | 'magicbricks' | 'squareyards' | 'facebook'
    listing_id  TEXT NOT NULL,            -- platform's own ID / slug
    url         TEXT,

    title       TEXT,
    price       INTEGER,                  -- monthly rent in ₹
    area_name   TEXT,                     -- locality name as listed
    address     TEXT,
    city        TEXT DEFAULT 'Pune',

    furnishing  TEXT,
    renter_type TEXT,
    gender      TEXT,
    occupancy   TEXT,
    brokerage   BOOLEAN,

    images      TEXT[],                   -- list of image URLs
    image_count INTEGER GENERATED ALWAYS AS (array_length(images, 1)) STORED,

    contact_raw TEXT,                     -- raw phone string from page
    contact     TEXT,                     -- normalized +91XXXXXXXXXX

    lat         FLOAT,
    lng         FLOAT,

    last_scraped_at TIMESTAMPTZ DEFAULT now(),  -- updated every upsert for cache freshness

    UNIQUE (platform, listing_id)
);

-- 3. Filtered Listings (passed image + preference match)
CREATE TABLE IF NOT EXISTS filtered_listings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES user_preferences(id) ON DELETE CASCADE,
    listing_id      UUID REFERENCES listings(id) ON DELETE CASCADE,
    match_score     FLOAT DEFAULT 0,      -- 0–1, how well it matches prefs
    created_at      TIMESTAMPTZ DEFAULT now(),

    UNIQUE (session_id, listing_id)
);

-- 4. Ranked Results (final output with metro data)
CREATE TABLE IF NOT EXISTS ranked_results (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID REFERENCES user_preferences(id) ON DELETE CASCADE,
    listing_id          UUID REFERENCES listings(id) ON DELETE CASCADE,
    rank                INTEGER,

    metro_station       TEXT,             -- nearest station name
    walking_distance_m  INTEGER,          -- metres to nearest station
    metro_travel_min    INTEGER,          -- minutes via metro to destination
    total_score         FLOAT,            -- final ranking score (lower = better)

    created_at          TIMESTAMPTZ DEFAULT now(),

    UNIQUE (session_id, listing_id)
);

-- ============================================================
-- Indexes for fast lookups
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_listings_platform   ON listings(platform);
CREATE INDEX IF NOT EXISTS idx_listings_city       ON listings(city);
CREATE INDEX IF NOT EXISTS idx_listings_price      ON listings(price);
CREATE INDEX IF NOT EXISTS idx_filtered_session    ON filtered_listings(session_id);
CREATE INDEX IF NOT EXISTS idx_ranked_session      ON ranked_results(session_id);
CREATE INDEX IF NOT EXISTS idx_ranked_rank         ON ranked_results(session_id, rank);


-- ============================================================
-- Facebook connect + groups agent (db/migrations/001_facebook_groups_agent.sql)
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
