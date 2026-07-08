"""Ontology-induction stage：从人确认的"暂无类型"实体归纳正式类型（LLM 调用 2，N3）。

新顺序（L1 §12 / L2 §15）的第二个全局阶段，跑在 **Gate2 之后、Gate1 之前**：
Gate2 里人把本体外概念点成 __untyped__ canonical 实体（一批干净、已确认的真实体），
本阶段把它们喂给 LLM 聚类、命名、定义，产出 node_type 候选（source='global_induction'），
经 DF 去噪后写 ontology_candidates，交 Gate1 人审。Gate1 通过后由 N5 回贴类型、升版。

为什么独立成阶段（而非塞回逐段抽取）：
- 类型归纳是**跨文档全局量**——要看一个概念在多少文档里反复出现，才敢提议它成一类，
  这和逐段流式抽取的视野天然冲突（与 B2/B4"逐段产候选、全局做统计"同一切分）。
- 只在人已确认实体后跑，输入干净（没有 LLM 幻觉实体），归纳质量高、不浪费 LLM 调用。

切分（与 graph_write 一致）：
1. induce(...)：薄编排层，读确认实体 → 跑一次 LLM → 落候选（碰 DB / LLM）。
2. _build_type_candidates(...)：**纯函数**，吃实体 + LLM 结果，产候选 + DF 去噪，可单测。
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.ontology_store import GraphStore, OntologyStore

logger = logging.getLogger(__name__)

# 新类型最低文档支持度：成员实体覆盖的文档数 < 此值即视为噪声，不进 Gate1（L2 §6.5-C 去噪）。
_DEFAULT_MIN_DF = 2
# 触发归纳的最少确认实体数：太少没有归纳价值，直接跳过省一次 LLM 调用。
_MIN_ENTITIES_TO_INDUCE = 2


class TypeCandidate:
    """一条归纳出的 node_type 候选（落 ontology_candidates 前的中间态）。"""

    __slots__ = ("type_name", "definition", "examples", "layer",
                 "member_entity_ids", "members", "df", "support")

    def __init__(
        self, type_name: str, *, definition: str = "", examples: list[str] | None = None,
        layer: str = "concept", member_entity_ids: list[str] | None = None,
        members: list[str] | None = None, df: int = 0, support: int = 0,
    ) -> None:
        self.type_name = type_name
        self.definition = definition
        self.examples = examples or []
        self.layer = layer
        self.member_entity_ids = member_entity_ids or []
        self.members = members or []
        self.df = df
        self.support = support


def _build_type_candidates(
    entities: list[dict[str, Any]],
    llm_result: dict[str, Any],
    *,
    min_df: int = _DEFAULT_MIN_DF,
) -> list[TypeCandidate]:
    """纯函数：把 LLM 归纳结果对回确认实体，算文档支持度 DF，去噪后产候选。

    entities：confirmed_untyped_entities(...) 的返回（id/canonical_name/document_count/...）。
    llm_result：{"new_types": [{type_name, definition, examples, members:[实体规范名...], layer}]}。
    members 用规范名回指实体（大小写/空白不敏感匹配），落候选时换成 entity_id 供 N5 回贴。
    DF = 该类型成员实体覆盖的文档数（按实体 document_count 取并集近似——同名实体已在
    Gate2 归并，故各成员文档集基本不重叠，求和是合理上界）。DF < 阈值丢弃。

    阈值自适应（修正单文档跑被全量误丢的 bug）：min_df 是"语料够大时"的去噪目标，
    但语料只有 1 篇时，任何类型都不可能覆盖 ≥2 篇——硬卡 min_df=2 会把人已确认的
    真实体全部丢光、永远无法升类型。故按确认实体覆盖的最大文档数 corpus_df 兜底封顶：
    effective_min_df = min(min_df, max(corpus_df, 1))。语料 ≥2 篇时去噪不变。
    """
    by_name: dict[str, dict[str, Any]] = {}
    corpus_df = 0
    for e in entities:
        cn = (e.get("canonical_name") or "").strip().lower()
        if cn:
            by_name[cn] = e
        corpus_df = max(corpus_df, int(e.get("document_count") or 0))
    effective_min_df = min(min_df, max(corpus_df, 1))

    out: list[TypeCandidate] = []
    for nt in llm_result.get("new_types", []) or []:
        if not isinstance(nt, dict):
            continue
        type_name = (nt.get("type_name") or "").strip()
        if not type_name:
            continue
        member_ids: list[str] = []
        member_objs: list[dict[str, Any]] = []
        df = 0
        support = 0
        seen: set[str] = set()
        for raw in nt.get("members", []) or []:
            key = (str(raw) or "").strip().lower()
            ent = by_name.get(key)
            if ent is None or ent["id"] in seen:
                continue
            seen.add(ent["id"])
            dc = int(ent.get("document_count") or 0)
            mc = int(ent.get("mention_count") or 0)
            quote = ""
            for mem in (ent.get("members") or []):
                if mem.get("quote"):
                    quote = str(mem["quote"])[:120]
                    break
            member_ids.append(ent["id"])
            member_objs.append({
                "entity_id": ent["id"],
                "name": ent.get("canonical_name") or str(raw),
                "document_count": dc,
                "mention_count": mc,
                "quote": quote,
            })
            df += dc
            support += mc
        if not member_ids:
            continue
        if df < effective_min_df:
            logger.info("induction: drop low-DF type %r (df=%d < %d)", type_name, df, effective_min_df)
            continue
        out.append(TypeCandidate(
            type_name=type_name,
            definition=(nt.get("definition") or "").strip(),
            examples=[str(x) for x in (nt.get("examples") or [])][:5],
            layer=(nt.get("layer") or "concept"),
            member_entity_ids=member_ids, members=member_objs,
            df=df, support=support,
        ))
    return out


def _format_entities_for_prompt(entities: list[dict[str, Any]]) -> str:
    """把确认实体列成喂 LLM 的紧凑文本：规范名 + 模型早先的类型建议 + 一句原文引用。"""
    lines: list[str] = []
    for e in entities:
        members = e.get("members") or []
        hints = sorted({m.get("proposed_type") for m in members if m.get("proposed_type")})
        quote = ""
        for m in members:
            if m.get("quote"):
                quote = str(m["quote"])[:120]
                break
        hint_str = f"（建议类型：{', '.join(hints)}）" if hints else ""
        quote_str = f" 例：{quote}" if quote else ""
        lines.append(f"- {e.get('canonical_name')}{hint_str}{quote_str}")
    return "\n".join(lines)


class OntologyInductor:
    """读人确认的 __untyped__ 实体，跑一次 LLM 归纳出 node_type 候选。"""

    stage_name = "ontology_induction"
    stage_version = "1"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8900",
        graph_store: "GraphStore | None" = None,
        ontology_store: "OntologyStore | None" = None,
        domain_id: str | None = None,
        knowledge_domain: str | None = None,
        min_df: int = _DEFAULT_MIN_DF,
    ) -> None:
        from knowledge_mining.mining.infra.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url)
        self._graph_store = graph_store
        self._ontology_store = ontology_store
        self._domain_id = domain_id
        self._knowledge_domain = knowledge_domain or domain_id
        self._min_df = min_df

    def induce(self) -> dict[str, int]:
        """归纳一轮：读确认实体 → LLM → 去噪 → 落 node_type 候选。返回计数 summary。

        无确认实体 / 实体太少 / LLM 不可用 → 安静跳过（返回 0 计数），不阻断主流程。
        """
        gstore = self._graph_store
        ostore = self._ontology_store
        if gstore is None or ostore is None or not self._domain_id:
            return {"entities": 0, "candidates": 0}

        entities = gstore.confirmed_untyped_entities(self._domain_id)
        if len(entities) < _MIN_ENTITIES_TO_INDUCE:
            logger.info("induction: only %d confirmed untyped entities; skip", len(entities))
            return {"entities": len(entities), "candidates": 0}

        existing_types = ""
        try:
            rows = ostore.active_node_types(self._domain_id)
            existing_types = ", ".join(sorted(r["name"] for r in rows)) if rows else ""
        except Exception:
            logger.warning("active_node_types lookup failed during induction", exc_info=True)

        task_id = self._client.submit_task(
            template_key="mining-ontology-induction",
            input={
                "untyped_entities": _format_entities_for_prompt(entities),
                "existing_types": existing_types,
            },
            knowledge_domain=self._knowledge_domain,
            pipeline_stage="ontology_induction",
            expected_output_type="json_object",
        )
        if not task_id:
            logger.warning("induction: LLM submit failed; no candidates produced")
            return {"entities": len(entities), "candidates": 0}

        items = self._client.poll_result(task_id)
        llm_result = items[0] if items and isinstance(items[0], dict) else {}

        candidates = _build_type_candidates(entities, llm_result, min_df=self._min_df)
        for c in candidates:
            ostore.upsert_candidate(
                self._domain_id, kind="node_type", proposed_name=c.type_name,
                payload={
                    "definition": c.definition, "examples": c.examples,
                    "layer": c.layer, "members": c.members,
                    "member_entity_ids": c.member_entity_ids,
                    "df": c.df, "support": c.support,
                },
                source="global_induction", score=float(c.df),
                layer=c.layer,
            )
        logger.info("induction done for %s: %d entities → %d type candidates",
                    self._domain_id, len(entities), len(candidates))
        return {"entities": len(entities), "candidates": len(candidates)}
