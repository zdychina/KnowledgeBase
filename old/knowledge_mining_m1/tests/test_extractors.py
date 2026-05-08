"""Test extractor implementations: RuleBasedEntityExtractor, DefaultRoleClassifier, NoOp variants."""
from __future__ import annotations

import knowledge_mining.mining.extractors as _ext
from knowledge_mining.mining.extractors import (
    DefaultRoleClassifier,
    EntityExtractor,
    NoOpEntityExtractor,
    NoOpSegmentEnricher,
    RoleClassifier,
    SegmentEnricher,
)
from knowledge_mining.mining.models import CanonicalSegmentData, RawSegmentData


class TestRuleBasedEntityExtractor:
    def test_extracts_command_entities(self):
        ext = _ext.RuleBasedEntityExtractor()
        result = ext.extract("ADD APN:APNNAME=\"internet\"", {})
        names = [r["name"] for r in result]
        assert "ADD APN" in names

    def test_extracts_multiple_commands(self):
        ext = _ext.RuleBasedEntityExtractor()
        result = ext.extract("Use ADD APN then SHOW APN to verify", {})
        names = [r["name"] for r in result]
        assert "ADD APN" in names
        assert "SHOW APN" in names

    def test_extracts_network_elements(self):
        ext = _ext.RuleBasedEntityExtractor()
        result = ext.extract("Configure SMF and UPF for N4 interface", {})
        names = [r["name"] for r in result]
        assert "SMF" in names
        assert "UPF" in names

    def test_extracts_parameters_from_table(self):
        ext = _ext.RuleBasedEntityExtractor()
        ctx = {
            "structure": {
                "columns": ["参数标识", "参数名称", "参数说明"],
                "rows": [
                    {"参数标识": "APNNAME", "参数名称": "APN名称", "参数说明": "必选"},
                ],
            },
        }
        result = ext.extract("", ctx)
        names = [r["name"] for r in result]
        assert "APNNAME" in names

    def test_deduplicates_entities(self):
        ext = _ext.RuleBasedEntityExtractor()
        result = ext.extract("SMF connects to SMF and UPF", {})
        smf_refs = [r for r in result if r["name"] == "SMF"]
        assert len(smf_refs) == 1

    def test_empty_text_no_context(self):
        ext = _ext.RuleBasedEntityExtractor()
        result = ext.extract("", {})
        assert result == []

    def test_protocol_conformance(self):
        ext = _ext.RuleBasedEntityExtractor()
        assert isinstance(ext, EntityExtractor)


class TestDefaultRoleClassifier:
    def test_parameter_from_section_title(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("text", "参数说明", "paragraph", {})
        assert result == "parameter"

    def test_example_from_section_title(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("text", "使用实例", "paragraph", {})
        assert result == "example"

    def test_procedure_from_section_title(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("text", "操作步骤", "paragraph", {})
        assert result == "procedure_step"

    def test_troubleshooting_from_section_title(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("text", "排障指南", "paragraph", {})
        assert result == "troubleshooting_step"

    def test_constraint_from_section_title(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("text", "注意事项", "paragraph", {})
        assert result == "constraint"

    def test_table_with_parameter_columns(self):
        cls = DefaultRoleClassifier()
        ctx = {"structure": {"columns": ["参数标识", "参数名称"]}}
        result = cls.classify("text", "some title", "table", ctx)
        assert result == "parameter"

    def test_table_without_params(self):
        cls = DefaultRoleClassifier()
        ctx = {"structure": {"columns": ["Name", "Value"]}}
        result = cls.classify("text", "some title", "table", ctx)
        assert result == "note"

    def test_code_returns_example(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("code", "some title", "code", {})
        assert result == "example"

    def test_unknown_for_plain_paragraph(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("plain text", "generic title", "paragraph", {})
        assert result == "unknown"

    def test_protocol_conformance(self):
        cls = DefaultRoleClassifier()
        assert isinstance(cls, RoleClassifier)


class TestNoOpEntityExtractor:
    def test_returns_empty_list(self):
        ext = NoOpEntityExtractor()
        result = ext.extract("ADD APN command", {})
        assert result == []

    def test_protocol_conformance(self):
        ext = NoOpEntityExtractor()
        assert isinstance(ext, EntityExtractor)


class TestNoOpSegmentEnricher:
    def test_returns_canonical_unchanged(self):
        enricher = NoOpSegmentEnricher()
        canon = CanonicalSegmentData(
            canonical_key="c000000",
            canonical_text="hello",
        )
        result = enricher.enrich(canon, [])
        assert result is canon

    def test_protocol_conformance(self):
        enricher = NoOpSegmentEnricher()
        assert isinstance(enricher, SegmentEnricher)
