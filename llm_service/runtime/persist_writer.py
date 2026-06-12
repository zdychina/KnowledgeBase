"""Background writer that persists sync-call records in batches.

Sync endpoints (execute, embed, rerank) push lightweight dataclass records
into an in-memory queue.  One or more PersistWriter coroutines drain the
queue and write to PostgreSQL in batches, completely outside the request
hot path.

Design choices:
  - Queue full → discard (sync latency > observability).
  - Batch flush every `flush_interval` seconds OR when `batch_size` records
    accumulate, whichever comes first.
  - Each record is a self-contained SQL payload so the writer does not need
    to know about provider / service internals.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from llm_service.db import LlmRuntimeDB

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Record types — one per sync-call shape
# ---------------------------------------------------------------------------

@dataclass
class SyncChatRecord:
    """Payload produced by LLMService.execute()."""

    task_id: str
    request_id: str
    attempt_id: str
    result_id: str
    caller_service: str
    knowledge_domain: str | None
    pipeline_stage: str
    idempotency_key: str | None
    template_key: str | None
    provider_name: str
    model: str
    messages_json: str
    input_json: str
    params_json: str
    expected_output_type: str
    output_schema_json: str
    final_status: str
    effective_priority: int
    max_attempts: int
    now: str
    lease_dt: str
    metadata_json: str
    # attempt fields
    raw_output_text: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    raw_response_json: str = "{}"
    error_type: str | None = None
    error_message: str | None = None
    # result fields
    parse_status: str = "not_required"
    parsed_output_json: str = "{}"
    text_output: str = ""
    parse_error: str | None = None
    validation_errors_json: str = "[]"


@dataclass
class SyncModelRecord:
    """Payload produced by ModelService embed()/rerank()."""

    task_type: str  # "embedding" | "rerank"
    model: str
    caller_service: str
    knowledge_domain: str | None
    pipeline_stage: str
    status: str
    latency_ms: int | None
    total_tokens: int | None
    input_json: str  # already serialized
    raw_response_json: str = "{}"
    text_output: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    now: str = ""


# Union type for queue items
PersistRecord = SyncChatRecord | SyncModelRecord


# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------

_CHAT_SQL = """\
INSERT INTO agent_llm_tasks
  (id, caller_service, knowledge_domain, pipeline_stage, task_type,
   idempotency_key, status, priority, available_at, attempt_count, max_attempts,
   created_at, updated_at, started_at, finished_at, lease_expires_at, metadata_json)
