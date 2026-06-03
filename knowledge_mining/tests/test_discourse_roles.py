"""Tests for RST discourse-role inference (Mining → Serving discourse linkage)."""
from __future__ import annotations

from knowledge_mining.mining.contracts.models import SegmentRelationData
from knowledge_mining.mining.stages.relations import (
    DISCOURSE_ROLE_NUCLEUS,
    DISCOURSE_ROLE_SATELLITE,
    compute_discourse_roles,
)


def _rel(src: str, tgt: str, rel: str) -> SegmentRelationData:
    return SegmentRelationData(source_segment_key=src, target_segment_key=tgt, relation_type=rel)


def test_support_relation_marks_source_nucleus_target_satellite():
    roles = compute_discourse_roles([_rel("A", "B", "elaborates")])
    assert roles["A"] == DISCOURSE_ROLE_NUCLEUS
    assert roles["B"] == DISCOURSE_ROLE_SATELLITE


def test_nucleus_precedence_over_satellite():
    # B is satellite in the first relation but nucleus (source) in the second.
    roles = compute_discourse_roles([
        _rel("A", "B", "elaborates"),
        _rel("B", "C", "backgrounds"),
    ])
    assert roles["B"] == DISCOURSE_ROLE_NUCLEUS
    assert roles["C"] == DISCOURSE_ROLE_SATELLITE


def test_multinuclear_and_causal_mark_both_nucleus():
    roles = compute_discourse_roles([
        _rel("A", "B", "contrasts_with"),
        _rel("C", "D", "causes"),
    ])
    assert all(roles[k] == DISCOURSE_ROLE_NUCLEUS for k in ("A", "B", "C", "D"))


def test_segments_without_relations_are_absent():
    roles = compute_discourse_roles([_rel("A", "B", "elaborates")])
    assert "Z" not in roles  # caller treats absent keys as "standalone"


def test_all_supported_satellite_relations():
    support = [
        "elaborates", "evidences", "backgrounds", "conditions",
        "summarizes", "justifies", "enables", "exemplifies", "purposes",
    ]
    for rt in support:
        roles = compute_discourse_roles([_rel("S", "T", rt)])
        assert roles["S"] == DISCOURSE_ROLE_NUCLEUS, rt
        assert roles["T"] == DISCOURSE_ROLE_SATELLITE, rt
