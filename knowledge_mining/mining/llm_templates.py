"""LLM template definitions for Mining v1.2.

Templates must be pre-registered with llm_service before use.
"""
from __future__ import annotations

from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    {
        "template_key": "mining-question-gen",
        "template_version": "1",
        "purpose": "从段落内容生成假设性检索问题",
        "system_prompt": "你是通信网络知识库的检索优化助手。",
        "user_prompt_template": (
            "根据以下技术文档段落，生成 2-3 个用户可能提出的问题。\n\n"
            "段落标题：$title\n段落内容：$content\n\n"
            "输出 JSON 数组，每个元素包含 question 字段。"
        ),
        "expected_output_type": "json_array",
    },
]
