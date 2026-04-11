-- Run this in your Supabase SQL editor (one time)
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS purpose   text;
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS nature    text;
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS image_url text;
