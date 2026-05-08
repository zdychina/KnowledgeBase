-- 002_unified_queue: add task_type to agent_llm_tasks, widen expected_output_type CHECK
-- Migration: run after 001_agent_llm_runtime.sqlite.sql

-- 1. Add task_type column to agent_llm_tasks
ALTER TABLE agent_llm_tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'chat'
    CHECK (task_type IN ('chat', 'embedding', 'rerank'));

CREATE INDEX IF NOT EXISTS idx_agent_llm_tasks_type
    ON agent_llm_tasks(task_type, created_at DESC);

-- 2. Widen expected_output_type CHECK on agent_llm_requests
-- SQLite cannot ALTER CHECK constraints, so recreate the table.
CREATE TABLE IF NOT EXISTS agent_llm_requests_new (
    id                       TEXT PRIMARY KEY,
    task_id                  TEXT NOT NULL REFERENCES agent_llm_tasks(id) ON DELETE CASCADE,
    provider                 TEXT NOT NULL,
    model                    TEXT NOT NULL,
    prompt_template_key      TEXT,
    messages_json            TEXT NOT NULL DEFAULT '[]',
    input_json               TEXT NOT NULL DEFAULT '{}',
    params_json              TEXT NOT NULL DEFAULT '{}',
    expected_output_type     TEXT NOT NULL,
    output_schema_json       TEXT NOT NULL DEFAULT '{}',
    created_at               TEXT NOT NULL,
    metadata_json            TEXT NOT NULL DEFAULT '{}'
);

INSERT OR IGNORE INTO agent_llm_requests_new
    SELECT id, task_id, provider, model, prompt_template_key, messages_json,
           input_json, params_json, expected_output_type, output_schema_json,
           created_at, metadata_json
    FROM agent_llm_requests;

DROP TABLE IF EXISTS agent_llm_requests;
ALTER TABLE agent_llm_requests_new RENAME TO agent_llm_requests;

CREATE INDEX IF NOT EXISTS idx_agent_llm_requests_task
    ON agent_llm_requests(task_id);
