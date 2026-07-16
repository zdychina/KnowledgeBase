"""PRD-05: discourse_role derivation (nucleus / satellite / standalone).

Covers the RST nuclearity table and the infer_discourse_roles() pure function.
No LLM / DB — these are in-memory unit tests.
"""
from __future__ import annotations

from knowledge_mining.mining.contracts.models import RawSegmentData, SegmentRelationData
from knowledge_mining.mining.contracts.rst_relations import RST_DB_VALUES, RST_NUCLEARITY
from knowledge_mining.mining.stages.relations import infer_discourse_roles


def _seg(index: int, doc: str = "doc") -> RawSegmentData:
    return RawSegmentData(document_key=doc, segment_index=index)


def _rel(src_idx: int, tgt_idx: int, relation_type: str, doc: str = "doc") -> SegmentRelationData:
    return SegmentRelationData(
        source_segment_key=f"{doc}#{src_idx}",
        target_segment_key=f"{doc}#{tgt_idx}",
        relation_type=relation_type,
    )


class TestNuclearityTable:
    def test_covers_exactly_the_rst_relations(self):
        """Every RST DB value must have a nuclearity entry, and no extras."""
        assert set(RST_NUCLEARITY) == set(RST_DB_VALUES)


class TestInferDiscourseRoles:
    def test_standalone_when_no_relations(self):
        segs = [_seg(0), _seg(1)]
        roles = infer_discourse_roles(segs, [])
        assert roles == {"doc#0": "standalone", "doc#1": "standalone"}

    def test_mono_prev_front_is_nucleus(self):
        # elaborates: earlier segment is the nucleus regardless of edge direction
        segs = [_seg(0), _seg(1)]
        roles = infer_discourse_roles(segs, [_rel(0, 1, "elaborates")])
        assert roles == {"doc#0": "nucleus", "doc#1": "satellite"}

    def test_mono_prev_direction_independent_of_source_target(self):
        # Same relation but edge points target->source; order still decides.
        segs = [_seg(0), _seg(1)]
        roles = infer_discourse_roles(segs, [_rel(1, 0, "elaborates")])
        assert roles == {"doc#0": "nucleus", "doc#1": "satellite"}

    def test_mono_post_back_is_nucleus(self):
        # causes: later segment (result/phenomenon) is the nucleus
        segs = [_seg(0), _seg(1)]
        roles = infer_discourse_roles(segs, [_rel(0, 1, "causes")])
        assert roles == {"doc#0": "satellite", "doc#1": "nucleus"}

    def test_multinuclear_both_nucleus(self):
        segs = [_seg(0), _seg(1)]
        roles = infer_discourse_roles(segs, [_rel(0, 1, "contrasts_with")])
        assert roles == {"doc#0": "nucleus", "doc#1": "nucleus"}

    def test_nucleus_wins_over_satellite(self):
        # seg1 is satellite in elaborates(0,1) but nucleus in elaborates(1,2).
        segs = [_seg(0), _seg(1), _seg(2)]
        roles = infer_discourse_roles(
            segs, [_rel(0, 1, "elaborates"), _rel(1, 2, "elaborates")]
        )
        assert roles["doc#1"] == "nucleus"

    def test_nucleus_not_downgraded_by_later_satellite_edge(self):
        # Process order: seg1 becomes nucleus first, then a satellite edge must
        # not downgrade it.
        segs = [_seg(0), _seg(1), _seg(2)]
        roles = infer_discourse_roles(
            segs, [_rel(1, 2, "elaborates"), _rel(0, 1, "elaborates")]
        )
        assert roles["doc#1"] == "nucleus"

    def test_structural_edges_ignored(self):
        # 'previous'/'next' are not RST relations -> no discourse role assigned.
        segs = [_seg(0), _seg(1)]
        roles = infer_discourse_roles(segs, [_rel(0, 1, "next")])
        assert roles == {"doc#0": "standalone", "doc#1": "standalone"}

    def test_relation_referencing_unknown_segment_skipped(self):
        segs = [_seg(0)]
        roles = infer_discourse_roles(segs, [_rel(0, 9, "elaborates")])
        assert roles == {"doc#0": "standalone"}

    def test_document_key_with_hash_parses_index(self):
        # document_key containing '#' must not break index recovery (rsplit).
        segs = [_seg(0, doc="a#b"), _seg(1, doc="a#b")]
        roles = infer_discourse_roles(segs, [_rel(0, 1, "elaborates", doc="a#b")])
        assert roles == {"a#b#0": "nucleus", "a#b#1": "satellite"}
