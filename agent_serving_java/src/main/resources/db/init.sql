-- =============================================================================
-- agent_serving_java -- PostgreSQL initialization script
-- Based on databases/asset_core/schemas/001_asset_core.sql
-- Compatible with PostgreSQL 14+
-- No foreign key constraints -- data integrity is enforced at application layer
-- Chinese FTS optional dependency: pg_jieba (falls back to simple dictionary)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Chinese segmentation extension (optional, requires pg_jieba plugin)
-- -----------------------------------------------------------------------------
-- CREATE EXTENSION IF NOT EXISTS pg_jieba;


-- =============================================================================
-- 1. Source batches
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_source_batches (
    id            TEXT        NOT NULL,
    batch_code    TEXT        NOT NULL,
    source_type   TEXT        NOT NULL,   -- manual_upload | folder_scan | api_import | official_vendor | expert_authored | user_import | synthetic_coldstart | other
    description   TEXT,
    created_by    TEXT,
    created_at    TEXT        NOT NULL,
    metadata_json TEXT        NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_source_batches    PRIMARY KEY (id),
    CONSTRAINT uq_asset_source_batches_code UNIQUE (batch_code)
);


-- =============================================================================
-- 2. Documents and snapshots
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_documents (
    id            TEXT NOT NULL,
    document_key  TEXT NOT NULL,
    document_name TEXT,
    document_type TEXT,                   -- markdown | html | pdf | ...
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    CONSTRAINT pk_asset_documents   PRIMARY KEY (id),
    CONSTRAINT uq_asset_documents_key UNIQUE (document_key)
);

-- Content snapshots shareable across documents (dedup boundary: normalized_content_hash)
CREATE TABLE IF NOT EXISTS asset_document_snapshots (
    id                      TEXT NOT NULL,
    normalized_content_hash TEXT NOT NULL,
    raw_content_hash        TEXT NOT NULL,
    mime_type               TEXT NOT NULL,   -- text/markdown | text/plain | text/html | application/pdf | ...
    title                   TEXT,
    scope_json              TEXT NOT NULL DEFAULT '{}',
    tags_json               TEXT NOT NULL DEFAULT '[]',
    parser_profile_json     TEXT NOT NULL DEFAULT '{}',
    metadata_json           TEXT NOT NULL DEFAULT '{}',
    created_at              TEXT NOT NULL,
    CONSTRAINT pk_asset_document_snapshots       PRIMARY KEY (id),
    CONSTRAINT uq_asset_document_snapshots_hash  UNIQUE (normalized_content_hash)
);

-- Document-snapshot links (with document-level scope/tags/path)
CREATE TABLE IF NOT EXISTS asset_document_snapshot_links (
    id                   TEXT NOT NULL,
    document_id          TEXT NOT NULL,
    document_snapshot_id TEXT NOT NULL,
    source_batch_id      TEXT,
    relative_path        TEXT NOT NULL,
    source_uri           TEXT NOT NULL,
    title                TEXT,
    scope_json           TEXT NOT NULL DEFAULT '{}',
    tags_json            TEXT NOT NULL DEFAULT '[]',
    linked_at            TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_document_snapshot_links PRIMARY KEY (id)
);


-- =============================================================================
-- 3. Raw segments and relations
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_raw_segments (
    id                   TEXT    NOT NULL,
    document_snapshot_id TEXT    NOT NULL,
    segment_key          TEXT    NOT NULL,
    segment_index        INTEGER NOT NULL,
    section_path         TEXT    NOT NULL DEFAULT '[]',
    section_title        TEXT,
    block_type           TEXT    NOT NULL DEFAULT 'unknown',   -- paragraph | heading | table | list | code | blockquote | html_table | raw_html | unknown
    semantic_role        TEXT    NOT NULL DEFAULT 'unknown',   -- concept | parameter | example | note | procedure_step | troubleshooting_step | constraint | alarm | checklist | unknown
    raw_text             TEXT    NOT NULL,
    normalized_text      TEXT    NOT NULL,
    content_hash         TEXT    NOT NULL,
    normalized_hash      TEXT    NOT NULL,
    token_count          INTEGER,
    structure_json       TEXT    NOT NULL DEFAULT '{}',
    source_offsets_json  TEXT    NOT NULL DEFAULT '{}',
    entity_refs_json     TEXT    NOT NULL DEFAULT '[]',
    metadata_json        TEXT    NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_raw_segments         PRIMARY KEY (id),
    CONSTRAINT uq_asset_raw_segments_key     UNIQUE (document_snapshot_id, segment_key)
);

