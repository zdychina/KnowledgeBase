"""B5 单测：graph_write 全局聚合 + 落库（纯逻辑 + 假 store，无需 DB）。

aggregate_build：
- auto + canonical → 升 canonical 实体（带 mention/document 计数）；pending 仅 mention；
- __untyped__ 概念 → 暂无类型 mention，proposed_type/off_schema_reason 随 metadata 存（喂 N3 归纳）；
- 候选边经 NPMI 闸：强共现保留、弱共现丢弃；relation_candidates → 关系候选。
persist_entities_and_mentions（全局A，Gate2 前）：
- 幂等先删快照旧数据；实体计数用 set；**不建边**；返回 entity_ids 映射。
persist_edges（终态，Gate1 后）：仅落保留边，端点须在 entity_ids 内，出处 source_refs 非空。
"""
from __future__ import annotations

from types import SimpleNamespace

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.infra.ontology_store import UNTYPED_NODE_TYPE
from knowledge_mining.mining.stages.graph_write import (
    aggregate_build, persist_entities_and_mentions, persist_edges,
)


def _seg(idx: int, refs: list[dict], meta: dict | None = None) -> RawSegmentData:
    return RawSegmentData(
        document_key="doc-1", segment_index=idx, block_type="paragraph",
        raw_text=f"seg{idx}", entity_refs_json=refs, metadata_json=meta or {},
    )


def _doc(snapshot_id: str, segments: list[RawSegmentData], doc_key: str = "doc-1") -> SimpleNamespace:
    seg_ids = {f"{doc_key}#{s.segment_index}": f"segid-{snapshot_id}-{s.segment_index}" for s in segments}
    return SimpleNamespace(
        snapshot_id=snapshot_id, seg_ids=seg_ids,
        profile=SimpleNamespace(document_key=doc_key), segments=segments, error=None,
    )


_SMF = {"type": "network_element", "name": "SMF", "canonical_name": "SMF", "resolve_status": "auto"}
_N4 = {"type": "interface", "name": "N4", "canonical_name": "N4", "resolve_status": "auto"}
_CONNECTS = {"head": "SMF", "head_type": "network_element",
             "tail": "N4", "tail_type": "interface", "relation_type": "connects_to"}


def test_auto_entities_and_kept_edge() -> None:
    seg = _seg(0, [_SMF, _N4], {"candidate_relations": [_CONNECTS]})
    bg = aggregate_build([_doc("snap1", [seg])], domain_id="cloud_core_network")

    ents = {(e.node_type, e.canonical_name): e for e in bg.entities}
    assert ("network_element", "SMF") in ents
    assert ("interface", "N4") in ents
    assert ents[("network_element", "SMF")].mention_count == 1
    assert ents[("network_element", "SMF")].document_count == 1

    assert len(bg.kept_edges) == 1
    edge = bg.kept_edges[0]
    assert edge.relation_type == "connects_to"
    assert edge.npmi == 1.0  # 恒共现


def test_pending_mention_no_entity() -> None:
    pending = {"type": "protocol", "name": "PFCP", "canonical_name": None, "resolve_status": "pending"}
    seg = _seg(0, [pending])
    bg = aggregate_build([_doc("snap1", [seg])], domain_id="cloud_core_network")
    assert bg.entities == []
    assert len(bg.mentions) == 1
    assert bg.mentions[0].resolve_status == "pending"


def test_untyped_ref_becomes_untyped_mention_with_meta() -> None:
    # 本体外概念（N1 起）走 __untyped__ ref，graph_write 落成暂无类型 mention，
    # proposed_type/off_schema_reason 随 metadata 存下来供 N3 归纳。
    untyped = {"type": UNTYPED_NODE_TYPE, "name": "网络切片", "canonical_name": None,
               "resolve_status": "pending", "proposed_type": "concept",
               "off_schema_reason": "llm_out_of_schema"}
    bg = aggregate_build([_doc("snap1", [_seg(0, [untyped])])], domain_id="cloud_core_network")
    assert bg.entities == []  # 暂无类型不升 canonical 实体
    assert len(bg.mentions) == 1
    m = bg.mentions[0]
    assert m.node_type == UNTYPED_NODE_TYPE
    assert m.metadata["proposed_type"] == "concept"
    assert m.metadata["off_schema_reason"] == "llm_out_of_schema"


def test_npmi_drops_weak_edge() -> None:
    # A 出现在 seg0/1/2，B 出现在 seg2/3/4，只 seg2 共现 → NPMI 低于 0.3 应丢
    a = {"type": "network_element", "name": "A", "canonical_name": "A", "resolve_status": "auto"}
    b = {"type": "interface", "name": "B", "canonical_name": "B", "resolve_status": "auto"}
    edge = {"head": "A", "head_type": "network_element",
            "tail": "B", "tail_type": "interface", "relation_type": "connects_to"}
    segs = [
        _seg(0, [a]),
        _seg(1, [a]),
        _seg(2, [a, b], {"candidate_relations": [edge]}),
        _seg(3, [b]),
        _seg(4, [b]),
    ]
    bg = aggregate_build([_doc("snap1", segs)], domain_id="cloud_core_network")
    assert len(bg.edges) == 1
    assert bg.edges[0].kept is False
    assert bg.edges[0].npmi < 0.3


