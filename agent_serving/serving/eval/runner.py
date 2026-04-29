"""EvalRunner — retrieval quality evaluation framework.

Metrics: Recall@K, MRR@K, NDCG@K, HitRate@K
Matching: expected_evidence_contains substring match in item.text
Route contribution: per-route unique hits
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class EvalQuestion:
    """A single eval question."""
    id: str
    question: str
    expected_entities: list[str] = field(default_factory=list)
    expected_evidence_contains: list[str] = field(default_factory=list)
    expected_semantic_role: str | None = None
    notes: str = ""


@dataclass
class EvalResult:
    """Result for a single eval question."""
    question_id: str
    question: str
    hit: bool = False
    recall_at_k: float = 0.0
    mrr_at_k: float = 0.0
    ndcg_at_k: float = 0.0
    route_contribution: dict[str, int] = field(default_factory=dict)
    top_item_score: float = 0.0
    matched_evidence: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """Aggregated evaluation report."""
    total_questions: int = 0
    hit_rate: float = 0.0
    recall_at_k: float = 0.0
    mrr_at_k: float = 0.0
    ndcg_at_k: float = 0.0
    route_contribution: dict[str, int] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)


class EvalRunner:
    """Runs retrieval quality evaluation against a set of eval questions."""

    def __init__(self, k: int = 10) -> None:
        self._k = k

    async def run(
        self,
        eval_questions: list[dict[str, Any]],
        search_fn: Callable[[str], Awaitable[dict]],
    ) -> EvalReport:
        """Run evaluation over all questions.

        Args:
            eval_questions: List of eval question dicts from domain.yaml
            search_fn: Async function that takes query string, returns ContextPack dict
        """
        results: list[EvalResult] = []

        for q_data in eval_questions:
            q = EvalQuestion(
                id=q_data.get("id", ""),
                question=q_data["question"],
                expected_entities=q_data.get("expected_entities", []),
                expected_evidence_contains=q_data.get("expected_evidence_contains", []),
                expected_semantic_role=q_data.get("expected_semantic_role"),
                notes=q_data.get("notes", ""),
            )
            result = await self._evaluate_question(q, search_fn)
            results.append(result)

        return self._build_report(results)

    async def _evaluate_question(
        self,
        question: EvalQuestion,
        search_fn: Callable[[str], Awaitable[dict]],
    ) -> EvalResult:
        """Evaluate a single question."""
        try:
            pack = await search_fn(question.question)
        except Exception:
            logger.warning("Search failed for question %s", question.id, exc_info=True)
            return EvalResult(question_id=question.id, question=question.question)

        items = pack.get("items", [])
        if not items:
            return EvalResult(question_id=question.id, question=question.question)

        # Check which items contain expected evidence
        expected = question.expected_evidence_contains
        if not expected:
            return EvalResult(
                question_id=question.id,
                question=question.question,
                hit=False,
            )

        # Find matching items
        relevant_indices: list[int] = []
        matched_evidence: list[str] = []
        for idx, item in enumerate(items[:self._k]):
            text = item.get("text", "").lower()
            matches = [e for e in expected if e.lower() in text]
            if matches:
                relevant_indices.append(idx)
                matched_evidence.extend(matches)

        hit = len(relevant_indices) > 0
        recall = len(matched_evidence) / max(len(expected), 1)

        # MRR: reciprocal rank of first relevant item
        mrr = 1.0 / (relevant_indices[0] + 1) if relevant_indices else 0.0

        # NDCG: normalized discounted cumulative gain
        ndcg = self._compute_ndcg(relevant_indices, len(items[:self._k]))

        # Route contribution
        route_contribution: dict[str, int] = {}
        for idx in relevant_indices:
            if idx < len(items):
                item = items[idx]
                routes = item.get("route_sources", [])
                for route in routes:
                    route_contribution[route] = route_contribution.get(route, 0) + 1

        top_score = items[0].get("score", 0.0) if items else 0.0

        return EvalResult(
            question_id=question.id,
            question=question.question,
            hit=hit,
            recall_at_k=recall,
            mrr_at_k=mrr,
            ndcg_at_k=ndcg,
            route_contribution=route_contribution,
            top_item_score=top_score,
            matched_evidence=list(set(matched_evidence)),
        )

    def _compute_ndcg(self, relevant_indices: list[int], total: int) -> float:
        """Compute NDCG@K."""
        if not relevant_indices:
            return 0.0

        # DCG
        dcg = sum(1.0 / math.log2(idx + 2) for idx in relevant_indices)

        # Ideal DCG (all relevant at top)
        ideal_count = min(len(relevant_indices), total)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))

        return dcg / idcg if idcg > 0 else 0.0

    def _build_report(self, results: list[EvalResult]) -> EvalReport:
        """Build aggregated report."""
        total = len(results)
        if total == 0:
            return EvalReport()

        hits = sum(1 for r in results if r.hit)
        total_recall = sum(r.recall_at_k for r in results)
        total_mrr = sum(r.mrr_at_k for r in results)
        total_ndcg = sum(r.ndcg_at_k for r in results)

        # Aggregate route contribution
        route_contribution: dict[str, int] = {}
        for r in results:
            for route, count in r.route_contribution.items():
                route_contribution[route] = route_contribution.get(route, 0) + count

        return EvalReport(
            total_questions=total,
            hit_rate=hits / total,
            recall_at_k=total_recall / total,
            mrr_at_k=total_mrr / total,
            ndcg_at_k=total_ndcg / total,
            route_contribution=route_contribution,
            results=results,
        )
