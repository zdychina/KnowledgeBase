"""Pipeline entry point: orchestrate all mining modules (v0.5).

Flow: ingest → profile → parse → segment → canonicalize → publish
Supports plugin injection for EntityExtractor, RoleClassifier, SegmentEnricher.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_mining.mining.canonicalization import canonicalize
from knowledge_mining.mining.document_profile import build_profile
from knowledge_mining.mining.extractors import DefaultRoleClassifier
from knowledge_mining.mining.extractors import EntityExtractor
from knowledge_mining.mining.extractors import NoOpSegmentEnricher
from knowledge_mining.mining.extractors import RoleClassifier
from knowledge_mining.mining.extractors import SegmentEnricher
import knowledge_mining.mining.extractors as _extractors_mod
RuleBasedEntityExtractor = _extractors_mod.RuleBasedEntityExtractor
from knowledge_mining.mining.ingestion import ingest_directory
from knowledge_mining.mining.models import BatchParams, RawSegmentData
from knowledge_mining.mining.parsers import create_parser
from knowledge_mining.mining.publishing import publish
from knowledge_mining.mining.segmentation import segment_document


def run_pipeline(
    input_path: Path,
    db_path: Path,
    *,
    batch_params: BatchParams | None = None,
    entity_extractor: EntityExtractor | None = None,
    role_classifier: RoleClassifier | None = None,
    segment_enricher: SegmentEnricher | None = None,
    chunk_size: int = 300,
    chunk_overlap: int = 30,
) -> dict[str, Any]:
    """Run the full mining pipeline.

    Returns a summary dict with discovery/parse/canonical/publish statistics.
    """
    extractor = entity_extractor or RuleBasedEntityExtractor()
    classifier = role_classifier or DefaultRoleClassifier()
    enricher = segment_enricher or NoOpSegmentEnricher()

    # Step 1: Ingest — recursive folder scan
    docs, ingest_summary = ingest_directory(input_path, batch_params)
    if not docs:
        return {**ingest_summary, "raw_segments": 0, "canonicals": 0,
                "source_mappings": 0, "active_version_id": None}

    # Step 2: Profile — batch params inheritance
    profiles = [build_profile(d) for d in docs]
    profile_map = {p.document_key: p for p in profiles}

    # Step 3: Parse + Segment — by file type
    all_segments: list[RawSegmentData] = []
    for doc, profile in zip(docs, profiles):
        file_type = doc.file_type
        parser = create_parser(file_type, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        doc_root = parser.parse(doc.content, doc.file_name, {})

        if doc_root is None:
            # Passthrough (html/pdf/doc/docx) — no segments
            continue

        parser_name = "markdown" if file_type == "markdown" else "txt" if file_type == "txt" else "unknown"
        segments = segment_document(
            doc_root, profile,
            role_classifier=classifier,
            entity_extractor=extractor,
            parser_name=parser_name,
        )
        all_segments.extend(segments)

    # Step 4: Canonicalize
    canonicals, mappings = canonicalize(all_segments, profile_map)

    # Step 5: Publish
    pub_result = publish(
        documents=docs,
        segments=all_segments,
        canonicals=canonicals,
        source_mappings=mappings,
        db_path=db_path,
        batch_params=batch_params,
    )

    return {
        **ingest_summary,
        "raw_segments": len(all_segments),
        "canonical_segments": len(canonicals),
        "source_mappings": len(mappings),
        "active_version_id": pub_result.get("active_version_id"),
        "status": pub_result.get("status", "unknown"),
        "version_code": pub_result.get("version_code"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M1 Knowledge Mining Pipeline (v0.5)")
    parser.add_argument("--input", required=True, help="Input directory path")
    parser.add_argument("--db", required=True, help="Output SQLite database path")
    parser.add_argument("--scope", default=None, help="Batch scope as JSON string")
    parser.add_argument("--default-document-type", default=None,
                        help="Default document_type for all documents")
    parser.add_argument("--default-source-type", default="folder_scan",
                        help="Default source_type (default: folder_scan)")
    parser.add_argument("--tags", default=None, help="Comma-separated tags")
    parser.add_argument("--chunk-size", type=int, default=300,
                        help="TXT chunk size in tokens (default: 300)")
    parser.add_argument("--chunk-overlap", type=int, default=30,
                        help="TXT chunk overlap in tokens (default: 30)")
    args = parser.parse_args()

    batch_scope = json.loads(args.scope) if args.scope else {}
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    batch_params = BatchParams(
        default_source_type=args.default_source_type,
        default_document_type=args.default_document_type,
        batch_scope=batch_scope,
        tags=tags,
    )

    summary = run_pipeline(
        Path(args.input), Path(args.db),
        batch_params=batch_params,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    print(f"Pipeline complete: {summary}")


if __name__ == "__main__":
    main()
