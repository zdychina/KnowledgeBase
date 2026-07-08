"""Entity-relations stage: pattern 约束抽概念关系（L2 §6.3 / §6.3.1 / B4）。

在**单段**内对已抽实体两两配对，按 active 本体的 allowed_pairs 过类型闸，产出
**候选边**（candidate edges）与**关系候选**（off-schema relation candidates），写进
segment.metadata_json，交给全局阶段 B5 graph_write 做跨文档 NPMI 关联强度过滤、去重、
落 ontology_entity_relations / ontology_candidates。

五道质量闸（L2 §6.3.1）分两处落：
- **本阶段（逐段）**：闸 1 端点合法、闸 2 非自环、闸 3 类型合法（allowed_pairs）。
- **B5（全局）**：闸 4 关系强度（NPMI≥阈值 或 LLM 确认）、闸 5 去冗余 / 冲突标记。
  NPMI 需要跨文档共现计数，是全局量，无法在逐段流式阶段算——故本模块只**实现** npmi()
  纯函数（可单测），由 B5 用 build 级计数调用。这是与 B2 逃生口一致的"逐段产候选、全局做统计"切分。

候选边落点：meta["candidate_relations"] = [{head, head_type, tail, tail_type, relation_type, segment_index}]
off-schema 关系候选：meta["relation_candidates"] = [{head_type, tail_type, head, tail, reason}]
"""
from __future__ import annotations

import dataclasses
import logging
import math
from typing import Any, TYPE_CHECKING

from knowledge_mining.mining.contracts.models import RawSegmentData

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.ontology_store import OntologyStore

logger = logging.getLogger(__name__)

_WILDCARD = "*"


def npmi(p_h: float, p_t: float, p_ht: float) -> float:
    """归一化点互信息（L2 §6.5）。范围 [-1,1]，>0 才算正关联。

    NPMI = ln(p(h,t)/(p(h)·p(t))) / -ln p(h,t)
    入参为概率（计数 ÷ 总段数）。p_ht<=0 时无共现，返回 -1（最弱）。
    """
    if p_ht <= 0.0 or p_h <= 0.0 or p_t <= 0.0:
        return -1.0
    pmi = math.log(p_ht / (p_h * p_t))
    denom = -math.log(p_ht)
    if denom == 0.0:
        return 1.0  # p_ht==1：恒共现，视为最强正关联
    return pmi / denom


def _node_key(ref: dict[str, Any]) -> str | None:
    """实体在图里的归一键：优先 canonical_name，回落表面词。"""
    return ref.get("canonical_name") or ref.get("name")


class EntityRelationBuilder:
    """pattern 约束的概念关系抽取器。allowed_pairs 索引一次性建好（只读、线程安全）。"""

    stage_name = "entity_relations"
    stage_version = "1"

    def __init__(
        self,
        *,
        ontology_store: "OntologyStore | None" = None,
        domain_id: str | None = None,
    ) -> None:
        self._store = ontology_store
        self._domain_id = domain_id
        # relation_name -> list[(head_type, tail_type)]；类型用 "*" 表通配
        self._patterns: dict[str, list[tuple[str, str]]] = {}
        self._built = False

    def _ensure_index(self) -> None:
        if self._built:
            return
        self._built = True
        store = self._store
        if store is None or not self._domain_id:
            return
        try:
            rows = store.active_relation_types(self._domain_id)
        except Exception:
            logger.warning("active_relation_types lookup failed for %s; relation builder runs empty",
                           self._domain_id, exc_info=True)
            return
        for r in rows:
            name = r.get("name")
            pairs = r.get("allowed_pairs_json") or []
            if not name:
                continue
            tuples: list[tuple[str, str]] = []
            for p in pairs:
                if isinstance(p, dict):
                    tuples.append((p.get("head", _WILDCARD), p.get("tail", _WILDCARD)))
            self._patterns[name] = tuples

    def _match_relations(self, head_type: str, tail_type: str) -> list[str]:
        """有序类型对 (head_type, tail_type) 命中的 relation 名列表（含通配）。"""
        out = []
        for name, tuples in self._patterns.items():
            for h, t in tuples:
                if (h == _WILDCARD or h == head_type) and (t == _WILDCARD or t == tail_type):
                    out.append(name)
                    break
        return out

    def build(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]:
        return self.build_batch(segments, **kwargs)

    def build_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]:
        if not segments:
            return []
        self._ensure_index()
        if not self._patterns:
            return segments  # 无 active 关系类型 → 不抽关系（迁移期/空本体）

        out: list[RawSegmentData] = []
        for seg in segments:
            refs = [r for r in seg.entity_refs_json if _node_key(r) and r.get("type")]
            if len(refs) < 2:
                out.append(seg)
                continue

            candidate_relations: list[dict[str, Any]] = []
            relation_candidates: list[dict[str, Any]] = []
            seen_edges: set[tuple[str, str, str]] = set()
            seen_offschema: set[tuple[str, str, str, str]] = set()

            # 同段实体有序两两配对（关系多为有向，故 (a,b) 与 (b,a) 都试）
            for i, head in enumerate(refs):
                for j, tail in enumerate(refs):
                    if i == j:
                        continue
                    hk, tk = _node_key(head), _node_key(tail)
                    ht, tt = head["type"], tail["type"]
                    # 闸 1 端点合法（本段已抽实体，循环内天然满足）；闸 2 非自环
                    if hk == tk:
                        continue
                    # 闸 3 类型合法
                    matched = self._match_relations(ht, tt)
                    if matched:
                        for rel in matched:
                            key = (hk, rel, tk)
                            if key in seen_edges:
                                continue
                            seen_edges.add(key)
                            candidate_relations.append({
                                "head": hk, "head_type": ht,
                                "tail": tk, "tail_type": tt,
                                "relation_type": rel,
                                "segment_index": seg.segment_index,
                            })
                    else:
                        # 类型不在任何 allowed_pairs → off-schema 关系候选（软约束，不落事实边）
                        okey = (ht, tt, hk, tk)
                        if okey in seen_offschema:
                            continue
                        seen_offschema.add(okey)
                        relation_candidates.append({
                            "head": hk, "head_type": ht,
                            "tail": tk, "tail_type": tt,
                            "reason": "off_schema_pair",
                        })

            if not candidate_relations and not relation_candidates:
                out.append(seg)
                continue

            meta = dict(seg.metadata_json)
            if candidate_relations:
                meta["candidate_relations"] = candidate_relations
            if relation_candidates:
                meta["relation_candidates"] = relation_candidates
            out.append(dataclasses.replace(seg, metadata_json=meta))
        return out
