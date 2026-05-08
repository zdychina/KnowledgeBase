from pathlib import Path

import aiosqlite

_SCHEMA_DIR = (
    Path(__file__).resolve().parent.parent
    / "databases"
    / "agent_llm_runtime"
    / "schemas"
)


async def _get_columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    """Return column names of a table."""
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Open (or create) the SQLite database and ensure schema is applied.

    Uses isolation_level=None (autocommit) so that every SQL statement
    commits immediately.  This prevents stale-read snapshots caused by
    implicit transactions lingering across shared aiosqlite connections
    (e.g. the API connection used by both submit and dashboard handlers).
    All existing commit() calls become harmless no-ops.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path, isolation_level=None, timeout=30.0)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = OFF")
    await conn.execute("PRAGMA busy_timeout = 30000")
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA synchronous = NORMAL")

    # 001: base schema (CREATE TABLE IF NOT EXISTS — idempotent)
    schema_001 = (_SCHEMA_DIR / "001_agent_llm_runtime.sqlite.sql").read_text(encoding="utf-8")
    await conn.executescript(schema_001)

    # 002: unified queue migration (conditional — ALTER TABLE is not idempotent)
    cols = await _get_columns(conn, "agent_llm_tasks")
    if "task_type" not in cols:
        await conn.execute(
            "ALTER TABLE agent_llm_tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'chat' "
            "CHECK (task_type IN ('chat', 'embedding', 'rerank'))"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_llm_tasks_type "
            "ON agent_llm_tasks(task_type, created_at DESC)"
        )

    # Widen expected_output_type CHECK on agent_llm_requests for existing DBs
    # New DBs already have the fixed schema from 001; this handles upgrades
    req_cols = await _get_columns(conn, "agent_llm_requests")
    if req_cols:
        # Check if the restrictive CHECK still exists by trying to detect it
        # SQLite stores CHECK in sql column of sqlite_master
        cur = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_llm_requests'"
        )
        row = await cur.fetchone()
        if row and "json_object" in (row["sql"] or ""):
            # Old schema with restrictive CHECK — recreate without it
            await conn.executescript("""
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
            """)

    await conn.execute("PRAGMA foreign_keys = ON")
    return conn
