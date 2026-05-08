"""Test document profile: batch params inheritance for v0.5."""
from __future__ import annotations

from knowledge_mining.mining.document_profile import build_profile
from knowledge_mining.mining.models import BatchParams, RawDocumentData


class TestBuildProfile:
    def test_inherits_source_type(self):
        doc = RawDocumentData(
            file_path="/data/a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
            source_type="folder_scan",
        )
        profile = build_profile(doc)
        assert profile.source_type == "folder_scan"

    def test_inherits_document_type(self):
        doc = RawDocumentData(
            file_path="/data/a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
            document_type="command",
        )
        profile = build_profile(doc)
        assert profile.document_type == "command"

    def test_inherits_scope_json(self):
        doc = RawDocumentData(
            file_path="/data/a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
            scope_json={"product": "5G", "version": "V1"},
        )
        profile = build_profile(doc)
        assert profile.scope_json == {"product": "5G", "version": "V1"}

    def test_inherits_tags_json(self):
        doc = RawDocumentData(
            file_path="/data/a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
            tags_json=["m1", "test"],
        )
        profile = build_profile(doc)
        assert profile.tags_json == ["m1", "test"]

    def test_inherits_structure_quality(self):
        doc = RawDocumentData(
            file_path="/data/a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
            structure_quality="markdown_native",
        )
        profile = build_profile(doc)
        assert profile.structure_quality == "markdown_native"

    def test_inherits_title(self):
        doc = RawDocumentData(
            file_path="/data/a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
            title="My Title",
        )
        profile = build_profile(doc)
        assert profile.title == "My Title"

    def test_document_key_is_relative_path(self):
        doc = RawDocumentData(
            file_path="/data/sub/a.md",
            relative_path="sub/a.md",
            file_name="a.md",
            file_type="markdown",
            content="# Hello",
            content_hash="h",
        )
        profile = build_profile(doc)
        assert profile.document_key == "sub/a.md"

    def test_defaults_when_no_source_type(self):
        doc = RawDocumentData(
            file_path="bare.md",
            relative_path="bare.md",
            file_name="bare.md",
            file_type="markdown",
            content="Just text",
            content_hash="h",
        )
        profile = build_profile(doc)
        assert profile.source_type == "other"
        assert profile.document_type is None
        assert profile.scope_json == {}
        assert profile.tags_json == []
        assert profile.structure_quality == "unknown"
        assert profile.title is None

    def test_profile_is_frozen(self):
        doc = RawDocumentData(
            file_path="a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="text",
            content_hash="h",
        )
        profile = build_profile(doc)
        from dataclasses import FrozenInstanceError
        import pytest
        with pytest.raises(FrozenInstanceError):
            profile.source_type = "other"  # type: ignore[misc]

    def test_scope_tags_are_copies(self):
        """Profile scope/tags are independent copies, not references."""
        doc = RawDocumentData(
            file_path="a.md",
            relative_path="a.md",
            file_name="a.md",
            file_type="markdown",
            content="text",
            content_hash="h",
            scope_json={"k": "v"},
            tags_json=["t1"],
        )
        profile = build_profile(doc)
        profile.scope_json["new_key"] = "new_val"
        assert "new_key" not in doc.scope_json
