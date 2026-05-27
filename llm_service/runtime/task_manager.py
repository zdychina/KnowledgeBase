from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from llm_service.db import LlmRuntimeDB
from llm_service.runtime.event_bus import EventBus


class TaskManager:
    def __init__(
        self,
        db: LlmRuntimeDB,
        event_bus: EventBus,
        max_attempts: int = 3,
        lease_duration: int = 300,
        backoff_base: float = 2.0,
        backoff_max: float = 60.0,
    ):
        self._db = db
        self._bus = event_bus
        self._default_max_attempts = max_attempts
        self._lease_duration = lease_duration
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    async def submit(
        self,
        caller_service: str,
        pipeline_stage: str,
        *,
        knowledge_domain: str | None = None,
        task_type: str = "chat",
        idempotency_key: str | None = None,
        max_attempts: int | None = None,
        priority: int = 100,
        metadata: dict | None = None,
    ) -> str:
        from llm_service.runtime.idempotency import find_existing_task

        if idempotency_key:
            existing = await find_existing_task(self._db, idempotency_key)
            if existing:
                return existing

        task_id = await self.insert_task_row(
            caller_service,
            pipeline_stage,
            knowledge_domain=knowledge_domain,
            task_type=task_type,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            priority=priority,
            metadata=metadata,
        )
        await self._bus.emit(task_id, "submitted", "task submitted")
        return task_id

    async def insert_task_row(
        self,
        caller_service: str,
        pipeline_stage: str,
        *,
        knowledge_domain: str | None = None,
        task_type: str = "chat",
        idempotency_key: str | None = None,
        max_attempts: int | None = None,
        priority: int = 100,
        metadata: dict | None = None,
    ) -> str:
        """Insert the task row without emitting events.

        This lets higher-level callers create the task and its request row in
        one transaction before workers can claim it.
        """
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        ma = max_attempts or self._default_max_attempts
        await self._db.execute(
            """INSERT INTO agent_llm_tasks
               (id, caller_service, knowledge_domain, pipeline_stage, task_type,
                idempotency_key, status, priority, available_at, attempt_count, max_attempts,
                created_at, updated_at, metadata_json)
               VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, %s, 0, %s, %s, %s, %s)""",
            (
                task_id, caller_service, knowledge_domain, pipeline_stage, task_type,
                idempotency_key, priority, now, ma,
                now, now, json.dumps(metadata or {}),
            ),
        )
        return task_id

    async def claim(self) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        lease_dt = datetime.now(timezone.utc) + timedelta(seconds=self._lease_duration)
        lease_str = lease_dt.isoformat()

        row = await self._db.fetchone(
            """UPDATE agent_llm_tasks
               SET status = 'running', started_at = %s, lease_expires_at = %s, updated_at = %s
               WHERE id = (
                   SELECT id FROM agent_llm_tasks
                   WHERE status = 'queued' AND available_at <= %s
                   ORDER BY priority DESC, created_at ASC LIMIT 1
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING id""",
            (now, lease_str, now, now),
        )
        if not row:
            return None

        task_id = row["id"]
        await self._bus.emit(task_id, "claimed", "task claimed by worker")
        return task_id

    async def complete(self, task_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE agent_llm_tasks SET status = 'succeeded', attempt_count = attempt_count + 1, finished_at = %s, updated_at = %s WHERE id = %s",
            (now, now, task_id),
        )
        await self._bus.emit(task_id, "succeeded", "task completed")

    async def fail(self, task_id: str, error_type: str, error_message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        row = await self._db.fetchone(
            "SELECT attempt_count, max_attempts FROM agent_llm_tasks WHERE id = %s",
            (task_id,),
        )
        if row is None:
            return
        new_count = row["attempt_count"] + 1

        if new_count < row["max_attempts"]:
            backoff = min(self._backoff_base ** new_count, self._backoff_max)
            available = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            await self._db.execute(
                """UPDATE agent_llm_tasks
                   SET status = 'queued', attempt_count = %s, available_at = %s, updated_at = %s
                   WHERE id = %s""",
                (new_count, available.isoformat(), now, task_id),
            )
            await self._bus.emit(task_id, "retried", f"attempt {new_count} failed: {error_message}")
        else:
            await self._db.execute(
                """UPDATE agent_llm_tasks
                   SET status = 'dead_letter', attempt_count = %s, finished_at = %s, updated_at = %s
                   WHERE id = %s""",
                (new_count, now, now, task_id),
            )
            await self._bus.emit(task_id, "dead_letter", f"exhausted after {new_count} attempts: {error_message}")

    async def cancel(self, task_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE agent_llm_tasks SET status = 'cancelled', finished_at = %s, updated_at = %s "
                "WHERE id = %s AND status = 'queued'",
                (now, now, task_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Task {task_id} cannot be cancelled (not in 'queued' status)")
        await self._bus.emit(task_id, "cancelled", "task cancelled")
