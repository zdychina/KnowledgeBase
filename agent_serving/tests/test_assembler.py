"""Tests for v1.1 ContextAssembler — seed items, source drill-down, graph expansion."""
import json

import pytest
import pytest_asyncio

from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.retrieval.graph_expander import GraphExpander
from agent_serving.serving.schemas.models import (
    ActiveScope,
    NormalizedQuery,
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalRoutePlan,
)
from agent_serving.tests.conftest import SEED_IDS


@pytest_asyncio.fixture
async def repo(pg_pool):
    return AssetRepository(pg_pool)


@pytest_asyncio.fixture
async def graph(pg_pool):
    return GraphExpander(pg_pool)


@pytest_asyncio.fixture
async def assembler(repo, graph):
    return ContextAssembler(repo, graph)


@pytest_asyncio.fixture
async def scope(repo):
    return await repo.resolve_active_scope()


def _make_candidate(ru_id, text, source_refs_json="{}", **metadata_overrides):
    metadata = {
        "document_snapshot_id": SEED_IDS["snap_udg"],
        "title": "Test RU",
        "block_type": "paragraph",
        "semantic_role": "parameter",
        "text": text,
        "source_refs_json": source_refs_json,
        "facets_json": "{}",
        "target_type": "",
        "target_ref_json": "{}",
    }
    metadata.update(metadata_overrides)
    return RetrievalCandidate(
        retrieval_unit_id=ru_id,
        score=1.0,
        source="fts_bm25",
        metadata=metadata,
    )


def _make_plan(**overrides):
    defaults = {
        "intent": "command_usage",
        "keywords": ["ADD", "APN"],
        "desired_roles": ["parameter"],
    }
    defaults.update(overrides)
    return QueryPlan(**defaults)


def _make_normalized(**overrides):
    defaults = {
        "original_query": "ADD APN",
        "intent": "command_usage",
        "keywords": ["ADD", "APN"],
    }
    defaults.update(overrides)
    return NormalizedQuery(**defaults)


