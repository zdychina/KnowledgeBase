-- Semantic Cache migration
-- Idempotent: uses IF NOT EXISTS throughout

CREATE TABLE IF NOT EXISTS serving_query_cache (
    id               TEXT        NOT NULL,
    domain           TEXT        NOT NULL DEFAULT 'default',
    query_text       TEXT        NOT NULL,
    query_embedding  vector(1024),
    context_pack_json JSONB      NOT NULL,
    hit_count        INTEGER     NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ,

    CONSTRAINT pk_serving_query_cache PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_sqc_embedding
    ON serving_query_cache
    USING ivfflat (query_embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_sqc_domain_expires
    ON serving_query_cache (domain, expires_at);
