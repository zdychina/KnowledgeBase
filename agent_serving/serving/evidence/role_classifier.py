"""EvidenceRoleClassifier — classifies items into evidence roles.

Rules:
- Entity exact match + high score → direct_answer
- Structural relation (same_section, next) → support
- Comparison intent + comparison keywords → contrast
- Graph expansion background → background
- No match → missing
"""
from __future__ import annotations

import logging

from agent_serving.serving.schemas.models import (
    ContextItem,
    QueryUnderstanding,
    RetrievalCandidate,
)

logger = logging.getLogger(__name__)

_ROLE_DIRECT_ANSWER = "direct_answer"
_ROLE_SUPPORT = "support"
_ROLE_CONTRAST = "contrast"
_ROLE_BACKGROUND = "background"
_ROLE_MISSING = "missing"

_DIRECT_ANSWER_THRESHOLD = 0.7
_CONTRAST_KEYWORDS = {"区别", "差异", "对比", "比较", "不同", "vs", "versus"}


class EvidenceRoleClassifier:
    """Classifies context items into evidence roles."""

    def classify(
        self,
        candidate: RetrievalCandidate,
        understanding: QueryUnderstanding,
    ) -> str:
        """Classify a single candidate into an evidence role."""
        # Direct answer: entity match + high score
        if self._is_entity_match(candidate, understanding):
            if candidate.score >= _DIRECT_ANSWER_THRESHOLD:
                return _ROLE_DIRECT_ANSWER

        # Contrast: comparison intent + contrast content
        if understanding.intent in ("comparative", "comparison"):
            if self._has_contrast_keywords(candidate):
                return _ROLE_CONTRAST

        # Support: structural relation
        relation = candidate.metadata.get("expansion_relation_type", "")
        if relation in ("same_section", "next", "same_parent_section"):
            return _ROLE_SUPPORT

        # Background: graph expansion
        source = candidate.source
        if source == "graph_expansion":
            return _ROLE_BACKGROUND

        # Default: missing
        return _ROLE_MISSING

    def classify_item(
        self,
        item: ContextItem,
        understanding: QueryUnderstanding,
    ) -> str:
        """Classify a ContextItem (used after assembly)."""
        # Direct answer: seed item with high score
        if item.role == "seed" and item.score >= _DIRECT_ANSWER_THRESHOLD:
            return _ROLE_DIRECT_ANSWER

        # Support: context/support role items
        if item.role in ("context", "support"):
            if item.relation_to_seed in ("same_section", "next", "same_parent_section"):
                return _ROLE_SUPPORT
            return _ROLE_BACKGROUND

        # Contrast: comparison intent
        if understanding.intent in ("comparative", "comparison"):
            if self._has_contrast_keywords_in_text(item.text):
                return _ROLE_CONTRAST

        return _ROLE_MISSING

    def _is_entity_match(
        self,
        candidate: RetrievalCandidate,
        understanding: QueryUnderstanding,
    ) -> bool:
        """Check if candidate matches any query entity."""
        import json
        entity_names = {e.name.lower() for e in understanding.entities}
        if not entity_names:
            return False

        # Check entity_refs_json
        refs_str = candidate.metadata.get("entity_refs_json", "[]")
        try:
            refs = json.loads(refs_str)
            for ref in refs:
                if ref.get("normalized_name", "").lower() in entity_names:
                    return True
        except (json.JSONDecodeError, TypeError):
            pass

        # Check source
        if candidate.source == "entity_exact":
            return True

        return False

    def _has_contrast_keywords(self, candidate: RetrievalCandidate) -> bool:
        text = candidate.metadata.get("text", "").lower()
        return any(kw in text for kw in _CONTRAST_KEYWORDS)

    def _has_contrast_keywords_in_text(self, text: str) -> bool:
        return any(kw in text.lower() for kw in _CONTRAST_KEYWORDS)
