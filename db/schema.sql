-- ============================================================
-- Flat Hunter — Supabase Schema
-- Run this entire file once in Supabase SQL Editor
-- ============================================================

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
    destination_lng     FLOAT
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
