-- =====================================================
-- OBJECTS SYSTEM (Unified Entity Table)
-- Run once in Supabase SQL editor
-- =====================================================

CREATE TABLE IF NOT EXISTS objects_v1 (
  id          serial PRIMARY KEY,
  name        text NOT NULL,
  created_by  integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  latitude    numeric,
  longitude   numeric,
  purpose     text,
  object_type text,
  is_mobile   boolean DEFAULT false,
  image_url   text,
  expires_at  timestamptz,
  created_at  timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS object_members_v1 (
  id         serial PRIMARY KEY,
  object_id  integer NOT NULL REFERENCES objects_v1(id) ON DELETE CASCADE,
  user_id    integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  joined_at  timestamptz DEFAULT now(),
  UNIQUE(object_id, user_id)
);

CREATE TABLE IF NOT EXISTS object_ratings_v1 (
  id         serial PRIMARY KEY,
  object_id  integer NOT NULL REFERENCES objects_v1(id) ON DELETE CASCADE,
  user_id    integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  rating     smallint NOT NULL CHECK (rating >= 1 AND rating <= 5),
  created_at timestamptz DEFAULT now(),
  UNIQUE(object_id, user_id)
);

ALTER TABLE objects_v1        DISABLE ROW LEVEL SECURITY;
ALTER TABLE object_members_v1 DISABLE ROW LEVEL SECURITY;
ALTER TABLE object_ratings_v1 DISABLE ROW LEVEL SECURITY;
