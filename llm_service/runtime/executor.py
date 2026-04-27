from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

import aiosqlite

from llm_service.providers.base import ProviderError, ProviderProtocol
from llm_service.runtime.event_bus import EventBus
from llm_service.runtime.parser import ParseResult, parse_output
from llm_service.runtime.task_manager import TaskManager


class Executor:
    def __init__(
        self,
        db: aiosqlite.Connection,
        task_manager: TaskManager,
        event_bus: EventBus,
        provider: ProviderProtocol,
    ):
        self._db = db
        self._mgr = task_manager
        self._bus = event_bus
        self._provider = provider

    async def run(
        self,
        task_id: str,
        messages: list[dict],
        params: dict,
        expected_type: str = "json_object",
        schema: dict | None = None,
    ) -> ParseResult | None:
        """Execute task with retry loop. Returns ParseResult on success, None on exhaustion."""
        # Get or create request row for this task
        cur = await self._db.execute("SELECT id FROM agent_llm_requests WHERE task_id = ?", (task_id,))
        req_row = await cur.fetchone()
        request_id = req_row["id"] if req_row else ""

        while True:
            cur = await self._db.execute("SELECT attempt_count FROM agent_llm_tasks WHERE id = ?", (task_id,))
            task_row = await cur.fetchone()
            if task_row is None:
                return None
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
                # Build response_format hint from expected_type
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
                return parse_result

            except ProviderError as e:
                latency = int((time.monotonic() - start) * 1000)
                finished = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    """UPDATE agent_llm_attempts
                       SET status = 'failed', error_type = ?, error_message = ?, latency_ms = ?, finished_at = ?
                       WHERE id = ?""",
                    (e.error_type, e.message, latency, finished, attempt_id),
                )
                await self._db.commit()

                cur = await self._db.execute("SELECT max_attempts FROM agent_llm_tasks WHERE id = ?", (task_id,))
                t = await cur.fetchone()
                if t is None:
                    return None
                if attempt_no >= t["max_attempts"]:
                    await self._mgr.fail(task_id, e.error_type, e.message)
                    return None
                else:
                    await self._mgr.fail(task_id, e.error_type, e.message)
                    # Read backoff time and sleep before retry
                    cur = await self._db.execute("SELECT available_at FROM agent_llm_tasks WHERE id = ?", (task_id,))
                    row = await cur.fetchone()
                    if row is None:
                        return None
                    available_at = datetime.fromisoformat(row["available_at"])
                    delay = (available_at - datetime.now(timezone.utc)).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(delay)
            except Exception as e:
                latency = int((time.monotonic() - start) * 1000)
                finished = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    """UPDATE agent_llm_attempts
                       SET status = 'failed', error_type = ?, error_message = ?, latency_ms = ?, finished_at = ?
                       WHERE id = ?""",
                    ("unexpected_error", str(e), latency, finished, attempt_id),
                )
                await self._db.commit()

                cur = await self._db.execute("SELECT max_attempts FROM agent_llm_tasks WHERE id = ?", (task_id,))
                t = await cur.fetchone()
                if t is None:
                    return None
                if attempt_no >= t["max_attempts"]:
                    await self._mgr.fail(task_id, "unexpected_error", str(e))
                    return None
                else:
                    await self._mgr.fail(task_id, "unexpected_error", str(e))
                    cur = await self._db.execute("SELECT available_at FROM agent_llm_tasks WHERE id = ?", (task_id,))
                    row = await cur.fetchone()
                    if row is None:
                        return None
                    available_at = datetime.fromisoformat(row["available_at"])
                    delay = (available_at - datetime.now(timezone.utc)).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(delay)
