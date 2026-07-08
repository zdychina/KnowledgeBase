"""Graph-write stage: 全局落图 + 出处（L2 §6.4 / B5）。

每个 build 跑一次的**全局阶段**（不在逐文档流式管线里）。消费 B2/B3/B4 attach 在
segment 上的产物，跨文档聚合，落 canonical 实体 / 事实边 / 出处 / mention，并把逃生口
候选（B2 out_of_schema）与 off-schema 关系候选（B4 relation_candidates）汇成 ontology_candidates。

切分（与 B2/B4 一致的"逐段产候选、全局做统计"）：
- 逐段已做：闸 1 端点合法、闸 2 非自环、闸 3 类型合法（候选边在 meta["candidate_relations"]）。
- 本阶段做：闸 4 关系强度（跨文档共现算 NPMI ≥ 阈值才落边）、闸 5 去冗余（同三元组去重）。

设计分两半：
1. aggregate_build(...)：**纯函数**，吃 doc 视图（snapshot_id/seg_ids/document_key/segments），
   产出 BuildGraph（实体/边/候选 + NPMI），不碰 DB，可单测。
2. persist_build_graph(...)：薄落库层，按 BuildGraph 写 GraphStore/OntologyStore；
   mention/evidence 走"删快照旧数据再写"保证重跑幂等，实体计数用 set（非累加）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable

from knowledge_mining.mining.infra.ontology_store import UNTYPED_NODE_TYPE
from knowledge_mining.mining.stages.entity_relations import npmi

logger = logging.getLogger(__name__)

_DEFAULT_NPMI_THRESHOLD = 0.3
_DEFAULT_MIN_CANDIDATE_DF = 2  # DF=1 的逃生口候选不进 Gate1（L2 §6.5-C 去噪）
_QUOTE_MAX = 300


def _node_key(ref: dict[str, Any]) -> str | None:
    return ref.get("canonical_name") or ref.get("name")


@dataclass
class MentionRec:
    snapshot_id: str
    segment_id: str
    node_type: str
    mention_text: str
    canonical_name: str | None
    resolve_status: str
    quote: str
    metadata: dict = field(default_factory=dict)  # untyped 概念的 proposed_type/reason（喂 induction）


@dataclass
class EntityRec:
    node_type: str
    canonical_name: str
    mention_count: int = 0
    snapshots: set = field(default_factory=set)
    evidence: list = field(default_factory=list)  # (snapshot_id, segment_id, quote)

    @property
    def document_count(self) -> int:
        return len(self.snapshots)


@dataclass
class EdgeRec:
    head: str
    head_type: str
    tail: str
    tail_type: str
    relation_type: str
    cooccur: int
    npmi: float
    source_segs: list  # (snapshot_id, segment_id, quote)
    kept: bool


@dataclass
class RelCandidateRec:
    head_type: str
    tail_type: str
    cooccur: int
    examples: list  # [(head, tail), ...]


@dataclass
class BuildGraph:
    mentions: list[MentionRec] = field(default_factory=list)
    entities: list[EntityRec] = field(default_factory=list)
    edges: list[EdgeRec] = field(default_factory=list)
    rel_candidates: list[RelCandidateRec] = field(default_factory=list)
    npmi_threshold: float = _DEFAULT_NPMI_THRESHOLD
    total_segments: int = 0

    @property
    def kept_edges(self) -> list[EdgeRec]:
        return [e for e in self.edges if e.kept]


def _segment_key(doc_key: str, seg_index: int) -> str:
    return f"{doc_key}#{seg_index}"


def aggregate_build(
    docs: Iterable[Any],
    *,
    domain_id: str,
    npmi_threshold: float = _DEFAULT_NPMI_THRESHOLD,
) -> BuildGraph:
    """跨文档聚合 → BuildGraph。docs 元素需有 snapshot_id / seg_ids / profile.document_key / segments。"""
    g = BuildGraph(npmi_threshold=npmi_threshold)

    entity_acc: dict[tuple[str, str], EntityRec] = {}
    name_segs: dict[str, set[tuple[int, int]]] = {}     # 实体串 → 出现的段全局 id 集（算 NPMI）
    edge_acc: dict[tuple[str, str, str], dict[str, Any]] = {}
    rel_cand_acc: dict[tuple[str, str], RelCandidateRec] = {}
    seg_total = 0

    for ci, doc in enumerate(docs):
        snapshot_id = getattr(doc, "snapshot_id", None)
        seg_ids = getattr(doc, "seg_ids", {}) or {}
        profile = getattr(doc, "profile", None)
        doc_key = getattr(profile, "document_key", "") if profile else ""
        segments = getattr(doc, "segments", []) or []

        for seg in segments:
            seg_total += 1
            si = seg.segment_index
            gid = (ci, si)
            seg_id = seg_ids.get(_segment_key(doc_key, si)) or f"{ci}#{si}"
            quote = (seg.raw_text or "")[:_QUOTE_MAX]
            meta = seg.metadata_json or {}

            # -- mentions + 实体聚合 --
            for ref in seg.entity_refs_json or []:
                name = ref.get("name")
                ntype = ref.get("type")
                if not name or not ntype:
                    continue
                canonical = ref.get("canonical_name")
                status = ref.get("resolve_status", "pending")
                # untyped 概念把模型的 proposed_type/reason 随 mention 存下来，供 N3 归纳用
                mmeta: dict[str, Any] = {}
                if ntype == UNTYPED_NODE_TYPE:
                    if ref.get("proposed_type"):
                        mmeta["proposed_type"] = ref["proposed_type"]
                    if ref.get("off_schema_reason"):
                        mmeta["off_schema_reason"] = ref["off_schema_reason"]
                g.mentions.append(MentionRec(
                    snapshot_id=snapshot_id, segment_id=seg_id, node_type=ntype,
                    mention_text=name, canonical_name=canonical,
                    resolve_status=status, quote=quote, metadata=mmeta,
                ))
                key_str = _node_key(ref)
                if key_str:
                    name_segs.setdefault(key_str, set()).add(gid)
                # 只有归一确定（auto）+ 有 canonical 才升为 canonical 实体；pending 仅留 mention 待 Gate2
                if status == "auto" and canonical:
                    ek = (ntype, canonical)
                    rec = entity_acc.get(ek)
                    if rec is None:
                        rec = EntityRec(node_type=ntype, canonical_name=canonical)
                        entity_acc[ek] = rec
                    rec.mention_count += 1
                    if snapshot_id:
                        rec.snapshots.add(snapshot_id)
                    rec.evidence.append((snapshot_id, seg_id, quote))

            # -- 候选边（B4 产物）聚合 --
            for ce in meta.get("candidate_relations", []) or []:
                h, t, rel = ce.get("head"), ce.get("tail"), ce.get("relation_type")
                if not h or not t or not rel:
                    continue
                ek = (h, rel, t)
                acc = edge_acc.get(ek)
                if acc is None:
                    acc = {"head_type": ce.get("head_type", ""),
                           "tail_type": ce.get("tail_type", ""),
                           "segs": [], "count": 0}
                    edge_acc[ek] = acc
                acc["count"] += 1
                acc["segs"].append((snapshot_id, seg_id, quote))

            # 逃生口节点候选已下线（N1）：本体外概念改走 __untyped__ pending mention，
            # 由 ontology_induction（N3）从人确认后的实体归纳类型，不在此聚合。

            # -- off-schema 关系候选（B4 relation_candidates）--
            for rc in meta.get("relation_candidates", []) or []:
                ht, tt = rc.get("head_type"), rc.get("tail_type")
                if not ht or not tt:
                    continue
                rk = (ht, tt)
                rec = rel_cand_acc.get(rk)
                if rec is None:
                    rec = RelCandidateRec(head_type=ht, tail_type=tt, cooccur=0, examples=[])
                    rel_cand_acc[rk] = rec
                rec.cooccur += 1
                pair = (rc.get("head"), rc.get("tail"))
                if pair not in rec.examples:
                    rec.examples.append(pair)

    g.total_segments = seg_total

    # 闸 4：NPMI 关系强度
    N = float(seg_total) or 1.0
    for (h, rel, t), acc in edge_acc.items():
        sh = name_segs.get(h, set())
        st = name_segs.get(t, set())
        p_h = len(sh) / N
        p_t = len(st) / N
        p_ht = len(sh & st) / N
        score = npmi(p_h, p_t, p_ht)
        g.edges.append(EdgeRec(
            head=h, head_type=acc["head_type"], tail=t, tail_type=acc["tail_type"],
            relation_type=rel, cooccur=acc["count"], npmi=score,
            source_segs=acc["segs"], kept=(score >= npmi_threshold),
        ))

    g.entities = list(entity_acc.values())
    g.rel_candidates = list(rel_cand_acc.values())
    return g


def persist_entities_and_mentions(
    graph_store: Any,
    ontology_store: Any,
    bg: BuildGraph,
    *,
    domain_id: str,
    ontology_version_id: str | None = None,
) -> tuple[dict[str, int], dict[tuple[str, str], str]]:
    """全局A（Gate2 之前）：落 canonical 实体 + mention + 出处 + off-schema 关系候选。

    **不建事实边**——边后移到 Gate1 通过、类型回贴之后由 persist_edges 从 DB 重聚合（N4/N5）。
    幂等：先删本 build 涉及快照的旧 mention/evidence 再写。
    返回 (计数, entity_ids 映射)；entity_ids 供同进程内首跑建边复用。
    """
    # 1) 幂等：清掉本 build 涉及快照的旧 mention/evidence
    snapshots = {m.snapshot_id for m in bg.mentions if m.snapshot_id}
    for snap in snapshots:
        graph_store.delete_snapshot_artifacts(snap)

    # 2) canonical 实体（upsert 聚合）+ 计数 set（非累加）+ 出处
    entity_ids: dict[tuple[str, str], str] = {}
    for e in bg.entities:
        eid = graph_store.upsert_entity(
            domain_id, canonical_name=e.canonical_name, node_type=e.node_type,
            first_ontology_version_id=ontology_version_id,
        )
        entity_ids[(e.node_type, e.canonical_name)] = eid
        graph_store.set_entity_counts(
            eid, mention_count=e.mention_count, document_count=e.document_count)
        for snap, seg_id, quote in e.evidence:
            if snap and seg_id:
                graph_store.add_evidence(
                    domain_id, document_snapshot_id=snap, segment_id=seg_id,
                    target_kind="entity", target_id=eid, quote=quote)

    # 3) mention（含出处）；untyped 概念的 proposed_type/reason 随 metadata 落库供归纳用
    n_mentions = 0
    for m in bg.mentions:
        if not m.snapshot_id or not m.segment_id:
            continue
        resolved_eid = entity_ids.get((m.node_type, m.canonical_name)) if m.canonical_name else None
        mid = graph_store.add_mention(
            document_snapshot_id=m.snapshot_id, segment_id=m.segment_id,
            node_type=m.node_type, mention_text=m.mention_text,
            canonical_name=m.canonical_name, resolved_entity_id=resolved_eid,
            resolve_status=m.resolve_status, metadata=m.metadata or None,
        )
        graph_store.add_evidence(
            domain_id, document_snapshot_id=m.snapshot_id, segment_id=m.segment_id,
            target_kind="mention", target_id=mid, quote=m.quote)
        n_mentions += 1

    # 4) off-schema 关系候选 → ontology_candidates（Gate1 关系类型评审）。节点类型候选由 N3 归纳产出。
    n_cands = 0
    for r in bg.rel_candidates:
        ontology_store.upsert_candidate(
            domain_id, kind="relation_type",
            proposed_name=f"{r.head_type}->{r.tail_type}",
            payload={"head_type": r.head_type, "tail_type": r.tail_type,
                     "cooccur": r.cooccur, "examples": r.examples[:5]},
            source="escape_hatch", score=float(r.cooccur))
        n_cands += 1

    return ({
        "entities": len(bg.entities),
        "mentions": n_mentions,
        "candidates": n_cands,
    }, entity_ids)


def reaggregate_edges(
    mention_rows: list[dict[str, Any]],
    *,
    domain_id: str,
    relation_builder: Any | None = None,
    npmi_threshold: float = _DEFAULT_NPMI_THRESHOLD,
) -> tuple[BuildGraph, dict[tuple[str, str], str]]:
    """终态建边的 DB 重聚合（Gate1 之后，N4/N5）：从已确认 mention 重建逐段实体视图，
    重跑关系抽取 + NPMI 聚合，产出 BuildGraph + entity_ids 映射。

    为什么从 DB 重建而非复用首跑内存态：resume 是新进程（首跑内存随进程退出已丢），
    且人在 Gate2/Gate1 期间可能合并/改名/补类型——边必须连"人确认后、类型已定"的实体，
    故以 mention 表（resolved_entity_id + 实体当前 node_type/canonical_name）为唯一真相源。

    mention_rows 每项需含：document_snapshot_id / segment_id / entity_id /
    node_type（实体当前类型）/ canonical_name / quote（所在段原文）。
    relation_builder 为 EntityRelationBuilder（按 active 本体 allowed_pairs 过类型闸）。
    """
    entity_ids: dict[tuple[str, str], str] = {}
    # snapshot → 有序 segment_id → 该段的已确认实体行
    by_snap: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in mention_rows:
        snap = r.get("document_snapshot_id")
        seg_id = r.get("segment_id")
        ntype = r.get("node_type")
        canon = r.get("canonical_name")
        eid = r.get("entity_id")
        if not snap or not seg_id or not ntype or not canon or not eid:
            continue
        entity_ids[(ntype, canon)] = eid
        by_snap.setdefault(snap, {}).setdefault(seg_id, []).append(r)

    from knowledge_mining.mining.contracts.models import RawSegmentData

    docs: list[Any] = []
    for snap, seg_map in by_snap.items():
        segments: list[RawSegmentData] = []
        seg_ids: dict[str, str] = {}
        for si, (seg_id, rows_in_seg) in enumerate(seg_map.items()):
            refs = [{"type": r["node_type"], "name": r["canonical_name"],
                     "canonical_name": r["canonical_name"], "resolve_status": "human"}
                    for r in rows_in_seg]
            quote = next((r.get("quote") for r in rows_in_seg if r.get("quote")), "") or ""
            segments.append(RawSegmentData(
                document_key=snap, segment_index=si, block_type="paragraph",
                raw_text=quote, entity_refs_json=refs,
            ))
            seg_ids[_segment_key(snap, si)] = seg_id
        built = relation_builder.build_batch(segments) if relation_builder else segments
        docs.append(SimpleNamespace(
            snapshot_id=snap, seg_ids=seg_ids,
            profile=SimpleNamespace(document_key=snap), segments=built, error=None,
        ))

    bg = aggregate_build(docs, domain_id=domain_id, npmi_threshold=npmi_threshold)
    return bg, entity_ids


def persist_edges(
    graph_store: Any,
    bg: BuildGraph,
    entity_ids: dict[tuple[str, str], str],
    *,
    domain_id: str,
    ontology_version_id: str | None = None,
) -> int:
    """终态建边（Gate1 之后）：仅落过闸 4 的事实边，端点须为已确认且类型已定的 canonical 实体。

    entity_ids 为 (node_type, canonical_name)→entity_id 映射（首跑用内存、resume 用 DB 重建）。
    出处强约束：拿不到出处不落边。
    """
    n_edges = 0
    for e in bg.kept_edges:
        hid = entity_ids.get((e.head_type, e.head))
        tid = entity_ids.get((e.tail_type, e.tail))
        if not hid or not tid or hid == tid:
            continue  # 端点未确认/未定类型 → 不落边
        evidence_ids = []
        for snap, seg_id, quote in e.source_segs:
            if snap and seg_id:
                evidence_ids.append(graph_store.add_evidence(
                    domain_id, document_snapshot_id=snap, segment_id=seg_id,
                    target_kind="relation", target_id=f"{hid}->{tid}:{e.relation_type}",
                    quote=quote))
        if not evidence_ids:
            continue  # 出处强约束：拿不到出处不落边
        graph_store.upsert_relation(
            domain_id, head_entity_id=hid, tail_entity_id=tid,
            relation_type=e.relation_type, source_refs=evidence_ids,
            confidence=max(0.0, min(1.0, (e.npmi + 1.0) / 2.0)),
            ontology_version_id=ontology_version_id)
        n_edges += 1
    return n_edges


def scoped_recompute(pool: Any, domain_id: str, affected_entity_ids: list[str]) -> int:
    """局部重算：只重算受影响实体所在段落涉及的边（NPMI 是全局量但分母不变，
    范围外实体对的边数学上不变，故 scoped 是精确而非近似）。

    流程：取这些实体所在段落的全部已确认 mention → 算出重算集合（含同段邻居）→
    删该集合内的旧边 → reaggregate_edges 重算 → persist_edges 落新边。
    无 active 本体则跳过返回 0（与 graph_write_final 容错一致）。
    """
    from knowledge_mining.mining.infra.ontology_store import OntologyStore, GraphStore
    from knowledge_mining.mining.stages.entity_relations import EntityRelationBuilder

    if not affected_entity_ids:
        return 0
    ostore = OntologyStore(pool)
    active = ostore.active_version(domain_id)
    if active is None:
        return 0
    gstore = GraphStore(pool)

    rows = gstore.resolved_mentions_around_entities(domain_id, affected_entity_ids)
    if not rows:
        return 0
    recompute_ids = {r["entity_id"] for r in rows} | set(affected_entity_ids)
    gstore.delete_edges_among(domain_id, list(recompute_ids))

    rel_builder = EntityRelationBuilder(ontology_store=ostore, domain_id=domain_id)
    bg, entity_ids = reaggregate_edges(rows, domain_id=domain_id, relation_builder=rel_builder)
    return persist_edges(gstore, bg, entity_ids,
                         domain_id=domain_id, ontology_version_id=active["id"])
