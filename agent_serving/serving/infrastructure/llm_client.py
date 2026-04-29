"""Async LLM client for Serving — wraps Mining's sync LlmClient.

Provides:
- Async execute/register_template via asyncio.to_thread
- Serving template registration at init (idempotent)
- Health check for availability

Fallback: all methods return None/False when LLM service is unreachable,
so the pipeline degrades gracefully to rule-based paths.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from knowledge_mining.mining.llm_client import LlmClient

logger = logging.getLogger(__name__)

# ── Serving LLM templates ──────────────────────────────────────────────

SERVING_TEMPLATES: list[dict[str, Any]] = [
    {
        "template_key": "serving-query-understanding",
        "template_version": "1",
        "purpose": "理解用户查询，提取意图、实体、关键词和证据需求",
        "system_prompt": (
            "你是一个知识库查询理解系统。你的任务是分析用户的查询，提取以下信息：\n"
            "1. 意图分类（factoid/conceptual/procedural/comparative/troubleshooting/navigational/general）\n"
            "2. 命名实体（网络元素如SMF/AMF/UPF、命令如ADD/MOD/DEL、产品名如UDG/UNC/CloudCore）\n"
            "3. 关键词（去除停用词后的核心词）\n"
            "4. 证据需求（需要什么类型的证据来回答）\n\n"
            "输出严格的 JSON 格式，不要添加任何其他文本。"
        ),
        "user_prompt_template": "分析以下查询：\n\n$query",
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "factoid", "conceptual", "procedural",
                        "comparative", "troubleshooting", "navigational", "general",
                    ],
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "name": {"type": "string"},
                            "normalized_name": {"type": "string"},
                        },
                        "required": ["type", "name"],
                    },
                },
                "keywords": {"type": "array", "items": {"type": "string"}},
                "scope": {
                    "type": "object",
                    "properties": {
                        "products": {"type": "array", "items": {"type": "string"}},
                        "network_elements": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "evidence_need": {
                    "type": "object",
                    "properties": {
                        "preferred_roles": {"type": "array", "items": {"type": "string"}},
                        "preferred_blocks": {"type": "array", "items": {"type": "string"}},
                        "needs_comparison": {"type": "boolean"},
                        "needs_citation": {"type": "boolean"},
                    },
                },
                "sub_queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "intent": {"type": "string"},
                        },
                    },
                },
                "ambiguities": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["intent", "entities", "keywords"],
        }),
    },
    {
        "template_key": "serving-reranker",
        "template_version": "1",
        "purpose": "对检索结果进行 LLM 相关性重排序",
        "system_prompt": (
            "你是一个文档相关性评估系统。你的任务是根据查询对候选文档进行相关性排序。\n"
            "对于每个候选文档，给出一个0-1之间的相关性分数。\n"
            "按相关性从高到低排列。\n"
            "输出严格的 JSON 格式，不要添加任何其他文本。"
        ),
        "user_prompt_template": (
            "查询：$query\n\n"
            "候选文档：\n$candidates\n\n"
            "请对以上 $count 个候选文档按相关性排序。"
        ),
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "ranking": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        },
                        "required": ["index", "score"],
                    },
                },
            },
            "required": ["ranking"],
        }),
    },
]


class ServingLlmClient:
    """Async LLM client for Serving pipeline.

    Wraps Mining's sync LlmClient with async methods via asyncio.to_thread.
    Registers serving templates on first use (idempotent).
    All methods return None/False on failure so the pipeline degrades gracefully.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8900",
        timeout: int = 60,
    ) -> None:
        self._sync = LlmClient(base_url=base_url, timeout=timeout)
        self._templates_registered = False

    async def ensure_templates(self) -> None:
        """Register serving templates with the LLM service (idempotent)."""
        if self._templates_registered:
            return
        for tpl in SERVING_TEMPLATES:
            ok = await asyncio.to_thread(self._sync.register_template, tpl)
            if ok:
                logger.info("Registered serving template: %s", tpl["template_key"])
            else:
                logger.warning("Failed to register template: %s", tpl["template_key"])
        self._templates_registered = True

    def is_available(self) -> bool:
        """Check if LLM service is reachable."""
        return self._sync.health_check()

    async def execute(self, **kwargs: Any) -> dict | None:
        """Async execute via LLM service.

        Keyword args are forwarded to LlmClient.execute():
          template_key, input, caller_domain, pipeline_stage, expected_output_type
        """
        await self.ensure_templates()
        return await asyncio.to_thread(self._sync.execute, **kwargs)

    def close(self) -> None:
        """Close the underlying sync client."""
        self._sync.close()
