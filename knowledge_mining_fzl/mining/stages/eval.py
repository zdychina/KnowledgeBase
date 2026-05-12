"""Evaluation: retrieval quality assessment + v1.5 data quality audit.

v1.5 adds `run_data_quality_eval()` — post-extraction structural checks
(GraphRAG pattern: audit after extraction, not filter before).

Existing `run_eval()` for Recall@K evaluation is preserved unchanged.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class EvalStage:
    """Stage wrapper for evaluation operations."""
    stage_name = "eval"
    stage_version = "1"

    def execute(self, context: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return context


# ---------------------------------------------------------------------------
# Data quality check result (v1.5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QualityCheckResult:
    """Result of a single data quality check."""
    check_id: str
    description: str
    passed: bool
    details: str = ""
    violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataQualityReport:
    """Post-extraction data quality audit report (GraphRAG pattern).

    All checks are structural/statistical — no hyperparameters.
    """
    total_checks: int
    passed: int
    failed: int
    checks: tuple[QualityCheckResult, ...]

    @property
    def all_passed(self) -> bool:
        return self.failed == 0


def run_data_quality_eval(
    profile: Any,
    asset_db_path: str,
    *,
    golden_segment_hash: str = "52bffeb308e54bff9e40b93fcf8c3e50",
) -> DataQualityReport:
    """Post-extraction data quality audit (GraphRAG pattern).

    Checks real SQLite products, not mock data.
    All checks are structural/statistical, no hyperparameters.

    Args:
        profile: DomainProfile.
        asset_db_path: Path to asset_core.sqlite.
        golden_segment_hash: Golden regression segment hash.
    """
    from knowledge_mining.mining.infra.db import AssetCoreDB

    db = AssetCoreDB(asset_db_path)
    db.open()

    try:
        checks: list[QualityCheckResult] = []

        checks.append(_check_no_qn_prefix(db))
        checks.append(_check_question_source_traceable(db))
        checks.append(_check_llm_provenance(db))
        checks.append(_check_golden_regression(db, golden_segment_hash))
        checks.append(_check_toc_no_questions(db))
        checks.append(_check_entity_card_not_navigation(db))

        total = len(checks)
        passed = sum(1 for c in checks if c.passed)
        failed = total - passed

        return DataQualityReport(
            total_checks=total,
            passed=passed,
            failed=failed,
            checks=tuple(checks),
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Individual quality checks
# ---------------------------------------------------------------------------

def _check_no_qn_prefix(db: Any) -> QualityCheckResult:
    """generated_question.title should not match ^Q\\d+:"""
    rows = db._fetchall(
        "SELECT unit_key, title FROM asset_retrieval_units "
        "WHERE unit_type = 'generated_question'"
    )
    qn_pattern = re.compile(r"^Q\d+\s*[:：]")
    violations: list[str] = []
    for row in rows:
        title = row["title"] or ""
        if qn_pattern.match(title):
            violations.append(f"{row['unit_key']}: {title[:60]}")

    return QualityCheckResult(
        check_id="no_qn_prefix",
        description="generated_question titles should not contain Qn prefix",
        passed=len(violations) == 0,
        details=f"Checked {len(rows)} generated_question units",
        violations=tuple(violations),
    )


def _check_question_source_traceable(db: Any) -> QualityCheckResult:
    """Every generated_question should have a source_segment_id."""
    rows = db._fetchall(
        "SELECT unit_key, source_segment_id FROM asset_retrieval_units "
        "WHERE unit_type = 'generated_question'"
    )
    violations: list[str] = []
    for row in rows:
        seg_id = row["source_segment_id"]
        if not seg_id:
            violations.append(f"{row['unit_key']}: missing source_segment_id")

    return QualityCheckResult(
        check_id="question_source_traceable",
        description="every generated_question has a source_segment_id",
        passed=len(violations) == 0,
        details=f"Checked {len(rows)} generated_question units",
        violations=tuple(violations[:10]),
    )


def _check_llm_provenance(db: Any) -> QualityCheckResult:
    """LLM-generated units should have task_id in llm_result_refs_json."""
    rows = db._fetchall(
        "SELECT unit_key, llm_result_refs_json FROM asset_retrieval_units "
        "WHERE unit_type IN ('generated_question', 'raw_text') "
        "AND llm_result_refs_json IS NOT NULL "
        "AND llm_result_refs_json != '{}'"
    )
    missing_task_id = 0
    violations: list[str] = []
    for row in rows:
        refs = row["llm_result_refs_json"]
        if isinstance(refs, str):
            try:
                refs = json.loads(refs)
            except (json.JSONDecodeError, TypeError):
                continue
        if isinstance(refs, dict) and "task_id" not in refs:
            missing_task_id += 1
            if len(violations) < 10:
                violations.append(f"{row['unit_key']}: has llm_result_refs but no task_id")

    return QualityCheckResult(
        check_id="llm_provenance",
        description="LLM-generated units have traceable task_id",
        passed=missing_task_id == 0,
        details=f"Checked {len(rows)} LLM-generated units, {missing_task_id} missing task_id",
        violations=tuple(violations),
    )


def _check_golden_regression(db: Any, segment_hash: str) -> QualityCheckResult:
    """Golden segment should generate 0 questions (known TOC/navigation content)."""
    seg_rows = db._fetchall(
        "SELECT segment_key FROM asset_raw_segments "
        "WHERE content_hash = %s",
        (segment_hash,),
    )
    if not seg_rows:
        return QualityCheckResult(
            check_id="golden_regression",
            description=f"segment {segment_hash[:12]}... generates 0 questions",
            passed=True,
            details="Golden segment not found in DB — check skipped",
        )

    seg_keys = [row["segment_key"] for row in seg_rows]
    placeholders = ",".join("%s" for _ in seg_keys)
    q_rows = db._fetchall(
        f"SELECT unit_key FROM asset_retrieval_units "
        f"WHERE segment_key IN ({placeholders}) "
        f"AND unit_type = 'generated_question'",
        tuple(seg_keys),
    )

    violations = [row["unit_key"] for row in q_rows]

    return QualityCheckResult(
        check_id="golden_regression",
        description=f"segment {segment_hash[:12]}... generates 0 questions",
        passed=len(violations) == 0,
        details=f"Found {len(violations)} questions for golden segment",
        violations=tuple(violations[:10]),
    )


def _check_toc_no_questions(db: Any) -> QualityCheckResult:
    """Segments marked as navigation should not have generated questions."""
    rows = db._fetchall(
        "SELECT s.segment_key FROM asset_raw_segments s "
        "JOIN asset_retrieval_units u ON u.segment_key = s.segment_key "
        "WHERE u.unit_type = 'generated_question' "
        "AND json_extract(s.metadata_json, '$.content_assessment.is_navigation') = 1"
    )
    violations = [row["segment_key"] for row in rows]

    return QualityCheckResult(
        check_id="toc_no_questions",
        description="navigation segments should not generate questions",
        passed=len(violations) == 0,
        details=f"Found {len(violations)} navigation segments with questions",
        violations=tuple(violations[:10]),
    )


def _check_entity_card_not_navigation(db: Any) -> QualityCheckResult:
    """entity_card should not come from navigation segments."""
    rows = db._fetchall(
        "SELECT u.unit_key FROM asset_retrieval_units u "
        "JOIN asset_raw_segments s ON u.segment_key = s.segment_key "
        "WHERE u.unit_type = 'entity_card' "
        "AND json_extract(s.metadata_json, '$.content_assessment.is_navigation') = 1"
    )
    violations = [row["unit_key"] for row in rows]

    return QualityCheckResult(
        check_id="entity_card_not_navigation",
        description="entity_card should not come from navigation segments",
        passed=len(violations) == 0,
        details=f"Found {len(violations)} entity cards from navigation segments",
        violations=tuple(violations[:10]),
    )


# ---------------------------------------------------------------------------
# Retrieval quality eval (unchanged)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvalResult:
    """Result for a single eval question."""
    question_id: str
    question: str
    hit: bool
    recall_rank: int | None
    matched_entities: list[str] = field(default_factory=list)
    evidence_found: bool = False


@dataclass(frozen=True)
class EvalReport:
    """Aggregate evaluation report."""
    domain_id: str
    total_questions: int
    recall_at_5: float
    recall_at_10: float
    per_question: tuple[EvalResult, ...]
    miss_count: int


def run_eval(
    profile: Any,
    asset_db_path: str,
    *,
    k: int = 5,
) -> EvalReport:
    """Run retrieval evaluation against a domain pack's eval_questions."""
    from knowledge_mining.mining.infra.db import AssetCoreDB
    from knowledge_mining.mining.infra.text_utils import tokenize_for_search

    questions = profile.eval_questions
    if not questions:
        logger.warning("No eval questions in domain pack '%s'", profile.domain_id)
        return EvalReport(
            domain_id=profile.domain_id,
            total_questions=0,
            recall_at_5=0.0,
            recall_at_10=0.0,
            per_question=(),
            miss_count=0,
        )

    db = AssetCoreDB(asset_db_path)
    db.open()

    try:
        results: list[EvalResult] = []
        for q in questions:
            result = _evaluate_question(q, db, k)
            results.append(result)

        total = len(results)
        hits_5 = sum(1 for r in results if r.hit)
        hits_10 = sum(1 for r in results if r.recall_rank is not None and r.recall_rank <= 10)
        misses = sum(1 for r in results if not r.hit)

        return EvalReport(
            domain_id=profile.domain_id,
            total_questions=total,
            recall_at_5=hits_5 / total if total > 0 else 0.0,
            recall_at_10=hits_10 / total if total > 0 else 0.0,
            per_question=tuple(results),
            miss_count=misses,
        )
    finally:
        db.close()


