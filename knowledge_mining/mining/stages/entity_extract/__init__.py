"""Entity extract stage: ontology-aware entity extraction (independent LLM call).

从 enrich 拆出来的独立阶段（L4 §15）。enrich 回归篇章本职（语义角色 + 内容质量），
本阶段专司本体实体抽取，自己跑一次 LLM 调用，把 active 本体的点类型表喂进 prompt。

双通道输出（L4 §15.2）：
- 通道 A（对齐已知）：实体落在 active 类型表内 → 写 entity_refs_json；
- 通道 B（提议新类型）：重要但清单外 / 低置信 → 不硬塞、不丢弃，进 meta["out_of_schema"]，
  由全局阶段（B5/graph_write）跨文档聚合打分写 ontology_candidates，逃生口入口。

下游 resolve / entity_relations / graph_write 读 entity_refs_json + meta["out_of_schema"]，
不关心是谁写的，接口不变（爆炸半径小）。
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, TYPE_CHECKING

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.infra.ontology_store import UNTYPED_NODE_TYPE

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile
    from knowledge_mining.mining.infra.ontology_store import OntologyStore

logger = logging.getLogger(__name__)

# in-schema 实体最低置信度；低于此值即便类型合法也转入逃生口复核（防硬塞）。
_MIN_ENTITY_CONFIDENCE = 0.5


class EntityExtractor:
    """LLM-backed ontology entity extraction via llm_service HTTP API.

    构造同 LlmEnricher（base_url / profile / ontology_store / domain_id），
    以便读 active 本体点类型作为抽取约束的真相源。
    """

    stage_name = "entity_extract"
    stage_version = "1"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        profile: "DomainProfile | None" = None,
        knowledge_domain: str | None = None,
        ontology_store: "OntologyStore | None" = None,
        domain_id: str | None = None,
    ) -> None:
        from knowledge_mining.mining.infra.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url)
        self._profile = profile
        self._knowledge_domain = knowledge_domain or (profile.domain_id if profile else None)
        self._ontology_store = ontology_store
        self._domain_id = domain_id or (profile.domain_id if profile else None)

    def _resolve_allowed_types(self) -> frozenset[str]:
        """抽取允许的对象类型：优先读 active 本体点类型，回落 domain.yaml。"""
        store = self._ontology_store
        if store is not None and self._domain_id:
            try:
                rows = store.active_node_types(self._domain_id)
                if rows:
                    return frozenset(r["name"] for r in rows)
            except Exception:
                logger.warning(
                    "active_node_types lookup failed for %s; falling back to profile.entity_types",
                    self._domain_id, exc_info=True,
                )
        return self._profile.entity_types if self._profile else frozenset()

    def extract(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]:
        return self.extract_batch(segments, **kwargs)

    def extract_batch(
        self,
        segments: list[RawSegmentData],
        **kwargs: Any,
    ) -> list[RawSegmentData]:
        """Batch entity extraction via LLM. Returns original segment when LLM unavailable."""
        if not segments:
            return []

        profile = self._profile
        allowed_types = self._resolve_allowed_types()
        allowed_types_str = ", ".join(sorted(allowed_types)) if allowed_types else ""
        min_enrich_tokens = (
            profile.retrieval_policy.min_enrich_tokens
            if profile and hasattr(profile, "retrieval_policy")
            else 30
        )

        # Phase 0: 跳过 tiny 段落（实体抽取在过短段落上无意义，且它们已判非实质）
        tiny_indices: set[int] = set()
        for idx, seg in enumerate(segments):
            tc = seg.token_count if seg.token_count is not None else 0
            if tc < min_enrich_tokens:
                tiny_indices.add(idx)

        substantial_segments = [seg for idx, seg in enumerate(segments) if idx not in tiny_indices]

        # Phase 1: 仅提交实质段落
        seg_tasks: dict[str, str] = {}
        for sub_idx, seg in enumerate(substantial_segments):
            task_id = self._client.submit_task(
                template_key="mining-entity-extraction",
                input={
                    "text": seg.raw_text,
                    "section_title": seg.section_title or "",
                    "block_type": seg.block_type,
                    "allowed_types": allowed_types_str,
                },
                knowledge_domain=self._knowledge_domain,
                pipeline_stage="entity_extract",
                expected_output_type="json_object",
            )
            if task_id:
                seg_tasks[str(sub_idx)] = task_id

        # Phase 2: 并发轮询
        llm_raw: dict[str, list[dict]] = self._client.poll_all(seg_tasks)
        llm_results: dict[int, dict[str, Any]] = {}
        for key, items in llm_raw.items():
            if items and isinstance(items[0], dict):
                llm_results[int(key)] = items[0]

        # Phase 3: 应用结果（仅实质段落；tiny 原样返回，不抽实体）
        enriched_substantial = [
            _apply_entity_result(seg, llm_results[sub_idx], allowed_types)
            if sub_idx in llm_results
            else seg
            for sub_idx, seg in enumerate(substantial_segments)
        ]

        # Phase 4: 合回原顺序
        result: list[RawSegmentData] = []
        sub_cursor = 0
        for orig_idx, orig_seg in enumerate(segments):
            if orig_idx in tiny_indices:
                result.append(orig_seg)
            else:
                result.append(enriched_substantial[sub_cursor])
                sub_cursor += 1

        return result


def _apply_entity_result(
    seg: RawSegmentData,
    result: dict[str, Any],
    allowed_types: frozenset[str],
) -> RawSegmentData:
    """把双通道抽取结果落进 segment.entity_refs_json（N1 重排，L1 §12 / L2 §15.2）。

    新顺序下"本体外概念不再直接产候选"，而是统一写成 entity_refs：
    - 通道 A 类型合法且置信够 → 普通 ref {type, name}（resolve 归一→auto/pending）。
    - 通道 A 类型不在清单 / 置信不足，或通道 B 模型自报的清单外概念 → **暂无类型 ref**
      {type: '__untyped__', name, proposed_type, off_schema_reason}。

    暂无类型 ref 经 resolve 必为 pending（哨兵类型不会命中别名词典），
    经 graph_write 落成一条 node_type='__untyped__' 的 pending mention，天然进 Gate2。
    人确认后由 ontology_induction（N3）从这批干净实体归纳正式类型。
    """
    entity_refs: list[dict[str, Any]] = []

    def _add_untyped(name: str, proposed_type: str | None, reason: str,
                     extra: dict[str, Any] | None = None) -> None:
        ref: dict[str, Any] = {"type": UNTYPED_NODE_TYPE, "name": name,
                               "off_schema_reason": reason}
        if proposed_type and proposed_type != UNTYPED_NODE_TYPE:
            ref["proposed_type"] = proposed_type
        if extra:
            ref.update(extra)
        entity_refs.append(ref)

    # 通道 A：对齐已知类型
    for e in result.get("entities", []) or []:
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        if not name:
            continue
        etype = e.get("type", "unknown")
        conf = e.get("confidence")
        conf_ok = not isinstance(conf, (int, float)) or conf >= _MIN_ENTITY_CONFIDENCE
        type_ok = not allowed_types or etype in allowed_types
        if type_ok and conf_ok:
            entity_refs.append({"type": etype, "name": name})
        elif not type_ok:
            _add_untyped(name, etype, "off_schema_type")
        else:
            # 类型合法但置信不足 → 转暂无类型，交 Gate2 人确认
            _add_untyped(name, etype, "low_confidence")

    # 通道 B：模型自报的清单外重要概念 → 暂无类型
    for item in result.get("out_of_schema", []) or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        extra: dict[str, Any] = {}
        if item.get("reason"):
            extra["proposed_reason"] = item["reason"]
        if item.get("evidence"):
            extra["evidence"] = item["evidence"]
        _add_untyped(item["name"], item.get("proposed_type") or item.get("type"),
                     "llm_out_of_schema", extra or None)

    changes: dict[str, Any] = {}

    if entity_refs:
        existing = {(r["type"], r["name"]) for r in seg.entity_refs_json}
        merged_refs = list(seg.entity_refs_json) + [
            ref for ref in entity_refs if (ref["type"], ref["name"]) not in existing
        ]
        changes["entity_refs_json"] = merged_refs

    if not changes:
        return seg

    return dataclasses.replace(seg, entity_refs_json=changes["entity_refs_json"])
