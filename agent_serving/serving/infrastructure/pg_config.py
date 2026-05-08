"""Serving PostgreSQL configuration and connection pool factory.

Reads PG_* and EMBEDDING_DIMENSIONS from .env via pydantic-settings.
Creates a sync ConnectionPool with dict_row factory and autocommit.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class ServingDbConfig(BaseSettings):
    """Serving-layer PG connection config, read from environment."""

    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_dbname: str = "coremasterkb"
    pg_user: str = "kb_user"
    pg_password: str = ""
    pg_sslmode: str = "disable"
    pg_gssencmode: str = "disable"
    pg_pool_min: int = 2
    pg_pool_max: int = 10
    embedding_dimensions: int | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_dbname} "
            f"user={self.pg_user} password={self.pg_password} "
            f"sslmode={self.pg_sslmode} gssencmode={self.pg_gssencmode}"
        )

    @staticmethod
    def _configure_connection(conn) -> None:
        """Set autocommit on each connection pulled from the pool."""
        conn.autocommit = True

    def create_pool(self) -> ConnectionPool:
        return ConnectionPool(
            self.conninfo,
            min_size=self.pg_pool_min,
            max_size=self.pg_pool_max,
            open=False,
            kwargs={"row_factory": dict_row},
            configure=self._configure_connection,
        )
