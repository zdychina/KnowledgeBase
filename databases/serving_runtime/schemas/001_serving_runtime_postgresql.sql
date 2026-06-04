-- serving_runtime: PostgreSQL DDL
-- Serving 服务运行态库：查询日志、检索审计

CREATE TABLE IF NOT EXISTS serving_query_logs (
    id                  TEXT    NOT NULL,

    -- Original input
    query_text          TEXT    NOT NULL,
    domain              TEXT    NOT NULL DEFAULT 'default',
    channel             TEXT    NOT NULL,

    -- Query analysis results (from NormalizedQuery)
    intent              TEXT,
    normalizer_source   TEXT,
    keywords_json       TEXT    NOT NULL DEFAULT '[]',
    entities_json       TEXT    NOT NULL DEFAULT '[]',
    scope_json          TEXT    NOT NULL DEFAULT '{}',

    -- Knowledge base version (from ActiveScope)
    release_id          TEXT,
    build_id            TEXT,
    snapshot_count      INTEGER,

    -- Response summary (from ContextPack)
    result_item_count   INTEGER,
    result_seed_count   INTEGER,
    result_has_result   BOOLEAN NOT NULL DEFAULT TRUE,
    result_issues_json  TEXT    NOT NULL DEFAULT '[]',

    -- Result details (no text body to keep row size small)
    result_items_json       TEXT    NOT NULL DEFAULT '[]',
    result_sources_json     TEXT    NOT NULL DEFAULT '[]',
    result_relations_json   TEXT    NOT NULL DEFAULT '[]',

    -- Performance
    duration_ms         INTEGER,

    -- Metadata
    queried_at          TEXT    NOT NULL,
    metadata_json       TEXT    NOT NULL DEFAULT '{}',

    CONSTRAINT pk_serving_query_logs PRIMARY KEY (id)
);

-- ---- serving_query_logs indexes ----
CREATE INDEX IF NOT EXISTS idx_sql_queried_at
    ON serving_query_logs (queried_at);

CREATE INDEX IF NOT EXISTS idx_sql_intent
    ON serving_query_logs (intent, queried_at);

CREATE INDEX IF NOT EXISTS idx_sql_channel_release
    ON serving_query_logs (channel, release_id);

CREATE INDEX IF NOT EXISTS idx_sql_has_result
    ON serving_query_logs (result_has_result, queried_at);
