"""Domain Pack Reader — Serving-specific configuration from Mining domain packs.

Reads domain.yaml and provides Serving-specific configuration:
- route_policy: intent -> route weight mapping
- entity_types / strong_entity_types
- eval_questions
- extractor_rules (regex)

Falls back to built-in defaults when no domain pack is loaded.
Does NOT modify Mining's domain_pack.py.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DOMAIN_PACKS_DIR = Path(
    os.environ.get(
        "DOMAIN_PACKS_DIR",
        str(Path(__file__).resolve().parents[2] / "knowledge_mining" / "domain_packs"),
    )
)

# Built-in default route policy
_DEFAULT_ROUTE_POLICY: dict[str, dict[str, dict[str, float]]] = {
    "default": {
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 1.0, "top_k": 30},
        "dense_vector": {"weight": 0.8, "top_k": 50},
    },
    "command_usage": {
        "entity_exact": {"weight": 1.4, "top_k": 20},
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "dense_vector": {"weight": 0.5, "top_k": 30},
    },
    "concept_lookup": {
        "dense_vector": {"weight": 1.2, "top_k": 50},
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 0.6, "top_k": 20},
    },
    "troubleshooting": {
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 1.2, "top_k": 30},
        "dense_vector": {"weight": 0.6, "top_k": 30},
    },
    "comparison": {
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "dense_vector": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 1.0, "top_k": 30},
    },
}


@dataclass(frozen=True)
class ServingDomainProfile:
    """Serving-specific configuration extracted from a domain pack."""
    domain_id: str
    entity_types: frozenset[str] = frozenset()
    strong_entity_types: frozenset[str] = frozenset()
    route_policy: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    extractor_rules: tuple[dict[str, Any], ...] = ()
    eval_questions: tuple[dict[str, Any], ...] = ()
    query_understanding: dict[str, Any] = field(default_factory=dict)


def load_serving_profile(
    domain_id: str | None = None,
    packs_root: Path | None = None,
) -> ServingDomainProfile:
    """Load a ServingDomainProfile from a domain pack YAML.

    Returns built-in defaults when domain_id is None or pack not found.
    """
    if not domain_id:
        return _build_default_profile()

    root = packs_root or _DOMAIN_PACKS_DIR
    yaml_path = root / domain_id / "domain.yaml"

    if not yaml_path.exists():
        logger.warning("Domain pack not found: %s, using defaults", yaml_path)
        return _build_default_profile(domain_id)

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return ServingDomainProfile(
        domain_id=domain_id,
        entity_types=frozenset(data.get("entity_types", [])),
        strong_entity_types=frozenset(data.get("strong_entity_types", [])),
        route_policy=_parse_route_policy(data.get("serving", {})),
        extractor_rules=tuple(data.get("extractor_rules", [])),
        eval_questions=tuple(data.get("eval_questions", [])),
        query_understanding=data.get("serving", {}).get("query_understanding", {}),
    )


def _parse_route_policy(
    serving_section: dict[str, Any],
) -> dict[str, dict[str, dict[str, float]]]:
    """Parse serving.route_policy from domain.yaml, falling back to defaults."""
    policy = serving_section.get("route_policy", None)
    if not policy:
        return _DEFAULT_ROUTE_POLICY

    # Merge with defaults (user policy overrides defaults)
    merged = {**_DEFAULT_ROUTE_POLICY, **policy}
    return merged


def _build_default_profile(
    domain_id: str = "default",
) -> ServingDomainProfile:
    return ServingDomainProfile(
        domain_id=domain_id,
        route_policy=_DEFAULT_ROUTE_POLICY,
    )


def get_route_policy(
    profile: ServingDomainProfile | None,
    intent: str,
) -> dict[str, dict[str, float]]:
    """Get route weights for a specific intent from the profile."""
    if not profile:
        return _DEFAULT_ROUTE_POLICY.get(intent, _DEFAULT_ROUTE_POLICY["default"])
    return profile.route_policy.get(intent, profile.route_policy.get("default", _DEFAULT_ROUTE_POLICY["default"]))
