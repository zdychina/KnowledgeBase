"""Pluggable content understanding interfaces for M1 Mining.

M1 provides lightweight rule-based implementations for semantic_role
and entity_refs extraction. Future: replace with domain-specific
extractors, NER models, or LLM-based classifiers.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.models import CanonicalSegmentData, RawSegmentData


@runtime_checkable
class EntityExtractor(Protocol):
    """Extract entities from text. M1 default: lightweight rule-based."""

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        """Return list of entity refs like [{"type": "command", "name": "ADD APN"}]."""
        ...


@runtime_checkable
class RoleClassifier(Protocol):
    """Classify semantic role of a segment. M1 default: rule-based."""

    def classify(
        self,
        text: str,
        section_title: str | None,
        block_type: str,
        context: dict[str, Any],
    ) -> str:
        """Return semantic_role from the v0.5 enum."""
        ...


@runtime_checkable
class SegmentEnricher(Protocol):
    """Enrich canonical segment with summary/quality_score. M1 default: no-op."""

    def enrich(
        self,
        canonical: CanonicalSegmentData,
        sources: list[RawSegmentData],
    ) -> CanonicalSegmentData:
        """Return enriched canonical (may be same instance if no changes)."""
        ...


# --- Lightweight rule-based implementations ---

# Network element abbreviations commonly found in core network docs
_NF_PATTERN = re.compile(
    r"\b(SMF|UPF|AMF|PCF|UDM|UDR|AUSF|NRF|NSSF|BSF|CHF|SMSF|LMF|GMLC|NEF|SCF)"
    r"\b",
)

# Command patterns: ADD/SHOW/MOD/DEL/DSP/LST/REG/DEREG etc. followed by uppercase word(s)
_CMD_PATTERN = re.compile(
    r"\b(ADD|SHOW|MOD|DEL|DSP|LST|REG|DEREG|SET|GET|CFG|ACT|DEACT|CLR|PRT)"
    r"\s+([A-Z][A-Z0-9_]{1,20})",
)

# Section title keywords → semantic_role mapping
_ROLE_RULES: list[tuple[list[str], str]] = [
    (["参数", "参数说明", "参数标识"], "parameter"),
    (["使用实例", "命令格式", "示例", "配置示例"], "example"),
    (["操作步骤", "流程", "检查项", "前置检查", "checklist"], "procedure_step"),
    (["排障", "故障", "troubleshoot"], "troubleshooting_step"),
    (["注意事项", "限制", "约束", "constraint"], "constraint"),
    (["概述", "简介"], "concept"),
]


class RuleBasedEntityExtractor:
    """M1 lightweight entity extractor: commands and network elements."""

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()

        # Extract command entities
        for match in _CMD_PATTERN.finditer(text):
            cmd_name = f"{match.group(1)} {match.group(2)}"
            key = f"command:{cmd_name}"
            if key not in seen:
                seen.add(key)
                refs.append({"type": "command", "name": cmd_name})

        # Extract network element entities
        for match in _NF_PATTERN.finditer(text):
            nf_name = match.group(1)
            key = f"network_element:{nf_name}"
            if key not in seen:
                seen.add(key)
                refs.append({"type": "network_element", "name": nf_name})

        # Extract parameter entities from table structure
        structure = context.get("structure") if context else None
        if structure and isinstance(structure, dict):
            columns = structure.get("columns", [])
            if any("参数" in c for c in columns):
                rows = structure.get("rows", [])
                for row in rows:
                    param_name = row.get("参数标识") or row.get("参数名称") or row.get("参数名")
                    if param_name:
                        key = f"parameter:{param_name}"
                        if key not in seen:
                            seen.add(key)
                            refs.append({"type": "parameter", "name": param_name})

        return refs


class NoOpEntityExtractor:
    """Fallback: no entity extraction."""

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        return []


class DefaultRoleClassifier:
    """M1 lightweight role classifier based on section title keywords."""

    def classify(
        self,
        text: str,
        section_title: str | None,
        block_type: str,
        context: dict[str, Any],
    ) -> str:
        title = (section_title or "").lower()

        # Check section title against role rules
        for keywords, role in _ROLE_RULES:
            if any(kw.lower() in title for kw in keywords):
                return role

        # Block-type based heuristics
        if block_type == "table":
            structure = context.get("structure") if context else None
            if structure and isinstance(structure, dict):
                columns = structure.get("columns", [])
                if columns and any("参数" in c for c in columns):
                    return "parameter"
            return "note"

        if block_type == "code":
            return "example"

        return "unknown"


class NoOpSegmentEnricher:
    """M1 default: no enrichment."""

    def enrich(
        self,
        canonical: CanonicalSegmentData,
        sources: list[RawSegmentData],
    ) -> CanonicalSegmentData:
        return canonical
