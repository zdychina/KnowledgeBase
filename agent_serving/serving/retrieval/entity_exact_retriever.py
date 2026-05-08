"""EntityExactRetriever — entity-based exact matching retrieval.

Strategies (in priority order):
1. entity_card type retrieval units where text matches entity name exactly
2. entity_refs_json LIKE coarse filter → JSON parse exact match
3. generated_question type units containing entity name

Returns candidates with source="entity_exact".
"""
from __future__ import annotations

import json
import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from agent_serving.serving.schemas.constants import ROUTE_ENTITY_EXACT
from agent_serving.serving.schemas.models import (
    EntityRef,
    RetrievalCandidate,
    RetrievalQuery,
    ScoreChain,
)
from agent_serving.serving.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)

_EXACT_MATCH_SCORE = 0.95
_PARTIAL_MATCH_SCORE = 0.7


class EntityExactRetriever(Retriever):
    """Retrieves candidates by matching entity names in retrieval units."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def retrieve(
        self,
        query: RetrievalQuery,
        snapshot_ids: list[str],
        top_k: int = 30,
    ) -> list[RetrievalCandidate]:
        """Unified interface: use query.entities (primary), fallback to query.keywords."""
        if not snapshot_ids:
            return []

        # Primary: entity names from query.entities
        entity_names = [e.name for e in query.entities if e.name]
        # Fallback: keywords as entity-like terms
        if not entity_names:
            entity_names = [kw for kw in query.keywords if len(kw) >= 2]
        if not entity_names:
            return []

        candidates = await self._retrieve_by_entities(entity_names, snapshot_ids, query.scope)
        return candidates[:top_k]

    async def _retrieve_by_entities(
        self,
        entity_names: list[str],
        snapshot_ids: list[str],
        scope: dict | None = None,
    ) -> list[RetrievalCandidate]:
        """Core retrieval: match entity names across multiple strategies."""
        all_candidates: list[RetrievalCandidate] = []

        placeholders = ",".join("%s" for _ in snapshot_ids)
        seen_ids: set[str] = set()
        scope_filter, scope_params = self._build_scope_filter(scope)

        for name in entity_names:
            # Strategy 1: entity_card units with exact name match
            card_candidates = await self._match_entity_cards(
                name, snapshot_ids, placeholders, scope_filter, scope_params,
            )
            for c in card_candidates:
                if c.retrieval_unit_id not in seen_ids:
                    seen_ids.add(c.retrieval_unit_id)
                    all_candidates.append(c)

            # Strategy 2: entity_refs_json LIKE → JSON parse
            ref_candidates = await self._match_entity_refs(
                name, snapshot_ids, placeholders, scope_filter, scope_params,
            )
            for c in ref_candidates:
                if c.retrieval_unit_id not in seen_ids:
                    seen_ids.add(c.retrieval_unit_id)
                    all_candidates.append(c)

            # Strategy 3: generated_question containing entity name
            q_candidates = await self._match_generated_questions(
                name, snapshot_ids, placeholders, scope_filter, scope_params,
            )
            for c in q_candidates:
                if c.retrieval_unit_id not in seen_ids:
                    seen_ids.add(c.retrieval_unit_id)
                    all_candidates.append(c)

        return all_candidates

    async def _match_entity_cards(
        self,
        entity_name: str,
        snapshot_ids: list[str],
        placeholders: str,
        scope_filter: str = "",
        scope_params: list[str] | None = None,
    ) -> list[RetrievalCandidate]:
        """Strategy 1: match entity_card units by text."""
        sql = f"""
            SELECT id, document_snapshot_id, text, title, block_type,
                   semantic_role, source_refs_json, facets_json,
                   target_type, target_ref_json, unit_type, source_segment_id
            FROM asset_retrieval_units
            WHERE unit_type = 'entity_card'
              AND text LIKE %s
              AND document_snapshot_id IN ({placeholders})
              {scope_filter}
        """
        params: list[Any] = [f"%{entity_name}%", *snapshot_ids, *(scope_params or [])]
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
        return self._rows_to_candidates(rows, entity_name, source=ROUTE_ENTITY_EXACT)

    async def _match_entity_refs(
        self,
        entity_name: str,
        snapshot_ids: list[str],
        placeholders: str,
        scope_filter: str = "",
        scope_params: list[str] | None = None,
    ) -> list[RetrievalCandidate]:
        """Strategy 2: match entity_refs_json via LIKE + JSON parse."""
        sql = f"""
            SELECT id, document_snapshot_id, text, title, block_type,
                   semantic_role, source_refs_json, facets_json,
                   entity_refs_json, target_type, target_ref_json,
                   unit_type, source_segment_id
            FROM asset_retrieval_units
            WHERE entity_refs_json::text LIKE %s
              AND document_snapshot_id IN ({placeholders})
              {scope_filter}
        """
        params: list[Any] = [f"%{entity_name}%", *snapshot_ids, *(scope_params or [])]
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()

        # JSON parse exact match filter
        candidates = []
        for row in rows:
            r = dict(row)
            entity_refs_str = r.get("entity_refs_json", "[]")
            if self._has_exact_entity(entity_refs_str, entity_name):
                score = _EXACT_MATCH_SCORE if self._is_exact_name(entity_refs_str, entity_name) else _PARTIAL_MATCH_SCORE
                candidates.append(self._row_to_candidate(r, score, ROUTE_ENTITY_EXACT))
        return candidates

    async def _match_generated_questions(
        self,
        entity_name: str,
        snapshot_ids: list[str],
        placeholders: str,
        scope_filter: str = "",
        scope_params: list[str] | None = None,
    ) -> list[RetrievalCandidate]:
        """Strategy 3: match generated_question units."""
        sql = f"""
            SELECT id, document_snapshot_id, text, title, block_type,
                   semantic_role, source_refs_json, facets_json,
                   target_type, target_ref_json, unit_type, source_segment_id
            FROM asset_retrieval_units
            WHERE unit_type = 'generated_question'
              AND text LIKE %s
              AND document_snapshot_id IN ({placeholders})
              {scope_filter}
        """
        params: list[Any] = [f"%{entity_name}%", *snapshot_ids, *(scope_params or [])]
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
        return self._rows_to_candidates(rows, entity_name, source=ROUTE_ENTITY_EXACT)

    def _has_exact_entity(self, entity_refs_json: str, name: str) -> bool:
        """Check if entity_refs contains an entity with matching name."""
        try:
            refs = json.loads(entity_refs_json)
            if not isinstance(refs, list):
                return False
            name_lower = name.lower()
            return any(
                ref.get("name", "").lower() == name_lower
                or ref.get("normalized_name", "").lower() == name_lower
                for ref in refs
            )
        except (json.JSONDecodeError, TypeError):
            return False

    def _is_exact_name(self, entity_refs_json: str, name: str) -> bool:
        """Check for exact entity name match (higher score)."""
        try:
            refs = json.loads(entity_refs_json)
            name_upper = name.upper()
            return any(
                ref.get("normalized_name", "").upper() == name_upper
                for ref in refs
            )
        except (json.JSONDecodeError, TypeError):
            return False

    def _rows_to_candidates(
        self,
        rows: list[Any],
        entity_name: str,
        source: str,
    ) -> list[RetrievalCandidate]:
        candidates = []
        for row in rows:
            r = dict(row)
            score = _PARTIAL_MATCH_SCORE
            if entity_name.upper() in (r.get("text", "") or "").upper():
                score = _EXACT_MATCH_SCORE
            candidates.append(self._row_to_candidate(r, score, source))
        return candidates

    def _row_to_candidate(
        self,
        r: dict,
        score: float,
        source: str,
    ) -> RetrievalCandidate:
        return RetrievalCandidate(
            retrieval_unit_id=str(r["id"]),
            score=score,
            source=source,
            metadata={
                "document_snapshot_id": r.get("document_snapshot_id"),
                "title": r.get("title"),
                "block_type": r.get("block_type", "unknown"),
                "semantic_role": r.get("semantic_role", "unknown"),
                "text": r.get("text", ""),
                "source_refs_json": r.get("source_refs_json", "{}"),
                "facets_json": r.get("facets_json", "{}"),
                "target_type": r.get("target_type", ""),
                "target_ref_json": r.get("target_ref_json", "{}"),
                "unit_type": r.get("unit_type", ""),
                "source_segment_id": r.get("source_segment_id"),
            },
            score_chain=ScoreChain(
                raw_score=score,
                route_sources=[source],
            ),
        )

    @staticmethod
    def _build_scope_filter(scope: dict | None) -> tuple[str, list[str]]:
        """Build SQL filter from query scope for facets_json pushdown.

        Returns (sql_fragment, params) using parameterized JSONB to prevent injection.
        """
        if not scope:
            return "", []
        conditions: list[str] = []
        params: list[str] = []
        for key, values in scope.items():
            if isinstance(values, list) and values:
                conditions.append("facets_json @> %s::jsonb")
                params.append(json.dumps({key: values}))
        if not conditions:
            return "", []
        return " AND " + " AND ".join(conditions), params