def test_relation_candidate_aggregated() -> None:
    meta = {"relation_candidates": [
        {"head": "ALM-1", "head_type": "alarm", "tail": "GWFD-1",
         "tail_type": "feature", "reason": "off_schema_pair"},
    ]}
    bg = aggregate_build([_doc("snap1", [_seg(0, [], meta)])], domain_id="cloud_core_network")
    assert len(bg.rel_candidates) == 1
    rc = bg.rel_candidates[0]
    assert rc.head_type == "alarm" and rc.tail_type == "feature"
    assert rc.cooccur == 1


# ---- persist 层（假 store）----

class _FakeGraph:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.entities: dict[tuple, str] = {}
        self.counts: dict[str, tuple] = {}
        self.mentions: list[dict] = []
        self.relations: list[dict] = []
        self.evidence: list[dict] = []
        self._seq = 0

    def _id(self, p: str) -> str:
        self._seq += 1
        return f"{p}-{self._seq}"

    def delete_snapshot_artifacts(self, snap: str) -> None:
        self.deleted.append(snap)

    def upsert_entity(self, domain, *, canonical_name, node_type, first_ontology_version_id=None):
        key = (node_type, canonical_name)
        eid = self.entities.get(key) or self._id("ent")
        self.entities[key] = eid
        return eid

    def set_entity_counts(self, eid, *, mention_count, document_count):
        self.counts[eid] = (mention_count, document_count)

    def add_mention(self, **kw):
        mid = self._id("men")
        self.mentions.append({**kw, "id": mid})
        return mid

    def add_evidence(self, domain, **kw):
        eid = self._id("ev")
        self.evidence.append({**kw, "id": eid})
        return eid

    def upsert_relation(self, domain, *, head_entity_id, tail_entity_id, relation_type,
                        source_refs, confidence=0.7, ontology_version_id=None, has_conflict=False):
        assert source_refs, "source_refs 必须非空（出处强约束）"
        rid = self._id("rel")
        self.relations.append({
            "head": head_entity_id, "tail": tail_entity_id, "rel": relation_type,
            "source_refs": source_refs, "id": rid,
        })
        return rid


class _FakeOntology:
    def __init__(self) -> None:
        self.candidates: list[dict] = []

    def upsert_candidate(self, domain, *, kind, proposed_name, payload=None,
                         source="escape_hatch", evidence=None, score=None, layer="concept"):
        self.candidates.append({"kind": kind, "name": proposed_name, "score": score})
        return f"cand-{len(self.candidates)}"


def test_persist_entities_then_edges() -> None:
    seg = _seg(0, [_SMF, _N4], {"candidate_relations": [_CONNECTS]})
    bg = aggregate_build([_doc("snap1", [seg])], domain_id="cloud_core_network")
    gs, os_ = _FakeGraph(), _FakeOntology()

    # 全局A：实体 + mention，不建边
    summary, entity_ids = persist_entities_and_mentions(
        gs, os_, bg, domain_id="cloud_core_network", ontology_version_id="v1")
    assert gs.deleted == ["snap1"]              # 幂等先删
    assert summary["entities"] == 2
    assert summary["mentions"] == 2
    assert gs.relations == []                   # 此阶段不建边
    smf_id = gs.entities[("network_element", "SMF")]
    assert gs.counts[smf_id] == (1, 1)          # 计数 set 而非累加
    assert entity_ids[("network_element", "SMF")] == smf_id

    # 终态建边：复用 entity_ids
    n_edges = persist_edges(gs, bg, entity_ids,
                            domain_id="cloud_core_network", ontology_version_id="v1")
    assert n_edges == 1
    assert gs.relations and gs.relations[0]["source_refs"]


def test_persist_edges_skips_unconfirmed_endpoint() -> None:
    seg = _seg(0, [_SMF, _N4], {"candidate_relations": [_CONNECTS]})
    bg = aggregate_build([_doc("snap1", [seg])], domain_id="cloud_core_network")
    gs = _FakeGraph()
    # entity_ids 只含 SMF（N4 未确认）→ 端点缺失，不落边
    n_edges = persist_edges(
        gs, bg, {("network_element", "SMF"): "ent-x"},
        domain_id="cloud_core_network", ontology_version_id="v1")
    assert n_edges == 0
    assert gs.relations == []


def test_persist_flushes_relation_candidates() -> None:
    meta = {"relation_candidates": [{"head": "ALM-1", "head_type": "alarm",
                                     "tail": "GWFD-1", "tail_type": "feature",
                                     "reason": "off_schema_pair"}]}
    d1 = _doc("snap1", [_seg(0, [], meta)], doc_key="doc-1")
    d2 = _doc("snap2", [_seg(0, [], meta)], doc_key="doc-2")
    bg = aggregate_build([d1, d2], domain_id="cloud_core_network")
    gs, os_ = _FakeGraph(), _FakeOntology()
    persist_entities_and_mentions(gs, os_, bg, domain_id="cloud_core_network")

    kinds = {c["kind"] for c in os_.candidates}
    names = {c["name"] for c in os_.candidates}
    # 节点类型候选已下线（N1/N3 归纳产出）；此阶段只汇关系类型候选
    assert kinds == {"relation_type"}
    assert "alarm->feature" in names