VALUES (%s, %s, %s, %s, 'chat', %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s)
"""

_CHAT_REQUEST_SQL = """\
INSERT INTO agent_llm_requests
  (id, task_id, provider, model, prompt_template_key, messages_json, input_json,
   params_json, expected_output_type, output_schema_json, created_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CHAT_ATTEMPT_OK_SQL = """\
INSERT INTO agent_llm_attempts
  (id, task_id, request_id, attempt_no, status, started_at, finished_at,
   raw_output_text, prompt_tokens, completion_tokens, total_tokens,
   latency_ms, raw_response_json)
VALUES (%s, %s, %s, 1, 'succeeded', %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CHAT_ATTEMPT_FAIL_SQL = """\
INSERT INTO agent_llm_attempts
  (id, task_id, request_id, attempt_no, status, started_at, finished_at,
   raw_output_text, prompt_tokens, completion_tokens, total_tokens,
   latency_ms, raw_response_json, error_type, error_message)
VALUES (%s, %s, %s, 1, 'failed', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CHAT_RESULT_SQL = """\
INSERT INTO agent_llm_results
  (id, task_id, attempt_id, parse_status, parsed_output_json, text_output,
   parse_error, validation_errors_json, created_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _model_task_sql() -> str:
    return """\
INSERT INTO agent_llm_tasks
  (id, caller_service, knowledge_domain, pipeline_stage, task_type, status,
   priority, attempt_count, max_attempts,
   created_at, updated_at, started_at, finished_at, metadata_json)
VALUES (%s, %s, %s, %s, %s, %s, 100, 1, 1, %s, %s, %s, %s, '{}')
"""


def _model_request_sql() -> str:
    return """\
INSERT INTO agent_llm_requests
  (id, task_id, provider, model, messages_json, input_json,
   params_json, expected_output_type, output_schema_json, created_at, metadata_json)
VALUES (%s, %s, 'sync', %s, '[]', %s, '{}', 'text', '{}', %s, '{}')
"""


def _model_attempt_sql() -> str:
    return """\
INSERT INTO agent_llm_attempts
  (id, task_id, request_id, attempt_no, status,
   total_tokens, latency_ms, started_at, finished_at,
   raw_response_json, error_type, error_message, metadata_json)
VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, '{}')
"""


def _model_result_sql() -> str:
    return """\
INSERT INTO agent_llm_results
  (id, task_id, attempt_id, parse_status, parsed_output_json,
   text_output, parse_error, validation_errors_json, created_at, metadata_json)
VALUES (%s, %s, %s, 'not_required', %s, %s, NULL, '[]', %s, '{}')
"""


def _model_call_sql() -> str:
    return """\
INSERT INTO agent_llm_model_calls
  (id, call_type, model, caller_service, knowledge_domain, pipeline_stage,
   input_count, status, latency_ms, token_usage, error_message, created_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


# ---------------------------------------------------------------------------
# PersistWriter
# ---------------------------------------------------------------------------

class PersistWriter:
    """Drains a queue of PersistRecord and writes them to PostgreSQL."""

    def __init__(
        self,
        db: LlmRuntimeDB,
        *,
        queue_size: int = 10000,
        batch_size: int = 20,
        flush_interval: float = 0.5,
        writer_count: int = 1,
    ) -> None:
        self._db = db
        self._queue: asyncio.Queue[PersistRecord | None] = asyncio.Queue(maxsize=queue_size)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._writer_count = writer_count
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._dropped = 0

    # -- public API (called by sync handlers) ------------------------------

    def enqueue(self, record: PersistRecord) -> bool:
        """Try to enqueue a record. Returns False if dropped (queue full)."""
        try:
            self._queue.put_nowait(record)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped <= 10 or self._dropped % 1000 == 0:
                logger.warning(
                    "PersistWriter queue full, dropped record (total_dropped=%d)",
                    self._dropped,
                )
            return False

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        for i in range(self._writer_count):
            t = asyncio.create_task(self._writer_loop(f"persist-{i}"), name=f"persist-{i}")
            self._tasks.append(t)
        logger.info(
            "PersistWriter started (writers=%d, batch=%d, flush=%.1fs, queue=%d)",
            self._writer_count, self._batch_size, self._flush_interval,
            self._queue.maxsize,
        )

    async def stop(self) -> None:
        self._running = False
        # Drain remaining items before cancelling
        await self._flush_all()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("PersistWriter stopped (total_dropped=%d)", self._dropped)

    # -- internals ----------------------------------------------------------

    async def _writer_loop(self, name: str) -> None:
        while self._running:
            try:
                batch: list[PersistRecord] = []
                # Wait for first item
                try:
                    item = await asyncio.wait_for(
                        self._queue.get(), timeout=self._flush_interval,
                    )
                    if item is None:
                        continue
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass

                # Collect more items up to batch_size (non-blocking)
                while len(batch) < self._batch_size:
                    try:
                        item = self._queue.get_nowait()
                        if item is None:
                            continue
                        batch.append(item)
                    except asyncio.QueueEmpty:
                        break

                if batch:
                    await self._write_batch(batch)

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("%s error", name)
                await asyncio.sleep(1.0)

    async def _flush_all(self) -> None:
        """Drain everything left in the queue."""
        batch: list[PersistRecord] = []
        for _ in range(self._queue.maxsize + self._writer_count):
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    batch.append(item)
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._write_batch(batch)

    async def _write_batch(self, batch: list[PersistRecord]) -> None:
        """Write a batch of records. Each record gets its own transaction."""
        for record in batch:
            try:
                if isinstance(record, SyncChatRecord):
                    await self._write_chat(record)
                elif isinstance(record, SyncModelRecord):
                    await self._write_model(record)
            except Exception:
                logger.exception(
                    "PersistWriter failed to write record (type=%s)",
                    type(record).__name__,
                )

    async def _write_chat(self, r: SyncChatRecord) -> None:
        async with self._db.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    _CHAT_SQL,
                    (
                        r.task_id, r.caller_service, r.knowledge_domain,
                        r.pipeline_stage, r.idempotency_key, r.final_status,
                        r.effective_priority, r.now, r.max_attempts,
                        r.now, r.now, r.now, r.now, r.lease_dt, r.metadata_json,
                    ),
                )
                await conn.execute(
                    _CHAT_REQUEST_SQL,
                    (
                        r.request_id, r.task_id, r.provider_name, r.model,
                        r.template_key, r.messages_json, r.input_json,
                        r.params_json, r.expected_output_type,
                        r.output_schema_json, r.now,
                    ),
                )
                if r.final_status == "succeeded":
                    await conn.execute(
                        _CHAT_ATTEMPT_OK_SQL,
                        (
                            r.attempt_id, r.task_id, r.request_id, r.now, r.now,
                            r.raw_output_text, r.prompt_tokens, r.completion_tokens,
                            r.total_tokens, r.latency_ms, r.raw_response_json,
                        ),
                    )
                else:
                    await conn.execute(
                        _CHAT_ATTEMPT_FAIL_SQL,
                        (
                            r.attempt_id, r.task_id, r.request_id, r.now, r.now,
                            r.raw_output_text, r.prompt_tokens, r.completion_tokens,
                            r.total_tokens, r.latency_ms, r.raw_response_json,
                            r.error_type, r.error_message,
                        ),
                    )
                await conn.execute(
                    _CHAT_RESULT_SQL,
                    (
                        r.result_id, r.task_id, r.attempt_id, r.parse_status,
                        r.parsed_output_json, r.text_output, r.parse_error,
                        r.validation_errors_json, r.now,
                    ),
                )

    async def _write_model(self, r: SyncModelRecord) -> None:
        now = r.now if hasattr(r, "now") else datetime.now(timezone.utc).isoformat()
        task_id = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        attempt_id = uuid.uuid4().hex

        input_data = json.loads(r.input_json) if isinstance(r.input_json, str) else r.input_json
        input_count = len(input_data.get("texts") or input_data.get("documents") or [])

        async with self._db.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    _model_task_sql(),
                    (
                        task_id, r.caller_service, r.knowledge_domain,
                        r.pipeline_stage, r.task_type, r.status,
                        now, now, now, now,
                    ),
                )
                await conn.execute(
                    _model_request_sql(),
                    (
                        request_id, task_id, r.model,
                        r.input_json, now,
                    ),
                )
                await conn.execute(
                    _model_attempt_sql(),
                    (
                        attempt_id, task_id, request_id, r.status,
                        r.total_tokens, r.latency_ms, now, now,
                        r.raw_response_json, r.error_type, r.error_message,
                    ),
                )
                if r.status == "succeeded":
                    await conn.execute(
                        _model_result_sql(),
                        (
                            uuid.uuid4().hex, task_id, attempt_id,
                            r.raw_response_json, r.text_output, now,
                        ),
                    )
                await conn.execute(
                    _model_call_sql(),
                    (
                        uuid.uuid4().hex, r.task_type, r.model,
                        r.caller_service, r.knowledge_domain, r.pipeline_stage,
                        input_count, r.status, r.latency_ms,
                        r.total_tokens, r.error_message, now,
                    ),
                )
