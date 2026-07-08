"""Resolve stage: 实体归一（消歧）+ 人审分流（L2 §6.2 / B3）。

把 enrich 抽出的每个 mention（segment.entity_refs_json 里的 {type,name}）归一到
canonical_name 并打 resolve_status：

- **Tier1**（默认开）：精确归一化 + ontology_alias_dictionary 命中 → resolve_status='auto'。
  归一后的表面词若本身就是某 canonical（别名词典里出现过的标准名）→ 也判 auto（指向自己）。
- **Tier2**（默认关，留开关）：向量近邻 → 仍标 pending 交人确认（消歧由人拍板，原则要求）。
- **Tier3 LLM**：MVP 不做。
- 其余未命中/不确定 → resolve_status='pending'，触发 Gate2（人审）。

产物写回 entity_refs_json 每一项：追加 canonical_name(可空) + resolve_status 两个键。
下游 B5 graph_write 据此写 asset_segment_entity_mentions。
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, TYPE_CHECKING

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.infra.ontology_bootstrap import _normalize_alias

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


class EntityResolver:
    """别名词典驱动的实体归一器。索引一次性建好（只读、线程安全）。"""

    stage_name = "resolve"
    stage_version = "1"

    def __init__(
        self,
        *,
        ontology_store: "OntologyStore | None" = None,
        domain_id: str | None = None,
        enable_tier2_vector: bool = False,
    ) -> None:
        self._store = ontology_store
        self._domain_id = domain_id
        self._enable_tier2_vector = enable_tier2_vector  # 预留开关，MVP 始终走 pending
        # 归一索引：归一化表面词 → canonical（原形）
        self._alias_map: dict[str, str] = {}
        # 已知 canonical 的归一形 → 原形（用于"表面词本身就是标准名"的自归一）
        self._canonical_norm: dict[str, str] = {}
        self._built = False

    def _ensure_index(self) -> None:
        if self._built:
            return
        self._built = True
        store = self._store
        if store is None or not self._domain_id:
            return
        try:
            rows = store.all_aliases(self._domain_id)
        except Exception:
            logger.warning("all_aliases lookup failed for %s; resolver runs empty",
                           self._domain_id, exc_info=True)
            return
        for r in rows:
            alias_n = r.get("alias_normalized")
            canonical = r.get("canonical_name")
            if alias_n and canonical:
                self._alias_map[alias_n] = canonical
                self._canonical_norm[_normalize_alias(canonical)] = canonical

    def _resolve_one(self, name: str) -> tuple[str | None, str]:
        """归一单个表面词 → (canonical_name | None, resolve_status)。"""
        norm = _normalize_alias(name)
        canonical = self._alias_map.get(norm)
        if canonical is not None:
            return canonical, "auto"
        self_canonical = self._canonical_norm.get(norm)
        if self_canonical is not None:
            return self_canonical, "auto"
        # Tier2 向量归一 MVP 默认关；即便将来开了也只产候选、仍走 pending（消歧由人拍板）。
        return None, "pending"

    def resolve(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]:
        return self.resolve_batch(segments, **kwargs)

    def resolve_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]:
        if not segments:
            return []
        self._ensure_index()

        out: list[RawSegmentData] = []
        for seg in segments:
            refs = seg.entity_refs_json
            if not refs:
                out.append(seg)
                continue
            new_refs = []
            changed = False
            for ref in refs:
                name = ref.get("name")
                if not name:
                    new_refs.append(ref)
                    continue
                canonical, status = self._resolve_one(name)
                merged = dict(ref)
                merged["canonical_name"] = canonical
                merged["resolve_status"] = status
                new_refs.append(merged)
                if merged != ref:
                    changed = True
            out.append(dataclasses.replace(seg, entity_refs_json=new_refs) if changed else seg)
        return out
