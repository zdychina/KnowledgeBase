"""B4 单测：entity_relations pattern 约束抽关系 + npmi 纯函数（无需 DB）。

验证：
- 合法类型对（命中 allowed_pairs）→ candidate_relations；
- 自环被闸 2 拦掉；
- 类型不在任何 pattern → off-schema relation_candidates；
- 通配 "*" pattern 命中任意类型对；
- npmi() 数学口径（无共现=-1、独立≈0、强共现>0）。
"""
from __future__ import annotations

import math

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.stages.entity_relations import EntityRelationBuilder, npmi


class _FakeStore:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def active_relation_types(self, domain_id: str) -> list[dict]:
        return self._rows


def _builder(rows: list[dict]) -> EntityRelationBuilder:
    return EntityRelationBuilder(ontology_store=_FakeStore(rows), domain_id="cloud_core_network")


def _seg(refs: list[dict]) -> RawSegmentData:
    return RawSegmentData(
        document_key="doc-1", segment_index=3, block_type="paragraph",
        raw_text="x", entity_refs_json=refs,
    )


_CONNECTS = {
    "name": "connects_to",
    "allowed_pairs_json": [{"head": "network_element", "tail": "interface"}],
}
_PART_OF = {
    "name": "part_of",
    "allowed_pairs_json": [{"head": "*", "tail": "*"}],
}


def test_legal_pair_makes_candidate_edge() -> None:
    seg = _seg([
        {"type": "network_element", "name": "SMF", "canonical_name": "SMF"},
        {"type": "interface", "name": "N4", "canonical_name": "N4"},
    ])
    out = _builder([_CONNECTS]).build_batch([seg])[0]
    edges = out.metadata_json["candidate_relations"]
    assert any(
        e["head"] == "SMF" and e["tail"] == "N4" and e["relation_type"] == "connects_to"
        for e in edges
    )
    # interface→network_element 反向不在 pattern，不应作为 connects_to 候选边
    assert not any(e["head"] == "N4" and e["relation_type"] == "connects_to" for e in edges)


def test_self_loop_filtered() -> None:
    seg = _seg([
        {"type": "network_element", "name": "SMF", "canonical_name": "SMF"},
        {"type": "network_element", "name": "SMF会话", "canonical_name": "SMF"},
    ])
    out = _builder([_PART_OF]).build_batch([seg])[0]
    # 两个都归一到 SMF → 自环，应无候选边、无 off-schema
    assert "candidate_relations" not in out.metadata_json
    assert "relation_candidates" not in out.metadata_json


def test_off_schema_pair_becomes_candidate() -> None:
    seg = _seg([
        {"type": "alarm", "name": "ALM-1", "canonical_name": "ALM-1"},
        {"type": "feature", "name": "GWFD-1", "canonical_name": "GWFD-1"},
    ])
    # 只有 connects_to(network_element→interface)，alarm/feature 不命中任何 pattern
    out = _builder([_CONNECTS]).build_batch([seg])[0]
    assert "candidate_relations" not in out.metadata_json
    cands = out.metadata_json["relation_candidates"]
    assert any(c["head_type"] == "alarm" and c["reason"] == "off_schema_pair" for c in cands)


def test_wildcard_matches_any_pair() -> None:
    seg = _seg([
        {"type": "alarm", "name": "ALM-1", "canonical_name": "ALM-1"},
        {"type": "feature", "name": "GWFD-1", "canonical_name": "GWFD-1"},
    ])
    out = _builder([_PART_OF]).build_batch([seg])[0]
    edges = out.metadata_json["candidate_relations"]
    assert any(e["relation_type"] == "part_of" for e in edges)


def test_empty_patterns_no_extraction() -> None:
    seg = _seg([
        {"type": "network_element", "name": "SMF", "canonical_name": "SMF"},
        {"type": "interface", "name": "N4", "canonical_name": "N4"},
    ])
    out = _builder([]).build_batch([seg])[0]
    assert out is seg


def test_single_entity_no_pairs() -> None:
    seg = _seg([{"type": "network_element", "name": "SMF", "canonical_name": "SMF"}])
    out = _builder([_PART_OF]).build_batch([seg])[0]
    assert out is seg


def test_npmi_math() -> None:
    assert npmi(0.5, 0.5, 0.0) == -1.0           # 无共现
    assert npmi(0.0, 0.5, 0.1) == -1.0           # 退化输入
    # 独立：p_ht = p_h*p_t → pmi=0 → npmi=0
    assert abs(npmi(0.5, 0.5, 0.25)) < 1e-9
    # 完全共现 p_ht=1 → 约定返回 1.0
    assert npmi(1.0, 1.0, 1.0) == 1.0
    # 正关联：共现高于独立期望 → >0
    assert npmi(0.5, 0.5, 0.4) > 0.0
