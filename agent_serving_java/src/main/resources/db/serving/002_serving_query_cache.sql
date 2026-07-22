-- =============================================================================
-- Serving runtime — semantic query cache.
-- Same routing story as 001: applied against every DataSource serving can reach.
--
-- Kept in a SEPARATE script from 001 on purpose: this one needs the pgvector
-- extension, which is otherwise installed only by the mining side
-- (databases/asset_core/schemas/002_asset_core_postgresql.sql). A domain DB that
-- mining has never written to may not have it, and CREATE EXTENSION needs
-- privileges the serving DB user may not hold. ServingRuntimeSchemaInitializer
-- runs each script independently so failing here degrades the cache only —
-- query logging still gets its table.
--
-- Columns must stay in sync with mapper/SemanticCacheMapper.xml.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS serving_query_cache (
    id               TEXT        NOT NULL,
    domain           TEXT        NOT NULL DEFAULT 'default',
    release_id       TEXT        NOT NULL DEFAULT '',
    query_text       TEXT        NOT NULL,
    query_embedding  vector(1024),
    context_pack_json JSONB      NOT NULL,
    hit_count        INTEGER     NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ,

    CONSTRAINT pk_serving_query_cache PRIMARY KEY (id)
);

-- Same trap as 001: the CREATE above is skipped on a database that already has an
-- older shape of this table. `release_id` was added later (see
-- db/migrate_v2_semantic_cache.sql), and idx_sqc_domain_release_expires below
-- indexes it, so this must run after the CREATE and before the indexes.
ALTER TABLE serving_query_cache
    ADD COLUMN IF NOT EXISTS release_id TEXT NOT NULL DEFAULT '';

-- ---- serving_query_cache indexes ----
CREATE INDEX IF NOT EXISTS idx_sqc_embedding
    ON serving_query_cache
    USING ivfflat (query_embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_sqc_domain_expires
    ON serving_query_cache (domain, expires_at);

CREATE INDEX IF NOT EXISTS idx_sqc_domain_release_expires
    ON serving_query_cache (domain, release_id, expires_at);
