-- serving_query_cache: 语义缓存
-- 用于缓存相似查询的结果，避免重复检索
-- 依赖: vector 扩展 (pgvector)

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

-- ---- serving_query_cache indexes ----
CREATE INDEX IF NOT EXISTS idx_sqc_embedding
    ON serving_query_cache
    USING ivfflat (query_embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_sqc_domain_expires
    ON serving_query_cache (domain, expires_at);

CREATE INDEX IF NOT EXISTS idx_sqc_domain_release_expires
    ON serving_query_cache (domain, release_id, expires_at);
