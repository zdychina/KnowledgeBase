"""Background worker that claims and executes queued tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import aiosqlite

from llm_service.providers.base import ProviderProtocol
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
        templates: TemplateRegistry,
        concurrency: int = 4,
        poll_interval: float = 1.0,
    ):
        self._db = db
        self._mgr = task_manager
        self._bus = event_bus
        self._provider = provider
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
            except Exception as e:
                logger.exception("%s error: %s", name, e)
                await asyncio.sleep(self._poll_interval)

    async def _execute_task(self, task_id: str) -> None:
        """Execute a claimed task: read request → call provider → parse → complete/fail."""
        # Read request data
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
                resp = await self._provider.complete(messages=messages, params=params)
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

                # fail() handles re-queue vs dead_letter based on attempt_count/max_attempts
                await self._mgr.fail(task_id, error_type, error_msg)
                # Return to _loop, which will re-claim after backoff (task is re-queued)
                return


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
