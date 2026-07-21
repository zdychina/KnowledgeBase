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
_RUNTIME_DDL_V4 = _REPO_ROOT / "databases" / "mining_runtime" / "schemas" / "004_mining_runtime_run_stage.sql"
_ASSET_DOMAIN_DDL = _REPO_ROOT / "databases" / "asset_core" / "schemas" / "003_asset_core_domain_isolation.sql"
# Ontology concept layer — must apply AFTER asset/runtime (FKs target asset_* and mining_runs).
_ONTOLOGY_DDL = _REPO_ROOT / "databases" / "ontology" / "schemas" / "001_ontology_concept_postgresql.sql"


def _connect_safely(
    cfg: MiningDbConfig,
    *,
    maintenance: bool,
    autocommit: bool,
):
    """Open PostgreSQL without propagating credential-bearing driver errors."""
    database_name = "postgres" if maintenance else cfg.pg_dbname
    conninfo = cfg.maintenance_conninfo if maintenance else cfg.conninfo
    try:
        return psycopg.connect(
            conninfo,
            autocommit=autocommit,
            connect_timeout=5,
        )
    except psycopg.Error:
        # psycopg connection errors may echo the full conninfo (including the
        # password). Suppress the driver context at this boundary.
        raise RuntimeError(
            f"Unable to connect to PostgreSQL database {database_name!r}"
        ) from None


def ensure_database(cfg: MiningDbConfig) -> None:
    """Create the target database if it doesn't exist (connects to postgres maintenance DB)."""
    from psycopg import sql

    conn = _connect_safely(
        cfg,
        maintenance=True,
        autocommit=True,
    )
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

    conn = _connect_safely(
        cfg,
        maintenance=False,
        autocommit=True,
    )
    try:
        ddl_paths = (
            _ASSET_DDL, _RUNTIME_DDL, _RUNTIME_DDL_V3, _RUNTIME_DDL_V4,
            _ASSET_DOMAIN_DDL, _ONTOLOGY_DDL,
        )
        for ddl_path in ddl_paths:
            ddl = ddl_path.read_text(encoding="utf-8")
            _execute_ddl(
                conn,
                ddl,
                transactional=ddl_path in (_RUNTIME_DDL_V4, _ASSET_DOMAIN_DDL),
            )
            logger.info("Applied DDL: %s", ddl_path.name)
    finally:
        conn.close()


def _execute_ddl(conn, ddl: str, *, transactional: bool = False) -> None:
    """Execute DDL statement-by-statement, ignoring duplicate object errors.

    Splits on semicolons but respects dollar-quoted strings ($$...$$)
    used in PL/pgSQL function bodies.
    """
    import psycopg.errors

    stmts = _split_ddl(ddl)
    if transactional:
        with conn.transaction():
            for stmt in stmts:
                stmt = _strip_leading_comments(stmt)
                if not stmt:
                    continue
                try:
                    with conn.cursor() as cur:
                        cur.execute(stmt)
                except Exception as exc:
                    logger.error("DDL execution failed: %s | Statement: %s", exc, stmt[:200])
                    raise
        return

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
    """Split DDL on semicolons, respecting $$ quoting and line comments."""
    stmts: list[str] = []
    current: list[str] = []
    in_dollar_quote = False
    in_line_comment = False

    i = 0
    while i < len(ddl):
        if in_line_comment:
            current.append(ddl[i])
            if ddl[i] == "\n":
                in_line_comment = False
            i += 1
        elif ddl[i:i+2] == "--" and not in_dollar_quote:
            in_line_comment = True
            current.append("--")
            i += 2
        elif ddl[i:i+2] == "$$" and not in_dollar_quote:
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
