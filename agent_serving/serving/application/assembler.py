"""ContextAssembler — builds ContextPack from retrieval results.

v2 design:
- seed items from retrieval_candidates (retrieval_units)
- source drill-down via resolve_source_segments (parsed source_refs_json)
- context expansion via GraphExpander relations
- Evidence role classification
- Citation building
- Score chain propagation
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agent_serving.serving.schemas.models import (
    ActiveScope,
    ContextItem,
    ContextPack,
    ContextQuery,
    ContextRelation,
    Issue,
    NormalizedQuery,
    QueryPlan,
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalRoutePlan,
    SourceRef,
)
from agent_serving.serving.schemas.constants import (
    ISSUE_LOW_CONFIDENCE,
    ISSUE_NO_RESULT,
    KIND_RAW_SEGMENT,
    KIND_RETRIEVAL_UNIT,
    ROLE_CONTEXT,
    ROLE_SEED,
    ROLE_SUPPORT,
)
from agent_serving.serving.schemas.json_utils import safe_json_parse
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.retrieval.graph_expander import (
    GraphExpander,
    parse_source_refs,
    parse_target_ref,
)
from agent_serving.serving.evidence.role_classifier import EvidenceRoleClassifier

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles ContextPack from retrieval + expansion results."""

    def __init__(self, repo: AssetRepository, graph: GraphExpander) -> None:
        self._repo = repo
        self._graph = graph
        self._role_classifier = EvidenceRoleClassifier()

    async def assemble(
        self,
        *,
        query: str,
        understanding: QueryUnderstanding | None = None,
        normalized: NormalizedQuery | None = None,
        plan: QueryPlan | None = None,
        scope: ActiveScope | None = None,
        candidates: list[RetrievalCandidate] | None = None,
        route_plan: RetrievalRoutePlan | None = None,
    ) -> ContextPack:
        """Full assembly pipeline: seed → source drill-down → expansion → pack.

        Supports both v1 (normalized+plan) and v2 (understanding+route_plan) calls.
        """
        # Normalize params: support both v1 and v2 call signatures
        if normalized is None and understanding is None:
            understanding = QueryUnderstanding(original_query=query)
        if plan is None:
            plan = QueryPlan()
        if scope is None:
            scope = ActiveScope(release_id="", build_id="")
        if candidates is None:
            candidates = []
        if route_plan is None:
            route_plan = RetrievalRoutePlan()

        # 1. Build seed items from retrieval candidates
        seed_items = self._build_seed_items(
            candidates, understanding=understanding,
        )

        # 2. Source drill-down
        all_source_segment_ids: list[str] = []
        for candidate in candidates:
            seg_ids = self._resolve_candidate_sources(candidate)
            all_source_segment_ids.extend(seg_ids)

        # Deduplicate
        seen_segs: set[str] = set()
        unique_seg_ids: list[str] = []
        for sid in all_source_segment_ids:
            if sid not in seen_segs:
                seen_segs.add(sid)
                unique_seg_ids.append(sid)

        # 3. Fetch source segments
        if unique_seg_ids and scope.snapshot_ids:
            source_segments = await self._repo.resolve_segments_by_ids(
                unique_seg_ids, snapshot_ids=scope.snapshot_ids,
            )
        else:
            source_segments = []
        source_seg_map = {str(s["id"]): s for s in source_segments}
        source_items = self._build_source_items(source_segments)

        # 4. Graph expansion if enabled
        expanded_items: list[ContextItem] = []
        relation_items: list[ContextRelation] = []

        expansion_enabled = route_plan.assembly.relation_expansion
        # Also check legacy plan's expansion flag for backward compatibility
        if not expansion_enabled and plan.expansion.enable_relation_expansion:
            expansion_enabled = True
        elif not plan.expansion.enable_relation_expansion:
            expansion_enabled = False
        if expansion_enabled and unique_seg_ids and scope.snapshot_ids:
            max_depth = route_plan.assembly.max_relation_depth
            max_results = route_plan.assembly.max_expanded
            relation_types = route_plan.assembly.relation_types or None

            expansions = await self._graph.expand(
                seed_segment_ids=unique_seg_ids,
                max_depth=max_depth,
                relation_types=relation_types,
                max_results=max_results,
                snapshot_ids=scope.snapshot_ids,
            )

            expanded_data = await self._graph.fetch_expanded_segments(
                expansions, snapshot_ids=scope.snapshot_ids,
            )
            expanded_items = self._build_expanded_items(expanded_data)

            for exp in expansions:
                relation_items.append(ContextRelation(
                    id=f"rel-{exp['from_segment_id']}-{exp['segment_id']}",
                    from_id=exp["from_segment_id"],
                    to_id=exp["segment_id"],
                    relation_type=exp["relation_type"],
                    distance=exp["depth"],
                ))

        # 5. Fetch direct relations
        if unique_seg_ids:
            direct_relations = await self._repo.get_relations_for_segments(
                unique_seg_ids,
                relation_types=route_plan.assembly.relation_types or None,
            )
            for rel in direct_relations:
                rid = str(rel["id"])
                relation_items.append(ContextRelation(
                    id=rid,
                    from_id=str(rel["from_segment_id"]),
                    to_id=str(rel["to_segment_id"]),
                    relation_type=rel["relation_type"],
                    distance=0,
                ))

        # Deduplicate relations
        seen_rels: set[str] = set()
        unique_relations: list[ContextRelation] = []
        for r in relation_items:
            if r.id not in seen_rels:
                seen_rels.add(r.id)
                unique_relations.append(r)

        # 6. Build source references
        document_ids = set()
        for seg in source_segments:
            if seg.get("document_id"):
                document_ids.add(str(seg["document_id"]))
        doc_sources = await self._repo.get_document_sources(
            list(document_ids), snapshot_ids=scope.snapshot_ids,
        )
        sources = self._build_sources(doc_sources)

        # 7. Build issues
        issues = self._build_issues(seed_items, understanding, normalized)

        # 8. Assemble final pack
        all_items = seed_items + source_items + expanded_items
        max_items = route_plan.assembly.max_items + route_plan.assembly.max_expanded
        all_items = all_items[:max_items]

        # Build ContextQuery from understanding or normalized
        if understanding:
            context_query = ContextQuery(
                original=query,
                normalized=self._format_understanding(understanding),
                intent=understanding.intent,
                entities=understanding.entities,
                scope=understanding.scope,
                keywords=understanding.keywords,
            )
        elif normalized:
            context_query = ContextQuery(
                original=query,
                normalized=self._format_normalized(normalized),
                intent=normalized.intent,
                entities=normalized.entities,
                scope=normalized.scope,
                keywords=normalized.keywords,
            )
        else:
            context_query = ContextQuery(original=query, normalized="")

        return ContextPack(
            query=context_query,
            items=all_items,
            relations=unique_relations,
            sources=sources,
            issues=issues,
            suggestions=self._build_suggestions(issues),
        )

    def _build_seed_items(
        self,
        candidates: list[RetrievalCandidate],
        understanding: QueryUnderstanding | None = None,
    ) -> list[ContextItem]:
        items = []
        for c in candidates:
            # Build citation
            citation = self._build_citation(c)

            # Classify evidence role
            evidence_role = ""
            if understanding:
                evidence_role = self._role_classifier.classify(c, understanding)

            # Get route sources from score_chain
            route_sources = []
            if c.score_chain:
                route_sources = c.score_chain.route_sources

            items.append(ContextItem(
                id=c.retrieval_unit_id,
                kind=KIND_RETRIEVAL_UNIT,
                role=ROLE_SEED,
                text=c.metadata.get("text", ""),
                score=c.score,
                title=c.metadata.get("title"),
                block_type=c.metadata.get("block_type", "unknown"),
                semantic_role=c.metadata.get("semantic_role", "unknown"),
                source_refs=safe_json_parse(c.metadata.get("source_refs_json", "{}")),
                metadata=c.metadata,
                route_sources=route_sources,
                score_chain=c.score_chain,
                evidence_role=evidence_role,
                citation=citation,
            ))
        return items

    def _build_citation(self, candidate: RetrievalCandidate) -> dict:
        """Build citation dict from source_refs_json and metadata."""
        source_refs = safe_json_parse(candidate.metadata.get("source_refs_json", "{}"))
        citation: dict = {}
        if source_refs:
            citation["raw_segment_ids"] = source_refs.get("raw_segment_ids", [])
        if candidate.metadata.get("title"):
            citation["section"] = candidate.metadata["title"]
        if candidate.metadata.get("document_snapshot_id"):
            citation["document_snapshot_id"] = candidate.metadata["document_snapshot_id"]
        return citation

    def _resolve_candidate_sources(self, candidate: RetrievalCandidate) -> list[str]:
        """Resolve source segment IDs with 4-layer priority."""
        seg_id = candidate.metadata.get("source_segment_id")
        if seg_id:
            return [seg_id]

        source_refs = candidate.metadata.get("source_refs_json", "{}")
        seg_ids = parse_source_refs(source_refs)
        if seg_ids:
            return seg_ids

        target_type = candidate.metadata.get("target_type", "")
        target_ref = candidate.metadata.get("target_ref_json", "{}")
        if target_type and target_ref and target_ref != "{}":
            seg_ids = parse_target_ref(target_ref)
            if seg_ids:
                return seg_ids

        return []

    def _build_source_items(
        self, segments: list[dict[str, Any]],
    ) -> list[ContextItem]:
        items = []
        for seg in segments:
            items.append(ContextItem(
                id=str(seg["id"]),
                kind=KIND_RAW_SEGMENT,
                role=ROLE_CONTEXT,
                text=seg.get("raw_text", ""),
                score=0.0,
                title=seg.get("snapshot_title"),
                block_type=seg.get("block_type", "unknown"),
                semantic_role=seg.get("semantic_role", "unknown"),
                source_id=str(seg.get("document_id", "")),
                source_refs={},
            ))
        return items

    def _build_expanded_items(
        self, expanded: list[dict[str, Any]],
    ) -> list[ContextItem]:
        items = []
        for seg in expanded:
            items.append(ContextItem(
                id=str(seg["id"]),
                kind=KIND_RAW_SEGMENT,
                role=ROLE_SUPPORT,
                text=seg.get("raw_text", ""),
                score=0.0,
                title=seg.get("doc_title"),
                block_type=seg.get("block_type", "unknown"),
                semantic_role=seg.get("semantic_role", "unknown"),
                source_id=str(seg.get("document_id", "")),
                relation_to_seed=seg.get("expansion_relation_type", ""),
                evidence_role="background",
            ))
        return items

    def _build_sources(
        self, docs: list[dict[str, Any]],
    ) -> list[SourceRef]:
        seen: set[str] = set()
        sources = []
        for doc in docs:
            doc_id = str(doc["id"])
            if doc_id in seen:
                continue
            seen.add(doc_id)
            sources.append(SourceRef(
                id=doc_id,
                document_key=doc.get("document_key", ""),
                title=doc.get("title"),
                relative_path=doc.get("relative_path"),
                scope_json=safe_json_parse(doc.get("scope_json", "{}")),
            ))
        return sources

    def _build_issues(
        self,
        items: list[ContextItem],
        understanding: QueryUnderstanding | None = None,
        normalized: NormalizedQuery | None = None,
    ) -> list[Issue]:
        issues: list[Issue] = []
        query_text = ""
        if understanding:
            query_text = understanding.original_query
        elif normalized:
            query_text = normalized.original_query

        if not items:
            issues.append(Issue(
                type=ISSUE_NO_RESULT,
                message="未找到相关内容",
                detail={"query": query_text},
            ))
        elif all(item.score < 0.1 for item in items):
            issues.append(Issue(
                type=ISSUE_LOW_CONFIDENCE,
                message="检索结果置信度较低",
                detail={"top_score": max(item.score for item in items)},
            ))

        return issues

    def _build_suggestions(self, issues: list[Issue]) -> list[str]:
        suggestions: list[str] = []
        for issue in issues:
            if issue.type == ISSUE_NO_RESULT:
                suggestions.append("尝试使用更通用的关键词")
            elif issue.type == ISSUE_LOW_CONFIDENCE:
                suggestions.append("尝试更精确的描述或添加产品/版本约束")
        return suggestions

    def _format_normalized(self, normalized: NormalizedQuery) -> str:
        parts = [f"intent={normalized.intent}"]
        for e in normalized.entities:
            parts.append(f"{e.type}={e.name}")
        parts.extend(normalized.keywords)
        return " ".join(parts)

    def _format_understanding(self, understanding: QueryUnderstanding) -> str:
        parts = [f"intent={understanding.intent}"]
        for e in understanding.entities:
            parts.append(f"{e.type}={e.name}")
        parts.extend(understanding.keywords)
        return " ".join(parts)
