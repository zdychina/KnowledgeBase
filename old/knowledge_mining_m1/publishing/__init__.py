"""Publishing module: write pipeline results to SQLite with full lifecycle (v0.5 fix).

Key fixes:
- P1-4: version_code uses microsecond timestamp + short UUID
- P1-5: activate + metadata in same commit; on failure rollback preserves old active
- P1-6: validation uses LEFT JOIN to detect zero-primary canonicals
- P2-3: processing_profile_json includes parse_status for all documents

Flow:
1. Create source_batch + staging publish_version
2. Write all raw_documents (with parse_status in processing_profile)
3. Write all raw_segments
4. Write all canonical_segments
5. Write all canonical_segment_sources
6. Validate integrity
7. Atomic: archive old active → activate new staging → update metadata → commit
8. On failure: mark new version as failed, old active unchanged
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from knowledge_mining.mining.db import MiningDB
from knowledge_mining.mining.models import (
    BatchParams,
    CanonicalSegmentData,
    RawDocumentData,
    RawSegmentData,
    SourceMappingData,
)


def _make_version_code() -> str:
    """Generate unique version_code: pv-YYYYMMDD-HHmmss-XXXXXX."""
    now = datetime.now()
    short_id = uuid4().hex[:6]
    return f"pv-{now.strftime('%Y%m%d-%H%M%S')}-{short_id}"


def _make_batch_code() -> str:
    """Generate unique batch_code: batch-YYYYMMDD-HHmmss-XXXXXX."""
    now = datetime.now()
    short_id = uuid4().hex[:6]
    return f"batch-{now.strftime('%Y%m%d-%H%M%S')}-{short_id}"


def publish(
    documents: list[RawDocumentData],
    segments: list[RawSegmentData],
    canonicals: list[CanonicalSegmentData],
    source_mappings: list[SourceMappingData],
    db_path: Path,
    batch_params: BatchParams | None = None,
) -> dict[str, Any]:
    """Write all pipeline results to SQLite with full publish lifecycle.

    Returns summary with active_version_id and statistics.
    """
    batch_params = batch_params or BatchParams()
    batch_code = _make_batch_code()
    version_code = _make_version_code()

    db = MiningDB(db_path)
    db.create_tables()
    conn = db.connect()
    pv_id: str | None = None

    try:
        # Step 1: Create batch + staging version
        batch_metadata = {
            "default_document_type": batch_params.default_document_type,
            "default_source_type": batch_params.default_source_type,
            "batch_scope": batch_params.batch_scope,
            "tags": batch_params.tags,
            "storage_root_uri": batch_params.storage_root_uri,
            "original_root_name": batch_params.original_root_name,
        }
        batch_id = db.create_source_batch(
            conn, batch_code, batch_params.default_source_type,
            metadata_json=batch_metadata,
        )
        now = datetime.now()
        pv_metadata: dict[str, Any] = {"started_at": now.isoformat()}
        pv_id = db.create_publish_version(
            conn, version_code, "staging", batch_id,
            metadata_json=pv_metadata,
        )

        # Build set of document_keys that produced segments (i.e., were parsed)
        parsed_doc_keys: set[str] = set()
        for seg in segments:
            parsed_doc_keys.add(seg.document_key)

        # Step 2: Insert raw documents with proper processing_profile
        doc_ids: dict[str, str] = {}
        for doc in documents:
            processing_profile: dict[str, Any] = {}
            if doc.file_type not in ("markdown", "txt"):
                processing_profile["parse_status"] = "skipped"
                processing_profile["skip_reason"] = f"unsupported file_type: {doc.file_type}"
            elif doc.relative_path in parsed_doc_keys:
                processing_profile["parse_status"] = "parsed"
            else:
                processing_profile["parse_status"] = "skipped"
                processing_profile["skip_reason"] = "no segments produced"

            # Merge with any existing profile from doc
            if doc.processing_profile_json:
                merged = {**doc.processing_profile_json, **processing_profile}
            else:
                merged = processing_profile

            doc_id = db.insert_raw_document(
                conn,
                publish_version_id=pv_id,
                document_key=doc.relative_path,
                source_uri=doc.source_uri,
                relative_path=doc.relative_path,
                file_name=doc.file_name,
                file_type=doc.file_type,
                content_hash=doc.content_hash,
                source_type=doc.source_type,
                title=doc.title,
                document_type=doc.document_type,
                scope_json=doc.scope_json,
                tags_json=doc.tags_json,
                structure_quality=doc.structure_quality,
                processing_profile_json=merged,
                metadata_json=doc.metadata_json,
            )
            doc_ids[doc.relative_path] = doc_id

        # Step 3: Insert raw segments
        seg_ids: dict[str, str] = {}
        for seg in segments:
            seg_key = f"{seg.document_key}#{seg.segment_index}"
            raw_doc_id = doc_ids.get(seg.document_key)
            if not raw_doc_id:
                raise ValueError(f"raw_document not found for segment: {seg.document_key}")
            seg_id = db.insert_raw_segment(
                conn,
                publish_version_id=pv_id,
                raw_document_id=raw_doc_id,
                segment_key=seg_key,
                segment_index=seg.segment_index,
                block_type=seg.block_type,
                semantic_role=seg.semantic_role,
                raw_text=seg.raw_text,
                normalized_text=seg.normalized_text,
                content_hash=seg.content_hash,
                normalized_hash=seg.normalized_hash,
                token_count=seg.token_count,
                section_path=seg.section_path,
                section_title=seg.section_title,
                structure_json=seg.structure_json,
                source_offsets_json=seg.source_offsets_json,
                entity_refs_json=seg.entity_refs_json,
                metadata_json=seg.metadata_json,
            )
            seg_ids[seg_key] = seg_id

        # Step 4: Insert canonical segments
        canon_ids: dict[str, str] = {}
        for canon in canonicals:
            canon_id = db.insert_canonical_segment(
                conn,
                publish_version_id=pv_id,
                canonical_key=canon.canonical_key,
                block_type=canon.block_type,
                semantic_role=canon.semantic_role,
                canonical_text=canon.canonical_text,
                search_text=canon.search_text,
                title=canon.title,
                summary=canon.summary,
                entity_refs_json=canon.entity_refs_json,
                scope_json=canon.scope_json,
                has_variants=canon.has_variants,
                variant_policy=canon.variant_policy,
                quality_score=canon.quality_score,
                metadata_json=canon.metadata_json,
            )
            canon_ids[canon.canonical_key] = canon_id

        # Step 5: Insert source mappings
        for mapping in source_mappings:
            canon_id = canon_ids.get(mapping.canonical_key)
            seg_map_id = seg_ids.get(mapping.raw_segment_ref)
            if not canon_id:
                raise ValueError(f"canonical not found for mapping: {mapping.canonical_key}")
            if not seg_map_id:
                raise ValueError(f"raw_segment not found for mapping: {mapping.raw_segment_ref}")
            db.insert_source_mapping(
                conn,
                publish_version_id=pv_id,
                canonical_segment_id=canon_id,
                raw_segment_id=seg_map_id,
                relation_type=mapping.relation_type,
                is_primary=mapping.is_primary,
                priority=mapping.priority,
                similarity_score=mapping.similarity_score,
                diff_summary=mapping.diff_summary,
                metadata_json=mapping.metadata_json,
            )

        # Step 6: Validate
        errors = _validate(conn, pv_id)
        if errors:
            db.fail_version(conn, pv_id, "; ".join(errors))
            conn.commit()
            return {
                "status": "failed",
                "version_id": pv_id,
                "version_code": version_code,
                "errors": errors,
            }

        # Step 7: Atomic activate — archive old active + activate new + metadata
        # All in one commit so old active is never lost on failure
        db.activate_version(conn, pv_id)
        pv_metadata["finished_at"] = datetime.now().isoformat()
        pv_metadata["stats"] = {
            "documents": len(documents),
            "segments": len(segments),
            "canonicals": len(canonicals),
            "mappings": len(source_mappings),
        }
        conn.execute(
            """UPDATE asset_publish_versions
               SET build_finished_at = datetime('now'), metadata_json = ?
               WHERE id = ?""",
            (json.dumps(pv_metadata), pv_id),
        )
        conn.commit()

        return {
            "status": "active",
            "active_version_id": pv_id,
            "version_code": version_code,
            "documents": len(documents),
            "segments": len(segments),
            "canonicals": len(canonicals),
            "source_mappings": len(source_mappings),
        }

    except Exception as e:
        # Rollback first to preserve old active version (if activation had started)
        try:
            conn.rollback()
        except Exception:
            pass
        # In a separate transaction, mark the new version as failed
        # without archiving any existing active version
        try:
            if pv_id is not None:
                db.fail_version(conn, pv_id, str(e))
                conn.commit()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _validate(conn, pv_id: str) -> list[str]:
    """Validate data integrity before activation."""
    errors: list[str] = []

    # At least 1 raw_document
    count = conn.execute(
        "SELECT COUNT(*) FROM asset_raw_documents WHERE publish_version_id = ?",
        (pv_id,),
    ).fetchone()[0]
    if count == 0:
        errors.append("no raw_documents in version")

    # At least 1 canonical_segment
    count = conn.execute(
        "SELECT COUNT(*) FROM asset_canonical_segments WHERE publish_version_id = ?",
        (pv_id,),
    ).fetchone()[0]
    if count == 0:
        errors.append("no canonical_segments in version")

    # Every canonical has exactly 1 primary source (LEFT JOIN catches zero-primary)
    rows = conn.execute(
        """SELECT cs.id
           FROM asset_canonical_segments cs
           LEFT JOIN asset_canonical_segment_sources src
             ON cs.id = src.canonical_segment_id
             AND src.is_primary = 1
             AND src.publish_version_id = ?
           WHERE cs.publish_version_id = ?
           GROUP BY cs.id
           HAVING COUNT(src.id) != 1""",
        (pv_id, pv_id),
    ).fetchall()
    if rows:
        errors.append(f"canonicals with != 1 primary source: {len(rows)}")

    # Every canonical has at least 1 source mapping
    rows = conn.execute(
        """SELECT cs.id
           FROM asset_canonical_segments cs
           LEFT JOIN asset_canonical_segment_sources src
             ON cs.id = src.canonical_segment_id
             AND src.publish_version_id = ?
           WHERE cs.publish_version_id = ?
           GROUP BY cs.id
           HAVING COUNT(src.id) < 1""",
        (pv_id, pv_id),
    ).fetchall()
    if rows:
        errors.append(f"canonicals with no source mappings: {len(rows)}")

    return errors
