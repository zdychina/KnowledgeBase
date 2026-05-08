"""Ingestion module: recursive folder scan for v0.5.

Discovers md/txt/html/htm/pdf/doc/docx files. All files are registered as
raw_documents; only md/txt are parsed into raw_segments later.
No manifest.jsonl, no frontmatter parsing, no external metadata.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from knowledge_mining.mining.models import BatchParams, RawDocumentData

# Recognized file extensions → file_type mapping
_EXTENSION_MAP: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
}

# Extensions eligible for parsing (generate raw_segments)
PARSABLE_EXTENSIONS = {".md", ".markdown", ".txt"}

# Files to always skip
_SKIP_NAMES = {
    "manifest.jsonl", "manifest.json",
    "html_to_md_mapping.json", "html_to_md_mapping.csv",
    ".ds_store", "thumbs.db", ".gitkeep",
}


def ingest_directory(
    input_path: Path,
    batch_params: BatchParams | None = None,
) -> tuple[list[RawDocumentData], dict[str, Any]]:
    """Recursively scan input_path for recognized files.

    Returns (documents, summary) where summary contains:
        discovered_documents, parsed_documents, unparsed_documents,
        skipped_files, failed_files.
    """
    input_path = Path(input_path)
    batch_params = batch_params or BatchParams()

    documents: list[RawDocumentData] = []
    summary: dict[str, Any] = {
        "discovered_documents": 0,
        "parsed_documents": 0,
        "unparsed_documents": 0,
        "skipped_files": 0,
        "failed_files": 0,
    }

    for file_path in sorted(input_path.rglob("*")):
        if not file_path.is_file():
            continue

        # Skip known metadata/system files
        if file_path.name.lower() in _SKIP_NAMES:
            summary["skipped_files"] += 1
            continue

        rel_path = file_path.relative_to(input_path)
        ext = file_path.suffix.lower()

        # Determine file_type
        file_type = _EXTENSION_MAP.get(ext)
        if file_type is None:
            summary["skipped_files"] += 1
            continue

        summary["discovered_documents"] += 1

        try:
            content_bytes = file_path.read_bytes()
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            # Read text content for parsable types; empty string for binary
            if ext in PARSABLE_EXTENSIONS:
                content = content_bytes.decode("utf-8", errors="replace")
                summary["parsed_documents"] += 1
            else:
                content = ""
                summary["unparsed_documents"] += 1

            doc = RawDocumentData(
                file_path=str(file_path),
                relative_path=str(rel_path).replace("\\", "/"),
                file_name=file_path.name,
                file_type=file_type,
                content=content,
                content_hash=content_hash,
                source_uri=str(file_path),
                source_type=batch_params.default_source_type,
                document_type=batch_params.default_document_type,
                title=_infer_title(file_path, content, file_type),
                scope_json=dict(batch_params.batch_scope),
                tags_json=list(batch_params.tags),
                structure_quality=_infer_structure_quality(ext),
                processing_profile_json={},
                metadata_json={},
            )
            documents.append(doc)
        except Exception:
            summary["failed_files"] += 1

    return documents, summary


def _infer_title(file_path: Path, content: str, file_type: str) -> str | None:
    """Infer document title: H1 for markdown, filename for others."""
    if file_type == "markdown" and content:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    return file_path.stem


def _infer_structure_quality(ext: str) -> str:
    """Map extension to structure_quality."""
    mapping = {
        ".md": "markdown_native",
        ".markdown": "markdown_native",
        ".txt": "plain_text_only",
        ".html": "full_html",
        ".htm": "full_html",
        ".pdf": "unknown",
        ".doc": "unknown",
        ".docx": "unknown",
    }
    return mapping.get(ext, "unknown")
