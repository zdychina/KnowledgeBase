"""PostgreSQL schema initialization for llm_service.

Ensures the target database exists (creates if needed),
then applies DDL for agent_llm_runtime tables.
"""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg

from .pg_config import LlmDbConfig

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DDL_PATH = _REPO_ROOT / "databases" / "agent_llm_runtime" / "schemas" / "002_agent_llm_runtime_postgresql.sql"


def ensure_database(cfg: LlmDbConfig) -> None:
    """Create the target database if it doesn't exist (connects to postgres maintenance DB)."""
    from psycopg import sql

    conn = psycopg.connect(cfg.maintenance_conninfo, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg.pg_dbname,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cfg.pg_dbname)))
                logger.info("Created database %s", cfg.pg_dbname)
            else:
                logger.info("Database %s already exists", cfg.pg_dbname)
    finally:
        conn.close()


def ensure_schema(cfg: LlmDbConfig) -> None:
    """Ensure database exists, then execute DDL file (idempotent)."""
    ensure_database(cfg)

    conn = psycopg.connect(cfg.conninfo, autocommit=True)
    try:
        ddl = _DDL_PATH.read_text(encoding="utf-8")
        _execute_ddl(conn, ddl)
        logger.info("Applied DDL: %s", _DDL_PATH.name)
    finally:
        conn.close()


def _execute_ddl(conn, ddl: str) -> None:
    """Execute DDL statement-by-statement, ignoring duplicate object errors."""
    import psycopg.errors

    stmts = _split_ddl(ddl)
    for stmt in stmts:
        # Strip leading/trailing comment lines — keep the actual SQL
        lines = stmt.strip().split('\n')
        sql_lines = [l for l in lines if not l.strip().startswith('--')]
        stmt = '\n'.join(sql_lines).strip()
        if not stmt:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
        except (
            psycopg.errors.DuplicateObject,
            psycopg.errors.DuplicateTable,
            psycopg.errors.DuplicateFunction,
        ):
            pass


def _split_ddl(ddl: str) -> list[str]:
    """Split DDL on semicolons, respecting $$ quoting."""
    stmts: list[str] = []
    current: list[str] = []
    in_dollar_quote = False

    i = 0
    while i < len(ddl):
        if ddl[i:i+2] == "$$" and not in_dollar_quote:
            in_dollar_quote = True
            current.append("$$")
            i += 2
        elif ddl[i:i+2] == "$$" and in_dollar_quote:
            in_dollar_quote = False
            current.append("$$")
            i += 2
        elif ddl[i] == ";" and not in_dollar_quote:
            current.append(";")
            stmt = "".join(current).strip()
            if stmt:
                stmts.append(stmt)
            current = []
            i += 1
        else:
            current.append(ddl[i])
            i += 1

    remaining = "".join(current).strip()
    if remaining:
        stmts.append(remaining)

    return stmts
