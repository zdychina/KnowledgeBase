"""Canonicalization module: three-layer dedup producing L1 canonical + L2 source mapping (v0.5).

Key changes from v1.1:
- v0.5 field names: block_type, semantic_role, entity_refs_json, scope_json
- Every raw segment must produce a canonical (including singletons)
- Each canonical has exactly one primary source (is_primary=True)
- relation_type: primary/exact_duplicate/normalized_duplicate/near_duplicate/scope_variant/conflict_candidate
- scope_variant: generic scope_json dimension comparison (not product/version/NE specific)
- No segment_type, command_name
"""
from __future__ import annotations

from typing import Any

from knowledge_mining.mining.models import (
    CanonicalSegmentData,
    DocumentProfile,
    RawSegmentData,
    SourceMappingData,
)
from knowledge_mining.mining.text_utils import (
    hamming_distance,
    jaccard_similarity,
    simhash_fingerprint,
)

# Dedup thresholds
_SIMHASH_THRESHOLD = 3
_JACCARD_THRESHOLD = 0.85


def canonicalize(
    segments: list[RawSegmentData],
    profiles: dict[str, DocumentProfile],
) -> tuple[list[CanonicalSegmentData], list[SourceMappingData]]:
    """Three-layer dedup: exact → normalized → simhash+Jaccard.

    Every segment (including singletons) produces a canonical.
    Each canonical has exactly one primary source.
    """
    if not segments:
        return [], []

    canonicals: list[CanonicalSegmentData] = []
    mappings: list[SourceMappingData] = []
    canonical_idx = 0

    # Track assigned segments by composite key
    assigned: set[str] = set()

    # Layer 1: exact duplicates (content_hash) — only process groups with > 1 member
    hash_groups: dict[str, list[RawSegmentData]] = {}
    for seg in segments:
        hash_groups.setdefault(seg.content_hash, []).append(seg)

    for hash_val, group in hash_groups.items():
        if len(group) > 1:
            # True exact duplicate — create canonical and mark all assigned
            canonical, group_mappings = _create_canonical_group(
                group, profiles, f"c{canonical_idx:06d}",
            )
            canonical_idx += 1
            canonicals.append(canonical)
            mappings.extend(group_mappings)
            for seg in group:
                assigned.add(_seg_key(seg))
        # Singletons: leave unassigned for normalized/near layers

    # Layer 2: normalized duplicates (normalized_hash)
    norm_groups: dict[str, list[RawSegmentData]] = {}
    for seg in segments:
        if _seg_key(seg) in assigned:
            continue
        norm_groups.setdefault(seg.normalized_hash, []).append(seg)

    for group in norm_groups.values():
        if len(group) < 2:
            continue
        canonical, group_mappings = _create_canonical_group(
            group, profiles, f"c{canonical_idx:06d}",
        )
        canonical_idx += 1
        canonicals.append(canonical)
        mappings.extend(group_mappings)
        for seg in group:
            assigned.add(_seg_key(seg))

    # Layer 3: near duplicates (simhash + Jaccard) — then singletons
    remaining = [seg for seg in segments if _seg_key(seg) not in assigned]
    layer3_assigned: set[int] = set()

    for i, seg in enumerate(remaining):
        if i in layer3_assigned:
            continue
        group = [seg]
        fp1 = simhash_fingerprint(seg.raw_text)
        for j in range(i + 1, len(remaining)):
            if j in layer3_assigned:
                continue
            other = remaining[j]
            fp2 = simhash_fingerprint(other.raw_text)
            if (hamming_distance(fp1, fp2) <= _SIMHASH_THRESHOLD
                    and jaccard_similarity(seg.raw_text, other.raw_text) >= _JACCARD_THRESHOLD):
                group.append(other)
                layer3_assigned.add(j)
        canonical, group_mappings = _create_canonical_group(
            group, profiles, f"c{canonical_idx:06d}",
        )
        canonical_idx += 1
        canonicals.append(canonical)
        mappings.extend(group_mappings)

    return canonicals, mappings


def _seg_key(seg: RawSegmentData) -> str:
    """Stable composite key for a raw segment."""
    return f"{seg.document_key}#{seg.segment_index}"


