"""Tests for AssetRepository — active scope, source drill-down, relations."""
import json

import pytest
import pytest_asyncio

from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.tests.conftest import SEED_IDS


@pytest_asyncio.fixture
async def repo(pg_pool):
    return AssetRepository(pg_pool)


@pytest.mark.pg
class TestResolveActiveScope:
    @pytest.mark.asyncio
    async def test_active_scope_found(self, repo, seed_ids):
        scope = await repo.resolve_active_scope()
        assert scope.release_id == seed_ids["release_id"]
        assert scope.build_id == seed_ids["build_id"]
        assert len(scope.snapshot_ids) == 3
        assert len(scope.document_snapshot_map) > 0

    @pytest.mark.asyncio
    async def test_no_active_release(self, pg_pool):
        async with pg_pool.connection() as conn:
            await conn.execute(
                "UPDATE asset_publish_releases SET status = 'retired' WHERE id = %s",
                (SEED_IDS["release_id"],),
            )
        repo = AssetRepository(pg_pool)

        with pytest.raises(ValueError, match="no_active_release"):
            await repo.resolve_active_scope()

        # Restore for other tests
        async with pg_pool.connection() as conn:
            await conn.execute(
                "UPDATE asset_publish_releases SET status = 'active' WHERE id = %s",
                (SEED_IDS["release_id"],),
            )

    @pytest.mark.asyncio
    async def test_multiple_active_releases(self, pg_pool):
        async with pg_pool.connection() as conn:
            with pytest.raises(Exception):
                await conn.execute(
                    "INSERT INTO asset_publish_releases "
                    "(id, release_code, build_id, channel, status, metadata_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    ("dup-release", "DUP-001", SEED_IDS["build_id"], "default", "active", "{}"),
                )


@pytest.mark.pg
class TestResolveSourceSegments:
    @pytest.mark.asyncio
    async def test_valid_source_refs(self, repo, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        segments = await repo.resolve_source_segments(source_refs)
        assert len(segments) == 1
        assert segments[0]["id"] == seed_ids["rs_add_apn_udg"]
        assert segments[0]["raw_text"] is not None

    @pytest.mark.asyncio
    async def test_empty_source_refs(self, repo):
        segments = await repo.resolve_source_segments(None)
        assert segments == []

    @pytest.mark.asyncio
    async def test_malformed_json(self, repo):
        segments = await repo.resolve_source_segments("not json")
        assert segments == []

    @pytest.mark.asyncio
    async def test_multiple_segments(self, repo, seed_ids):
        source_refs = json.dumps({
            "raw_segment_ids": [seed_ids["rs_add_apn_udg"], seed_ids["rs_5g_concept"]],
        })
        segments = await repo.resolve_source_segments(source_refs)
        assert len(segments) == 2


@pytest.mark.pg
class TestGetRelations:
    @pytest.mark.asyncio
    async def test_relations_for_segments(self, repo, seed_ids):
        relations = await repo.get_relations_for_segments(
            [seed_ids["rs_add_apn_udg"]],
        )
        assert len(relations) >= 1
        assert any(r["relation_type"] == "next" for r in relations)

    @pytest.mark.asyncio
    async def test_empty_segment_list(self, repo):
        relations = await repo.get_relations_for_segments([])
        assert relations == []

    @pytest.mark.asyncio
    async def test_relation_type_filter(self, repo, seed_ids):
        relations = await repo.get_relations_for_segments(
            [seed_ids["rs_add_apn_udg"]],
            relation_types=["next"],
        )
        assert all(r["relation_type"] == "next" for r in relations)


@pytest.mark.pg
class TestGetDocumentSources:
    @pytest.mark.asyncio
    async def test_fetch_documents(self, repo, seed_ids):
        sources = await repo.get_document_sources([seed_ids["doc_udg"]])
        assert len(sources) >= 1
        assert any(s["document_key"] == "UDG_OM_REF" for s in sources)

    @pytest.mark.asyncio
    async def test_empty_ids(self, repo):
        sources = await repo.get_document_sources([])
        assert sources == []

    @pytest.mark.asyncio
    async def test_documents_filtered_by_snapshot(self, repo, seed_ids):
        """Documents from non-active snapshots should be excluded."""
        sources = await repo.get_document_sources(
            [seed_ids["doc_udg"], seed_ids["doc_unc"]],
            snapshot_ids=[seed_ids["snap_udg"]],
        )
        assert all(s["document_key"] != "UNC_OM_REF" for s in sources)


@pytest.mark.pg
class TestBuildViewConsistency:
    """Tests for selection_status and build scope isolation."""

    @pytest.mark.asyncio
    async def test_removed_selection_excluded_from_scope(self, pg_pool):
        """Set one build_document_snapshot to 'removed' and verify it's excluded."""
        from agent_serving.tests.conftest import SNAP_UNC, BUILD_ID
        async with pg_pool.connection() as conn:
            await conn.execute(
                "UPDATE asset_build_document_snapshots SET selection_status = 'removed' "
                "WHERE document_snapshot_id = %s AND build_id = %s",
                (SNAP_UNC, BUILD_ID),
            )
        repo = AssetRepository(pg_pool)
        scope = await repo.resolve_active_scope()

        # UNC snapshot should be excluded
        assert SNAP_UNC not in scope.snapshot_ids
        assert SNAP_UNC not in scope.document_snapshot_map.values()
        # Still has the other 2
        assert len(scope.snapshot_ids) == 2

        # Restore
        async with pg_pool.connection() as conn:
            await conn.execute(
                "UPDATE asset_build_document_snapshots SET selection_status = 'active' "
                "WHERE document_snapshot_id = %s AND build_id = %s",
                (SNAP_UNC, BUILD_ID),
            )

    @pytest.mark.asyncio
    async def test_source_segments_filtered_by_snapshot(self, repo, seed_ids):
        """resolve_source_segments should only return segments in active snapshots."""
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        segments = await repo.resolve_source_segments(
            source_refs,
            snapshot_ids=[seed_ids["snap_udg"]],
        )
        assert len(segments) == 1

        segments = await repo.resolve_source_segments(
            source_refs,
            snapshot_ids=[seed_ids["snap_unc"]],
        )
        assert len(segments) == 0
