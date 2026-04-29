"""Eval integration test — runs eval questions against seeded DB."""
import json

import pytest
import pytest_asyncio
import aiosqlite

from agent_serving.serving.eval.runner import EvalRunner
from agent_serving.serving.schemas.models import ContextPack, ContextQuery
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite
from agent_serving.tests.conftest import _seed_v11_data


class TestEvalFramework:
    """Test the EvalRunner with mock search function."""

    @pytest.mark.asyncio
    async def test_eval_with_mock_results(self):
        """EvalRunner correctly computes metrics."""
        async def mock_search(query: str) -> dict:
            # Simulate a ContextPack response
            return {
                "items": [
                    {"text": "SMF是5GC中的会话管理功能", "score": 0.9,
                     "route_sources": ["fts_bm25"]},
                    {"text": "UPF是用户面功能", "score": 0.7,
                     "route_sources": ["entity_exact"]},
                ],
            }

        runner = EvalRunner(k=10)
        questions = [
            {
                "id": "q001",
                "question": "什么是SMF",
                "expected_entities": ["SMF"],
                "expected_evidence_contains": ["SMF", "5GC"],
            },
            {
                "id": "q002",
                "question": "什么是UPF",
                "expected_entities": ["UPF"],
                "expected_evidence_contains": ["UPF"],
            },
        ]
        report = await runner.run(questions, mock_search)
        assert report.total_questions == 2
        assert report.hit_rate == 1.0  # Both questions hit
        assert report.mrr_at_k > 0
        assert report.ndcg_at_k > 0

    @pytest.mark.asyncio
    async def test_eval_empty_results(self):
        """EvalRunner handles empty results."""
        async def mock_search(query: str) -> dict:
            return {"items": []}

        runner = EvalRunner(k=10)
        questions = [
            {
                "id": "q001",
                "question": "test",
                "expected_evidence_contains": ["nonexistent"],
            },
        ]
        report = await runner.run(questions, mock_search)
        assert report.hit_rate == 0.0

    @pytest.mark.asyncio
    async def test_eval_route_contribution(self):
        """EvalRunner tracks route contribution."""
        async def mock_search(query: str) -> dict:
            return {
                "items": [
                    {"text": "SMF test", "score": 0.9,
                     "route_sources": ["fts_bm25", "entity_exact"]},
                ],
            }

        runner = EvalRunner(k=10)
        questions = [
            {
                "id": "q001",
                "question": "SMF",
                "expected_evidence_contains": ["SMF"],
            },
        ]
        report = await runner.run(questions, mock_search)
        assert "fts_bm25" in report.route_contribution
        assert "entity_exact" in report.route_contribution

    @pytest.mark.asyncio
    async def test_ndcg_computation(self):
        """NDCG is correctly computed."""
        runner = EvalRunner(k=10)
        # Perfect ranking: relevant at position 0
        ndcg = runner._compute_ndcg([0], 10)
        assert abs(ndcg - 1.0) < 0.001

        # Relevant at position 1
        ndcg = runner._compute_ndcg([1], 10)
        assert 0 < ndcg < 1.0

        # No relevant items
        ndcg = runner._compute_ndcg([], 10)
        assert ndcg == 0.0
