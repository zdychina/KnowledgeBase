"""Tests for RetrievalRouter."""
import pytest

from agent_serving.serving.application.retrieval_router import RetrievalRouter
from agent_serving.serving.schemas.models import (
    QueryUnderstanding,
    RetrievalRoutePlan,
)


class TestRetrievalRouter:
    def test_default_route_plan(self):
        router = RetrievalRouter()
        understanding = QueryUnderstanding(
            original_query="test", intent="general",
        )
        plan = router.route(understanding)
        assert isinstance(plan, RetrievalRoutePlan)
        assert len(plan.routes) > 0

    def test_command_usage_routes(self):
        router = RetrievalRouter()
        understanding = QueryUnderstanding(
            original_query="ADD APN", intent="command_usage",
        )
        plan = router.route(understanding)
        # entity_exact should have highest weight
        entity_route = next(r for r in plan.routes if r.name == "entity_exact")
        assert entity_route.weight > 1.0

    def test_concept_lookup_routes(self):
        router = RetrievalRouter()
        understanding = QueryUnderstanding(
            original_query="什么是SMF", intent="concept_lookup",
        )
        plan = router.route(understanding)
        # dense_vector should have highest weight
        dense_route = next(r for r in plan.routes if r.name == "dense_vector")
        assert dense_route.weight > 1.0

    def test_troubleshooting_routes(self):
        router = RetrievalRouter()
        understanding = QueryUnderstanding(
            original_query="SMF故障排查", intent="troubleshooting",
        )
        plan = router.route(understanding)
        assert len(plan.routes) >= 2

    def test_fusion_method_multi_route(self):
        router = RetrievalRouter()
        understanding = QueryUnderstanding(
            original_query="test", intent="general",
        )
        plan = router.route(understanding)
        # Multiple routes should use weighted_rrf
        assert plan.fusion.method == "weighted_rrf"

    def test_comparison_rerank_cascade(self):
        router = RetrievalRouter()
        understanding = QueryUnderstanding(
            original_query="SMF vs UPF", intent="comparative",
            evidence_need={"needs_comparison": True},
        )
        plan = router.route(understanding)
        assert plan.rerank.method == "cascade"

    def test_domain_profile_override(self):
        from agent_serving.serving.domain_pack_reader import ServingDomainProfile
        router = RetrievalRouter()
        profile = ServingDomainProfile(
            domain_id="test",
            route_policy={
                "default": {"lexical_bm25": {"weight": 2.0, "top_k": 100}},
            },
        )
        understanding = QueryUnderstanding(original_query="test")
        plan = router.route(understanding, domain_profile=profile)
        bm25_route = next(r for r in plan.routes if r.name == "lexical_bm25")
        assert bm25_route.weight == 2.0
