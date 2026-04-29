"""Tests for QueryUnderstanding Engine."""
import pytest

from agent_serving.serving.application.query_understanding import QueryUnderstandingEngine
from agent_serving.serving.schemas.models import QueryUnderstanding


class TestQueryUnderstandingModels:
    def test_query_understanding_defaults(self):
        qu = QueryUnderstanding(original_query="test")
        assert qu.intent == "general"
        assert qu.source == "rule"
        assert qu.entities == []
        assert qu.keywords == []

    def test_sub_query(self):
        from agent_serving.serving.schemas.models import SubQuery
        sq = SubQuery(text="ADD APN", intent="command_usage")
        assert sq.text == "ADD APN"

    def test_evidence_need(self):
        from agent_serving.serving.schemas.models import EvidenceNeed
        en = EvidenceNeed(needs_comparison=True, preferred_roles=["parameter"])
        assert en.needs_comparison is True
        assert en.preferred_roles == ["parameter"]


class TestRuleUnderstanding:
    @pytest.mark.asyncio
    async def test_command_intent(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("ADD APN命令怎么写")
        assert result.intent == "command_usage"
        assert result.source == "rule"

    @pytest.mark.asyncio
    async def test_concept_intent(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("什么是SMF")
        assert result.intent == "concept_lookup"

    @pytest.mark.asyncio
    async def test_troubleshooting_intent(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("SMF注册失败如何排查")
        assert result.intent == "troubleshooting"

    @pytest.mark.asyncio
    async def test_comparison_intent(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("SMF和UPF的区别")
        assert result.intent == "comparative"

    @pytest.mark.asyncio
    async def test_entity_extraction(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("ADD SMF")
        assert len(result.entities) > 0
        assert any(e.type == "command" for e in result.entities)

    @pytest.mark.asyncio
    async def test_scope_extraction(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("UDG上配置SMF")
        assert "network_elements" in result.scope
        assert "SMF" in result.scope["network_elements"]

    @pytest.mark.asyncio
    async def test_keywords_extraction(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("如何配置PFCP会话")
        assert len(result.keywords) > 0

    @pytest.mark.asyncio
    async def test_llm_fallback_when_no_client(self):
        engine = QueryUnderstandingEngine(llm_client=None)
        result = await engine.understand("测试查询")
        assert result.source == "rule"

    @pytest.mark.asyncio
    async def test_evidence_need_roles(self):
        engine = QueryUnderstandingEngine()
        result = await engine.understand("ADD APN参数说明")
        assert result.evidence_need.preferred_roles is not None
