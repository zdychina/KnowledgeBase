"""Domain Pack v1.4 tests.

Tests cover:
- Domain pack loading (generic + cloud_core_network)
- Entity schema from profile
- Rule-based extraction with profile
- Retrieval policy from profile
- Toy domain pack works without core code changes
- Eval questions contract
- Backward compatibility
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PACKS_ROOT = Path(__file__).resolve().parent.parent / "domain_packs"


@pytest.fixture
def cloud_profile():
    from knowledge_mining.mining.domain_pack import load_domain_pack
    return load_domain_pack("cloud_core_network", packs_root=PACKS_ROOT)


@pytest.fixture
def generic_profile():
    from knowledge_mining.mining.domain_pack import load_domain_pack
    return load_domain_pack("generic", packs_root=PACKS_ROOT)


# ---------------------------------------------------------------------------
# Test: Domain Pack Loader
# ---------------------------------------------------------------------------

class TestDomainPackLoader:
    def test_load_cloud_core_network(self, cloud_profile):
        assert cloud_profile.domain_id == "cloud_core_network"
        assert "command" in cloud_profile.entity_types
        assert "SMF" in cloud_profile.display_name or "Cloud" in cloud_profile.display_name

    def test_load_generic(self, generic_profile):
        assert generic_profile.domain_id == "generic"
        assert generic_profile.entity_types == frozenset({"concept"})
        assert generic_profile.strong_entity_types == frozenset()

    def test_load_nonexistent_raises(self):
        from knowledge_mining.mining.domain_pack import load_domain_pack
        with pytest.raises(FileNotFoundError):
            load_domain_pack("nonexistent_domain", packs_root=PACKS_ROOT)

    def test_profile_is_frozen(self, cloud_profile):
        with pytest.raises(AttributeError):
            cloud_profile.domain_id = "changed"

    def test_extractor_rules_compiled(self, cloud_profile):
        for rule in cloud_profile.extractor_rules:
            assert rule.compiled is not None
            assert rule.compiled.pattern == rule.pattern


# ---------------------------------------------------------------------------
# Test: Entity Schema from Profile
# ---------------------------------------------------------------------------

class TestDomainEntitySchema:
    def test_cloud_schema_has_entity_types(self, cloud_profile):
        from knowledge_mining.mining.llm_templates import build_templates_from_profile
        templates = build_templates_from_profile(cloud_profile)
        seg_tpl = next(t for t in templates if t["template_key"] == "mining-segment-understanding")
        schema = json.loads(seg_tpl["output_schema_json"])
        entity_type_enum = schema["properties"]["entities"]["items"]["properties"]["type"]["enum"]
        assert "command" in entity_type_enum
        assert "network_element" in entity_type_enum

    def test_generic_schema_has_concept_only(self, generic_profile):
        from knowledge_mining.mining.llm_templates import build_templates_from_profile
        templates = build_templates_from_profile(generic_profile)
        seg_tpl = next(t for t in templates if t["template_key"] == "mining-segment-understanding")
        schema = json.loads(seg_tpl["output_schema_json"])
        entity_type_enum = schema["properties"]["entities"]["items"]["properties"]["type"]["enum"]
        assert entity_type_enum == ["concept"]

    def test_backward_compat_templates(self):
        """TEMPLATES import still works (loads cloud_core_network by default)."""
        from knowledge_mining.mining.llm_templates import TEMPLATES
        assert len(TEMPLATES) >= 4
        keys = [t["template_key"] for t in TEMPLATES]
        assert "mining-question-gen" in keys
        assert "mining-segment-understanding" in keys


# ---------------------------------------------------------------------------
# Test: Domain Rule Extractor
# ---------------------------------------------------------------------------

class TestDomainRuleExtractor:
    def test_cloud_extracts_commands(self, cloud_profile):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor(profile=cloud_profile)
        refs = ext.extract("ADD SMF instance-name", {})
        assert any(r["type"] == "command" and "ADD" in r["name"] for r in refs)

    def test_cloud_extracts_network_elements(self, cloud_profile):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor(profile=cloud_profile)
        refs = ext.extract("Configure SMF and UPF for 5GC", {})
        types = {r["type"] for r in refs}
        names = {r["name"] for r in refs}
        assert "network_element" in types
        assert "SMF" in names
        assert "UPF" in names

    def test_cloud_extracts_interfaces(self, cloud_profile):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor(profile=cloud_profile)
        refs = ext.extract("N4 interface between SMF and UPF", {})
        iface_refs = [r for r in refs if r["type"] == "interface"]
        assert len(iface_refs) >= 1
        assert "N4" in iface_refs[0]["name"]

    def test_cloud_extracts_alarms(self, cloud_profile):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor(profile=cloud_profile)
        refs = ext.extract("ALM-SMF-001 occurred", {})
        assert any(r["type"] == "alarm" for r in refs)

    def test_generic_no_regex_extractions(self, generic_profile):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor(profile=generic_profile)
        refs = ext.extract("ADD SMF instance-name", {})
        # Generic has no extractor rules, so no regex extractions
        assert len(refs) == 0

    def test_section_title_extraction(self, cloud_profile):
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor(profile=cloud_profile)
        result = ext.extract_from_section_title("ADD SMF")
        assert result is not None
        assert result["type"] == "command"
        assert "ADD" in result["name"]


# ---------------------------------------------------------------------------
# Test: Domain Retrieval Policy
# ---------------------------------------------------------------------------

class TestDomainRetrievalPolicy:
    def test_cloud_entity_card_only_strong(self, cloud_profile):
        from knowledge_mining.mining.retrieval_units import build_retrieval_units
        from knowledge_mining.mining.models import RawSegmentData

        seg = RawSegmentData(
            document_key="doc:test",
            segment_index=0,
            raw_text="Configure SMF and UPF",
            entity_refs_json=[
                {"type": "network_element", "name": "SMF"},
                {"type": "concept", "name": "5GC architecture"},
            ],
        )
        units = build_retrieval_units([seg], profile=cloud_profile)
        entity_cards = [u for u in units if u.unit_type == "entity_card"]
        assert len(entity_cards) == 1  # SMF gets card, concept does not
        assert entity_cards[0].title == "SMF"

    def test_generic_no_entity_cards(self, generic_profile):
        from knowledge_mining.mining.retrieval_units import build_retrieval_units
        from knowledge_mining.mining.models import RawSegmentData

        seg = RawSegmentData(
            document_key="doc:test",
            segment_index=0,
            raw_text="This describes a concept",
            entity_refs_json=[{"type": "concept", "name": "test"}],
        )
        units = build_retrieval_units([seg], profile=generic_profile)
        entity_cards = [u for u in units if u.unit_type == "entity_card"]
        assert len(entity_cards) == 0  # generic has no strong types

    def test_max_questions_from_policy(self, cloud_profile):
        assert cloud_profile.retrieval_policy.max_questions_per_segment == 2


# ---------------------------------------------------------------------------
# Test: Toy Domain Pack (no core code changes)
# ---------------------------------------------------------------------------

class TestToyDomainPack:
    def test_toy_domain_works(self):
        """Create a toy domain pack and verify extraction works without core code changes."""
        from knowledge_mining.mining.domain_pack import load_domain_pack
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor

        # Write toy domain pack to temp dir
        with tempfile.TemporaryDirectory() as tmpdir:
            toy_dir = Path(tmpdir) / "toy"
            toy_dir.mkdir()
            toy_yaml = toy_dir / "domain.yaml"
            toy_yaml.write_text(
                "domain_id: toy\n"
                'display_name: "Toy Domain"\n'
                "entity_types:\n  - person\n"
                "strong_entity_types:\n  - person\n"
                "role_keyword_rules: []\n"
                "heading_role_keywords: []\n"
                "extractor_rules:\n"
                "  - name: person_name\n"
                r'    pattern: "\\b([A-Z][a-z]+ [A-Z][a-z]+)\\b"' + "\n"
                "    entity_type: person\n"
                "retrieval_policy:\n  max_questions_per_segment: 1\n"
                "llm_templates: []\n"
                "eval_questions: []\n",
                encoding="utf-8",
            )

            profile = load_domain_pack("toy", packs_root=Path(tmpdir))
            assert profile.domain_id == "toy"
            assert profile.strong_entity_types == frozenset({"person"})

            ext = RuleBasedEntityExtractor(profile=profile)
            refs = ext.extract("John Smith met Jane Doe today", {})
            assert len(refs) == 2
            assert all(r["type"] == "person" for r in refs)
            names = {r["name"] for r in refs}
            assert "John Smith" in names
            assert "Jane Doe" in names


# ---------------------------------------------------------------------------
# Test: Eval Questions Contract
# ---------------------------------------------------------------------------

class TestEvalQuestionsContract:
    def test_cloud_has_eval_questions(self, cloud_profile):
        assert len(cloud_profile.eval_questions) == 30

    def test_eval_question_structure(self, cloud_profile):
        for q in cloud_profile.eval_questions:
            assert q.id
            assert q.question
            assert isinstance(q.expected_entities, tuple)

    def test_generic_has_empty_eval(self, generic_profile):
        assert len(generic_profile.eval_questions) == 0

    def test_eval_coverage_distribution(self, cloud_profile):
        """Verify the 30 questions cover expected categories."""
        categories = {
            "command": 0, "concept": 0, "parameter": 0,
            "troubleshooting": 0, "cross": 0,
        }
        for q in cloud_profile.eval_questions:
            qid = q.id
            if qid <= "q008":
                categories["command"] += 1
            elif qid <= "q015":
                categories["concept"] += 1
            elif qid <= "q022":
                categories["parameter"] += 1
            elif qid <= "q027":
                categories["troubleshooting"] += 1
            else:
                categories["cross"] += 1

        assert categories["command"] == 8
        assert categories["concept"] == 7
        assert categories["parameter"] == 7
        assert categories["troubleshooting"] == 5
        assert categories["cross"] == 3


# ---------------------------------------------------------------------------
# Test: Role Classifier Profile-driven
# ---------------------------------------------------------------------------

class TestRoleClassifier:
    def test_cloud_role_classification(self, cloud_profile):
        from knowledge_mining.mining.extractors import DefaultRoleClassifier
        clf = DefaultRoleClassifier(profile=cloud_profile)
        assert clf.classify("text", "参数说明", "paragraph", {}) == "parameter"
        assert clf.classify("text", "使用实例", "paragraph", {}) == "example"
        assert clf.classify("text", "操作步骤", "paragraph", {}) == "procedure_step"
        assert clf.classify("text", "some random title", "paragraph", {}) == "unknown"

    def test_generic_role_classification(self, generic_profile):
        from knowledge_mining.mining.extractors import DefaultRoleClassifier
        clf = DefaultRoleClassifier(profile=generic_profile)
        assert clf.classify("text", "parameter settings", "paragraph", {}) == "parameter"
        assert clf.classify("text", "some title", "paragraph", {}) == "unknown"


# ---------------------------------------------------------------------------
# Test: Enricher Profile-driven
# ---------------------------------------------------------------------------

class TestEnricherProfile:
    def test_enricher_uses_profile(self, cloud_profile):
        from knowledge_mining.mining.enrich import RuleBasedEnricher
        from knowledge_mining.mining.models import RawSegmentData

        enricher = RuleBasedEnricher(profile=cloud_profile)
        seg = RawSegmentData(
            document_key="doc:test",
            segment_index=0,
            block_type="paragraph",
            raw_text="ADD SMF instance-name",
        )
        result = enricher.enrich([seg])
        assert len(result) == 1
        assert any(r["type"] == "command" for r in result[0].entity_refs_json)

    def test_enricher_heading_role(self, cloud_profile):
        from knowledge_mining.mining.enrich import RuleBasedEnricher
        from knowledge_mining.mining.models import RawSegmentData

        enricher = RuleBasedEnricher(profile=cloud_profile)
        seg = RawSegmentData(
            document_key="doc:test",
            segment_index=0,
            block_type="heading",
            section_title="参数说明",
            raw_text="参数说明",
        )
        result = enricher.enrich([seg])
        assert result[0].metadata_json.get("heading_role") == "parameter_definition"


# ---------------------------------------------------------------------------
# Test: Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_models_strong_entity_types_empty(self):
        """STRONG_ENTITY_TYPES is now empty (deprecated)."""
        from knowledge_mining.mining.models import STRONG_ENTITY_TYPES
        assert STRONG_ENTITY_TYPES == frozenset()

    def test_default_profile_loads(self):
        from knowledge_mining.mining.domain_pack import get_default_profile
        profile = get_default_profile()
        assert profile.domain_id == "cloud_core_network"
        assert "command" in profile.strong_entity_types

    def test_extractors_without_profile(self):
        """RuleBasedEntityExtractor works without explicit profile (loads default)."""
        from knowledge_mining.mining.extractors import RuleBasedEntityExtractor
        ext = RuleBasedEntityExtractor()
        refs = ext.extract("ADD SMF instance-name", {})
        assert any(r["type"] == "command" for r in refs)
