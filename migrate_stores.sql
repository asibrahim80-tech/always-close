-- Run this in your Supabase SQL editor (one time)
-- =====================================================
-- STORES SYSTEM
-- =====================================================

-- Main stores table
CREATE TABLE IF NOT EXISTS stores_v1 (
  id          serial PRIMARY KEY,
  name        text NOT NULL,
  created_by  integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  latitude    numeric,
  longitude   numeric,
  purpose     text,
  nature      text,
  image_url   text,
  expires_at  timestamptz,
  created_at  timestamptz DEFAULT now()
);

-- Store followers/members
CREATE TABLE IF NOT EXISTS store_members_v1 (
  id         serial PRIMARY KEY,
  store_id   integer NOT NULL REFERENCES stores_v1(id) ON DELETE CASCADE,
  user_id    integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  joined_at  timestamptz DEFAULT now(),
  UNIQUE(store_id, user_id)
);

-- Store ratings
CREATE TABLE IF NOT EXISTS store_ratings_v1 (
  id         serial PRIMARY KEY,
  store_id   integer NOT NULL REFERENCES stores_v1(id) ON DELETE CASCADE,
  user_id    integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  rating     smallint NOT NULL CHECK (rating >= 1 AND rating <= 5),
  created_at timestamptz DEFAULT now(),
  UNIQUE(store_id, user_id)
);

-- Disable RLS so the service role key works without policy issues
ALTER TABLE stores_v1       DISABLE ROW LEVEL SECURITY;
ALTER TABLE store_members_v1 DISABLE ROW LEVEL SECURITY;
ALTER TABLE store_ratings_v1 DISABLE ROW LEVEL SECURITY;
