"""Shared test fixtures: PG pool backend for integration tests.

Tests require a seeded PostgreSQL database.
Run `python -m agent_serving.scripts.seed_pg` before tests.

All PG-dependent tests are marked with @pytest.mark.pg.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_serving.serving.infrastructure.pg_config import ServingDbConfig

# Fixed IDs for deterministic tests (same as seed_pg.py)
BATCH_ID = "00000000-0000-0000-0000-000000000001"
BUILD_ID = "11111111-1111-1111-1111-111111111111"
RELEASE_ID = "22222222-2222-2222-2222-222222222222"

DOC_UDG = "33333333-3333-3333-3333-333333333333"
DOC_UNC = "44444444-4444-4444-4444-444444444444"
DOC_FEATURE = "55555555-5555-5555-5555-555555555555"

SNAP_UDG = "aaaa0000-0000-0000-0000-000000000001"
SNAP_UNC = "aaaa0000-0000-0000-0000-000000000002"
SNAP_FEATURE = "aaaa0000-0000-0000-0000-000000000003"

LINK_UDG = "bbbb0000-0000-0000-0000-000000000001"
LINK_UNC = "bbbb0000-0000-0000-0000-000000000002"
LINK_FEATURE = "bbbb0000-0000-0000-0000-000000000003"

RS_ADD_APN_UDG = "cccc0000-0000-0000-0000-000000000001"
RS_ADD_APN_UNC = "cccc0000-0000-0000-0000-000000000002"
RS_5G_CONCEPT = "cccc0000-0000-0000-0000-000000000003"

REL_NEXT = "dddd0000-0000-0000-0000-000000000001"
REL_PREV = "dddd0000-0000-0000-0000-000000000002"

RU_ADD_APN = "eeee0000-0000-0000-0000-000000000001"
RU_5G = "eeee0000-0000-0000-0000-000000000002"
RU_ADD_APN_CTX = "eeee0000-0000-0000-0000-000000000003"
RU_5G_HEADING = "eeee0000-0000-0000-0000-000000000004"
RU_SMF_ENTITY = "eeee0000-0000-0000-0000-000000000005"
RU_SMF_QUESTION = "eeee0000-0000-0000-0000-000000000006"


SEED_IDS = {
    "batch_id": BATCH_ID,
    "build_id": BUILD_ID,
    "release_id": RELEASE_ID,
    "doc_udg": DOC_UDG,
    "doc_unc": DOC_UNC,
    "doc_feature": DOC_FEATURE,
    "snap_udg": SNAP_UDG,
    "snap_unc": SNAP_UNC,
    "snap_feature": SNAP_FEATURE,
    "rs_add_apn_udg": RS_ADD_APN_UDG,
    "rs_add_apn_unc": RS_ADD_APN_UNC,
    "rs_5g_concept": RS_5G_CONCEPT,
    "ru_add_apn": RU_ADD_APN,
    "ru_5g": RU_5G,
    "ru_add_apn_ctx": RU_ADD_APN_CTX,
    "ru_5g_heading": RU_5G_HEADING,
    "ru_smf_entity": RU_SMF_ENTITY,
    "ru_smf_question": RU_SMF_QUESTION,
}


@pytest_asyncio.fixture
async def pg_pool():
    """AsyncConnectionPool for tests (reads PG_* from .env)."""
    config = ServingDbConfig()
    pool = config.create_pool()
    await pool.open()
    yield pool
    await pool.close()


@pytest.fixture
def seed_ids():
    return SEED_IDS
