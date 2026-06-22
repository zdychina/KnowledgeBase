"""Tests for runtime/idempotency.py::find_existing_task.

These tests lock down the status-priority semantics so that refactors of
LLMService._submit_with_idempotency (which should delegate here) cannot
silently change behavior.
"""
import pytest

from llm_service.runtime.idempotency import find_existing_task


class _FakeDB:
    """Minimal stub: maps (idempotency_key, status) -> ordered list of task_ids.

    `fetchone` returns the first row configured for that (key, status) pair,
    or None.
    """

    def __init__(self, rows: dict[tuple[str, str], list[str]]):
        self._rows = rows
        self.queries: list[tuple[str, str]] = []

    async def fetchone(self, sql, params):
        key, status = params
        self.queries.append((key, status))
        ids = self._rows.get((key, status), [])
        return {"id": ids[0]} if ids else None


pytestmark = pytest.mark.asyncio


async def test_find_existing_task_prefers_succeeded_over_running_and_queued():
    """All three statuses exist → succeeded wins."""
    db = _FakeDB({
        ("k1", "succeeded"): ["t-succ"],
        ("k1", "running"): ["t-run"],
        ("k1", "queued"): ["t-q"],
    })
    result = await find_existing_task(db, "k1")
    assert result == "t-succ"
    # Must short-circuit on first hit — should not query running/queued
    assert db.queries == [("k1", "succeeded")]


async def test_find_existing_task_falls_back_to_running():
    db = _FakeDB({
        ("k1", "running"): ["t-run"],
        ("k1", "queued"): ["t-q"],
    })
    result = await find_existing_task(db, "k1")
    assert result == "t-run"
    assert db.queries == [("k1", "succeeded"), ("k1", "running")]


async def test_find_existing_task_falls_back_to_queued():
    db = _FakeDB({("k1", "queued"): ["t-q"]})
    result = await find_existing_task(db, "k1")
    assert result == "t-q"
    assert db.queries == [("k1", "succeeded"), ("k1", "running"), ("k1", "queued")]


async def test_find_existing_task_returns_none_when_only_terminal():
    """failed / dead_letter / cancelled are never queried → returns None."""
    db = _FakeDB({})  # no active rows; only terminal states exist in real DB
    result = await find_existing_task(db, "k1")
    assert result is None
    # The function never queries terminal states
    assert ("k1", "failed") not in db.queries
    assert ("k1", "dead_letter") not in db.queries
    assert ("k1", "cancelled") not in db.queries


async def test_find_existing_task_returns_none_for_unknown_key():
    db = _FakeDB({})
    result = await find_existing_task(db, "never-seen")
    assert result is None
    assert len(db.queries) == 3  # all three active statuses checked


async def test_find_existing_task_picks_latest_within_status():
    """ORDER BY created_at DESC means the first row returned is the latest."""
    db = _FakeDB({("k1", "succeeded"): ["latest-id", "older-id"]})
    result = await find_existing_task(db, "k1")
    assert result == "latest-id"
