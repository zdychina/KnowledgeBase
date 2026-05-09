"""FastMCP server — two tools, instructions carry full usage guide."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from mcp_server import __version__
from mcp_server.client import health_check as _health_check
from mcp_server.client import search_knowledge as _search_knowledge
from mcp_server.schemas import (
    EntityRef,
    HealthResult,
    SearchInput,
)

mcp = FastMCP(
    "cloud-core-knowledge",
    instructions="""\
你是云核心网知识证据底座。

## 何时使用
当用户问云核心网相关的概念、网元、接口、协议、参数、配置、故障、对比分析等问题时调用。
纯翻译润色、与云核心网无关的问题不需要调用。

## 调用流程
1. health_check() — 检查知识库是否可用。不可用时不要编造知识。
2. search_knowledge(query) — 检索知识库，返回证据包。

## 如何理解证据包
返回的 items 中每条证据有 evidence_role 字段：
- direct_answer：最接近主答案的证据，优先信任
- support：支撑性证据（前置条件、参数、限制、步骤）
- contrast：对比性证据（差异、区分、比较）
- background：背景信息，不能单独支撑操作类结论
- missing：相关但不足以支撑答案

判断证据是否充分时看四件事：
- 相关性：证据是否真在回答用户问题
- 覆盖度：是否覆盖了用户关心的核心点
- 条件完整性：产品、网元、场景、版本、前提是否清楚
- 风险等级：操作类问题比概念解释类要求更严格

## 回答行为
- 证据充分 → 直接结论 + 依据 + 前提限制
- 证据部分 → 保守结论 + 最强证据 + 缺失点 + 用户补什么能提高置信度
- 证据不足 → 追问用户缩小答案空间（问产品/网元/版本/场景/目标），不瞎编

## 回答时必须区分三层内容
1. 证据直接支持的内容
2. 基于证据做出的推断
3. 当前还不确定或缺失的部分

## 推理护栏
- 不要编造命令、参数、约束、依赖、步骤
- 不要默认脑补产品、版本、网元、场景
- 不要把背景材料说成确定结论
- 不要在证据不支撑时宣称因果关系
- 如果不同证据冲突，要把冲突显式说出来
""",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "9000")),
)


# ── Tools ────────────────────────────────────────────────────────────────


# health_check 暂不对外暴露，内部可通过 _health_check() 调用
# @mcp.tool()
# def health_check() -> HealthResult:
#     """检查知识库是否可用。不可用时不要编造知识，告知用户当前无法查询。"""
#     return _health_check()


@mcp.tool()
def search_knowledge(
    query: str,
    domain: str = "cloud_core_network",
    scope: dict | None = None,
    entities: list[dict] | None = None,
    debug: bool = False,
) -> dict:
    """检索云核心网知识库，返回证据包。输入用户问题即可。

    何时使用：用户问云核心网相关的概念、网元、接口、协议、参数、配置、故障、对比分析等问题时调用。纯翻译润色、与云核心网无关的问题不需要调用。

    如何理解证据包：
    返回的 items 中每条证据有 evidence_role 字段：
    - direct_answer：最接近主答案的证据，优先信任
    - support：支撑性证据（前置条件、参数、限制、步骤）
    - contrast：对比性证据（差异、区分、比较）
    - background：背景信息，不能单独支撑操作类结论
    - missing：相关但不足以支撑答案

    判断证据是否充分时看四件事：
    - 相关性：证据是否真在回答用户问题
    - 覆盖度：是否覆盖了用户关心的核心点
    - 条件完整性：产品、网元、场景、版本、前提是否清楚
    - 风险等级：操作类问题比概念解释类要求更严格

    回答行为：
    - 证据充分 → 直接结论 + 依据 + 前提限制
    - 证据部分 → 保守结论 + 最强证据 + 缺失点 + 用户补什么能提高置信度
    - 证据不足 → 追问用户缩小答案空间（问产品/网元/版本/场景/目标），不瞎编

    回答时必须区分三层内容：
    1. 证据直接支持的内容
    2. 基于证据做出的推断
    3. 当前还不确定或缺失的部分

    推理护栏：
    - 不要编造命令、参数、约束、依赖、步骤
    - 不要默认脑补产品、版本、网元、场景
    - 不要把背景材料说成确定结论
    - 不要在证据不支撑时宣称因果关系
    - 如果不同证据冲突，要把冲突显式说出来

    Args:
        query: 用户原问题
        domain: 知识域，默认 cloud_core_network
        scope: 产品/网元等约束，如 {"products":["UDG"],"network_elements":["SMF"]}
        entities: 已识别实体列表，每个元素含 name, type
        debug: 是否返回检索过程诊断信息
    """
    entity_refs = [EntityRef(**e) for e in entities] if entities else None

    inp = SearchInput(
        query=query,
        domain=domain,
        scope=scope,
        entities=entity_refs,
        debug=debug,
    )
    return _search_knowledge(inp)
