"""Background worker that claims and executes queued tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone

import aiosqlite

from llm_service.providers.base import ProviderProtocol
from llm_service.providers.model_base import ModelProviderProtocol
from llm_service.providers.utils import extract_doc_text
from llm_service.runtime.event_bus import EventBus
from llm_service.runtime.parser import parse_output
from llm_service.runtime.task_manager import TaskManager
from llm_service.runtime.template_registry import TemplateRegistry

logger = logging.getLogger(__name__)


class Worker:
    """Background worker loop: continuously claim → execute → complete/fail."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        task_manager: TaskManager,
        event_bus: EventBus,
        provider: ProviderProtocol,
        model_provider: ModelProviderProtocol | None = None,
        templates: TemplateRegistry | None = None,
        concurrency: int = 4,
        poll_interval: float = 1.0,
    ):
        self._db = db
        self._mgr = task_manager
        self._bus = event_bus
        self._provider = provider
        self._model_provider = model_provider
        self._templates = templates
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._running = True
        for i in range(self._concurrency):
            t = asyncio.create_task(self._loop(f"worker-{i}"))
            self._tasks.append(t)
        logger.info("Worker started with %d concurrency", self._concurrency)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Worker stopped")

    async def _loop(self, name: str) -> None:
        while self._running:
            try:
                task_id = await self._mgr.claim()
                if task_id:
                    await self._execute_task(task_id)
                else:
                    await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                return
            except sqlite3.OperationalError as e:
                if "database is locked" not in str(e).lower():
                    logger.exception("%s database error: %s", name, e)
                else:
                    logger.warning("%s claim skipped because sqlite writer is busy", name)
                await asyncio.sleep(self._poll_interval)
            except Exception as e:
                logger.exception("%s error: %s", name, e)
                await asyncio.sleep(self._poll_interval)

    async def _execute_task(self, task_id: str) -> None:
        """Dispatch to the correct executor based on task_type."""
        cur = await self._db.execute("SELECT task_type FROM agent_llm_tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        if not row:
            await self._mgr.fail(task_id, "missing_task", "task row not found")
            return
        task_type = row["task_type"]

        if task_type == "chat":
            await self._execute_chat(task_id)
        elif task_type == "embedding":
            await self._execute_embedding(task_id)
        elif task_type == "rerank":
            await self._execute_rerank(task_id)
        else:
            await self._mgr.fail(task_id, "unknown_task_type", f"unsupported task_type: {task_type}")

    # ------------------------------------------------------------------
    # Chat execution (original logic)
    # ------------------------------------------------------------------

    async def _execute_chat(self, task_id: str) -> None:
        """Execute a chat task: read request → call provider → parse → complete/fail."""
        cur = await self._db.execute("SELECT * FROM agent_llm_requests WHERE task_id = ?", (task_id,))
        req = await cur.fetchone()
        if not req:
            await self._mgr.fail(task_id, "missing_request", "no request row found")
            return

        messages = json.loads(req["messages_json"] or "[]")
        params = json.loads(req["params_json"] or "{}")
        expected_type = req["expected_output_type"]
        schema = json.loads(req["output_schema_json"] or "{}") or None
        request_id = req["id"]

        attempt_no = 0
        while True:
            cur = await self._db.execute("SELECT attempt_count, max_attempts FROM agent_llm_tasks WHERE id = ?", (task_id,))
            task_row = await cur.fetchone()
            if not task_row:
                return
            attempt_no = task_row["attempt_count"] + 1

            attempt_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                """INSERT INTO agent_llm_attempts
                   (id, task_id, request_id, attempt_no, status, started_at)
                   VALUES (?, ?, ?, ?, 'running', ?)""",
                (attempt_id, task_id, request_id, attempt_no, now),
            )
            await self._db.commit()

            start = time.monotonic()
            try:
                response_format = (
                    {"type": "json_object"}
                    if expected_type in ("json_object", "json_array")
                    else None
                )
                resp = await self._provider.complete(
                    messages=messages, params=params,
                    response_format=response_format,
                )
                latency = int((time.monotonic() - start) * 1000)
                finished = datetime.now(timezone.utc).isoformat()

                await self._db.execute(
                    """UPDATE agent_llm_attempts
                       SET status = 'succeeded', raw_output_text = ?, prompt_tokens = ?,
                           completion_tokens = ?, total_tokens = ?, latency_ms = ?, finished_at = ?,
                           raw_response_json = ?
                       WHERE id = ?""",
                    (
                        resp.output_text, resp.prompt_tokens, resp.completion_tokens,
                        resp.total_tokens, latency, finished,
                        json.dumps(resp.raw_response or {}), attempt_id,
                    ),
                )
                await self._db.commit()

                parse_result = parse_output(resp.output_text, expected_type, schema)

                result_id = str(uuid.uuid4())
                await self._db.execute(
                    """INSERT INTO agent_llm_results
                       (id, task_id, attempt_id, parse_status, parsed_output_json, text_output,
                        parse_error, validation_errors_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result_id, task_id, attempt_id, parse_result.parse_status,
                        json.dumps(parse_result.parsed_output if parse_result.parsed_output is not None else {}),
                        parse_result.text_output, parse_result.parse_error,
                        json.dumps(parse_result.validation_errors),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                await self._db.commit()

                await self._mgr.complete(task_id)
                return

            except Exception as e:
                latency = int((time.monotonic() - start) * 1000)
                finished = datetime.now(timezone.utc).isoformat()
                error_type = getattr(e, "error_type", "unexpected_error")
                error_msg = str(e)

                await self._db.execute(
                    """UPDATE agent_llm_attempts
                       SET status = 'failed', error_type = ?, error_message = ?, latency_ms = ?, finished_at = ?
                       WHERE id = ?""",
                    (error_type, error_msg, latency, finished, attempt_id),
                )
                await self._db.commit()

                await self._mgr.fail(task_id, error_type, error_msg)
                return

    # ------------------------------------------------------------------
    # Embedding execution
    # ------------------------------------------------------------------

    async def _execute_embedding(self, task_id: str) -> None:
        """Execute an embedding task: read input → call model provider → store result."""
        if not self._model_provider:
            await self._mgr.fail(task_id, "no_model_provider", "model_provider not configured")
            return

        cur = await self._db.execute("SELECT * FROM agent_llm_requests WHERE task_id = ?", (task_id,))
        req = await cur.fetchone()
        if not req:
            await self._mgr.fail(task_id, "missing_request", "no request row found")
            return

        input_data = json.loads(req["input_json"] or "{}")
        texts = input_data.get("texts", [])
        model = input_data.get("model")
        dimensions = input_data.get("dimensions")
        request_id = req["id"]

        cur = await self._db.execute("SELECT attempt_count, max_attempts FROM agent_llm_tasks WHERE id = ?", (task_id,))
        task_row = await cur.fetchone()
        if not task_row:
            return
        attempt_no = task_row["attempt_count"] + 1

        attempt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO agent_llm_attempts
               (id, task_id, request_id, attempt_no, status, started_at)
               VALUES (?, ?, ?, ?, 'running', ?)""",
            (attempt_id, task_id, request_id, attempt_no, now),
        )
        await self._db.commit()

        start = time.monotonic()
        try:
            result = await self._model_provider.embed(texts, model=model, dimensions=dimensions)
            latency = int((time.monotonic() - start) * 1000)
            finished = datetime.now(timezone.utc).isoformat()

            token_usage = 0
            if result.get("usage"):
                token_usage = result["usage"].get("total_tokens", 0)

            await self._db.execute(
                """UPDATE agent_llm_attempts
                   SET status = 'succeeded', total_tokens = ?, latency_ms = ?, finished_at = ?,
                       raw_response_json = ?
                   WHERE id = ?""",
                (token_usage, latency, finished, json.dumps(result), attempt_id),
            )
            await self._db.commit()

            # text_output: source texts for dashboard visibility
            text_output = "\n".join(texts)

            result_id = str(uuid.uuid4())
            await self._db.execute(
                """INSERT INTO agent_llm_results
                   (id, task_id, attempt_id, parse_status, parsed_output_json, text_output,
                    parse_error, validation_errors_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result_id, task_id, attempt_id, "not_required",
                    json.dumps(result), text_output, None, "[]",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await self._db.commit()

            await self._mgr.complete(task_id)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            finished = datetime.now(timezone.utc).isoformat()
            error_type = getattr(e, "error_type", "unexpected_error")
            error_msg = str(e)

            await self._db.execute(
                """UPDATE agent_llm_attempts
                   SET status = 'failed', error_type = ?, error_message = ?, latency_ms = ?, finished_at = ?
                   WHERE id = ?""",
                (error_type, error_msg, latency, finished, attempt_id),
            )
            await self._db.commit()

            await self._mgr.fail(task_id, error_type, error_msg)

    # ------------------------------------------------------------------
    # Rerank execution
    # ------------------------------------------------------------------

    async def _execute_rerank(self, task_id: str) -> None:
        """Execute a rerank task: read input → call model provider → store result."""
        if not self._model_provider:
            await self._mgr.fail(task_id, "no_model_provider", "model_provider not configured")
            return

        cur = await self._db.execute("SELECT * FROM agent_llm_requests WHERE task_id = ?", (task_id,))
        req = await cur.fetchone()
        if not req:
            await self._mgr.fail(task_id, "missing_request", "no request row found")
            return

        input_data = json.loads(req["input_json"] or "{}")
        query = input_data.get("query", "")
        documents = input_data.get("documents", [])
        model = input_data.get("model")
        top_n = input_data.get("top_n")
        request_id = req["id"]

        cur = await self._db.execute("SELECT attempt_count, max_attempts FROM agent_llm_tasks WHERE id = ?", (task_id,))
        task_row = await cur.fetchone()
        if not task_row:
            return
        attempt_no = task_row["attempt_count"] + 1

        attempt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO agent_llm_attempts
               (id, task_id, request_id, attempt_no, status, started_at)
               VALUES (?, ?, ?, ?, 'running', ?)""",
            (attempt_id, task_id, request_id, attempt_no, now),
        )
        await self._db.commit()

        start = time.monotonic()
        try:
            result = await self._model_provider.rerank(query, documents, model=model, top_n=top_n)
            latency = int((time.monotonic() - start) * 1000)
            finished = datetime.now(timezone.utc).isoformat()

            token_usage = result.get("usage", {}).get("total_tokens", 0)

            await self._db.execute(
                """UPDATE agent_llm_attempts
                   SET status = 'succeeded', total_tokens = ?, latency_ms = ?, finished_at = ?,
                       raw_response_json = ?
                   WHERE id = ?""",
                (token_usage, latency, finished, json.dumps(result), attempt_id),
            )
            await self._db.commit()

            # text_output: query + reranked results summary for dashboard
            lines = [f"Query: {query}"]
            for r in result.get("results", []):
                score = r.get("relevance_score", 0)
                doc = extract_doc_text(r.get("document"))[:100]
                lines.append(f"  [{r.get('index', '?')}] score={score:.4f}: {doc}")
            text_output = "\n".join(lines)

            result_id = str(uuid.uuid4())
            await self._db.execute(
                """INSERT INTO agent_llm_results
                   (id, task_id, attempt_id, parse_status, parsed_output_json, text_output,
                    parse_error, validation_errors_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result_id, task_id, attempt_id, "not_required",
                    json.dumps(result), text_output, None, "[]",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await self._db.commit()

            await self._mgr.complete(task_id)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            finished = datetime.now(timezone.utc).isoformat()
            error_type = getattr(e, "error_type", "unexpected_error")
            error_msg = str(e)

            await self._db.execute(
                """UPDATE agent_llm_attempts
                   SET status = 'failed', error_type = ?, error_message = ?, latency_ms = ?, finished_at = ?
                   WHERE id = ?""",
                (error_type, error_msg, latency, finished, attempt_id),
            )
            await self._db.commit()

            await self._mgr.fail(task_id, error_type, error_msg)


class LeaseRecovery:
    """Periodically scans for running tasks whose lease has expired and re-queues them."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        task_manager: TaskManager,
        event_bus: EventBus,
        interval: float = 30.0,
    ):
        self._db = db
        self._mgr = task_manager
        self._bus = event_bus
        self._interval = interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("LeaseRecovery started (interval=%.1fs)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("LeaseRecovery stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._recover()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.exception("LeaseRecovery error: %s", e)
            await asyncio.sleep(self._interval)

    async def _recover(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = await self._db.execute(
            """SELECT id, attempt_count, max_attempts FROM agent_llm_tasks
               WHERE status = 'running' AND lease_expires_at < ?""",
            (now,),
        )
        expired = await cur.fetchall()
        if not expired:
            return

        for row in expired:
            task_id = row["id"]
            attempt_count = row["attempt_count"]
            max_attempts = row["max_attempts"]

            # Mark the hanging attempt as failed (if any)
            await self._db.execute(
                """UPDATE agent_llm_attempts SET status = 'failed', error_type = 'lease_expired',
                   error_message = 'lease expired, recovered by lease recovery'
                   WHERE task_id = ? AND status = 'running'""",
                (task_id,),
            )
            await self._db.commit()

            if attempt_count < max_attempts:
                # Re-queue with backoff
                await self._mgr.fail(task_id, "lease_expired", "lease expired, re-queued")
                logger.info("LeaseRecovery: re-queued task %s", task_id[:8])
            else:
                # Exhausted → dead_letter
                await self._mgr.fail(task_id, "lease_expired", "lease expired, exhausted")
                logger.info("LeaseRecovery: dead_lettered task %s", task_id[:8])
