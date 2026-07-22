CREATE TABLE IF NOT EXISTS mining_runs (
    id               TEXT PRIMARY KEY,
    source_batch_id  TEXT,
    input_path       TEXT NOT NULL,
    status           TEXT NOT NULL,
    current_stage    TEXT NOT NULL DEFAULT 'queued',
    build_id         TEXT,
    total_documents  INTEGER NOT NULL DEFAULT 0,
    new_count        INTEGER NOT NULL DEFAULT 0,
    updated_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    failed_count     INTEGER NOT NULL DEFAULT 0,
    committed_count  INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    error_summary    TEXT,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS mining_run_documents (
    id                      TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL REFERENCES mining_runs(id) ON DELETE CASCADE,
    document_key            TEXT NOT NULL,
    raw_content_hash        TEXT NOT NULL,
    normalized_content_hash TEXT,
    action                  TEXT NOT NULL,
    status                  TEXT NOT NULL,
    document_id             TEXT,
    document_snapshot_id    TEXT,
    error_message           TEXT,
    started_at              TEXT,
    finished_at             TEXT,
    metadata_json           TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, document_key)
);

CREATE TABLE IF NOT EXISTS mining_run_stage_events (
    id               TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL REFERENCES mining_runs(id) ON DELETE CASCADE,
    run_document_id  TEXT REFERENCES mining_run_documents(id) ON DELETE CASCADE,
    stage            TEXT NOT NULL,
    status           TEXT NOT NULL,
    duration_ms      INTEGER,
    output_summary   TEXT,
    error_message    TEXT,
    created_at       TEXT NOT NULL,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mining_runs_status
    ON mining_runs(status);

CREATE INDEX IF NOT EXISTS idx_mining_run_documents_run_status
    ON mining_run_documents(run_id, status);

CREATE INDEX IF NOT EXISTS idx_mining_run_documents_snapshot
    ON mining_run_documents(document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_mining_run_stage_events_run
    ON mining_run_stage_events(run_id, stage, created_at);

CREATE INDEX IF NOT EXISTS idx_mining_run_stage_events_document
    ON mining_run_stage_events(run_document_id, stage, created_at);
