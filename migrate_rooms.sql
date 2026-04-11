-- Run this in your Supabase SQL editor (one time)

-- Add new columns to rooms_v1
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS purpose    text;
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS nature     text;
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS image_url  text;
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS expires_at timestamptz;

-- Room ratings (one rating per user per room)
CREATE TABLE IF NOT EXISTS room_ratings_v1 (
  id         serial PRIMARY KEY,
  room_id    integer NOT NULL REFERENCES rooms_v1(id) ON DELETE CASCADE,
  user_id    integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  rating     smallint NOT NULL CHECK (rating >= 1 AND rating <= 5),
  created_at timestamptz DEFAULT now(),
  UNIQUE(room_id, user_id)
);

-- User ratings (one rating per rater per target user)
CREATE TABLE IF NOT EXISTS user_ratings_v1 (
  id            serial PRIMARY KEY,
  rated_user_id integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  rater_id      integer NOT NULL REFERENCES users_v1(id) ON DELETE CASCADE,
  rating        smallint NOT NULL CHECK (rating >= 1 AND rating <= 5),
  created_at    timestamptz DEFAULT now(),
  UNIQUE(rated_user_id, rater_id)
);
