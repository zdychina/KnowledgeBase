"""PostgreSQL connection configuration for Mining v3.0.

All values come from .env (PG_HOST, PG_PORT, etc.).
No hardcoded defaults — missing env vars will raise an error.

Per-domain connections use `conninfo_from_env()` which reads a
postgresql:// URL from an environment variable specified in
domain_registry.yaml.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from psycopg.conninfo import make_conninfo
from pydantic import Field
from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parents[3]  # knowledge_mining/mining/infra/ -> CoreMasterKB/


def conninfo_from_url(url: str) -> str:
    """Convert a supported PostgreSQL URL to safely escaped conninfo."""
    value = str(url).strip()
    if value.startswith("jdbc:"):
        value = value[5:]

    try:
        parsed = urlparse(value)
        if parsed.scheme not in ("postgresql", "postgres"):
            raise ValueError("Invalid URL scheme for PostgreSQL database URL")
        if not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError

        params: dict[str, object] = {
            "host": parsed.hostname,
            "dbname": unquote(parsed.path.strip("/")),
        }
        if parsed.port is not None:
            params["port"] = parsed.port
        if parsed.username:
            params["user"] = unquote(parsed.username)
        if parsed.password:
            params["password"] = unquote(parsed.password)

        for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
            if values:
                params[key] = values[0]

        return make_conninfo(**params)
    except ValueError as exc:
        if str(exc).startswith("Invalid URL scheme"):
            raise
        raise ValueError("Invalid PostgreSQL database URL") from exc
    except Exception as exc:
        raise ValueError("Invalid PostgreSQL database URL") from exc


def conninfo_from_env(env_var: str) -> str:
    """Read a PostgreSQL URL from an environment variable and convert to psycopg conninfo.

    Supports formats:
    - postgresql://user:password@host:port/dbname
    - postgres://user:password@host:port/dbname

    Returns a psycopg-compatible conninfo string:
        host=... port=... dbname=... user=... password=...
    """
    import os

    url = os.environ.get(env_var, "")
    if not url:
        raise ValueError(
            f"Environment variable '{env_var}' is not set or empty. "
            f"Set it to a PostgreSQL URL, e.g. postgresql://user:pass@host:5432/dbname"
        )

    return conninfo_from_url(url)


class MiningDbConfig(BaseSettings):
    """PostgreSQL connection settings, loaded from environment variables."""

    pg_host: str
    pg_port: int = 5432
    pg_dbname: str
    pg_user: str
    # Excluding the password from repr prevents pytest fixture diagnostics and
    # incidental logging from printing a live database credential.
    pg_password: str = Field(repr=False)
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
        return make_conninfo(
            host=self.pg_host,
            port=self.pg_port,
            dbname=self.pg_dbname,
            user=self.pg_user,
            password=self.pg_password,
            sslmode=self.pg_sslmode,
            gssencmode=self.pg_gssencmode,
        )

    @property
    def maintenance_conninfo(self) -> str:
        """Connection string for the postgres maintenance DB (used to CREATE DATABASE)."""
        return make_conninfo(
            host=self.pg_host,
            port=self.pg_port,
            dbname="postgres",
            user=self.pg_user,
            password=self.pg_password,
            sslmode=self.pg_sslmode,
            gssencmode=self.pg_gssencmode,
        )
