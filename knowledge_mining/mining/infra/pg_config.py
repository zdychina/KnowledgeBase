"""PostgreSQL connection configuration for Mining v3.0.

All values come from .env (PG_HOST, PG_PORT, etc.).
No hardcoded defaults — missing env vars will raise an error.

Per-domain connections use `conninfo_from_env()` which reads a
postgresql:// URL from an environment variable specified in
domain_registry.yaml.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parents[3]  # knowledge_mining/mining/infra/ -> CoreMasterKB/


def conninfo_from_env(env_var: str) -> str:
    """Read a PostgreSQL URL from an environment variable and convert to psycopg conninfo.

    Supports formats:
    - postgresql://user:password@host:port/dbname
    - postgres://user:password@host:port/dbname

    Returns a psycopg-compatible conninfo string:
        host=... port=... dbname=... user=... password=...
    """
    url = os.environ.get(env_var, "")
    if not url:
        raise ValueError(
            f"Environment variable '{env_var}' is not set or empty. "
            f"Set it to a PostgreSQL URL, e.g. postgresql://user:pass@host:5432/dbname"
        )

    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError(
            f"Invalid URL scheme in '{env_var}': expected postgresql:// or postgres://, "
            f"got {parsed.scheme}://"
        )

    parts = []
    if parsed.hostname:
        parts.append(f"host={parsed.hostname}")
    if parsed.port:
        parts.append(f"port={parsed.port}")
    if parsed.path and parsed.path.strip("/"):
        parts.append(f"dbname={parsed.path.strip('/')}")
    if parsed.username:
        parts.append(f"user={parsed.username}")
    if parsed.password:
        parts.append(f"password={unquote(parsed.password)}")

    # Copy query params (like sslmode) as key=value
    qs = parse_qs(parsed.query)
    for key, values in qs.items():
        parts.append(f"{key}={values[0]}")

    return " ".join(parts)


class MiningDbConfig(BaseSettings):
    """PostgreSQL connection settings, loaded from environment variables."""

    pg_host: str
    pg_port: int = 5432
    pg_dbname: str
    pg_user: str
    pg_password: str
    pg_sslmode: str = "disable"
    pg_gssencmode: str = "disable"
    pg_pool_min: int = 2
    pg_pool_max: int = 10

    model_config = {
        "env_prefix": "",
        "env_file": str(_REPO_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def conninfo(self) -> str:
        """Build psycopg connection string."""
        return (
            f"host={self.pg_host} "
            f"port={self.pg_port} "
            f"dbname={self.pg_dbname} "
            f"user={self.pg_user} "
            f"password={self.pg_password} "
            f"sslmode={self.pg_sslmode} "
            f"gssencmode={self.pg_gssencmode}"
        )

    @property
    def maintenance_conninfo(self) -> str:
        """Connection string for the postgres maintenance DB (used to CREATE DATABASE)."""
        return (
            f"host={self.pg_host} "
            f"port={self.pg_port} "
            f"dbname=postgres "
            f"user={self.pg_user} "
            f"password={self.pg_password} "
            f"sslmode={self.pg_sslmode} "
            f"gssencmode={self.pg_gssencmode}"
        )
