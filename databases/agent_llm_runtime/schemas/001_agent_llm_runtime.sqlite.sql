PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_llm_prompt_templates (
    id                   TEXT PRIMARY KEY,
    template_key         TEXT NOT NULL,
    template_version     TEXT NOT NULL,
    purpose              TEXT NOT NULL,
    system_prompt        TEXT,
    user_prompt_template TEXT NOT NULL,
    expected_output_type TEXT NOT NULL CHECK (
        expected_output_type IN ('json_object', 'json_array', 'text')
    ),
    output_schema_json   TEXT NOT NULL DEFAULT '{}',
    status               TEXT NOT NULL CHECK (status IN ('draft', 'active', 'archived')),
    created_at           TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    UNIQUE (template_key, template_version)
);

CREATE TABLE IF NOT EXISTS agent_llm_tasks (
    id                TEXT PRIMARY KEY,
    caller_domain     TEXT NOT NULL,
    pipeline_stage    TEXT NOT NULL,
    idempotency_key   TEXT,
    status            TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter', 'cancelled')
    ),
    priority          INTEGER NOT NULL DEFAULT 100,
    available_at      TEXT,
    lease_expires_at  TEXT,
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL DEFAULT 3,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    metadata_json     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_tasks_status_priority
    ON agent_llm_tasks(status, priority, created_at);

CREATE TABLE IF NOT EXISTS agent_llm_requests (
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
    raw_response_json  TEXT NOT NULL DEFAULT '{}',
    error_type         TEXT,
    error_message      TEXT,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    total_tokens       INTEGER,
    latency_ms         INTEGER,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    metadata_json      TEXT NOT NULL DEFAULT '{}',
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
    parsed_output_json     TEXT NOT NULL DEFAULT '{}',
    text_output            TEXT,
    parse_error            TEXT,
    validation_errors_json TEXT NOT NULL DEFAULT '[]',
    created_at             TEXT NOT NULL,
    metadata_json          TEXT NOT NULL DEFAULT '{}'
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
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_events_task
    ON agent_llm_events(task_id, created_at);

-- Model call logs (embedding / rerank — lightweight, append-only)
CREATE TABLE IF NOT EXISTS agent_llm_model_calls (
    id             TEXT PRIMARY KEY,
    call_type      TEXT NOT NULL CHECK (call_type IN ('embedding', 'rerank')),
    model          TEXT NOT NULL,
    input_count    INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    latency_ms     INTEGER,
    token_usage    INTEGER,
    error_message  TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_llm_model_calls_type
    ON agent_llm_model_calls(call_type, created_at DESC);
