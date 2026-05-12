-- CoreMasterKB Asset Core Schema v1.1 - Generic SQL baseline
--
-- Notes:
-- 1. This file mirrors the SQLite contract semantically.
-- 2. asset_core stores stable content assets plus build/release control data.
-- 3. Shared immutable content snapshots are the content reuse boundary.
-- 4. Build selects document -> snapshot mappings.
-- 5. Release publishes one build to one channel.
-- 6. Full-text search integration is implementation-specific and should be adapted by the runtime database layer.

CREATE TABLE IF NOT EXISTS asset_source_batches (
    id            TEXT PRIMARY KEY,
    batch_code    TEXT NOT NULL UNIQUE,
    source_type   TEXT NOT NULL,
    domain        TEXT NOT NULL DEFAULT 'default',
    description   TEXT,
    created_by    TEXT,
    created_at    TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asset_documents (
    id             TEXT PRIMARY KEY,
    document_key   TEXT NOT NULL UNIQUE,
    document_name  TEXT,
    document_type  TEXT,
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_document_snapshots (
    id                      TEXT PRIMARY KEY,
    normalized_content_hash TEXT NOT NULL UNIQUE,
    raw_content_hash        TEXT NOT NULL,
    mime_type               TEXT NOT NULL,
    title                   TEXT,
    scope_json              TEXT NOT NULL DEFAULT '{}',
    tags_json               TEXT NOT NULL DEFAULT '[]',
    parser_profile_json     TEXT NOT NULL DEFAULT '{}',
    metadata_json           TEXT NOT NULL DEFAULT '{}',
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_document_snapshot_links (
    id                   TEXT PRIMARY KEY,
    document_id          TEXT NOT NULL REFERENCES asset_documents(id) ON DELETE CASCADE,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE RESTRICT,
    source_batch_id      TEXT REFERENCES asset_source_batches(id) ON DELETE SET NULL,
    relative_path        TEXT NOT NULL,
    source_uri           TEXT NOT NULL,
    title                TEXT,
    scope_json           TEXT NOT NULL DEFAULT '{}',
    tags_json            TEXT NOT NULL DEFAULT '[]',
    linked_at            TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asset_raw_segments (
    id                   TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    segment_key          TEXT NOT NULL,
    segment_index        INTEGER NOT NULL,
    section_path         TEXT NOT NULL DEFAULT '[]',
    section_title        TEXT,
    block_type           TEXT NOT NULL DEFAULT 'unknown',
    semantic_role        TEXT NOT NULL DEFAULT 'unknown',
    raw_text             TEXT NOT NULL,
    normalized_text      TEXT NOT NULL,
    content_hash         TEXT NOT NULL,
    normalized_hash      TEXT NOT NULL,
    token_count          INTEGER,
    structure_json       TEXT NOT NULL DEFAULT '{}',
    source_offsets_json  TEXT NOT NULL DEFAULT '{}',
    entity_refs_json     TEXT NOT NULL DEFAULT '[]',
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    UNIQUE (document_snapshot_id, segment_key)
);

CREATE TABLE IF NOT EXISTS asset_raw_segment_relations (
    id                   TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    source_segment_id    TEXT NOT NULL REFERENCES asset_raw_segments(id) ON DELETE CASCADE,
    target_segment_id    TEXT NOT NULL REFERENCES asset_raw_segments(id) ON DELETE CASCADE,
    relation_type        TEXT NOT NULL,
    weight               DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    confidence           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    distance             INTEGER,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source_segment_id, target_segment_id, relation_type)
);

CREATE TABLE IF NOT EXISTS asset_retrieval_units (
    id                   TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    unit_key             TEXT NOT NULL,
    unit_type            TEXT NOT NULL,
    target_type          TEXT NOT NULL,
    target_ref_json      TEXT NOT NULL DEFAULT '{}',
    title                TEXT,
    text                 TEXT NOT NULL,
    search_text          TEXT NOT NULL,
    block_type           TEXT NOT NULL DEFAULT 'unknown',
    semantic_role        TEXT NOT NULL DEFAULT 'unknown',
    facets_json          TEXT NOT NULL DEFAULT '{}',
    entity_refs_json     TEXT NOT NULL DEFAULT '[]',
    source_refs_json     TEXT NOT NULL DEFAULT '{}',
    llm_result_refs_json TEXT NOT NULL DEFAULT '{}',
    weight               DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at           TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    UNIQUE (document_snapshot_id, unit_key)
);

CREATE TABLE IF NOT EXISTS asset_retrieval_embeddings (
    id                 TEXT PRIMARY KEY,
    retrieval_unit_id  TEXT NOT NULL REFERENCES asset_retrieval_units(id) ON DELETE CASCADE,
    embedding_model    TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    text_kind          TEXT NOT NULL,
    embedding_dim      INTEGER NOT NULL,
    embedding_vector   TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    metadata_json      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asset_builds (
    id               TEXT PRIMARY KEY,
    build_code       TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL,
    build_mode       TEXT NOT NULL,
    domain           TEXT NOT NULL DEFAULT 'default',
    source_batch_id  TEXT REFERENCES asset_source_batches(id) ON DELETE SET NULL,
    parent_build_id  TEXT REFERENCES asset_builds(id) ON DELETE SET NULL,
    mining_run_id    TEXT,
    summary_json     TEXT NOT NULL DEFAULT '{}',
    validation_json  TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    finished_at      TEXT
);

CREATE TABLE IF NOT EXISTS asset_build_document_snapshots (
    build_id              TEXT NOT NULL REFERENCES asset_builds(id) ON DELETE CASCADE,
    document_id           TEXT NOT NULL REFERENCES asset_documents(id) ON DELETE CASCADE,
    document_snapshot_id  TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE RESTRICT,
    selection_status      TEXT NOT NULL,
    reason                TEXT NOT NULL,
    metadata_json         TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (build_id, document_id)
);

CREATE TABLE IF NOT EXISTS asset_publish_releases (
    id                   TEXT PRIMARY KEY,
    release_code         TEXT NOT NULL UNIQUE,
    build_id             TEXT NOT NULL REFERENCES asset_builds(id) ON DELETE RESTRICT,
    domain               TEXT NOT NULL DEFAULT 'default',
    channel              TEXT NOT NULL DEFAULT 'prod',
    status               TEXT NOT NULL,
    previous_release_id  TEXT REFERENCES asset_publish_releases(id) ON DELETE SET NULL,
    released_by          TEXT,
    release_notes        TEXT,
    activated_at         TEXT,
    deactivated_at       TEXT,
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_asset_documents_type
    ON asset_documents(document_type);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshots_raw_hash
    ON asset_document_snapshots(raw_content_hash);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshot_links_document
    ON asset_document_snapshot_links(document_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshot_links_snapshot
    ON asset_document_snapshot_links(document_snapshot_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_document_snapshot_links_batch
    ON asset_document_snapshot_links(source_batch_id);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_snapshot
    ON asset_raw_segments(document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segment_relations_snapshot
    ON asset_raw_segment_relations(document_snapshot_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_snapshot
    ON asset_retrieval_units(document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_retrieval_embeddings_unit
    ON asset_retrieval_embeddings(retrieval_unit_id);

CREATE INDEX IF NOT EXISTS idx_asset_builds_status
    ON asset_builds(status, created_at);

CREATE INDEX IF NOT EXISTS idx_asset_build_document_snapshots_snapshot
    ON asset_build_document_snapshots(document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_build
    ON asset_publish_releases(build_id);

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_domain_channel_status
    ON asset_publish_releases(domain, channel, status);
