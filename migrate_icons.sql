-- Add icon column to rooms and stores
ALTER TABLE rooms_v1 ADD COLUMN IF NOT EXISTS icon text DEFAULT '🏠';
ALTER TABLE stores_v1 ADD COLUMN IF NOT EXISTS icon text DEFAULT '🏪';
