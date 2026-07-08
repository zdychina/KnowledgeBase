"""Shared test fixtures — PostgreSQL backend.

All DB fixtures connect to the real PostgreSQL instance configured in .env.
Tables are cleaned up after each test via TRUNCATE.
"""
from __future__ import annotations

import pytest

from knowledge_mining.mining.infra.pg_config import MiningDbConfig
from knowledge_mining.mining.infra.pg_schema import ensure_schema


@pytest.fixture(scope="session")
def db_config():
    """Load PG config once per test session."""
    return MiningDbConfig()


@pytest.fixture(autouse=True, scope="session")
def _ensure_schema(db_config):
    """Ensure database + schema exist before any test runs."""
    ensure_schema(db_config)


def _truncate_all(conn):
    """Truncate all mining tables (asset + runtime + ontology) for clean test isolation."""
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
def asset_db(db_config):
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
def _cleanup_db(db_config):
    """Auto-cleanup all tables BEFORE each test for full isolation."""
    import psycopg
    conn = psycopg.connect(db_config.conninfo, autocommit=True)
    try:
        _truncate_all(conn)
    finally:
        conn.close()
    yield

@pytest.fixture
def runtime_db(db_config):
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
