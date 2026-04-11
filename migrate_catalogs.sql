-- ════════════════════════════════════════════════════════
--  Catalogs for Rooms & Stores   (run once in Supabase)
-- ════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS catalogs_v1 (
    id          SERIAL PRIMARY KEY,
    entity_type TEXT    NOT NULL CHECK (entity_type IN ('room','store')),
    entity_id   INTEGER NOT NULL,
    category    TEXT    NOT NULL DEFAULT 'general',
    title       TEXT    NOT NULL,
    description TEXT,
    price       NUMERIC(10,2),
    currency    TEXT    DEFAULT 'SAR',
    image_url   TEXT,
    phone       TEXT,
    website     TEXT,
    hours       TEXT,
    sort_order  INTEGER DEFAULT 0,
    created_by  BIGINT  NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE catalogs_v1 DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_catalog_entity
    ON catalogs_v1 (entity_type, entity_id);
