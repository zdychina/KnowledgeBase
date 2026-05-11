"""PostgreSQL connection configuration for Mining v3.0.

All values come from .env (PG_HOST, PG_PORT, etc.).
No hardcoded defaults — missing env vars will raise an error.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parents[3]  # knowledge_mining/mining/infra/ -> CoreMasterKB/


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
