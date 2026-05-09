"""Deterministic evidence sufficiency evaluation — no I/O, no LLM calls.

Algorithm extracted from SKILL.md lines 209-275.
"""

from __future__ import annotations

from mcp_server.schemas import (
    EvidenceAssessment,
    ItemSummary,
)

# --- intent → followup question templates ---

_INTENT_FOLLOWUPS: dict[str, list[str]] = {
    "concept_lookup": [
        "你更关心概念解释，还是具体的配置或操作步骤？",
        "这个问题是针对哪个产品或网元？",
        "这是学习性咨询，还是现网操作前的判断？",
    ],
    "config_help": [
        "这是针对哪个产品版本和网元？",
        "你要的是配置步骤，还是参数含义说明？",
        "有没有现网操作风险方面的顾虑？",
    ],
    "troubleshooting": [
        "你遇到的具体故障现象是什么？",
        "这是针对哪个产品、哪个网元？",
        "你要的是原因分析，还是一套可执行的排查步骤？",
    ],
    "comparison": [
        "你要对比的是哪两个（或多个）对象？",
        "对比维度是功能、性能、还是适用场景？",
        "有没有特定的版本或场景约束？",
    ],
    "procedure": [
        "你要的是完整的操作步骤，还是某个环节的细节？",
        "这是针对哪个产品和版本？",
        "操作完成后需要验证吗？",
    ],
    "parameter_inquiry": [
        "这个参数属于哪个产品、哪个网元、哪个功能？",
        "你关心的是参数含义、取值范围、还是默认值？",
        "是否有现网修改的计划？",
    ],
}

_DEFAULT_FOLLOWUPS = [
    "你这里更关心概念解释，还是现网配置步骤？",
    "这个问题是针对 SMF、UPF，还是某个具体产品版本？",
    "你要的是原因分析，还是一套可执行的排查步骤？",
    "这是学习性咨询，还是现网变更前的判断？",
]


def evaluate_evidence(
    items_summary: list[ItemSummary],
    intent: str,
    query: str,
) -> EvidenceAssessment:
    """Pure-function evidence evaluation based on SKILL.md rules."""
    if not items_summary:
        return EvidenceAssessment(
            evidence_sufficiency="insufficient",
            recommended_action="ask_followup",
            reasoning="无检索结果，无法形成证据支撑。",
            coverage_gaps=["无任何证据"],
            followup_questions=_get_followups(intent),
        )

    # --- count by evidence_role ---
    direct_answer = 0
    support = 0
    contrast = 0
    background = 0
    missing = 0

    for item in items_summary:
        role = item.evidence_role.lower().strip()
        if role == "direct_answer":
            direct_answer += 1
        elif role == "support":
            support += 1
        elif role == "contrast":
            contrast += 1
        elif role == "background":
            background += 1
        elif role == "missing":
            missing += 1

    total = len(items_summary)
    has_background_only = (total > 0) and (direct_answer == 0) and (support == 0) and (contrast == 0)

    # --- decision logic (from SKILL.md) ---
    if direct_answer > 0 and support > 0:
        sufficiency = "sufficient"
        action = "answer_now"
        reasoning = f"有 {direct_answer} 条直接证据 + {support} 条支撑证据，证据充分。"
        gaps: list[str] = []
    elif direct_answer > 0 and support == 0:
        sufficiency = "partial"
        action = "answer_with_caution"
        reasoning = f"有 {direct_answer} 条直接证据但缺少支撑证据，回答需谨慎。"
        gaps = ["缺少支撑性证据（前提条件、参数、限制等）"]
    elif direct_answer == 0 and (support > 0 or contrast > 0):
        sufficiency = "partial"
        action = "answer_with_caution"
        roles_desc = []
        if support > 0:
            roles_desc.append(f"{support} 条支撑证据")
        if contrast > 0:
            roles_desc.append(f"{contrast} 条对比证据")
        reasoning = f"无直接答案证据，但有 {' + '.join(roles_desc)}，可做方向性判断。"
        gaps = ["缺少直接回答证据"]
    elif has_background_only:
        sufficiency = "insufficient"
        action = "ask_followup"
        reasoning = f"仅有 {background} 条背景证据，不足以支撑可靠结论。"
        gaps = ["仅有背景信息，缺少直接答案和支撑证据"]
    else:
        sufficiency = "insufficient"
        action = "ask_followup"
        reasoning = "证据不足以可靠支撑用户问题。"
        gaps = ["证据不充分"]

    return EvidenceAssessment(
        evidence_sufficiency=sufficiency,
        recommended_action=action,
        reasoning=reasoning,
        coverage_gaps=gaps,
        followup_questions=_get_followups(intent) if sufficiency != "sufficient" else [],
        direct_answer_count=direct_answer,
        support_count=support,
        has_background_only=has_background_only,
    )


def _get_followups(intent: str) -> list[str]:
    """Return followup question templates for the given intent."""
    key = intent.lower().strip()
    return _INTENT_FOLLOWUPS.get(key, _DEFAULT_FOLLOWUPS)
