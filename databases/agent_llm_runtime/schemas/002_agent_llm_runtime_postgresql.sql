-- agent_llm_runtime: PostgreSQL DDL
-- Converted from 001_agent_llm_runtime.sqlite.sql

CREATE TABLE IF NOT EXISTS agent_llm_prompt_templates (
    id                   TEXT PRIMARY KEY,
    template_key         TEXT NOT NULL,
    template_version     TEXT NOT NULL,
    knowledge_domain     TEXT,
    purpose              TEXT NOT NULL,
    system_prompt        TEXT,
    user_prompt_template TEXT NOT NULL,
    expected_output_type TEXT NOT NULL CHECK (
        expected_output_type IN ('json_object', 'json_array', 'text')
    ),
    output_schema_json   JSONB NOT NULL DEFAULT '{}',
    status               TEXT NOT NULL CHECK (status IN ('draft', 'active', 'archived')),
    created_at           TIMESTAMPTZ NOT NULL,
    metadata_json        JSONB NOT NULL DEFAULT '{}'
);

ALTER TABLE agent_llm_prompt_templates
    ADD COLUMN IF NOT EXISTS knowledge_domain TEXT;

ALTER TABLE agent_llm_prompt_templates
    DROP CONSTRAINT IF EXISTS agent_llm_prompt_templates_template_key_template_version_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_llm_prompt_templates_key_version_domain
    ON agent_llm_prompt_templates(template_key, template_version, COALESCE(knowledge_domain, ''));

CREATE INDEX IF NOT EXISTS idx_agent_llm_prompt_templates_domain_status
    ON agent_llm_prompt_templates(knowledge_domain, status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_llm_tasks (
    id                TEXT PRIMARY KEY,
    caller_service    TEXT NOT NULL,
    knowledge_domain  TEXT,
    pipeline_stage    TEXT NOT NULL,
    task_type         TEXT NOT NULL DEFAULT 'chat' CHECK (
        task_type IN ('chat', 'embedding', 'rerank')
    ),
    idempotency_key   TEXT,
    status            TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter', 'cancelled')
    ),
    priority          INTEGER NOT NULL DEFAULT 100,
    available_at      TIMESTAMPTZ,
    lease_expires_at  TIMESTAMPTZ,
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL DEFAULT 3,
    created_at        TIMESTAMPTZ NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    metadata_json     JSONB NOT NULL DEFAULT '{}'
);

ALTER TABLE agent_llm_tasks
    ADD COLUMN IF NOT EXISTS caller_service TEXT;

ALTER TABLE agent_llm_tasks
    ADD COLUMN IF NOT EXISTS knowledge_domain TEXT;

ALTER TABLE agent_llm_tasks
    ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'chat';

ALTER TABLE agent_llm_tasks
    ALTER COLUMN caller_service SET NOT NULL;

ALTER TABLE agent_llm_tasks
    DROP COLUMN IF EXISTS caller_domain;

