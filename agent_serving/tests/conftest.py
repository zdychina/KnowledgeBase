"""Shared test fixtures: v1.1 schema from shared DDL + seed data.

Uses the v1.1 three-layer model:
- documents + document_snapshots + snapshot_links
- raw_segments + relations
- retrieval_units with FTS5
- builds + build_document_snapshots
- publish_releases
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
import aiosqlite

from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite

# Fixed IDs for deterministic tests
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


async def _seed_v11_data(db: aiosqlite.Connection) -> None:
    """Insert v1.1 seed data with full three-layer model."""
    now = "2026-04-21T00:00:00Z"

    # source_batch
    await db.execute(
        "INSERT INTO asset_source_batches (id, batch_code, source_type, description, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (BATCH_ID, "BATCH-2026-04-21-001", "folder_scan", "v1.1 test batch", now, "{}"),
    )

    # documents
    await db.executemany(
        "INSERT INTO asset_documents (id, document_key, document_name, document_type, metadata_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (DOC_UDG, "UDG_OM_REF", "UDG OM参考手册", "command", "{}", now),
            (DOC_UNC, "UNC_OM_REF", "UNC OM参考手册", "command", "{}", now),
            (DOC_FEATURE, "5G_FEATURES", "5G特性与功能", "feature", "{}", now),
        ],
    )

    # document_snapshots
    await db.executemany(
        "INSERT INTO asset_document_snapshots "
        "(id, normalized_content_hash, raw_content_hash, mime_type, title, scope_json, tags_json, "
        "parser_profile_json, metadata_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (SNAP_UDG, "nhash_udg", "rhash_udg", "text/markdown", "UDG OM参考手册",
             json.dumps({"products": ["UDG"], "network_elements": ["UDM"]}), "[]", "{}", "{}", now),
            (SNAP_UNC, "nhash_unc", "rhash_unc", "text/markdown", "UNC OM参考手册",
             json.dumps({"products": ["UNC"], "network_elements": ["AMF"]}), "[]", "{}", "{}", now),
            (SNAP_FEATURE, "nhash_feature", "rhash_feature", "text/markdown", "5G特性与功能",
             json.dumps({"products": ["CloudCore"], "domains": ["5G"]}), "[]", "{}", "{}", now),
        ],
    )

    # document_snapshot_links
    await db.executemany(
        "INSERT INTO asset_document_snapshot_links "
        "(id, document_id, document_snapshot_id, source_batch_id, relative_path, source_uri, title, "
        "scope_json, tags_json, linked_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (LINK_UDG, DOC_UDG, SNAP_UDG, BATCH_ID, "udg_om.md", "file:///docs/udg_om.md",
             "UDG OM参考手册", "{}", "[]", now, "{}"),
            (LINK_UNC, DOC_UNC, SNAP_UNC, BATCH_ID, "unc_om.md", "file:///docs/unc_om.md",
             "UNC OM参考手册", "{}", "[]", now, "{}"),
            (LINK_FEATURE, DOC_FEATURE, SNAP_FEATURE, BATCH_ID, "5g_features.md", "file:///docs/5g_features.md",
             "5G特性与功能", "{}", "[]", now, "{}"),
        ],
    )

    # raw_segments
    await db.executemany(
        "INSERT INTO asset_raw_segments "
        "(id, document_snapshot_id, segment_key, segment_index, section_path, section_title, "
        "block_type, semantic_role, raw_text, normalized_text, content_hash, normalized_hash, "
        "entity_refs_json, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (RS_ADD_APN_UDG, SNAP_UDG, "UDG_ADD_APN", 0,
             json.dumps([{"title": "ADD APN", "level": 2}]), "ADD APN",
             "paragraph", "parameter",
             "ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]",
             "add apn 命令用于在udg上新增apn配置",
             "hash1", "nhash1",
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
             "{}"),
            (RS_ADD_APN_UNC, SNAP_UNC, "UNC_ADD_APN", 0,
             json.dumps([{"title": "ADD APN", "level": 2}]), "ADD APN",
             "paragraph", "parameter",
             "ADD APN 命令用于在UNC上新增APN配置。语法与UDG有差异。",
             "add apn 命令用于在unc上新增apn配置",
             "hash2", "nhash2",
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
             "{}"),
            (RS_5G_CONCEPT, SNAP_FEATURE, "5G_INTRO", 0,
             json.dumps([{"title": "5G概述", "level": 1}]), "5G概述",
             "paragraph", "concept",
             "5G是第五代移动通信技术，支持eMBB、mMTC和URLLC三大场景。",
             "5g是第五代移动通信技术",
             "hash3", "nhash3",
             json.dumps([{"type": "term", "name": "5G", "normalized_name": "5g"}]),
             "{}"),
        ],
    )

    # raw_segment_relations
    await db.executemany(
        "INSERT INTO asset_raw_segment_relations "
        "(id, document_snapshot_id, source_segment_id, target_segment_id, relation_type, weight, confidence, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (REL_NEXT, SNAP_UDG, RS_ADD_APN_UDG, RS_5G_CONCEPT, "next", 1.0, 1.0, "{}"),
            (REL_PREV, SNAP_UDG, RS_5G_CONCEPT, RS_ADD_APN_UDG, "previous", 1.0, 1.0, "{}"),
        ],
    )

    # retrieval_units (with source_segment_id bridge — v1.2 column)
    await db.executemany(
        "INSERT INTO asset_retrieval_units "
        "(id, document_snapshot_id, unit_key, unit_type, target_type, target_ref_json, title, "
        "text, search_text, block_type, semantic_role, facets_json, entity_refs_json, "
        "source_refs_json, weight, created_at, metadata_json, source_segment_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (RU_ADD_APN, SNAP_UDG, "RU_ADD_APN", "raw_text", "raw_segment",
             json.dumps({"raw_segment_id": RS_ADD_APN_UDG}),
             "ADD APN 命令",
             "ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]",
             "ADD APN 命令 新增 APN 配置 参数",
             "paragraph", "parameter",
             json.dumps({"products": ["UDG"]}),
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
             json.dumps({"raw_segment_ids": [RS_ADD_APN_UDG]}),
             1.0, now, "{}", RS_ADD_APN_UDG),
            (RU_5G, SNAP_FEATURE, "RU_5G_INTRO", "raw_text", "raw_segment",
             json.dumps({"raw_segment_id": RS_5G_CONCEPT}),
             "5G概述",
             "5G是第五代移动通信技术，支持eMBB、mMTC和URLLC三大场景。",
             "5G 概述 第五代 eMBB mMTC URLLC",
             "paragraph", "concept",
             json.dumps({"domains": ["5G"]}),
             json.dumps([{"type": "term", "name": "5G", "normalized_name": "5g"}]),
             json.dumps({"raw_segment_ids": [RS_5G_CONCEPT]}),
             1.0, now, "{}", RS_5G_CONCEPT),
            # contextual_text: same source_segment_id as RU_ADD_APN — for dedup test
            (RU_ADD_APN_CTX, SNAP_UDG, "RU_ADD_APN_CTX", "contextual_text", "raw_segment",
             json.dumps({"raw_segment_id": RS_ADD_APN_UDG}),
             "[ADD APN] ADD APN 命令",
             "[1.2 > ADD APN] ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]",
             "ADD APN 命令 新增 APN 配置 参数",
             "paragraph", "parameter",
             json.dumps({"products": ["UDG"]}),
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
             json.dumps({"raw_segment_ids": [RS_ADD_APN_UDG]}),
             0.9, now, "{}", RS_ADD_APN_UDG),
            # heading: low-value block type — for downweight test
            (RU_5G_HEADING, SNAP_FEATURE, "RU_5G_HEADING", "raw_text", "raw_segment",
             json.dumps({"raw_segment_id": RS_5G_CONCEPT}),
             "5G概述",
             "5G概述",
             "5G 概述",
             "heading", "concept",
             json.dumps({"domains": ["5G"]}),
             "[]",
             json.dumps({"raw_segment_ids": [RS_5G_CONCEPT]}),
             1.0, now, "{}", RS_5G_CONCEPT),
            # entity_card: SMF entity card
            (RU_SMF_ENTITY, SNAP_FEATURE, "RU_SMF_ENTITY", "entity_card", "raw_segment",
             json.dumps({"raw_segment_id": RS_5G_CONCEPT}),
             "SMF",
             "SMF (Session Management Function) 是5GC中的会话管理功能实体，负责PFCP会话建立和管理。",
             "SMF Session Management Function 5GC PFCP 会话",
             "paragraph", "concept",
             json.dumps({"network_elements": ["SMF"]}),
             json.dumps([{"type": "network_element", "name": "SMF", "normalized_name": "SMF"}]),
             json.dumps({"raw_segment_ids": [RS_5G_CONCEPT]}),
             1.0, now, "{}", RS_5G_CONCEPT),
            # generated_question: question about SMF
            (RU_SMF_QUESTION, SNAP_FEATURE, "RU_SMF_QUESTION", "generated_question", "raw_segment",
             json.dumps({"raw_segment_id": RS_5G_CONCEPT}),
             "SMF的作用是什么？",
             "SMF在5G核心网中负责会话管理，包括PFCP会话建立、UPF选择和IP地址分配。",
             "SMF 5G 核心网 会话管理 PFCP UPF IP",
             "paragraph", "concept",
             json.dumps({"domains": ["5G"]}),
             json.dumps([{"type": "network_element", "name": "SMF", "normalized_name": "SMF"}]),
             json.dumps({"raw_segment_ids": [RS_5G_CONCEPT]}),
             0.8, now, "{}", RS_5G_CONCEPT),
        ],
    )

    # v2: entity_refs_json column migration (if not already present)
    try:
        await db.execute(
            "ALTER TABLE asset_retrieval_units "
            "ADD COLUMN entity_refs_json TEXT DEFAULT '[]'"
        )
    except Exception:
        pass  # Column already exists

    # Update existing rows with entity_refs_json
    await db.execute(
        "UPDATE asset_retrieval_units SET entity_refs_json = ? WHERE id = ?",
        (json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]), RU_ADD_APN),
    )
    await db.execute(
        "UPDATE asset_retrieval_units SET entity_refs_json = ? WHERE id = ?",
        (json.dumps([{"type": "term", "name": "5G", "normalized_name": "5g"}]), RU_5G),
    )

    # build
    await db.execute(
        "INSERT INTO asset_builds "
        "(id, build_code, status, build_mode, source_batch_id, summary_json, validation_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (BUILD_ID, "BUILD-2026-04-21-001", "published", "full", BATCH_ID, "{}", "{}", now),
    )

    # build_document_snapshots
    await db.executemany(
        "INSERT INTO asset_build_document_snapshots "
        "(build_id, document_id, document_snapshot_id, selection_status, reason, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (BUILD_ID, DOC_UDG, SNAP_UDG, "active", "add", "{}"),
            (BUILD_ID, DOC_UNC, SNAP_UNC, "active", "add", "{}"),
            (BUILD_ID, DOC_FEATURE, SNAP_FEATURE, "active", "add", "{}"),
        ],
    )

    # publish_release
    await db.execute(
        "INSERT INTO asset_publish_releases "
        "(id, release_code, build_id, channel, status, released_by, activated_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (RELEASE_ID, "RELEASE-2026-04-21-001", BUILD_ID, "default", "active", "test", now, "{}"),
    )

    await db.commit()


@pytest_asyncio.fixture
async def db_connection():
    """In-memory SQLite with v1.1 schema and seed data."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_asset_tables_sqlite(db)
    await _seed_v11_data(db)
    yield db
    await db.close()


@pytest.fixture
def seed_ids():
    return SEED_IDS
