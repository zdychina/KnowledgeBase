"""Shared test fixtures — PostgreSQL backend.

Only tests requesting a DB fixture initialize PostgreSQL. Database setup and
cleanup are refused unless the configured database name ends with ``_test``.
"""
from __future__ import annotations

import pytest

from knowledge_mining.mining.infra.pg_config import MiningDbConfig
from knowledge_mining.mining.infra.pg_schema import ensure_schema


def _assert_disposable_database(db_config) -> None:
    """Refuse schema setup and cleanup unless the configured DB is disposable."""
    dbname = db_config.pg_dbname.strip().lower()
    if not dbname.endswith("_test"):
        raise RuntimeError(
            f"Refusing to use non-disposable PostgreSQL database {dbname!r}; "
            "test database names must end with '_test'."
        )


@pytest.fixture(scope="session")
def db_config():
    """Load PG config once per test session."""
    return MiningDbConfig()


@pytest.fixture(scope="session", autouse=True)
def _guard_test_database(db_config):
    """Reject a non-test database for every test session without connecting."""
    _assert_disposable_database(db_config)


@pytest.fixture(scope="session")
def _ensure_schema(db_config):
    """Ensure database + schema exist before any test runs."""
    _assert_disposable_database(db_config)
    ensure_schema(db_config)


def _truncate_all(conn):
    """Truncate all mining tables (asset + runtime + ontology) for clean test isolation.

    安全护栏（默认彻底关闭自动清表）：除非显式设置环境变量
    ``KB_ALLOW_TEST_TRUNCATE=1``，否则本函数直接返回、不删任何表——
    防止误删 ``.env`` 指向的真实库（尤其生产库 coremasterkb）。
    需要自动清测试库时，自行 ``export KB_ALLOW_TEST_TRUNCATE=1`` 再跑；
    平时一律手动清库。
    """
    import os

    if os.environ.get("KB_ALLOW_TEST_TRUNCATE") != "1":
        return

    conn.execute("TRUNCATE TABLE mining_run_stage_events CASCADE")
    conn.execute("TRUNCATE TABLE mining_run_documents CASCADE")
    conn.execute("TRUNCATE TABLE mining_runs CASCADE")
    conn.execute("TRUNCATE TABLE asset_raw_segment_relations CASCADE")
    conn.execute("TRUNCATE TABLE asset_raw_segments CASCADE")
    conn.execute("TRUNCATE TABLE asset_retrieval_embeddings CASCADE")
    conn.execute("TRUNCATE TABLE asset_retrieval_units CASCADE")
    conn.execute("TRUNCATE TABLE asset_build_document_snapshots CASCADE")
    conn.execute("TRUNCATE TABLE asset_publish_releases CASCADE")
    conn.execute("TRUNCATE TABLE asset_builds CASCADE")
    conn.execute("TRUNCATE TABLE asset_document_snapshot_links CASCADE")
    conn.execute("TRUNCATE TABLE asset_document_snapshots CASCADE")
    conn.execute("TRUNCATE TABLE asset_documents CASCADE")
    conn.execute("TRUNCATE TABLE asset_source_batches CASCADE")

    # 本体/图谱表是 domain 维度（不随 run 销毁），不清会让上批测试残留的待审
    # 候选/实体在下批测试里触发"本体确认"闸口暂停，污染端到端流水线断言。
    # asset_segment_entity_mentions 存待审 mention（按 run 关联）。
    # 这些表在更老的测试库里可能不存在，逐个 try 以保持向后兼容。
    for tbl in (
        "asset_segment_entity_mentions",
        "ontology_candidates",
        "ontology_evidence_nodes",
        "ontology_entity_relations",
        "ontology_entities",
        "ontology_alias_dictionary",
        "ontology_relation_types",
        "ontology_node_types",
        "ontology_versions",
    ):
        try:
            conn.execute(f"TRUNCATE TABLE {tbl} CASCADE")
        except Exception:
            pass


@pytest.fixture
def asset_db(db_config, _ensure_schema):
    """Provide an AssetCoreDB connected to PG, with cleanup after test."""
    from knowledge_mining.mining.infra.db import AssetCoreDB
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        db_config.conninfo,
        min_size=1,
        max_size=2,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    db = AssetCoreDB(pool)
    yield db

    import psycopg as _psycopg
    conn = _psycopg.connect(db_config.conninfo, autocommit=True)
    try:
        _truncate_all(conn)
    finally:
        conn.close()

    pool.close()


@pytest.fixture(autouse=True)
def _cleanup_db(request):
    """Auto-cleanup all tables BEFORE each test for full isolation."""
    if "_ensure_schema" not in request.fixturenames:
        yield
        return

    import psycopg
    db_config = request.getfixturevalue("db_config")
    _assert_disposable_database(db_config)
    conn = psycopg.connect(db_config.conninfo, autocommit=True)
    try:
        _truncate_all(conn)
    finally:
        conn.close()
    yield

@pytest.fixture
def runtime_db(db_config, _ensure_schema):
    """Provide a MiningRuntimeDB connected to PG, with cleanup after test."""
    from knowledge_mining.mining.infra.db import MiningRuntimeDB
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        db_config.conninfo,
        min_size=1,
        max_size=2,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    db = MiningRuntimeDB(pool)
    yield db

    import psycopg as _psycopg
    conn = _psycopg.connect(db_config.conninfo, autocommit=True)
    try:
        _truncate_all(conn)
    finally:
        conn.close()

    pool.close()