-- Inter-segment structural relations (knowledge graph edges)
CREATE TABLE IF NOT EXISTS asset_raw_segment_relations (
    id                   TEXT             NOT NULL,
    document_snapshot_id TEXT             NOT NULL,
    source_segment_id    TEXT             NOT NULL,
    target_segment_id    TEXT             NOT NULL,
    relation_type        TEXT             NOT NULL,   -- previous | next | same_section | same_parent_section | section_header_of | references | elaborates | condition | contrast | other
    weight               DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    confidence           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    distance             INTEGER,
    metadata_json        TEXT             NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_raw_segment_relations    PRIMARY KEY (id),
    CONSTRAINT uq_asset_raw_segment_relations    UNIQUE (source_segment_id, target_segment_id, relation_type)
);


-- =============================================================================
-- 4. Retrieval units (Serving primary search targets)
-- =============================================================================

-- A single raw_segment can produce multiple retrieval_units (e.g. raw text, context-augmented text)
CREATE TABLE IF NOT EXISTS asset_retrieval_units (
    id                   TEXT             NOT NULL,
    document_snapshot_id TEXT             NOT NULL,
    unit_key             TEXT             NOT NULL,
    unit_type            TEXT             NOT NULL,   -- raw_text | contextual_text | ...
    target_type          TEXT             NOT NULL,
    target_ref_json      TEXT             NOT NULL DEFAULT '{}',
    title                TEXT,
    text                 TEXT             NOT NULL,   -- original text returned to LLM
    search_text          TEXT             NOT NULL,   -- FTS-indexed text (may include context-augmented content)
    block_type           TEXT             NOT NULL DEFAULT 'unknown',
    semantic_role        TEXT             NOT NULL DEFAULT 'unknown',
    facets_json          TEXT             NOT NULL DEFAULT '{}',   -- {"product":"UDG","version":"V300R001C00"}
    entity_refs_json     TEXT             NOT NULL DEFAULT '[]',
    source_refs_json     TEXT             NOT NULL DEFAULT '{}',
    llm_result_refs_json TEXT             NOT NULL DEFAULT '{}',
    weight               DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source_segment_id    TEXT,                                     -- source raw_segment ID (for dedup and tracing)
    created_at           TEXT             NOT NULL,
    metadata_json        TEXT             NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_retrieval_units      PRIMARY KEY (id),
    CONSTRAINT uq_asset_retrieval_units_key  UNIQUE (document_snapshot_id, unit_key)
);

-- Vector embeddings (reserved for vector retrieval extension)
CREATE TABLE IF NOT EXISTS asset_retrieval_embeddings (
    id                 TEXT    NOT NULL,
    retrieval_unit_id  TEXT    NOT NULL,
    embedding_model    TEXT    NOT NULL,
    embedding_provider TEXT    NOT NULL,
    text_kind          TEXT    NOT NULL,
    embedding_dim      INTEGER NOT NULL,
    embedding_vector   TEXT    NOT NULL,   -- serialized vector
    content_hash       TEXT    NOT NULL,
    created_at         TEXT    NOT NULL,
    metadata_json      TEXT    NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_retrieval_embeddings PRIMARY KEY (id)
);


-- =============================================================================
-- 5. Build and release management
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_builds (
    id              TEXT NOT NULL,
    build_code      TEXT NOT NULL,
    status          TEXT NOT NULL,   -- queued | running | succeeded | failed | cancelled
    build_mode      TEXT NOT NULL,
    source_batch_id TEXT,
    parent_build_id TEXT,
    mining_run_id   TEXT,
    summary_json    TEXT NOT NULL DEFAULT '{}',
    validation_json TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    finished_at     TEXT,
    CONSTRAINT pk_asset_builds       PRIMARY KEY (id),
    CONSTRAINT uq_asset_builds_code  UNIQUE (build_code)
);

