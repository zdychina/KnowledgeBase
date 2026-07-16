"""B3 单测：resolve 实体归一 + 人审分流（纯逻辑，用假 store，无需 DB）。

验证 EntityResolver.resolve_batch：
- 命中别名 → canonical_name = 标准名，resolve_status='auto'；
- 表面词本身就是标准名（别名词典里出现过的 canonical）→ 自归一 auto；
- 未命中 → canonical_name=None，resolve_status='pending'（进 Gate2）；
- 大小写 / 多余空白被归一化吃掉。
"""
from __future__ import annotations

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.stages.resolve import EntityResolver


class _FakeStore:
    """假本体库：只实现 resolver 需要的 all_aliases。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all_aliases(self, domain_id: str) -> list[dict]:
        return self._rows


def _resolver() -> EntityResolver:
    rows = [
        {"alias_normalized": "用户面功能", "canonical_name": "UPF", "node_type": "network_element"},
        {"alias_normalized": "user plane function", "canonical_name": "UPF", "node_type": "network_element"},
        {"alias_normalized": "会话管理功能", "canonical_name": "SMF", "node_type": "network_element"},
    ]
    return EntityResolver(ontology_store=_FakeStore(rows), domain_id="cloud_core_network")


def _seg(refs: list[dict]) -> RawSegmentData:
    return RawSegmentData(
        document_key="doc-1",
        segment_index=0,
        block_type="paragraph",
        raw_text="x",
        entity_refs_json=refs,
    )


def _by_name(refs: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in refs}


def test_alias_hit_resolves_auto() -> None:
    seg = _seg([{"type": "network_element", "name": "用户面功能"}])
    out = _resolver().resolve_batch([seg])[0]
    ref = out.entity_refs_json[0]
    assert ref["canonical_name"] == "UPF"
    assert ref["resolve_status"] == "auto"


def test_surface_is_canonical_self_resolves() -> None:
    seg = _seg([{"type": "network_element", "name": "UPF"}])
    out = _resolver().resolve_batch([seg])[0]
    ref = out.entity_refs_json[0]
    assert ref["canonical_name"] == "UPF"
    assert ref["resolve_status"] == "auto"


def test_unknown_surface_is_pending() -> None:
    seg = _seg([{"type": "protocol", "name": "PFCP"}])
    out = _resolver().resolve_batch([seg])[0]
    ref = out.entity_refs_json[0]
    assert ref["canonical_name"] is None
    assert ref["resolve_status"] == "pending"


def test_case_and_whitespace_normalized() -> None:
    seg = _seg([{"type": "network_element", "name": "  User  Plane  Function  "}])
    out = _resolver().resolve_batch([seg])[0]
    ref = out.entity_refs_json[0]
    assert ref["canonical_name"] == "UPF"
    assert ref["resolve_status"] == "auto"


def test_empty_store_all_pending() -> None:
    r = EntityResolver(ontology_store=_FakeStore([]), domain_id="cloud_core_network")
    seg = _seg([{"type": "network_element", "name": "UPF"}])
    out = r.resolve_batch([seg])[0]
    assert out.entity_refs_json[0]["resolve_status"] == "pending"


def test_no_store_no_crash() -> None:
    r = EntityResolver(ontology_store=None, domain_id=None)
    seg = _seg([{"type": "network_element", "name": "UPF"}])
    out = r.resolve_batch([seg])[0]
    assert out.entity_refs_json[0]["resolve_status"] == "pending"


def test_segment_without_refs_unchanged() -> None:
    seg = _seg([])
    out = _resolver().resolve_batch([seg])[0]
    assert out is seg
