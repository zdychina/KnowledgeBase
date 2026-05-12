"""Snapshot stage: manage shared document snapshots for v1.1.

Implements the three-layer model:
- document (identity via document_key)
- snapshot (shared content via normalized_content_hash)
- link (document -> snapshot mapping)
"""
from __future__ import annotations

import uuid
from typing import Any

from knowledge_mining.mining.infra.db import AssetCoreDB
from knowledge_mining.mining.contracts.models import RawFileData, DocumentProfile


def select_or_create_snapshot(
    asset_db: AssetCoreDB,
    doc: RawFileData,
    profile: DocumentProfile,
    *,
    batch_id: str | None = None,
) -> tuple[str, str, str]:
    """Select existing or create new snapshot for a document.

    Returns (document_id, snapshot_id, link_id).
    If snapshot already exists (same normalized_content_hash), reuses it.
    """
    from knowledge_mining.mining.ingestion import get_mime_type

    mime_type = get_mime_type(doc.file_type)

    # 1. Upsert document (identity)
    document_id = uuid.uuid4().hex
    existing_doc = asset_db.get_document_by_key(profile.document_key)
    if existing_doc:
        document_id = existing_doc["id"]

    asset_db.upsert_document(
        document_id=document_id,
        document_key=profile.document_key,
        document_name=doc.file_name,
        document_type=profile.document_type,
        metadata_json=doc.metadata_json,
    )

    # 2. Find or create snapshot
    snapshot_id = uuid.uuid4().hex
    existing_snap = asset_db.get_snapshot_by_hash(doc.normalized_content_hash)
    if existing_snap:
        snapshot_id = existing_snap["id"]

    asset_db.upsert_snapshot(
        snapshot_id=snapshot_id,
        normalized_content_hash=doc.normalized_content_hash,
        raw_content_hash=doc.raw_content_hash,
        mime_type=mime_type,
        title=doc.title,
        scope_json=doc.scope_json,
        tags_json=doc.tags_json,
        parser_profile_json={"file_type": doc.file_type},
        metadata_json=doc.metadata_json,
    )

    # 3. Create link (always new for this ingestion)
    link_id = uuid.uuid4().hex
    asset_db.insert_snapshot_link(
        link_id=link_id,
        document_id=document_id,
        document_snapshot_id=snapshot_id,
        source_batch_id=batch_id,
        relative_path=doc.relative_path,
        source_uri=doc.source_uri,
        title=doc.title,
        scope_json=doc.scope_json,
        tags_json=doc.tags_json,
    )

    return document_id, snapshot_id, link_id
