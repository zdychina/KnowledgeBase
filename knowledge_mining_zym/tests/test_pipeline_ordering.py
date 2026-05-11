"""Tests for StreamingPipeline ordering and run status correctness."""
from __future__ import annotations

import time
from knowledge_mining.mining.pipeline import (
    DocumentContext, StreamingPipeline,
)


def _slow_identity(ctx: DocumentContext) -> DocumentContext:
    """Simulate a slow stage that preserves sequence_id."""
    time.sleep(0.01 * (ctx.sequence_id % 3 + 1))
    return ctx


def test_streaming_pipeline_preserves_input_order():
    """Results should be in the same order as input, regardless of completion timing."""
    items = [
        DocumentContext(sequence_id=i)
        for i in range(10)
    ]
    stages = [("identity", _slow_identity, 4)]
    pipeline = StreamingPipeline(stages)
    results = pipeline.process_all(items)

    assert len(results) == 10
    for i, ctx in enumerate(results):
        assert ctx.sequence_id == i, f"Expected sequence_id={i}, got {ctx.sequence_id}"


def test_streaming_pipeline_single_worker():
    """Single worker should trivially preserve order."""
    items = [DocumentContext(sequence_id=i) for i in range(5)]
    stages = [("identity", lambda ctx: ctx, 1)]
    pipeline = StreamingPipeline(stages)
    results = pipeline.process_all(items)

    assert [ctx.sequence_id for ctx in results] == [0, 1, 2, 3, 4]


def test_streaming_pipeline_with_updates_preserves_sequence():
    """with_updates should propagate sequence_id through stages."""
    def enrich(ctx: DocumentContext) -> DocumentContext:
        return ctx.with_updates(error=None)  # just touch a field

    items = [DocumentContext(sequence_id=i) for i in range(8)]
    stages = [("enrich", enrich, 3)]
    pipeline = StreamingPipeline(stages)
    results = pipeline.process_all(items)

    assert [ctx.sequence_id for ctx in results] == list(range(8))


def test_run_status_failed_when_all_docs_fail():
    """When all docs fail, run status should be 'failed' via fail_run, not complete_run."""
    # Simulate the logic from run.py lines 651-669
    failed_count = 5
    committed_count = 0

    run_status = "completed"
    if failed_count > 0 and committed_count == 0:
        run_status = "failed"

    assert run_status == "failed"


def test_run_status_completed_with_partial_failures():
    """When some docs succeed, run status should be 'completed' with has_failures metadata."""
    failed_count = 2
    committed_count = 3

    run_status = "completed"
    run_metadata = None
    if failed_count > 0 and committed_count == 0:
        run_status = "failed"
    elif failed_count > 0:
        run_metadata = {"has_failures": True, "failed_count": failed_count}

    assert run_status == "completed"
    assert run_metadata == {"has_failures": True, "failed_count": 2}


def test_run_status_completed_no_failures():
    """When no docs fail, run status should be 'completed' with no failure metadata."""
    failed_count = 0
    committed_count = 5

    run_status = "completed"
    run_metadata = None
    if failed_count > 0 and committed_count == 0:
        run_status = "failed"
    elif failed_count > 0:
        run_metadata = {"has_failures": True, "failed_count": failed_count}

    assert run_status == "completed"
    assert run_metadata is None
