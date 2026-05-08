"""Document profile module: derive profile from BatchParams + file metadata.

v0.5: No manifest, no frontmatter, no content inference.
All classification comes from BatchParams or file-level metadata.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_mining.mining.models import BatchParams, DocumentProfile, RawDocumentData


def build_profile(doc: RawDocumentData) -> DocumentProfile:
    """Build a DocumentProfile from a RawDocumentData.

    In v0.5, scope/tags/document_type/source_type are inherited from
    the document's own fields (which were set during ingestion from BatchParams).
    """
    return DocumentProfile(
        document_key=doc.relative_path,
        source_type=doc.source_type or "other",
        document_type=doc.document_type,
        scope_json=dict(doc.scope_json),
        tags_json=list(doc.tags_json),
        structure_quality=doc.structure_quality,
        title=doc.title,
    )
