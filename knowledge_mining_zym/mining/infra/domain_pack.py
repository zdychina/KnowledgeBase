"""Domain Pack: pluggable domain knowledge for the Mining pipeline.

A DomainProfile bundles all domain-specific knowledge:
- Entity types and strong entity types
- Regex extractors, role rules, heading role keywords
- LLM prompt templates
- Retrieval policy
- Eval questions

Loading a different domain pack swaps ALL domain knowledge without
changing any core mining code.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Base directory for domain packs (sibling of mining/)
_PACKS_ROOT = Path(__file__).resolve().parent.parent.parent / "domain_packs"


# ---------------------------------------------------------------------------
# Supporting dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExtractorRule:
    """A single regex-based extraction rule."""
    name: str
    pattern: str
    entity_type: str
    groups: tuple[dict[str, Any], ...] = ()

    # Compiled pattern (not serialized, built at load time)
    _compiled_pattern: Any = field(default=None, repr=False, compare=False)

    @property
    def compiled(self) -> Any:
        import re
        if self._compiled_pattern is None:
            return re.compile(self.pattern)
        return self._compiled_pattern


@dataclass(frozen=True)
class RetrievalPolicy:
    """Retrieval unit generation policy."""
    raw_text: str = "primary"
    generated_question: str = "auxiliary"
    entity_card: str = "strong_entities_only"
    table_row: str = "structured_tables"
    max_questions_per_segment: int = 2
    max_entity_cards_per_segment: int = 3


@dataclass(frozen=True)
class EvalQuestion:
    """A single eval question for retrieval quality assessment."""
    id: str
    question: str
    expected_entities: tuple[str, ...] = ()
    expected_evidence_contains: tuple[str, ...] = ()
    expected_semantic_role: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class DomainProfile:
    """Complete domain knowledge pack for the mining pipeline.

    Immutable: all collection fields are frozen/tuples.
    """
    domain_id: str
    display_name: str

    # Entity configuration
    entity_types: frozenset[str]
    strong_entity_types: frozenset[str]

    # Semantic role mapping: domain keywords -> core semantic_role
    role_keyword_rules: tuple[tuple[list[str], str], ...]

    # Heading role classification: domain keywords -> heading role
    heading_role_keywords: tuple[tuple[list[str], str], ...]

    # Rule-based extractors
    extractor_rules: tuple[ExtractorRule, ...]

    # LLM templates (list of dicts, replaces hardcoded llm_templates.py)
    llm_templates: tuple[dict[str, Any], ...]

    # Retrieval policy
    retrieval_policy: RetrievalPolicy

    # Eval questions
    eval_questions: tuple[EvalQuestion, ...]


# ---------------------------------------------------------------------------
# YAML -> DomainProfile converter
# ---------------------------------------------------------------------------

def _parse_extractor_rules(raw: list[dict[str, Any]]) -> tuple[ExtractorRule, ...]:
    import re as _re
    rules = []
    for r in raw:
        groups = tuple(r.get("groups", []))
        # Pre-compile pattern
        compiled = _re.compile(r["pattern"])
        rules.append(ExtractorRule(
            name=r["name"],
            pattern=r["pattern"],
            entity_type=r["entity_type"],
            groups=groups,
            _compiled_pattern=compiled,
        ))
    return tuple(rules)


def _parse_role_keyword_rules(
    raw: list[dict[str, Any]],
) -> tuple[tuple[list[str], str], ...]:
    return tuple(
        (item["keywords"], item["role"])
        for item in raw
    )


def _parse_retrieval_policy(raw: dict[str, Any]) -> RetrievalPolicy:
    return RetrievalPolicy(
        raw_text=raw.get("raw_text", "primary"),
        generated_question=raw.get("generated_question", "auxiliary"),
        entity_card=raw.get("entity_card", "strong_entities_only"),
        table_row=raw.get("table_row", "structured_tables"),
        max_questions_per_segment=raw.get("max_questions_per_segment", 2),
        max_entity_cards_per_segment=raw.get("max_entity_cards_per_segment", 3),
    )


def _parse_eval_questions(raw: list[dict[str, Any]]) -> tuple[EvalQuestion, ...]:
    return tuple(
        EvalQuestion(
            id=q["id"],
            question=q["question"],
            expected_entities=tuple(q.get("expected_entities", [])),
            expected_evidence_contains=tuple(q.get("expected_evidence_contains", [])),
            expected_semantic_role=q.get("expected_semantic_role"),
            notes=q.get("notes", ""),
        )
        for q in raw
    )


def _parse_domain_yaml(data: dict[str, Any]) -> DomainProfile:
    """Parse a domain.yaml dict into a DomainProfile."""
    return DomainProfile(
        domain_id=data["domain_id"],
        display_name=data["display_name"],
        entity_types=frozenset(data.get("entity_types", [])),
        strong_entity_types=frozenset(data.get("strong_entity_types", [])),
        role_keyword_rules=_parse_role_keyword_rules(
            data.get("role_keyword_rules", []),
        ),
        heading_role_keywords=_parse_role_keyword_rules(
            data.get("heading_role_keywords", []),
        ),
        extractor_rules=_parse_extractor_rules(
            data.get("extractor_rules", []),
        ),
        llm_templates=tuple(data.get("llm_templates", [])),
        retrieval_policy=_parse_retrieval_policy(
            data.get("retrieval_policy", {}),
        ),
        eval_questions=_parse_eval_questions(
            data.get("eval_questions", []),
        ),
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_domain_pack(domain_id: str, *, packs_root: Path | None = None) -> DomainProfile:
    """Load a DomainProfile from a YAML directory.

    Args:
        domain_id: Domain pack directory name (e.g. "cloud_core_network").
        packs_root: Override root directory (for testing).

    Returns:
        Parsed DomainProfile.

    Raises:
        FileNotFoundError: If domain pack directory or domain.yaml not found.
    """
    root = packs_root or _PACKS_ROOT
    yaml_path = root / domain_id / "domain.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Domain pack not found: {yaml_path} "
            f"(domain_id={domain_id!r}, packs_root={root})"
        )

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    profile = _parse_domain_yaml(data)
    logger.info("Loaded domain pack: %s (%s)", profile.display_name, profile.domain_id)
    return profile


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def get_default_profile() -> DomainProfile:
    """Load the default (cloud_core_network) profile.

    Provides backward compatibility for code that hasn't been migrated
    to explicitly pass a profile.
    """
    return load_domain_pack("cloud_core_network")


# Deprecated: used by models.STRONG_ENTITY_TYPES alias
def _deprecated_strong_entity_types() -> frozenset[str]:
    warnings.warn(
        "models.STRONG_ENTITY_TYPES is deprecated; use DomainProfile.strong_entity_types",
        DeprecationWarning,
        stacklevel=3,
    )
    return get_default_profile().strong_entity_types
