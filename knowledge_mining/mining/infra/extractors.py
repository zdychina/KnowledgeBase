"""Pluggable content understanding interfaces for v1.1 Mining.

Provides lightweight rule-based implementations for semantic_role
and entity_refs extraction. Future: replace with LLM-based classifiers.
"""
from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_mining.mining.infra.domain_pack import DomainProfile


# --- Lightweight rule-based implementations (profile-driven) ---

class RuleBasedEntityExtractor:
    """Profile-driven entity extractor using regex rules from DomainProfile."""

    def __init__(self, profile: DomainProfile | None = None) -> None:
        if profile is None:
            from knowledge_mining.mining.infra.domain_pack import get_default_profile
            profile = get_default_profile()
        self._profile = profile
        self._rules = profile.extractor_rules

        # Load extra domain-specific config from the YAML
        self._parameter_column_names: list[str] = []
        self._section_title_cmd_pattern: re.Pattern | None = None
        self._load_extra_config(profile)

    def _load_extra_config(self, profile: DomainProfile) -> None:
        """Load parameter_column_names and section_title_command_pattern from raw YAML data."""
        from pathlib import Path
        import yaml

        packs_root = Path(__file__).resolve().parent.parent.parent / "domain_packs"
        yaml_path = packs_root / profile.domain_id / "domain.yaml"
        if yaml_path.exists():
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._parameter_column_names = data.get("parameter_column_names", [])
            pattern_str = data.get("section_title_command_pattern", "")
            if pattern_str:
                self._section_title_cmd_pattern = re.compile(pattern_str)

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()

        for rule in self._rules:
            compiled = rule.compiled
            if not compiled:
                continue
            for match in compiled.finditer(text):
                # Handle multi-group patterns (e.g. command pattern with 2 groups)
                if rule.groups and len(match.groups()) >= 2:
                    entity_name = f"{match.group(1)} {match.group(2)}"
                else:
                    entity_name = match.group(1) if match.lastindex else match.group(0)

                key = f"{rule.entity_type}:{entity_name}"
                if key not in seen:
                    seen.add(key)
                    refs.append({"type": rule.entity_type, "name": entity_name})

        # Table-based parameter extraction (structural, not regex)
        structure = context.get("structure") if context else None
        if structure and isinstance(structure, dict) and self._parameter_column_names:
            columns = structure.get("columns", [])
            if any(pc in c for c in columns for pc in self._parameter_column_names):
                rows = structure.get("rows", [])
                for row in rows:
                    for col_name in columns:
                        for pc in self._parameter_column_names:
                            if pc in col_name:
                                param_name = row.get(col_name)
                                if param_name:
                                    key = f"parameter:{param_name}"
                                    if key not in seen:
                                        seen.add(key)
                                        refs.append({"type": "parameter", "name": param_name})

        return refs

    def extract_from_section_title(self, section_title: str) -> dict[str, str] | None:
        """Extract entity from section title (e.g. command names)."""
        if not self._section_title_cmd_pattern or not section_title:
            return None
        match = self._section_title_cmd_pattern.match(section_title.upper())
        if match and len(match.groups()) >= 2:
            return {"type": "command", "name": f"{match.group(1)} {match.group(2)}"}
        return None


class NoOpEntityExtractor:
    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        return []


class DefaultRoleClassifier:
    """Profile-driven role classifier using keyword rules from DomainProfile."""

    def __init__(self, profile: DomainProfile | None = None) -> None:
        if profile is None:
            from knowledge_mining.mining.infra.domain_pack import get_default_profile
            profile = get_default_profile()
        self._rules = profile.role_keyword_rules
        self._parameter_column_names: list[str] = []
        self._load_extra_config(profile)

    def _load_extra_config(self, profile: DomainProfile) -> None:
        from pathlib import Path
        import yaml

        packs_root = Path(__file__).resolve().parent.parent.parent / "domain_packs"
        yaml_path = packs_root / profile.domain_id / "domain.yaml"
        if yaml_path.exists():
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._parameter_column_names = data.get("parameter_column_names", [])

    def classify(
        self,
        text: str,
        section_title: str | None,
        block_type: str,
        context: dict[str, Any],
    ) -> str:
        title = (section_title or "").lower()

        for keywords, role in self._rules:
            if any(kw.lower() in title for kw in keywords):
                return role

        if block_type == "table":
            structure = context.get("structure") if context else None
            if structure and isinstance(structure, dict):
                columns = structure.get("columns", [])
                if columns and any(pc in c for c in columns for pc in self._parameter_column_names):
                    return "parameter"
            return "note"

        if block_type == "code":
            return "example"

        return "unknown"
