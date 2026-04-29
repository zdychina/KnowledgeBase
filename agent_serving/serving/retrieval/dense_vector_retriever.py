"""DenseVectorRetriever — brute-force cosine similarity over embedding vectors.

Loads embedding vectors from asset_retrieval_embeddings table, computes
cosine similarity against query embedding, returns top-K candidates.

Uses numpy for matrix operations (~75ms for 50k vectors at 2048 dims).
Zero external vector DB dependency; can be swapped to sqlite-vec later.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from agent_serving.serving.schemas.constants import ROUTE_DENSE_VECTOR
from agent_serving.serving.schemas.models import (
    RetrievalCandidate,
    RetrievalQuery,
    ScoreChain,
)
from agent_serving.serving.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


def _cosine_similarity_matrix(
    query_vec: list[float],
    matrix: list[list[float]],
) -> list[float]:
    """Compute cosine similarity between query and each row in matrix."""
    try:
        import numpy as np
        q = np.array(query_vec, dtype=np.float32)
        m = np.array(matrix, dtype=np.float32)
        # Normalize
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return [0.0] * len(matrix)
        q = q / q_norm
        m_norms = np.linalg.norm(m, axis=1, keepdims=True)
        m_norms = np.where(m_norms == 0, 1.0, m_norms)
        m = m / m_norms
        similarities = m @ q
        return similarities.tolist()
    except ImportError:
        # Pure-python fallback
        return _cosine_similarity_pure(query_vec, matrix)


def _cosine_similarity_pure(
    query_vec: list[float],
    matrix: list[list[float]],
) -> list[float]:
    """Pure-python cosine similarity fallback."""
    import math
    q_norm = math.sqrt(sum(v * v for v in query_vec))
    if q_norm == 0:
        return [0.0] * len(matrix)
    results = []
    for row in matrix:
        dot = sum(a * b for a, b in zip(query_vec, row))
        r_norm = math.sqrt(sum(v * v for v in row))
        results.append(dot / (q_norm * r_norm) if r_norm > 0 else 0.0)
    return results


class DenseVectorRetriever(Retriever):
    """Dense vector retrieval using brute-force cosine similarity."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._cache: dict[str, list[tuple[str, list[float]]]] = {}

    async def retrieve(
        self,
        query: RetrievalQuery,
        snapshot_ids: list[str],
        top_k: int = 50,
    ) -> list[RetrievalCandidate]:
        """Retrieve by query embedding vector.

        If query.query_embedding is None, auto-skip (return []).
        """
        if not snapshot_ids or not query.query_embedding:
            return []

        # Load embeddings for given snapshots
        entries = await self._load_embeddings(snapshot_ids)
        if not entries:
            return []

        # Compute similarities
        matrix = [vec for _, vec in entries]
        similarities = _cosine_similarity_matrix(query.query_embedding, matrix)

        # Build candidates and sort
        scored: list[tuple[float, str, int]] = []
        for idx, (ru_id, _) in enumerate(entries):
            scored.append((similarities[idx], ru_id, idx))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Fetch metadata for top-K
        top_ids = [ru_id for _, ru_id, _ in scored[:top_k]]
        if not top_ids:
            return []

        metadata_map = await self._fetch_metadata(top_ids)

        candidates = []
        for score, ru_id, _ in scored[:top_k]:
            meta = metadata_map.get(ru_id, {})
            candidates.append(RetrievalCandidate(
                retrieval_unit_id=ru_id,
                score=max(score, 0.0),
                source=ROUTE_DENSE_VECTOR,
                metadata=meta,
                score_chain=ScoreChain(
                    raw_score=max(score, 0.0),
                    route_sources=[ROUTE_DENSE_VECTOR],
                ),
            ))
        return candidates

    async def _load_embeddings(
        self,
        snapshot_ids: list[str],
    ) -> list[tuple[str, list[float]]]:
        """Load embedding vectors from asset_retrieval_embeddings."""
        cache_key = ",".join(sorted(snapshot_ids))
        if cache_key in self._cache:
            return [(k, v) for k, v in self._cache[cache_key]]

        placeholders = ",".join("?" for _ in snapshot_ids)
        sql = f"""
            SELECT e.retrieval_unit_id, e.embedding_vector
            FROM asset_retrieval_embeddings e
            JOIN asset_retrieval_units ru ON ru.id = e.retrieval_unit_id
            WHERE ru.document_snapshot_id IN ({placeholders})
        """
        cursor = await self._db.execute(sql, snapshot_ids)
        rows = await cursor.fetchall()

        entries: list[tuple[str, list[float]]] = []
        for row in rows:
            r = dict(row)
            vec_str = r.get("embedding_vector", "[]")
            try:
                vec = json.loads(vec_str) if isinstance(vec_str, str) else vec_str
                if isinstance(vec, list) and len(vec) > 0:
                    entries.append((str(r["retrieval_unit_id"]), vec))
            except (json.JSONDecodeError, TypeError):
                continue

        self._cache[cache_key] = entries
        return entries

    async def _fetch_metadata(
        self,
        retrieval_unit_ids: list[str],
    ) -> dict[str, dict]:
        """Fetch retrieval unit metadata for candidate building."""
        if not retrieval_unit_ids:
            return {}
        placeholders = ",".join("?" for _ in retrieval_unit_ids)
        sql = f"""
            SELECT id, document_snapshot_id, text, title, block_type,
                   semantic_role, source_refs_json, facets_json,
                   target_type, target_ref_json, unit_type, source_segment_id
            FROM asset_retrieval_units
            WHERE id IN ({placeholders})
        """
        cursor = await self._db.execute(sql, retrieval_unit_ids)
        rows = await cursor.fetchall()

        result: dict[str, dict] = {}
        for row in rows:
            r = dict(row)
            ru_id = str(r["id"])
            result[ru_id] = {
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
            }
        return result

    def invalidate_cache(self) -> None:
        self._cache.clear()
