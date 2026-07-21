"""Domain-isolation contracts for AssetCore repository writes and snapshots."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from knowledge_mining.mining.contracts.models import (
    DocumentProfile,
    RawFileData,
    RawSegmentData,
    SectionNode,
)
from knowledge_mining.mining.pipeline import DocumentContext, PipelineConfig, db_write_stage
from knowledge_mining.mining.snapshot import select_or_create_snapshot


def _create_document(asset_db, *, domain: str, document_id: str, key: str = "doc:/same.md") -> str:
    return asset_db.upsert_document(
        domain=domain,
        document_id=document_id,
        document_key=key,
        document_name="same.md",
        document_type="reference",
    )


def _create_snapshot(
    asset_db,
    *,
    domain: str,
    snapshot_id: str,
    content_hash: str = "same-hash",
    raw_hash: str = "raw-hash",
) -> str:
    return asset_db.upsert_snapshot(
        domain=domain,
        snapshot_id=snapshot_id,
        normalized_content_hash=content_hash,
        raw_content_hash=raw_hash,
        mime_type="text/markdown",
        title="Original",
        scope_json={"scope": "original"},
        tags_json=["original"],
        parser_profile_json={"parser": "original"},
        metadata_json={"metadata": "original"},
    )


def _create_batch(asset_db, *, domain: str, batch_id: str) -> str:
    return asset_db.upsert_source_batch(
        domain=domain,
        batch_id=batch_id,
        batch_code=f"CODE-{batch_id}",
        source_type="folder_scan",
    )


def test_same_document_key_isolated_between_domains(asset_db):
    odn_id = _create_document(asset_db, domain="odn", document_id="doc-odn")
    civil_id = _create_document(
        asset_db,
        domain="civil_engineering",
        document_id="doc-civil",
    )

    assert odn_id == "doc-odn"
    assert civil_id == "doc-civil"
    assert odn_id != civil_id
    assert asset_db.get_document_by_key(domain="odn", document_key="doc:/same.md")["id"] == odn_id
    assert (
        asset_db.get_document_by_key(
            domain="civil_engineering",
            document_key="doc:/same.md",
        )["id"]
        == civil_id
    )
    assert asset_db.get_document(domain="odn", document_id=civil_id) is None


def test_same_hash_isolated_between_domains(asset_db):
    odn_id = _create_snapshot(asset_db, domain="odn", snapshot_id="snap-odn")
    civil_id = _create_snapshot(
        asset_db,
        domain="civil_engineering",
        snapshot_id="snap-civil",
    )

    assert odn_id == "snap-odn"
    assert civil_id == "snap-civil"
    assert odn_id != civil_id
    assert asset_db.get_snapshot_by_hash(domain="odn", normalized_content_hash="same-hash")["id"] == odn_id
    assert (
        asset_db.get_snapshot_by_hash(
            domain="civil_engineering",
            normalized_content_hash="same-hash",
        )["id"]
        == civil_id
    )
    assert asset_db.get_snapshot(domain="odn", snapshot_id=civil_id) is None


def test_same_domain_hash_reuses_immutable_snapshot(asset_db):
    first_id = _create_snapshot(asset_db, domain="odn", snapshot_id="snap-first")
    second_id = asset_db.upsert_snapshot(
        domain="odn",
        snapshot_id="snap-second",
        normalized_content_hash="same-hash",
        raw_content_hash="changed-raw-hash",
        mime_type="application/pdf",
        title="Changed",
        scope_json={"scope": "changed"},
        tags_json=["changed"],
        parser_profile_json={"parser": "changed"},
        metadata_json={"metadata": "changed"},
    )

    assert first_id == second_id == "snap-first"
    row = asset_db.get_snapshot(domain="odn", snapshot_id=first_id)
    assert row["raw_content_hash"] == "raw-hash"
    assert row["mime_type"] == "text/markdown"
    assert row["title"] == "Original"
    assert row["scope_json"] == {"scope": "original"}
    assert row["tags_json"] == ["original"]
    assert row["parser_profile_json"] == {"parser": "original"}
    assert row["metadata_json"] == {"metadata": "original"}


def test_source_batch_queries_are_domain_scoped(asset_db):
    _create_batch(asset_db, domain="odn", batch_id="batch-odn")

    assert asset_db.get_source_batch(domain="odn", batch_id="batch-odn") is not None
    assert asset_db.get_source_batch(domain="civil_engineering", batch_id="batch-odn") is None
    assert asset_db.find_batch_by_code(domain="odn", batch_code="CODE-batch-odn") is not None
    assert (
        asset_db.find_batch_by_code(
            domain="civil_engineering",
            batch_code="CODE-batch-odn",
        )
        is None
    )


def test_link_rejects_document_from_another_domain(asset_db):
    document_id = _create_document(asset_db, domain="civil_engineering", document_id="doc-civil")
    snapshot_id = _create_snapshot(asset_db, domain="odn", snapshot_id="snap-odn")

    with pytest.raises(ValueError, match="domain_mismatch"):
        asset_db.insert_snapshot_link(
            domain="odn",
            link_id="link-doc-mismatch",
            document_id=document_id,
            document_snapshot_id=snapshot_id,
            source_batch_id=None,
            relative_path="same.md",
            source_uri="file:///same.md",
        )


def test_link_rejects_snapshot_from_another_domain(asset_db):
    document_id = _create_document(asset_db, domain="odn", document_id="doc-odn")
    snapshot_id = _create_snapshot(
        asset_db,
        domain="civil_engineering",
        snapshot_id="snap-civil",
    )

    with pytest.raises(ValueError, match="domain_mismatch"):
        asset_db.insert_snapshot_link(
            domain="odn",
            link_id="link-snapshot-mismatch",
            document_id=document_id,
            document_snapshot_id=snapshot_id,
            source_batch_id=None,
            relative_path="same.md",
            source_uri="file:///same.md",
        )


def test_link_rejects_source_batch_from_another_domain(asset_db):
    document_id = _create_document(asset_db, domain="odn", document_id="doc-odn")
    snapshot_id = _create_snapshot(asset_db, domain="odn", snapshot_id="snap-odn")
    batch_id = _create_batch(asset_db, domain="civil_engineering", batch_id="batch-civil")

    with pytest.raises(ValueError, match="domain_mismatch"):
        asset_db.insert_snapshot_link(
            domain="odn",
            link_id="link-batch-mismatch",
            document_id=document_id,
            document_snapshot_id=snapshot_id,
            source_batch_id=batch_id,
            relative_path="same.md",
            source_uri="file:///same.md",
        )


def test_link_allows_missing_source_batch_and_scopes_link_queries(asset_db):
    document_id = _create_document(asset_db, domain="odn", document_id="doc-odn")
    snapshot_id = _create_snapshot(asset_db, domain="odn", snapshot_id="snap-odn")

    link_id = asset_db.insert_snapshot_link(
        domain="odn",
        link_id="link-no-batch",
        document_id=document_id,
        document_snapshot_id=snapshot_id,
        source_batch_id=None,
        relative_path="same.md",
        source_uri="file:///same.md",
    )

    assert link_id == "link-no-batch"
    assert asset_db.get_active_link(domain="odn", document_id=document_id)["id"] == link_id
    assert asset_db.get_active_link(domain="civil_engineering", document_id=document_id) is None
    assert asset_db.get_links_by_snapshot(domain="odn", snapshot_id=snapshot_id)[0]["id"] == link_id
    assert asset_db.get_links_by_snapshot(domain="civil_engineering", snapshot_id=snapshot_id) == []


def test_legacy_shared_assets_are_not_visible_to_business_domain(asset_db):
    _create_document(asset_db, domain="__legacy_shared__", document_id="doc-legacy")
    _create_snapshot(asset_db, domain="__legacy_shared__", snapshot_id="snap-legacy")

    assert asset_db.get_document_by_key(domain="odn", document_key="doc:/same.md") is None
    assert asset_db.get_snapshot_by_hash(domain="odn", normalized_content_hash="same-hash") is None
    assert asset_db.get_document(domain="odn", document_id="doc-legacy") is None
    assert asset_db.get_snapshot(domain="odn", snapshot_id="snap-legacy") is None


def test_snapshot_helper_uses_ids_returned_by_conflicting_upserts():
    asset_db = MagicMock()
    asset_db.get_document_by_key.return_value = None
    asset_db.get_snapshot_by_hash.return_value = None
    asset_db.upsert_document.return_value = "doc-winner"
    asset_db.upsert_snapshot.return_value = "snap-winner"
    raw_file = RawFileData(
        file_path="/tmp/same.md",
        relative_path="same.md",
        file_name="same.md",
        file_type="markdown",
        content="# Same",
        raw_content_hash="raw-hash",
        normalized_content_hash="same-hash",
        source_uri="file:///tmp/same.md",
    )
    profile = DocumentProfile(document_key="doc:/same.md")

    document_id, snapshot_id, _ = select_or_create_snapshot(
        asset_db,
        raw_file,
        profile,
        domain="odn",
        batch_id=None,
    )

    assert document_id == "doc-winner"
    assert snapshot_id == "snap-winner"
    link_kwargs = asset_db.insert_snapshot_link.call_args.kwargs
    assert link_kwargs["document_id"] == "doc-winner"
    assert link_kwargs["document_snapshot_id"] == "snap-winner"


def _pipeline_context(*, action: str = "NEW", existing_doc: dict | None = None) -> DocumentContext:
    raw_file = RawFileData(
        file_path="/tmp/same.md",
        relative_path="same.md",
        file_name="same.md",
        file_type="markdown",
        content="# Same",
        raw_content_hash="raw-hash",
        normalized_content_hash="same-hash",
        source_uri="file:///tmp/same.md",
    )
    profile = DocumentProfile(document_key="doc:/same.md")
    segment = RawSegmentData(
        document_key=profile.document_key,
        segment_index=0,
        raw_text="Same",
        normalized_text="Same",
    )
    return DocumentContext(
        raw_file=raw_file,
        profile=profile,
        tree=SectionNode(title=None, level=0),
        segments=(segment,),
        action=action,
        existing_doc=existing_doc,
    )


def test_db_write_stage_propagates_pipeline_domain():
    asset_db = MagicMock()
    asset_db.count_segments_by_snapshot.return_value = 1
    cfg = PipelineConfig(domain="odn", asset_db=asset_db, batch_id="batch-odn")
    ctx = _pipeline_context()

    with patch(
        "knowledge_mining.mining.pipeline.select_or_create_snapshot",
        return_value=("doc-odn", "snap-odn", "link-odn"),
    ) as select_snapshot:
        result = db_write_stage(ctx, cfg)

    assert result.error is None
    select_snapshot.assert_called_once_with(
        asset_db,
        ctx.raw_file,
        ctx.profile,
        domain="odn",
        batch_id="batch-odn",
    )


def test_update_does_not_delete_historical_snapshot_assets():
    asset_db = MagicMock()
    asset_db.count_segments_by_snapshot.return_value = 1
    asset_db._fetchall.return_value = [
        {"document_snapshot_id": "snap-new"},
        {"document_snapshot_id": "snap-old"},
    ]
    cfg = PipelineConfig(domain="odn", asset_db=asset_db)
    ctx = _pipeline_context(action="UPDATE", existing_doc={"id": "doc-odn"})

    with patch(
        "knowledge_mining.mining.pipeline.select_or_create_snapshot",
        return_value=("doc-odn", "snap-new", "link-new"),
    ):
        result = db_write_stage(ctx, cfg)

    assert result.error is None
    asset_db._fetchall.assert_not_called()
    asset_db.delete_segments_by_snapshot.assert_not_called()
    asset_db.delete_relations_by_snapshot.assert_not_called()
    asset_db.delete_retrieval_units_by_snapshot.assert_not_called()