-- Per-document snapshot selection within a build
CREATE TABLE IF NOT EXISTS asset_build_document_snapshots (
    build_id             TEXT NOT NULL,
    document_id          TEXT NOT NULL,
    document_snapshot_id TEXT NOT NULL,
    selection_status     TEXT NOT NULL,   -- active | excluded
    reason               TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_build_document_snapshots PRIMARY KEY (build_id, document_id)
);

-- Publish releases (controls which build is visible for which domain)
CREATE TABLE IF NOT EXISTS asset_publish_releases (
    id                  TEXT NOT NULL,
    release_code        TEXT NOT NULL,
    build_id            TEXT NOT NULL,
    domain              TEXT NOT NULL,
    status              TEXT NOT NULL,   -- active | inactive | archived
    previous_release_id TEXT,
    released_by         TEXT,
    release_notes       TEXT,
    activated_at        TEXT,
    deactivated_at      TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_publish_releases       PRIMARY KEY (id),
    CONSTRAINT uq_asset_publish_releases_code  UNIQUE (release_code)
);


-- =============================================================================
-- 6. Indexes
-- =============================================================================

-- ---- asset_documents ----
CREATE INDEX IF NOT EXISTS idx_asset_documents_type
    ON asset_documents (document_type);

-- ---- asset_document_snapshots ----
CREATE INDEX IF NOT EXISTS idx_asset_document_snapshots_raw_hash
    ON asset_document_snapshots (raw_content_hash);

-- ---- asset_document_snapshot_links ----
CREATE INDEX IF NOT EXISTS idx_asset_dsl_document
    ON asset_document_snapshot_links (document_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_dsl_snapshot
    ON asset_document_snapshot_links (document_snapshot_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_dsl_batch
    ON asset_document_snapshot_links (source_batch_id);

-- ---- asset_raw_segments ----
CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_snapshot
    ON asset_raw_segments (document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_normalized_hash
    ON asset_raw_segments (normalized_hash);

-- ---- asset_raw_segment_relations ----
CREATE INDEX IF NOT EXISTS idx_asset_rsr_snapshot_type
    ON asset_raw_segment_relations (document_snapshot_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_asset_rsr_source
    ON asset_raw_segment_relations (source_segment_id);

CREATE INDEX IF NOT EXISTS idx_asset_rsr_target
    ON asset_raw_segment_relations (target_segment_id);

-- ---- asset_retrieval_units ----
CREATE INDEX IF NOT EXISTS idx_asset_ru_snapshot
    ON asset_retrieval_units (document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_ru_block_role
    ON asset_retrieval_units (block_type, semantic_role);

CREATE INDEX IF NOT EXISTS idx_asset_ru_source_segment
    ON asset_retrieval_units (source_segment_id);

-- FTS GIN index (core search index)
-- Uses 'simple' dictionary (language-agnostic, suitable for English command names and numbers)
-- After installing pg_jieba, replace 'simple' with 'jieba' and rebuild this index for Chinese segmentation
CREATE INDEX IF NOT EXISTS idx_asset_ru_fts
    ON asset_retrieval_units
    USING GIN (to_tsvector('simple', COALESCE(search_text, '')));

-- ---- asset_retrieval_embeddings ----
CREATE INDEX IF NOT EXISTS idx_asset_retrieval_embeddings_unit
    ON asset_retrieval_embeddings (retrieval_unit_id);

-- ---- asset_builds ----
CREATE INDEX IF NOT EXISTS idx_asset_builds_status
    ON asset_builds (status, created_at);

-- ---- asset_build_document_snapshots ----
CREATE INDEX IF NOT EXISTS idx_asset_bds_build_status
    ON asset_build_document_snapshots (build_id, selection_status);

CREATE INDEX IF NOT EXISTS idx_asset_bds_snapshot
    ON asset_build_document_snapshots (document_snapshot_id);

-- ---- asset_publish_releases ----
-- resolveActiveScope: WHERE domain=? AND status='active'
CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_domain_status
    ON asset_publish_releases (domain, status);

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_build
    ON asset_publish_releases (build_id);


-- =============================================================================
-- 7. Query logs
-- =============================================================================

CREATE TABLE IF NOT EXISTS serving_query_logs (
    id                  TEXT    NOT NULL,

    -- Original input
    query_text          TEXT    NOT NULL,
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