@pytest.mark.pg
class TestBasicAssembly:
    @pytest.mark.asyncio
    async def test_assemble_with_seed_items(self, assembler, scope, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN 命令用于在UDG上新增APN配置",
            source_refs_json=source_refs,
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        assert len(pack.items) >= 1
        assert pack.query.original == "ADD APN"
        assert pack.query.intent == "command_usage"

    @pytest.mark.asyncio
    async def test_assemble_empty_candidates(self, assembler, scope):
        pack = await assembler.assemble(
            query="不存在的内容",
            normalized=_make_normalized(original_query="不存在的内容", keywords=["不存在"]),
            plan=_make_plan(keywords=["不存在"]),
            scope=scope,
            candidates=[],
        )

        assert pack.items == []
        assert any(i.type == "no_result" for i in pack.issues)

    @pytest.mark.asyncio
    async def test_assemble_has_sources(self, assembler, scope, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json=source_refs,
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        # Should have source documents
        assert len(pack.sources) >= 1
        source_keys = [s.document_key for s in pack.sources]
        assert any("UDG" in k for k in source_keys)


@pytest.mark.pg
class TestSourceDrillDown:
    @pytest.mark.asyncio
    async def test_source_refs_parsed(self, assembler, scope, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json=source_refs,
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        # Should have raw_segment items (context role)
        context_items = [i for i in pack.items if i.kind == "raw_segment"]
        assert len(context_items) >= 1

    @pytest.mark.asyncio
    async def test_target_ref_fallback(self, assembler, scope, seed_ids):
        """When source_refs_json is empty, fall back to target_ref_json."""
        target_ref = json.dumps({"raw_segment_id": seed_ids["rs_add_apn_udg"]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json="{}",  # No source_refs
            target_type="raw_segment",
            target_ref_json=target_ref,
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        # Should still resolve the segment via target_ref_json fallback
        context_items = [i for i in pack.items if i.kind == "raw_segment"]
        assert len(context_items) >= 1

    @pytest.mark.asyncio
    async def test_no_refs_returns_seed_only(self, assembler, scope, seed_ids):
        """When neither source_refs nor target_ref exists, only seed items."""
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json="{}",
            target_type="",
            target_ref_json="{}",
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        # Only seed item, no context items
        seed_items = [i for i in pack.items if i.role == "seed"]
        context_items = [i for i in pack.items if i.role == "context"]
        assert len(seed_items) == 1
        assert len(context_items) == 0


@pytest.mark.pg
class TestGraphExpansion:
    @pytest.mark.asyncio
    async def test_relations_in_output(self, assembler, scope, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json=source_refs,
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        # Should have relations from seed data
        assert len(pack.relations) >= 1
        rel_types = [r.relation_type for r in pack.relations]
        assert "next" in rel_types or "previous" in rel_types

    @pytest.mark.asyncio
    async def test_expansion_disabled(self, assembler, scope, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json=source_refs,
        )
        plan = _make_plan()
        plan = plan.model_copy(update={
            "expansion": plan.expansion.model_copy(update={"enable_relation_expansion": False}),
        })

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=plan,
            scope=scope,
            candidates=[candidate],
        )

        # No expanded items (support role)
        expanded = [i for i in pack.items if i.role == "support"]
        assert len(expanded) == 0


@pytest.mark.pg
class TestEvidenceGroups:
    @pytest.mark.asyncio
    async def test_evidence_groups_built_by_snapshot_id(self, assembler, scope, seed_ids):
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json=source_refs,
        )

        pack = await assembler.assemble(
            query="ADD APN",
            normalized=_make_normalized(),
            plan=_make_plan(),
            scope=scope,
            candidates=[candidate],
        )

        # Should have evidence groups keyed by document_snapshot_id
        assert len(pack.evidence_groups) >= 1
        for g in pack.evidence_groups:
            assert g.document_snapshot_id
            assert len(g.item_ids) > 0
            # relation_ids should only contain relations connected to this group's items
            item_id_set = set(g.item_ids)
            for rid in g.relation_ids:
                rel = next((r for r in pack.relations if r.id == rid), None)
                if rel:
                    assert rel.from_id in item_id_set or rel.to_id in item_id_set


@pytest.mark.pg
class TestAssemblerV2Path:
    @pytest.mark.asyncio
    async def test_assemble_with_understanding_and_route_plan(self, assembler, scope, seed_ids):
        """V2 call signature: understanding + route_plan instead of normalized + plan."""
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidate = _make_candidate(
            seed_ids["ru_add_apn"],
            "ADD APN",
            source_refs_json=source_refs,
        )
        understanding = QueryUnderstanding(
            original_query="ADD APN",
            intent="command_usage",
            keywords=["ADD", "APN"],
        )
        route_plan = RetrievalRoutePlan()

        pack = await assembler.assemble(
            query="ADD APN",
            understanding=understanding,
            route_plan=route_plan,
            scope=scope,
            candidates=[candidate],
        )

        assert len(pack.items) >= 1
        assert pack.query.original == "ADD APN"
        assert pack.query.intent == "command_usage"
        assert "intent=command_usage" in pack.query.normalized

    @pytest.mark.asyncio
    async def test_max_items_truncation(self, assembler, scope, seed_ids):
        """max_items should truncate the final item list."""
        source_refs = json.dumps({"raw_segment_ids": [seed_ids["rs_add_apn_udg"]]})
        candidates = [
            _make_candidate(
                f"ru-{i}", f"candidate {i}",
                source_refs_json=source_refs,
            )
            for i in range(5)
        ]
        route_plan = RetrievalRoutePlan()
        route_plan = route_plan.model_copy(update={
            "assembly": route_plan.assembly.model_copy(update={
                "max_items": 2,
                "max_expanded": 0,
            }),
        })

        pack = await assembler.assemble(
            query="test",
            route_plan=route_plan,
            scope=scope,
            candidates=candidates,
        )
        assert len(pack.items) <= 2