CREATE INDEX IF NOT EXISTS idx_agent_llm_tasks_status_priority
    ON agent_llm_tasks(status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_agent_llm_tasks_type
    ON agent_llm_tasks(task_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_llm_tasks_service_domain
    ON agent_llm_tasks(caller_service, knowledge_domain, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_llm_requests (
    id                       TEXT PRIMARY KEY,
    task_id                  TEXT NOT NULL REFERENCES agent_llm_tasks(id) ON DELETE CASCADE,
    provider                 TEXT NOT NULL,
    model                    TEXT NOT NULL,
    prompt_template_key      TEXT,
    messages_json            JSONB NOT NULL DEFAULT '[]',
    input_json               JSONB NOT NULL DEFAULT '{}',
    params_json              JSONB NOT NULL DEFAULT '{}',
    expected_output_type     TEXT NOT NULL,
    output_schema_json       JSONB NOT NULL DEFAULT '{}',
    created_at               TIMESTAMPTZ NOT NULL,
    metadata_json            JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_requests_task
    ON agent_llm_requests(task_id);

CREATE TABLE IF NOT EXISTS agent_llm_attempts (
    id                 TEXT PRIMARY KEY,
    task_id            TEXT NOT NULL REFERENCES agent_llm_tasks(id) ON DELETE CASCADE,
    request_id         TEXT NOT NULL REFERENCES agent_llm_requests(id) ON DELETE CASCADE,
    attempt_no         INTEGER NOT NULL,
    status             TEXT NOT NULL CHECK (
        status IN ('running', 'succeeded', 'failed', 'timeout', 'rate_limited')
    ),
    raw_output_text    TEXT,
    raw_response_json  JSONB NOT NULL DEFAULT '{}',
    error_type         TEXT,
    error_message      TEXT,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    total_tokens       INTEGER,
    latency_ms         INTEGER,
    started_at         TIMESTAMPTZ NOT NULL,
    finished_at        TIMESTAMPTZ,
    metadata_json      JSONB NOT NULL DEFAULT '{}',
    UNIQUE (task_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_attempts_task
    ON agent_llm_attempts(task_id, attempt_no);

CREATE TABLE IF NOT EXISTS agent_llm_results (
    id                     TEXT PRIMARY KEY,
    task_id                TEXT NOT NULL REFERENCES agent_llm_tasks(id) ON DELETE CASCADE,
    attempt_id             TEXT REFERENCES agent_llm_attempts(id) ON DELETE SET NULL,
    parse_status           TEXT NOT NULL CHECK (
        parse_status IN ('not_required', 'succeeded', 'failed', 'schema_invalid')
    ),
    parsed_output_json     JSONB NOT NULL DEFAULT '{}',
    text_output            TEXT,
    parse_error            TEXT,
    validation_errors_json JSONB NOT NULL DEFAULT '[]',
    created_at             TIMESTAMPTZ NOT NULL,
    metadata_json          JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_results_task
    ON agent_llm_results(task_id);

CREATE TABLE IF NOT EXISTS agent_llm_events (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES agent_llm_tasks(id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL CHECK (
        event_type IN ('submitted', 'claimed', 'retried', 'succeeded', 'failed', 'cancelled', 'dead_letter')
    ),
    message        TEXT,
    metadata_json  JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_events_task
    ON agent_llm_events(task_id, created_at);

-- Model call logs (embedding / rerank — lightweight, append-only)
CREATE TABLE IF NOT EXISTS agent_llm_model_calls (
    id             TEXT PRIMARY KEY,
    call_type      TEXT NOT NULL CHECK (call_type IN ('embedding', 'rerank')),
    model          TEXT NOT NULL,
    caller_service TEXT NOT NULL,
    knowledge_domain TEXT,
    pipeline_stage TEXT NOT NULL,
    input_count    INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    latency_ms     INTEGER,
    token_usage    INTEGER,
    error_message  TEXT,
    created_at     TIMESTAMPTZ NOT NULL
);

ALTER TABLE agent_llm_model_calls
    ADD COLUMN IF NOT EXISTS caller_service TEXT;

ALTER TABLE agent_llm_model_calls
    ADD COLUMN IF NOT EXISTS knowledge_domain TEXT;

ALTER TABLE agent_llm_model_calls
    ADD COLUMN IF NOT EXISTS pipeline_stage TEXT;

UPDATE agent_llm_model_calls
SET caller_service = 'model'
WHERE caller_service IS NULL;

UPDATE agent_llm_model_calls
SET pipeline_stage = call_type
WHERE pipeline_stage IS NULL;

ALTER TABLE agent_llm_model_calls
    ALTER COLUMN caller_service SET NOT NULL;

ALTER TABLE agent_llm_model_calls
    ALTER COLUMN pipeline_stage SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_llm_model_calls_type
    ON agent_llm_model_calls(call_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_llm_model_calls_service_domain
    ON agent_llm_model_calls(caller_service, knowledge_domain, created_at DESC);