def _create_canonical_group(
    group: list[RawSegmentData],
    profiles: dict[str, DocumentProfile],
    canonical_key: str,
) -> tuple[CanonicalSegmentData, list[SourceMappingData]]:
    """Create a canonical segment from a group of raw segments."""
    primary = group[0]
    relations: list[SourceMappingData] = []
    has_variants = False
    variant_policy = "none"
    variant_dimensions: list[str] = []

    # Merge entity_refs from all sources
    merged_entities = _merge_entity_refs([seg.entity_refs_json for seg in group])

    # Merge scope_json from all source documents
    merged_scope, scope_conflicts = _merge_scopes(
        [profiles.get(seg.document_key) for seg in group],
    )

    for i, seg in enumerate(group):
        seg_ref = _seg_key(seg)

        if i == 0:
            # Primary source — exactly one per canonical
            relations.append(SourceMappingData(
                canonical_key=canonical_key,
                raw_segment_ref=seg_ref,
                relation_type="primary",
                is_primary=True,
                priority=0,
            ))
            continue

        # Determine relation type
        rel_type = "near_duplicate"
        if seg.content_hash == primary.content_hash:
            rel_type = "exact_duplicate"
        elif seg.normalized_hash == primary.normalized_hash:
            rel_type = "normalized_duplicate"

        # Check scope_variant: compare scope_json dimensions
        seg_scope = profiles.get(seg.document_key)
        pri_scope = profiles.get(primary.document_key)
        if seg_scope and pri_scope:
            dims = _find_scope_diff_dimensions(seg_scope.scope_json, pri_scope.scope_json)
            if dims:
                rel_type = "scope_variant"
                has_variants = True
                variant_dimensions = dims
                variant_policy = "require_scope"

        relations.append(SourceMappingData(
            canonical_key=canonical_key,
            raw_segment_ref=seg_ref,
            relation_type=rel_type,
            is_primary=False,
            priority=100,
            metadata_json={"variant_dimensions": variant_dimensions} if variant_dimensions else {},
        ))

    metadata: dict[str, Any] = {
        "canonicalization": {
            "method": "three_layer_dedup",
            "source_count": len(group),
        },
    }
    if scope_conflicts:
        metadata["scope_merge"] = {"conflicts": scope_conflicts}

    return CanonicalSegmentData(
        canonical_key=canonical_key,
        block_type=primary.block_type,
        semantic_role=primary.semantic_role,
        canonical_text=primary.raw_text,
        search_text=primary.raw_text.lower(),
        title=primary.section_title,
        summary=None,
        entity_refs_json=merged_entities,
        scope_json=merged_scope,
        has_variants=has_variants,
        variant_policy=variant_policy,
        quality_score=None,
        metadata_json=metadata,
        raw_segment_refs=[r.raw_segment_ref for r in relations],
    ), relations


def _merge_entity_refs(
    refs_list: list[list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Merge entity refs from multiple sources by type+name dedup."""
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for refs in refs_list:
        for ref in refs:
            key = f"{ref.get('type', '')}:{ref.get('name', '').lower()}"
            if key not in seen:
                seen.add(key)
                result.append(ref)
    return result


def _merge_scopes(
    profile_list: list[DocumentProfile | None],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge scope_json from multiple profiles. Arrays union, scalars conflict."""
    if not profile_list or all(p is None for p in profile_list):
        return {}, []

    merged: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []

    for profile in profile_list:
        if profile is None:
            continue
        for key, value in profile.scope_json.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(value, list) and isinstance(merged[key], list):
                # Union arrays
                existing = set(str(x) for x in merged[key])
                for item in value:
                    if str(item) not in existing:
                        merged[key] = [*merged[key], item]
                        existing.add(str(item))
            elif str(value) != str(merged[key]):
                conflicts.append({"key": key, "values": [str(merged[key]), str(value)]})

    return merged, conflicts


def _find_scope_diff_dimensions(
    scope_a: dict[str, Any], scope_b: dict[str, Any],
) -> list[str]:
    """Find scope_json keys where values differ between two scopes."""
    dims: list[str] = []
    all_keys = set(scope_a.keys()) | set(scope_b.keys())
    for key in all_keys:
        val_a = scope_a.get(key)
        val_b = scope_b.get(key)
        if val_a is None or val_b is None:
            continue
        if isinstance(val_a, list) and isinstance(val_b, list):
            if set(str(x) for x in val_a) != set(str(x) for x in val_b):
                dims.append(key)
        elif str(val_a) != str(val_b):
            dims.append(key)
    return dims
