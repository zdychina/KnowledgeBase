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


def build_templates_from_profile(profile: DomainProfile) -> list[dict[str, Any]]:
    """Build LLM template list from a DomainProfile.

    JSON Schema entity type enum is injected dynamically from profile.entity_types.
    """
    templates: list[dict[str, Any]] = []

    for tpl in profile.llm_templates:
        tpl_copy = dict(tpl)

        # Dynamically inject entity type enum into segment-understanding schema
        if tpl_copy.get("template_key") == "mining-segment-understanding":
            schema_str = tpl_copy.get("output_schema_json", "")
            if schema_str and profile.entity_types:
                try:
                    schema = json.loads(schema_str)
                    entity_items = schema.get("properties", {}).get("entities", {}).get("items", {})
                    type_prop = entity_items.get("properties", {}).get("type", {})
                    if "enum" not in type_prop:
                        type_prop["enum"] = sorted(profile.entity_types)
                        entity_items["properties"]["type"] = type_prop
                        schema["properties"]["entities"]["items"] = entity_items
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
