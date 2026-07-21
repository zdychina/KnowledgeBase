"""LLM template definitions for Mining — profile-driven.

Templates are loaded from DomainProfile.llm_templates.
The entity type enum in JSON Schema is built dynamically from profile.entity_types.

Callers must provide a domain profile or domain ID explicitly. Importing this
module never loads a scenario pack.
"""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile


_TEMPLATE_KEY_ALIASES = {
    "mining-question-generation": "mining-question-gen",
}


def _compat_entity_template(
    entities_schema: dict[str, Any], knowledge_domain: str
) -> dict[str, Any]:
    """Adapt a legacy combined understanding schema to the split entity stage."""
    return {
        "template_key": "mining-entity-extraction",
        "template_version": "compat-1",
        "purpose": "兼容旧 Domain Pack 的独立实体抽取",
        "system_prompt": (
            "你是领域知识实体抽取助手。只依据给定文本抽取实体；优先使用 allowed_types。"
            "无法可靠归入清单的概念放入 out_of_schema，不要臆造事实。"
        ),
        "user_prompt_template": (
            "文本：$text\n标题：$section_title\n块类型：$block_type\n"
            "允许的实体类型：$allowed_types\n"
            "输出 entities 与 out_of_schema 两个数组。"
        ),
        "expected_output_type": "json_object",
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "entities": entities_schema,
                "out_of_schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "proposed_type": {"type": "string"},
                            "reason": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["entities", "out_of_schema"],
            "additionalProperties": False,
        }, ensure_ascii=False),
        "knowledge_domain": knowledge_domain,
    }


def build_templates_from_profile(
    profile: DomainProfile,
    *,
    domain_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build LLM template list from a DomainProfile.

    JSON Schema entity type enum is injected dynamically from profile.entity_types.
    If domain_id is provided, it is injected as knowledge_domain for domain-scoped
    template resolution in llm_service.
    """
    knowledge_domain = domain_id or profile.domain_id
    templates: list[dict[str, Any]] = []
    combined_entities_schema: dict[str, Any] | None = None
    template_keys = {str(tpl.get("template_key", "")) for tpl in profile.llm_templates}

    for tpl in profile.llm_templates:
        tpl_copy = dict(tpl)
        template_key = str(tpl_copy.get("template_key", ""))
        tpl_copy["template_key"] = _TEMPLATE_KEY_ALIASES.get(
            template_key, template_key
        )

        # The selected domain is authoritative even when a shared or stale
        # scenario pack contains a different template scope.
        tpl_copy["knowledge_domain"] = knowledge_domain

        # Dynamically inject semantic_role enum into segment-understanding schema.
        # 实体类型 enum 不再在此注入：实体抽取已拆到 mining-entity-extraction，
        # 其 entities[].type 故意不设 enum（双通道靠 prompt + 阶段内后置过滤约束），
        # 以免静态 enum 与运行期 active 本体类型漂移、堵死通道 B 发现新类型。
        if tpl_copy.get("template_key") == "mining-segment-understanding":
            schema_str = tpl_copy.get("output_schema_json", "")
            if schema_str:
                try:
                    schema = json.loads(schema_str)
                    properties = schema.get("properties", {})
                    legacy_entities = properties.pop("entities", None)
                    if isinstance(legacy_entities, dict):
                        combined_entities_schema = legacy_entities
                        required = schema.get("required")
                        if isinstance(required, list):
                            schema["required"] = [
                                item for item in required if item != "entities"
                            ]
                    role_prop = properties.get("semantic_role", {})
                    if profile.semantic_roles and "enum" not in role_prop:
                        role_prop["enum"] = sorted(profile.semantic_roles)
                        properties["semantic_role"] = role_prop
                    tpl_copy["output_schema_json"] = json.dumps(
                        schema, ensure_ascii=False
                    )
                except (json.JSONDecodeError, KeyError):
                    pass

        templates.append(tpl_copy)

    if (
        "mining-entity-extraction" not in template_keys
        and combined_entities_schema is not None
    ):
        templates.append(
            _compat_entity_template(combined_entities_schema, knowledge_domain)
        )

    return templates


def load_templates(domain_id: str) -> list[dict[str, Any]]:
    """Load and build LLM templates for one explicit domain."""
    from knowledge_mining.mining.infra.domain_pack import load_domain_pack

    profile = load_domain_pack(domain_id)
    return build_templates_from_profile(profile, domain_id=domain_id)