def _evaluate_question(
    question: Any,
    db: Any,
    k: int = 5,
) -> EvalResult:
    """Evaluate a single question against retrieval units."""
    from knowledge_mining.mining.infra.text_utils import tokenize_for_search

    search_tokens = tokenize_for_search(question.question)
    if not search_tokens:
        return EvalResult(
            question_id=question.id,
            question=question.question,
            hit=False,
            recall_rank=None,
        )

    fts_query = " & ".join(search_tokens[:5])

    rows = db._fetchall(
        "SELECT unit_key, text, search_text, entity_refs_json "
        "FROM asset_retrieval_units "
        "WHERE search_vector @@ plainto_tsquery('simple', %s) "
        "ORDER BY weight DESC LIMIT %s",
        (fts_query, max(k, 10)),
    )

    if not rows:
        return EvalResult(
            question_id=question.id,
            question=question.question,
            hit=False,
            recall_rank=None,
        )

    expected_entities = set(question.expected_entities)
    expected_evidence = set(question.expected_evidence_contains)

    for rank, row in enumerate(rows, start=1):
        text = row["text"] or ""
        search_text = row["search_text"] or ""
        combined = f"{text} {search_text}".lower()

        matched = [e for e in expected_entities if e.lower() in combined]
        evidence_found = all(e.lower() in combined for e in expected_evidence)

        if matched or evidence_found:
            hit = rank <= k
            return EvalResult(
                question_id=question.id,
                question=question.question,
                hit=hit,
                recall_rank=rank,
                matched_entities=matched,
                evidence_found=evidence_found,
            )

    return EvalResult(
        question_id=question.id,
        question=question.question,
        hit=False,
        recall_rank=None,
    )


