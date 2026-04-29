"""Tests for EvidenceRoleClassifier."""
import pytest

from agent_serving.serving.schemas.models import (
    EntityRef,
    EvidenceNeed,
    QueryUnderstanding,
    RetrievalCandidate,
)
from agent_serving.serving.evidence.role_classifier import EvidenceRoleClassifier


class TestEvidenceRoleClassifier:
    def setup_method(self):
        self.classifier = EvidenceRoleClassifier()

    def test_direct_answer_entity_match(self):
        understanding = QueryUnderstanding(
            original_query="ADD APN",
            entities=[EntityRef(type="command", name="ADD APN")],
        )
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1",
            score=0.95,
            source="entity_exact",
            metadata={"entity_refs_json": '[{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]'},
        )
        role = self.classifier.classify(candidate, understanding)
        assert role == "direct_answer"

    def test_support_relation(self):
        understanding = QueryUnderstanding(original_query="test")
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1",
            score=0.5,
            source="fts_bm25",
            metadata={"expansion_relation_type": "same_section"},
        )
        role = self.classifier.classify(candidate, understanding)
        assert role == "support"

    def test_contrast_intent(self):
        understanding = QueryUnderstanding(
            original_query="SMF和UPF的区别",
            intent="comparative",
        )
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1",
            score=0.8,
            source="fts_bm25",
            metadata={"text": "SMF和UPF在功能上有明显的区别"},
        )
        role = self.classifier.classify(candidate, understanding)
        assert role == "contrast"

    def test_background_graph_expansion(self):
        understanding = QueryUnderstanding(original_query="test")
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1",
            score=0.3,
            source="graph_expansion",
            metadata={},
        )
        role = self.classifier.classify(candidate, understanding)
        assert role == "background"

    def test_missing_default(self):
        understanding = QueryUnderstanding(
            original_query="test", intent="general",
        )
        candidate = RetrievalCandidate(
            retrieval_unit_id="ru-1",
            score=0.2,
            source="fts_bm25",
            metadata={},
        )
        role = self.classifier.classify(candidate, understanding)
        assert role == "missing"

    def test_classify_item_seed_high_score(self):
        from agent_serving.serving.schemas.models import ContextItem
        understanding = QueryUnderstanding(
            original_query="ADD APN", intent="command_usage",
        )
        item = ContextItem(
            id="ru-1", kind="retrieval_unit", role="seed",
            text="ADD APN命令", score=0.9,
        )
        role = self.classifier.classify_item(item, understanding)
        assert role == "direct_answer"

    def test_classify_item_support(self):
        from agent_serving.serving.schemas.models import ContextItem
        understanding = QueryUnderstanding(original_query="test")
        item = ContextItem(
            id="seg-1", kind="raw_segment", role="support",
            text="相关内容", score=0.0,
            relation_to_seed="same_section",
        )
        role = self.classifier.classify_item(item, understanding)
        assert role == "support"
