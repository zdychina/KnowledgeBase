"""Resolve one domain registry entry to a PostgreSQL connection target."""
from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Literal, Mapping

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .pg_config import MiningDbConfig, conninfo_from_url


@dataclass(frozen=True)
class ResolvedDomainDatabase:
    conninfo: str
    pool_min: int
    pool_max: int
    source: Literal["env", "inline", "global"]


def _pool_bounds(pool_min: object, pool_max: object) -> tuple[int, int]:
    if (
        isinstance(pool_min, bool)
        or isinstance(pool_max, bool)
        or not isinstance(pool_min, int)
        or not isinstance(pool_max, int)
        or pool_min < 1
        or pool_max < pool_min
    ):
        raise ValueError("Invalid database pool bounds")
    return pool_min, pool_max


def _resolved_from_url(
    value: str, *, source: Literal["env"], default: MiningDbConfig
) -> ResolvedDomainDatabase:
    pool_min, pool_max = _pool_bounds(default.pg_pool_min, default.pg_pool_max)
    return ResolvedDomainDatabase(
        conninfo_from_url(value), pool_min, pool_max, source
    )


def _resolved_from_inline(database: object) -> ResolvedDomainDatabase:
    if not isinstance(database, Mapping):
        raise ValueError("Invalid inline database configuration")

    pool_min, pool_max = _pool_bounds(
        database.get("pool_min", 2), database.get("pool_max", 10)
    )
    conn_params = {
        key: database[key]
        for key in (
            "host",
            "port",
            "dbname",
            "user",
            "password",
            "sslmode",
            "gssencmode",
            "connect_timeout",
        )
        if database.get(key) is not None
    }
    if not conn_params.get("host") or not conn_params.get("dbname"):
        raise ValueError("Invalid inline database configuration")
    try:
        conninfo = make_conninfo(**conn_params)
    except Exception as exc:
        raise ValueError("Invalid inline database configuration") from exc
    return ResolvedDomainDatabase(conninfo, pool_min, pool_max, "inline")


def resolve_domain_database(
    entry: Mapping[str, object],
    default: MiningDbConfig,
    environ: Mapping[str, str] | None = None,
) -> ResolvedDomainDatabase:
    """Resolve env override, inline registry config, then global config."""
    env = os.environ if environ is None else environ
    env_name = str(entry.get("database_url_env") or "").strip()
    env_url = str(env.get(env_name, "")).strip() if env_name else ""
    if env_url:
        return _resolved_from_url(env_url, source="env", default=default)
    if entry.get("database") is not None:
        return _resolved_from_inline(entry["database"])

    pool_min, pool_max = _pool_bounds(default.pg_pool_min, default.pg_pool_max)
    return ResolvedDomainDatabase(default.conninfo, pool_min, pool_max, "global")


def ensure_domain_database_schema(resolved: ResolvedDomainDatabase) -> None:
    """Run the shared mining schema initializer for a resolved database."""
    from .pg_schema import ensure_schema

    values = conninfo_to_dict(resolved.conninfo)
    dbname = values.get("dbname")
    if not dbname:
        raise RuntimeError("Resolved domain database has no database name")
    cfg = SimpleNamespace(
        conninfo=resolved.conninfo,
        maintenance_conninfo=make_conninfo(resolved.conninfo, dbname="postgres"),
        pg_dbname=dbname,
    )
    ensure_schema(cfg)
