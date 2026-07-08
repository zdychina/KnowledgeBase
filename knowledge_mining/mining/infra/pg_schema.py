"""PostgreSQL schema initialization for Mining v3.0.

Ensures the target database exists (creates if needed),
then applies DDL for both asset_core and mining_runtime tables.
"""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg

from .pg_config import MiningDbConfig

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ASSET_DDL = _REPO_ROOT / "databases" / "asset_core" / "schemas" / "002_asset_core_postgresql.sql"
_RUNTIME_DDL = _REPO_ROOT / "databases" / "mining_runtime" / "schemas" / "002_mining_runtime_postgresql.sql"
_RUNTIME_DDL_V3 = _REPO_ROOT / "databases" / "mining_runtime" / "schemas" / "003_mining_runtime_domain.sql"
# Ontology concept layer — must apply AFTER asset/runtime (FKs target asset_* and mining_runs).
_ONTOLOGY_DDL = _REPO_ROOT / "databases" / "ontology" / "schemas" / "001_ontology_concept_postgresql.sql"


def ensure_database(cfg: MiningDbConfig) -> None:
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


def ensure_schema(cfg: MiningDbConfig) -> None:
    """Ensure database exists, then execute both DDL files (idempotent)."""
    ensure_database(cfg)

    conn = psycopg.connect(cfg.conninfo, autocommit=True)
    try:
        for ddl_path in (_ASSET_DDL, _RUNTIME_DDL, _RUNTIME_DDL_V3, _ONTOLOGY_DDL):
            ddl = ddl_path.read_text(encoding="utf-8")
            # Execute statement-by-statement for idempotency
            _execute_ddl(conn, ddl)
            logger.info("Applied DDL: %s", ddl_path.name)
    finally:
        conn.close()


def _execute_ddl(conn, ddl: str) -> None:
    """Execute DDL statement-by-statement, ignoring duplicate object errors.

    Splits on semicolons but respects dollar-quoted strings ($$...$$)
    used in PL/pgSQL function bodies.
    """
    import psycopg.errors

    # Split respecting $$ quoting
    stmts = _split_ddl(ddl)
    for stmt in stmts:
        stmt = _strip_leading_comments(stmt)
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
            pass  # Already exists — idempotent
        except Exception as exc:
            logger.error("DDL execution failed: %s | Statement: %s", exc, stmt[:200])
            raise


def _strip_leading_comments(stmt: str) -> str:
    """Remove leading single-line comments (-- ...) from a SQL statement."""
    lines = stmt.split("\n")
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            start = i + 1
        else:
            break
    result = "\n".join(lines[start:]).strip()
    return result


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

    # Handle remaining text
    remaining = "".join(current).strip()
    if remaining:
        stmts.append(remaining)

    return stmts
