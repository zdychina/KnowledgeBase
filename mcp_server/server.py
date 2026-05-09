"""FastMCP server — tools, resources, prompts."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from mcp_server import __version__
from mcp_server.client import health_check as _health_check
from mcp_server.client import search_knowledge as _search_knowledge
from mcp_server.evidence_rules import evaluate_evidence as _evaluate_evidence
from mcp_server.prompts import SEMANTIC_RULES, ANSWER_FRAMEWORK
from mcp_server.schemas import (
    EntityRef,
    EvaluateInput,
    EvidenceAssessment,
    HealthResult,
    ItemSummary,
    SearchInput,
    SearchResult,
)

mcp = FastMCP(
    "cloud-core-knowledge",
    instructions=(
        "云核心网知识证据底座 MCP Server。"
        "使用原则：先调用 health_check 确认后端可用，再调用 search_knowledge 获取证据，"
        "然后调用 evaluate_evidence 评估充分性，最后基于评估结果回答用户。"
        "核心原则：先取证再回答；证据不足先追问；推理必须受证据约束，不能瞎编。"
    ),
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "9000")),
)


# ── Tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def health_check() -> HealthResult:
    """检查 serving 后端是否可用。返回可用状态、版本号和延迟。"""
    return _health_check()


@mcp.tool()
def search_knowledge(
    query: str,
    domain: str = "cloud_core_network",
    scope: dict | None = None,
    entities: list[dict] | None = None,
    debug: bool = False,
    max_text_length: int = 1000,
) -> SearchResult:
    """检索云核心网知识库，返回结构化证据包。

    Args:
        query: 用户原问题
        domain: 知识域，默认 cloud_core_network
        scope: 产品/网元等约束，如 {"products":["UDG"],"network_elements":["SMF"]}
        entities: 已识别实体列表，每个元素含 name, type
        debug: 是否返回检索过程诊断信息
        max_text_length: 每个证据条目的文本截断长度，0 表示不截断
    """
    entity_refs = [EntityRef(**e) for e in entities] if entities else None

    inp = SearchInput(
        query=query,
        domain=domain,
        scope=scope,
        entities=entity_refs,
        debug=debug,
        max_text_length=max_text_length,
    )
    return _search_knowledge(inp)


@mcp.tool()
def evaluate_evidence(
    items_summary: list[dict],
    intent: str = "",
    query: str = "",
) -> EvidenceAssessment:
    """基于证据语义规则评估证据充分性（纯规则，不调 LLM）。

    Args:
        items_summary: 从 search_knowledge 返回的 items 中提取的摘要列表，
                       每个元素含 evidence_role, score, semantic_role
        intent: 检索到的 query intent
        query: 原始问题（用于生成更精准的追问建议）
    """
    summaries = [ItemSummary(**s) for s in items_summary]
    return _evaluate_evidence(summaries, intent, query)


# ── Resources ────────────────────────────────────────────────────────────


@mcp.resource("evidence://semantic-rules")
def semantic_rules() -> str:
    """证据语义规则：direct_answer / support / contrast / background / missing 的定义和优先信任规则。"""
    return SEMANTIC_RULES


@mcp.resource("evidence://answer-framework")
def answer_framework() -> str:
    """推荐回答框架：answer_now / answer_with_caution / ask_followup / delegate 各场景的回答骨架。"""
    return ANSWER_FRAMEWORK


# ── Prompts ──────────────────────────────────────────────────────────────


@mcp.prompt()
def evidence_guided_answer(query: str, evidence: str) -> str:
    """给 Agent 的回答引导模板。基于证据回答用户问题，三层内容区分 + 推理护栏。

    Args:
        query: 用户原始问题
        evidence: search_knowledge 返回的 JSON 证据包
    """
    return f"""\
请基于以下证据回答用户问题。必须遵守规则。

## 用户问题
{query}

## 证据包
{evidence}

## 回答要求

### 三层内容区分
1. **证据直接支持的内容** — 明确标注"依据证据"
2. **基于证据的推断** — 明确标注"推断"
3. **不确定或缺失的部分** — 明确标注"待确认"

### 推理护栏
- 不要编造命令、参数、约束、依赖、步骤
- 不要默认脑补产品、版本、网元、场景
- 不要把背景材料说成确定结论
- 不要在证据不支撑时宣称因果关系
- 如果不同证据冲突，要把冲突显式说出来

### 概率性表达（当证据不足以确定时）
- "从当前证据看，更可能是......"
- "现有证据支持到这里，但还不能确定......"

### 回答结构（推荐）
1. 结论或当前判断
2. 依据
3. 前提/限制
4. 不确定点
5. 建议下一步
"""
