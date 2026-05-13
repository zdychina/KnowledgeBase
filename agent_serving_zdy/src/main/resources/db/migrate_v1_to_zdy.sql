-- =============================================================================
-- Migration: agent_serving_v1 → agent_serving_zdy
-- Change summary: add multi-domain support (domain column on source_batches,
--                 builds, publish_releases; rework publish_releases indexes)
-- Target DB: PostgreSQL 14+
-- Idempotent: yes (uses IF NOT EXISTS / IF EXISTS throughout)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Step 0: Pre-flight checks (run these SELECTs before applying the migration)
-- ---------------------------------------------------------------------------
-- Check 1: confirm no duplicate active releases per channel
--   If this returns rows, resolve them before Step 3 (the UNIQUE index will fail).
--
-- SELECT channel, COUNT(*) AS cnt
-- FROM asset_publish_releases
-- WHERE status = 'active'
-- GROUP BY channel
-- HAVING COUNT(*) > 1;
--
-- Check 2: row counts for sanity
--
-- SELECT
--     (SELECT COUNT(*) FROM asset_source_batches)   AS source_batches,
--     (SELECT COUNT(*) FROM asset_builds)            AS builds,
--     (SELECT COUNT(*) FROM asset_publish_releases)  AS releases;


-- ---------------------------------------------------------------------------
-- Step 1: asset_source_batches — add domain column
-- ---------------------------------------------------------------------------
ALTER TABLE asset_source_batches
    ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'default';


-- ---------------------------------------------------------------------------
-- Step 2: asset_builds — add domain column
-- ---------------------------------------------------------------------------
ALTER TABLE asset_builds
    ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'default';


-- ---------------------------------------------------------------------------
-- Step 3: asset_publish_releases — add domain column, set channel default
-- ---------------------------------------------------------------------------
ALTER TABLE asset_publish_releases
    ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'default';

ALTER TABLE asset_publish_releases
    ALTER COLUMN channel SET DEFAULT 'prod';


-- ---------------------------------------------------------------------------
-- Step 4: drop obsolete index
-- ---------------------------------------------------------------------------
DROP INDEX IF EXISTS idx_asset_publish_releases_channel_status;


-- ---------------------------------------------------------------------------
-- Step 5: create new indexes
--
-- NOTE: uq_asset_publish_releases_domain_channel_active is a UNIQUE partial
--       index. It will fail if any (domain, channel) pair already has more
--       than one active release. Run Check 1 above first.
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_publish_releases_domain_channel_active
    ON asset_publish_releases (domain, channel)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_domain_channel_status
    ON asset_publish_releases (domain, channel, status);

CREATE INDEX IF NOT EXISTS idx_asset_builds_domain_status
    ON asset_builds (domain, status);

CREATE INDEX IF NOT EXISTS idx_asset_source_batches_domain
    ON asset_source_batches (domain);


-- ---------------------------------------------------------------------------
-- Step 6: post-migration verification
-- ---------------------------------------------------------------------------
-- Confirm columns exist:
--
-- SELECT column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE table_name IN ('asset_source_batches', 'asset_builds', 'asset_publish_releases')
--   AND column_name IN ('domain', 'channel')
-- ORDER BY table_name, column_name;
--
-- Confirm indexes exist:
--
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename IN ('asset_source_batches', 'asset_builds', 'asset_publish_releases')
--   AND indexname IN (
--       'uq_asset_publish_releases_domain_channel_active',
--       'idx_asset_publish_releases_domain_channel_status',
--       'idx_asset_builds_domain_status',
--       'idx_asset_source_batches_domain'
--   )
-- ORDER BY tablename, indexname;
