-- CoreMasterKB Asset Core Schema v1.1 - PostgreSQL
--
-- Adapted from 001_asset_core.sqlite.sql:
-- - TEXT → TEXT (kept for non-JSON), JSON TEXT → JSONB
-- - FTS5 virtual table → tsvector column + GIN index
-- - PRAGMA removed
-- - Auto-increment triggers replaced by pg_trgm + tsvector

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS asset_source_batches (
    id            TEXT PRIMARY KEY,
    batch_code    TEXT NOT NULL UNIQUE,
    source_type   TEXT NOT NULL CHECK (
        source_type IN (
            'manual_upload',
            'folder_scan',
            'api_import',
            'official_vendor',
            'expert_authored',
            'user_import',
            'synthetic_coldstart',
            'other'
        )
    ),
    description   TEXT,
    created_by    TEXT,
    created_at    TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS asset_documents (
    id             TEXT PRIMARY KEY,
    document_key   TEXT NOT NULL UNIQUE,
    document_name  TEXT,
    document_type  TEXT CHECK (
        document_type IS NULL OR
        document_type IN (
            'command', 'feature', 'procedure', 'troubleshooting', 'alarm',
            'constraint', 'checklist', 'expert_note', 'project_note',
            'standard', 'training', 'reference', 'other'
        )
    ),
    metadata_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_asset_documents_type
    ON asset_documents(document_type);

CREATE TABLE IF NOT EXISTS asset_document_snapshots (
    id                      TEXT PRIMARY KEY,
    normalized_content_hash TEXT NOT NULL UNIQUE,
    raw_content_hash        TEXT NOT NULL,
    mime_type               TEXT NOT NULL CHECK (
        mime_type IN (
            'text/markdown', 'text/plain', 'text/html', 'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/octet-stream', 'other'
        )
    ),
    title                   TEXT,
    scope_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags_json               JSONB NOT NULL DEFAULT '[]'::jsonb,
    parser_profile_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshots_raw_hash
    ON asset_document_snapshots(raw_content_hash);

CREATE TABLE IF NOT EXISTS asset_document_snapshot_links (
    id                   TEXT PRIMARY KEY,
    document_id          TEXT NOT NULL REFERENCES asset_documents(id) ON DELETE CASCADE,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE RESTRICT,
    source_batch_id      TEXT REFERENCES asset_source_batches(id) ON DELETE SET NULL,
    relative_path        TEXT NOT NULL,
    source_uri           TEXT NOT NULL,
    title                TEXT,
    scope_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags_json            JSONB NOT NULL DEFAULT '[]'::jsonb,
    linked_at            TEXT NOT NULL,
    metadata_json        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshot_links_document
    ON asset_document_snapshot_links(document_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshot_links_snapshot
    ON asset_document_snapshot_links(document_snapshot_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshot_links_batch
    ON asset_document_snapshot_links(source_batch_id);

CREATE TABLE IF NOT EXISTS asset_raw_segments (
    id                  TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    segment_key         TEXT NOT NULL,
    segment_index       INTEGER NOT NULL CHECK (segment_index >= 0),
    section_path        TEXT NOT NULL DEFAULT '[]',
    section_title       TEXT,
    block_type          TEXT NOT NULL DEFAULT 'unknown' CHECK (
        block_type IN ('paragraph', 'heading', 'table', 'list', 'code', 'blockquote', 'html_table', 'raw_html', 'unknown')
    ),
    semantic_role       TEXT NOT NULL DEFAULT 'unknown' CHECK (
        semantic_role IN (
            'concept', 'parameter', 'example', 'note', 'procedure_step',
            'troubleshooting_step', 'constraint', 'alarm', 'checklist', 'unknown'
        )
    ),
    raw_text            TEXT NOT NULL,
    normalized_text     TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    normalized_hash     TEXT NOT NULL,
    token_count         INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    structure_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_offsets_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    entity_refs_json    JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_snapshot_id, segment_key)
);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_snapshot
    ON asset_raw_segments(document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_snapshot_index
    ON asset_raw_segments(document_snapshot_id, segment_index);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_normalized_hash
    ON asset_raw_segments(normalized_hash);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_block_role
    ON asset_raw_segments(block_type, semantic_role);

CREATE TABLE IF NOT EXISTS asset_raw_segment_relations (
    id                  TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    source_segment_id   TEXT NOT NULL REFERENCES asset_raw_segments(id) ON DELETE CASCADE,
    target_segment_id   TEXT NOT NULL REFERENCES asset_raw_segments(id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL CHECK (
        relation_type IN (
            'previous', 'next', 'same_section', 'same_parent_section',
            'section_header_of', 'references', 'elaborates', 'condition',
            'contrast', 'evidences', 'causes', 'results_in', 'backgrounds',
            'conditions', 'summarizes', 'justifies', 'enables', 'contrasts_with',
            'parallels', 'sequences', 'unrelated', 'other'
        )
    ),
    weight              REAL NOT NULL DEFAULT 1.0,
    confidence          REAL NOT NULL DEFAULT 1.0,
    distance            INTEGER,
    metadata_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_segment_id, target_segment_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segment_relations_snapshot
    ON asset_raw_segment_relations(document_snapshot_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segment_relations_source
    ON asset_raw_segment_relations(source_segment_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segment_relations_target
    ON asset_raw_segment_relations(target_segment_id, relation_type);

CREATE TABLE IF NOT EXISTS asset_retrieval_units (
    id                   TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    unit_key             TEXT NOT NULL,
    unit_type            TEXT NOT NULL CHECK (
        unit_type IN (
            'raw_text', 'contextual_text', 'summary', 'generated_question',
            'entity_card', 'table_row', 'other'
        )
    ),
    target_type          TEXT NOT NULL CHECK (
        target_type IN ('raw_segment', 'section', 'document', 'entity', 'synthetic', 'other')
    ),
    target_ref_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    title                TEXT,
    text                 TEXT NOT NULL,
    search_text          TEXT NOT NULL,
    block_type           TEXT NOT NULL DEFAULT 'unknown' CHECK (
        block_type IN ('paragraph', 'heading', 'table', 'list', 'code', 'blockquote', 'html_table', 'raw_html', 'unknown')
    ),
    semantic_role        TEXT NOT NULL DEFAULT 'unknown' CHECK (
        semantic_role IN (
            'concept', 'parameter', 'example', 'note', 'procedure_step',
            'troubleshooting_step', 'constraint', 'alarm', 'checklist', 'unknown'
        )
    ),
    facets_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    entity_refs_json     JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_refs_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    llm_result_refs_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_segment_id    TEXT REFERENCES asset_raw_segments(id) ON DELETE SET NULL,
    weight               REAL NOT NULL DEFAULT 1.0,
    created_at           TEXT NOT NULL,
    metadata_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    search_vector        TSVECTOR,
    UNIQUE (document_snapshot_id, unit_key)
);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_snapshot
    ON asset_retrieval_units(document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_unit_type
    ON asset_retrieval_units(unit_type);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_block_role
    ON asset_retrieval_units(block_type, semantic_role);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_source_segment
    ON asset_retrieval_units(source_segment_id);

-- Full-text search GIN index on tsvector column
CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_search_vector_gin
    ON asset_retrieval_units USING GIN (search_vector);

-- Trigram GIN index for similarity/Chinese text search
CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_text_trgm_gin
    ON asset_retrieval_units USING GIN (text gin_trgm_ops);

CREATE TABLE IF NOT EXISTS asset_retrieval_embeddings (
    id                 TEXT PRIMARY KEY,
    retrieval_unit_id  TEXT NOT NULL REFERENCES asset_retrieval_units(id) ON DELETE CASCADE,
    embedding_model    TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    text_kind          TEXT NOT NULL,
    embedding_dim      INTEGER NOT NULL CHECK (embedding_dim > 0),
    embedding_vector   TEXT NOT NULL,
    embedding_vector_vec vector(1024),
    content_hash       TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    metadata_json      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_embeddings_unit
    ON asset_retrieval_embeddings(retrieval_unit_id);

-- HNSW index for native cosine similarity search
CREATE INDEX IF NOT EXISTS idx_asset_retrieval_embeddings_vec_hnsw
    ON asset_retrieval_embeddings USING hnsw (embedding_vector_vec vector_cosine_ops);

CREATE TABLE IF NOT EXISTS asset_builds (
    id               TEXT PRIMARY KEY,
    build_code       TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL CHECK (
        status IN ('building', 'validated', 'failed', 'published', 'archived')
    ),
    build_mode       TEXT NOT NULL CHECK (build_mode IN ('full', 'incremental')),
    source_batch_id  TEXT REFERENCES asset_source_batches(id) ON DELETE SET NULL,
    parent_build_id  TEXT REFERENCES asset_builds(id) ON DELETE SET NULL,
    mining_run_id    TEXT,
    summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TEXT NOT NULL,
    finished_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_asset_builds_status
    ON asset_builds(status, created_at);

CREATE INDEX IF NOT EXISTS idx_asset_builds_source_batch
    ON asset_builds(source_batch_id);

CREATE TABLE IF NOT EXISTS asset_build_document_snapshots (
    build_id              TEXT NOT NULL REFERENCES asset_builds(id) ON DELETE CASCADE,
    document_id           TEXT NOT NULL REFERENCES asset_documents(id) ON DELETE CASCADE,
    document_snapshot_id  TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE RESTRICT,
    selection_status      TEXT NOT NULL CHECK (selection_status IN ('active', 'removed')),
    reason                TEXT NOT NULL CHECK (reason IN ('add', 'update', 'retain', 'remove')),
    metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (build_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_asset_build_document_snapshots_snapshot
    ON asset_build_document_snapshots(document_snapshot_id);

CREATE TABLE IF NOT EXISTS asset_publish_releases (
    id                   TEXT PRIMARY KEY,
    release_code         TEXT NOT NULL UNIQUE,
    build_id             TEXT NOT NULL REFERENCES asset_builds(id) ON DELETE RESTRICT,
    channel              TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('staging', 'active', 'retired', 'failed')),
    previous_release_id  TEXT REFERENCES asset_publish_releases(id) ON DELETE SET NULL,
    released_by          TEXT,
    release_notes        TEXT,
    activated_at         TEXT,
    deactivated_at       TEXT,
    metadata_json        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_publish_releases_channel_active
    ON asset_publish_releases(channel)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_build
    ON asset_publish_releases(build_id);

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_channel_status
    ON asset_publish_releases(channel, status);

-- Function to auto-update search_vector from text + title + search_text
CREATE OR REPLACE FUNCTION asset_retrieval_units_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.search_text, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.text, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_asset_retrieval_units_search_vector
    BEFORE INSERT OR UPDATE OF title, text, search_text ON asset_retrieval_units
    FOR EACH ROW EXECUTE FUNCTION asset_retrieval_units_search_vector_update();

-- Function to auto-populate vector column from embedding_vector JSON TEXT
CREATE OR REPLACE FUNCTION populate_embedding_vector_vec() RETURNS trigger AS $$
BEGIN
    IF NEW.embedding_vector IS NOT NULL AND NEW.embedding_vector != '' THEN
        BEGIN
            NEW.embedding_vector_vec := NEW.embedding_vector::jsonb::text::vector;
        EXCEPTION WHEN OTHERS THEN
            NEW.embedding_vector_vec := NULL;
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_populate_embedding_vector
    BEFORE INSERT OR UPDATE OF embedding_vector ON asset_retrieval_embeddings
    FOR EACH ROW EXECUTE FUNCTION populate_embedding_vector_vec();
