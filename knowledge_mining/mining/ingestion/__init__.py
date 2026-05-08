"""Ingestion module: recursive folder scan for v1.1.

Discovers md/txt/html/htm/pdf/doc/docx files. Produces RawFileData objects
with raw_content_hash and normalized_content_hash.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_mining.mining.contracts.models import BatchParams, RawFileData
from knowledge_mining.mining.infra.hash_utils import compute_raw_hash, compute_snapshot_hash

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

PARSABLE_EXTENSIONS = {".md", ".markdown", ".txt"}

_SKIP_NAMES = {
    "manifest.jsonl", "manifest.json",
    "html_to_md_mapping.json", "html_to_md_mapping.csv",
    ".ds_store", "thumbs.db", ".gitkeep",
}

_MIME_MAP: dict[str, str] = {
    "markdown": "text/markdown",
    "txt": "text/plain",
    "html": "text/html",
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def ingest_directory(
    input_path: Path,
    batch_params: BatchParams | None = None,
) -> tuple[list[RawFileData], dict[str, Any]]:
    """Recursively scan input_path for recognized files."""
    input_path = Path(input_path)
    batch_params = batch_params or BatchParams()

    documents: list[RawFileData] = []
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
        if file_path.name.lower() in _SKIP_NAMES:
            summary["skipped_files"] += 1
            continue

        rel_path = file_path.relative_to(input_path)
        ext = file_path.suffix.lower()
        file_type = _EXTENSION_MAP.get(ext)
        if file_type is None:
            summary["skipped_files"] += 1
            continue

        summary["discovered_documents"] += 1

        try:
            content_bytes = file_path.read_bytes()
            raw_hash = compute_raw_hash(content_bytes)

            if ext in PARSABLE_EXTENSIONS:
                content = content_bytes.decode("utf-8", errors="replace")
                summary["parsed_documents"] += 1
            else:
                content = ""
                summary["unparsed_documents"] += 1

            normalized_hash = compute_snapshot_hash(content) if content else raw_hash

            doc = RawFileData(
                file_path=str(file_path),
                relative_path=str(rel_path).replace("\\", "/"),
                file_name=file_path.name,
                file_type=file_type,
                content=content,
                raw_content_hash=raw_hash,
                normalized_content_hash=normalized_hash,
                source_uri=str(file_path),
                source_type=batch_params.default_source_type,
                document_type=batch_params.default_document_type,
                title=_infer_title(file_path, content, file_type),
                scope_json=dict(batch_params.batch_scope),
                tags_json=list(batch_params.tags),
                metadata_json={},
            )
            documents.append(doc)
        except Exception:
            summary["failed_files"] += 1

    return documents, summary


def get_mime_type(file_type: str) -> str:
    """Map file_type to MIME type for asset_document_snapshots."""
    return _MIME_MAP.get(file_type, "application/octet-stream")


def _infer_title(file_path: Path, content: str, file_type: str) -> str | None:
    """Infer document title: H1 for markdown, filename for others."""
    if file_type == "markdown" and content:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    return file_path.stem
