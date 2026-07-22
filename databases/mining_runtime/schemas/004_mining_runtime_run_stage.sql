-- Mining Runtime Schema v1.3 - observable run phase and ingest audit events.
-- Executed transactionally by pg_schema.py; do not add BEGIN/COMMIT here.

ALTER TABLE mining_runs
    ADD COLUMN IF NOT EXISTS current_stage TEXT;

UPDATE mining_runs
SET current_stage = CASE
    WHEN status = 'completed' THEN 'done'
    WHEN status = 'awaiting_review' THEN 'review'
    WHEN status = 'queued' THEN 'queued'
    ELSE 'mining'
END
WHERE current_stage IS NULL OR current_stage = '';

ALTER TABLE mining_runs
    ALTER COLUMN current_stage SET DEFAULT 'queued';

ALTER TABLE mining_runs
    ALTER COLUMN current_stage SET NOT NULL;

ALTER TABLE mining_runs
    DROP CONSTRAINT IF EXISTS mining_runs_current_stage_check;

ALTER TABLE mining_runs
    ADD CONSTRAINT mining_runs_current_stage_check CHECK (
        current_stage IN ('queued', 'ingest', 'mining', 'review', 'publishing', 'done')
    );

ALTER TABLE mining_run_stage_events
    DROP CONSTRAINT IF EXISTS mining_run_stage_events_stage_check;

ALTER TABLE mining_run_stage_events
    ADD CONSTRAINT mining_run_stage_events_stage_check CHECK (
        stage IN (
            'ingest',
            'parse', 'segment', 'enrich', 'entity_extract', 'resolve', 'discourse',
            'retrieval_units', 'embedding', 'db_write', 'entity_relations',
            'graph_write', 'ontology_induction', 'graph_write_final',
            'commit_segments', 'build_relations', 'build_retrieval_units',
            'select_snapshot', 'assemble_build', 'validate_build',
            'publish_release', 'discourse_relations'
        )
    );
