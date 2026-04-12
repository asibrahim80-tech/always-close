-- ═══════════════════════════════════════════════════════════════════
-- migrate_profile.sql  —  Extended user profile fields
-- Run once in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════════════

-- 1. New columns on users_v1
ALTER TABLE users_v1
  ADD COLUMN IF NOT EXISTS email             TEXT,
  ADD COLUMN IF NOT EXISTS first_name        TEXT,
  ADD COLUMN IF NOT EXISTS last_name         TEXT,
  ADD COLUMN IF NOT EXISTS zodiac            TEXT,
  ADD COLUMN IF NOT EXISTS social_status     TEXT,          -- single | married | divorced | widowed
  ADD COLUMN IF NOT EXISTS has_children      BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS education         TEXT,          -- none | school | diploma | bachelor | master | phd
  ADD COLUMN IF NOT EXISTS profession        TEXT,
  ADD COLUMN IF NOT EXISTS university        TEXT,
  ADD COLUMN IF NOT EXISTS school            TEXT,
  ADD COLUMN IF NOT EXISTS country           TEXT,
  ADD COLUMN IF NOT EXISTS city              TEXT,
  ADD COLUMN IF NOT EXISTS neighborhood      TEXT,
  ADD COLUMN IF NOT EXISTS hobbies           TEXT[]  DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS habits            TEXT[]  DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS personality_traits TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS purpose           TEXT[]  DEFAULT '{}',  -- marriage | relationship | friendship | hangout | dining | travel | cinema | coffee
  ADD COLUMN IF NOT EXISTS profile_complete  INTEGER DEFAULT 0;     -- 0-100 completeness score

-- 2. User photos table (multiple photos per user)
CREATE TABLE IF NOT EXISTS user_photos_v1 (
  id         SERIAL PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  photo_url  TEXT    NOT NULL,
  order_num  INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE user_photos_v1 DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_user_photos_user ON user_photos_v1(user_id);

-- Done
SELECT 'migrate_profile.sql applied successfully' AS status;
