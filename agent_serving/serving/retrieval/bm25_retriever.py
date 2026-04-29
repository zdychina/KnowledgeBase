"""FTS5 + BM25 retriever — pure retrieval, no post-filtering.

Post-filtering (role/block_type preference, truncation) is handled
by the Reranker stage, not the retriever.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from agent_serving.serving.schemas.constants import ROUTE_LEXICAL_BM25
from agent_serving.serving.schemas.models import RetrievalCandidate, RetrievalQuery
from agent_serving.serving.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


def _tokenize_for_fts(text: str) -> str:
    """Tokenize text for FTS5 query.

    Uses jieba for Chinese segmentation when available.
    Falls back to simple whitespace splitting.
    """
    try:
        import jieba
        tokens = list(jieba.cut(text))
        # Keep tokens that are at least 2 chars or single CJK char
        return " ".join(
            t for t in tokens
            if len(t) >= 2 or _is_cjk(t)
        )
    except ImportError:
        return text


def _is_cjk(char: str) -> bool:
    """Check if a single character is CJK."""
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF)
        or (0x3400 <= cp <= 0x4DBF)
        or (0x2E80 <= cp <= 0x2EFF)
    )


def _build_fts_or_query(tokens: list[str]) -> str:
    """Build FTS5 OR query from tokens.

    Each token is individually double-quoted and joined with OR.
    This gives per-token matching instead of phrase matching,
    significantly improving Chinese recall.
    """
    escaped = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        escaped.append('"' + t.replace('"', '""') + '"')
    return " OR ".join(escaped)


class FTS5BM25Retriever(Retriever):
    """FTS5 BM25 retrieval over asset_retrieval_units.

    Returns raw scored candidates; role/block_type preference
    and budget truncation are handled by the Reranker stage.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def retrieve(
        self,
        query: RetrievalQuery,
        snapshot_ids: list[str],
        top_k: int = 50,
    ) -> list[RetrievalCandidate]:
        if not snapshot_ids:
            return []

        # Collect search terms: keywords + sub_queries, fallback to original_query
        search_terms = list(query.keywords)
        for sq in query.sub_queries:
            search_terms.extend(sq.split())
        if not search_terms and query.original_query:
            search_terms = _tokenize_for_fts(query.original_query).split()

        if not search_terms:
            return []

        # Build FTS OR query from terms (v1.2: OR semantics)
        fts_tokens = _tokenize_for_fts(" ".join(search_terms))
        token_list = [t for t in fts_tokens.split() if t]
        fts_query = _build_fts_or_query(token_list)
        if not fts_query:
            return []

        recall_limit = top_k * 5

        # FTS5 match on retrieval_units within snapshot scope
        placeholders = ",".join("?" for _ in snapshot_ids)
        sql = f"""
            SELECT
                ru.id,
                ru.document_snapshot_id,
                ru.text,
                ru.title,
                ru.block_type,
                ru.semantic_role,
                ru.source_refs_json,
                ru.facets_json,
                ru.target_type,
                ru.target_ref_json,
                ru.unit_type,
                ru.source_segment_id,
                bm25(asset_retrieval_units_fts) AS fts_score
            FROM asset_retrieval_units_fts fts
            JOIN asset_retrieval_units ru ON ru.id = fts.retrieval_unit_id
            WHERE asset_retrieval_units_fts MATCH ?
              AND ru.document_snapshot_id IN ({placeholders})
            ORDER BY fts_score
            LIMIT ?
        """
        params: list[Any] = [fts_query, *snapshot_ids, recall_limit]

        try:
            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()
        except Exception:
            logger.warning("FTS5 query failed, falling back to LIKE", exc_info=True)
            return await self._fallback_like(query, snapshot_ids, top_k)

        return self._rows_to_candidates(rows, source=ROUTE_LEXICAL_BM25)

    async def _fallback_like(
        self,
        query: RetrievalQuery,
        snapshot_ids: list[str],
        top_k: int = 50,
    ) -> list[RetrievalCandidate]:
        """LIKE fallback when FTS5 is not available."""
        # Collect search terms same as retrieve()
        search_terms = list(query.keywords)
        for sq in query.sub_queries:
            search_terms.extend(sq.split())
        if not search_terms and query.original_query:
            search_terms = _tokenize_for_fts(query.original_query).split()

        if not search_terms or not snapshot_ids:
            return []

        placeholders = ",".join("?" for _ in snapshot_ids)
        like_clauses = " OR ".join(
            "ru.text LIKE ?" for _ in search_terms
        )
        params: list[Any] = [f"%{k}%" for k in search_terms]
        params.extend(snapshot_ids)

        recall_limit = top_k * 5

        sql = f"""
            SELECT
                ru.id,
                ru.document_snapshot_id,
                ru.text,
                ru.title,
                ru.block_type,
                ru.semantic_role,
                ru.source_refs_json,
                ru.facets_json,
                ru.target_type,
                ru.target_ref_json,
                ru.unit_type,
                ru.source_segment_id
            FROM asset_retrieval_units ru
            WHERE ({like_clauses})
              AND ru.document_snapshot_id IN ({placeholders})
            LIMIT ?
        """
        params.append(recall_limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        candidates = []
        for row in rows:
            r = dict(row)
            text = (r.get("text", "") or "").lower()
            hit_count = sum(
                1 for kw in search_terms if kw.lower() in text
            )
            score = hit_count / max(len(search_terms), 1)
            candidates.append(self._row_to_candidate(r, score, source="like_fallback"))

        return candidates

    def _rows_to_candidates(
        self,
        rows: list[Any],
        source: str,
    ) -> list[RetrievalCandidate]:
        candidates = []
        for row in rows:
            r = dict(row)
            # bm25 returns negative scores (more negative = more relevant)
            score = -r.get("fts_score", 0.0)
            candidates.append(self._row_to_candidate(r, score, source))
        return candidates

    def _row_to_candidate(
        self,
        r: dict,
        score: float,
        source: str,
    ) -> RetrievalCandidate:
        return RetrievalCandidate(
            retrieval_unit_id=r["id"],
            score=score,
            source=source,
            metadata={
                "document_snapshot_id": r["document_snapshot_id"],
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
        )