def format_report(report: EvalReport) -> str:
    """Format an EvalReport as a human-readable string."""
    lines = [
        f"=== Eval Report: {report.domain_id} ===",
        f"Total questions: {report.total_questions}",
        f"Recall@5:  {report.recall_at_5:.1%}",
        f"Recall@10: {report.recall_at_10:.1%}",
        f"Misses: {report.miss_count}",
        "",
    ]

    for r in report.per_question:
        status = "HIT" if r.hit else "MISS"
        rank_str = f"rank={r.recall_rank}" if r.recall_rank else "not found"
        lines.append(f"  [{status}] {r.question_id}: {r.question[:50]}... ({rank_str})")

    return "\n".join(lines)


def format_quality_report(report: DataQualityReport) -> str:
    """Format a DataQualityReport as a human-readable string."""
    lines = [
        f"=== Data Quality Report ===",
        f"Checks: {report.total_checks} total, {report.passed} passed, {report.failed} failed",
        "",
    ]
    for c in report.checks:
        status = "PASS" if c.passed else "FAIL"
        lines.append(f"  [{status}] {c.check_id}: {c.description}")
        if c.details:
            lines.append(f"         {c.details}")
        if c.violations:
            for v in c.violations[:5]:
                lines.append(f"         - {v}")
            if len(c.violations) > 5:
                lines.append(f"         ... and {len(c.violations) - 5} more")

    return "\n".join(lines)
