from pathlib import Path

import aiosqlite

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "databases"
    / "agent_llm_runtime"
    / "schemas"
    / "001_agent_llm_runtime.sqlite.sql"
)


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Open (or create) the SQLite database and ensure schema is applied.

    Uses isolation_level=None (autocommit) so that every SQL statement
    commits immediately.  This prevents stale-read snapshots caused by
    implicit transactions lingering across shared aiosqlite connections
    (e.g. the API connection used by both submit and dashboard handlers).
    All existing commit() calls become harmless no-ops.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    await conn.executescript(schema_sql)
    await conn.commit()
    return conn
