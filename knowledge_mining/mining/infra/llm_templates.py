"""LLM template definitions for Mining — profile-driven.

Templates are loaded from DomainProfile.llm_templates.
The entity type enum in JSON Schema is built dynamically from profile.entity_types.

Backward-compatible: importing TEMPLATES loads cloud_core_network by default.
"""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile


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

    for tpl in profile.llm_templates:
        tpl_copy = dict(tpl)

        # Inject knowledge_domain for llm_service domain-scoped template resolution
        if knowledge_domain and "knowledge_domain" not in tpl_copy:
            tpl_copy["knowledge_domain"] = knowledge_domain

        # Dynamically inject semantic_role enum into segment-understanding schema.
        # 实体类型 enum 不再在此注入：实体抽取已拆到 mining-entity-extraction，
        # 其 entities[].type 故意不设 enum（双通道靠 prompt + 阶段内后置过滤约束），
        # 以免静态 enum 与运行期 active 本体类型漂移、堵死通道 B 发现新类型。
        if tpl_copy.get("template_key") == "mining-segment-understanding":
            schema_str = tpl_copy.get("output_schema_json", "")
            if schema_str and profile.semantic_roles:
                try:
                    schema = json.loads(schema_str)
                    role_prop = schema.get("properties", {}).get("semantic_role", {})
                    if "enum" not in role_prop:
                        role_prop["enum"] = sorted(profile.semantic_roles)
                        schema["properties"]["semantic_role"] = role_prop
                        tpl_copy["output_schema_json"] = json.dumps(schema)
                except (json.JSONDecodeError, KeyError):
                    pass

        templates.append(tpl_copy)

    return templates


# Backward compatibility: default templates loaded from cloud_core_network pack
def _load_default_templates() -> list[dict[str, Any]]:
    from knowledge_mining.mining.infra.domain_pack import get_default_profile
    return build_templates_from_profile(get_default_profile())


TEMPLATES: list[dict[str, Any]] = _load_default_templates()
