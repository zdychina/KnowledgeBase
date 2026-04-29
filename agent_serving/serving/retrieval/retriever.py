"""Abstract Retriever interface — v1.3 unified retrieval architecture.

All retrievers implement the same protocol so the search pipeline
can swap between BM25, vector, or hybrid without code changes.
Uses RetrievalQuery (v1.3) to carry full query semantics to each retriever.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from agent_serving.serving.schemas.models import RetrievalCandidate, RetrievalQuery


class Retriever(ABC):
    """Base class for retrieval strategies."""

    @abstractmethod
    async def retrieve(
        self,
        query: RetrievalQuery,
        snapshot_ids: list[str],
        top_k: int = 50,
    ) -> list[RetrievalCandidate]:
        """Return scored candidates from the index.

        Args:
            query: structured query with keywords, entities, embedding.
            snapshot_ids: document snapshots in scope.
            top_k: maximum candidates to return.

        Returns:
            Scored candidates sorted by descending relevance.
        """
        ...
