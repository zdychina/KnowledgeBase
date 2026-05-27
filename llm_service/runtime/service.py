from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from string import Template

from llm_service.config import LLMServiceConfig
from llm_service.db import LlmRuntimeDB
from llm_service.providers.base import ProviderProtocol
from llm_service.providers.model_base import ModelProviderProtocol
from llm_service.runtime.event_bus import EventBus
from llm_service.runtime.parser import ParseResult, parse_output
from llm_service.runtime.task_manager import TaskManager
from llm_service.runtime.template_registry import TemplateRegistry


logger = logging.getLogger(__name__)


class LLMService:
    """Top-level orchestrator: owns task_manager, event_bus, provider, templates."""

    def __init__(
        self,
        db: LlmRuntimeDB,
        provider: ProviderProtocol,
        config: LLMServiceConfig,
        model_provider: ModelProviderProtocol | None = None,
    ):
        self._db = db
        self._config = config
        self._bus = EventBus(db)
        self._submit_lock = asyncio.Lock()
        self._mgr = TaskManager(
            db, self._bus,
            max_attempts=config.default_max_attempts,
            lease_duration=config.lease_duration,
            backoff_base=config.retry_backoff_base,
            backoff_max=config.retry_backoff_max,
        )
        self._templates = TemplateRegistry(db)
        self._model_provider = model_provider
        self._provider = provider
        # Store provider info for request recording
        self._provider_name = getattr(provider, 'provider_name', 'unknown')
        self._default_model = getattr(provider, 'default_model', config.provider_model)

    # ------------------------------------------------------------------
    # Template resolution
    # ------------------------------------------------------------------

    async def _resolve_template(
        self,
        template_key: str | None,
        knowledge_domain: str | None,
        input: dict | None,
        messages: list[dict] | None,
        expected_output_type: str | None,
        output_schema: dict | None,
    ) -> dict:
        """If template_key is given, expand template into messages/schema.

        Caller-provided messages/schema take precedence over template defaults.
        """
        result = {
            "messages": messages,
            "expected_output_type": expected_output_type,
            "output_schema": output_schema,
        }
        if not template_key:
            return result

        tpl = await self._templates.get_by_key(template_key, knowledge_domain)
        if not tpl:
            return result

        # Build messages from template if caller didn't provide them
        if not messages:
            msgs = []
            if tpl.get("system_prompt"):
                msgs.append({"role": "system", "content": tpl["system_prompt"]})
            user_content = tpl.get("user_prompt_template", "")
            if input:
                tmpl = Template(user_content)
                user_content = tmpl.safe_substitute(input)
            msgs.append({"role": "user", "content": user_content})
            result["messages"] = msgs

        # Template expected_output_type as fallback when caller didn't specify
        if expected_output_type is None and tpl.get("expected_output_type"):
            result["expected_output_type"] = tpl["expected_output_type"]

        # Template schema as fallback
        if not output_schema and tpl.get("output_schema_json"):
            schema_raw = tpl["output_schema_json"]
            if isinstance(schema_raw, str):
                try:
                    result["output_schema"] = json.loads(schema_raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(schema_raw, dict):
                result["output_schema"] = schema_raw

        # Inject output schema into messages so LLM sees the constraint
        self._inject_schema_into_messages(result)

        return result

    @staticmethod
    def _inject_schema_into_messages(result: dict) -> None:
        """Append JSON Schema to system prompt so LLM generates conformant output."""
        schema = result.get("output_schema")
        expected_type = result.get("expected_output_type")
        msgs = result.get("messages")
        if not schema or expected_type not in ("json_object", "json_array") or not msgs:
            return

        schema_instruction = (
            "\n\n【输出格式定义（JSON Schema，这是格式规范，不要原样输出这段定义）】\n"
            "你的输出必须符合以下 JSON Schema 结构定义：\n"
            + json.dumps(schema, indent=2, ensure_ascii=False)
            + "\n\n注意：上面的 JSON Schema 是格式规范说明，不是你要输出的内容。"
            "请直接输出符合该格式的 JSON 数据，不要输出 Schema 定义本身。"
        )
        new_msgs = []
        injected = False
        for msg in msgs:
            if msg.get("role") == "system" and not injected:
                new_msgs.append({**msg, "content": msg["content"] + schema_instruction})
                injected = True
            else:
                new_msgs.append(msg)
        if not injected:
            new_msgs.insert(0, {"role": "system", "content": schema_instruction.strip()})
        result["messages"] = new_msgs

    # ------------------------------------------------------------------
    # Shared chat execution (used by both Worker and sync /execute)
    # ------------------------------------------------------------------

    async def execute_chat_attempt(
        self,
        task_id: str,
        request_id: str,
        messages: list[dict],
        params: dict,
        expected_type: str,
        schema: dict | None,
    ) -> ParseResult:
        """Execute a single chat attempt: call provider -> parse -> write result.

        On parse success: calls _mgr.complete() and returns ParseResult.
        On parse failure: calls _mgr.fail() (triggers retry) and raises RuntimeError.
        On provider error: writes failed attempt, calls _mgr.fail(), raises the exception.
        On pre-attempt error: calls _mgr.fail(), raises RuntimeError.
        """
        attempt_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            task_row = await self._db.fetchone(
                "SELECT attempt_count FROM agent_llm_tasks WHERE id = %s", (task_id,)
            )
            if not task_row:
                raise RuntimeError("task not found")
            attempt_no = task_row["attempt_count"] + 1

            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                """INSERT INTO agent_llm_attempts
                   (id, task_id, request_id, attempt_no, status, started_at)
                   VALUES (%s, %s, %s, %s, 'running', %s)""",
                (attempt_id, task_id, request_id, attempt_no, now),
            )
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
                   SET status = 'succeeded', raw_output_text = %s, prompt_tokens = %s,
                       completion_tokens = %s, total_tokens = %s, latency_ms = %s, finished_at = %s,
                       raw_response_json = %s
                   WHERE id = %s""",
                (
                    resp.output_text, resp.prompt_tokens, resp.completion_tokens,
                    resp.total_tokens, latency, finished,
                    json.dumps(resp.raw_response or {}), attempt_id,
                ),
            )

            parse_result = parse_output(resp.output_text, expected_type, schema)

            # Always write result row (contains parse_error for debugging)
            result_id = str(uuid.uuid4())
            await self._db.execute(
                """INSERT INTO agent_llm_results
                   (id, task_id, attempt_id, parse_status, parsed_output_json, text_output,
                    parse_error, validation_errors_json, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    result_id, task_id, attempt_id, parse_result.parse_status,
                    json.dumps(parse_result.parsed_output if parse_result.parsed_output is not None else {}),
                    parse_result.text_output, parse_result.parse_error,
                    json.dumps(parse_result.validation_errors),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            if parse_result.parse_status == "succeeded":
                await self._mgr.complete(task_id)
            else:
                # Mark attempt as failed (parse error, not provider error)
                await self._db.execute(
                    """UPDATE agent_llm_attempts
                       SET status = 'failed', error_type = 'parse_failed', error_message = %s
                       WHERE id = %s""",
                    (parse_result.parse_error or f"parse_status={parse_result.parse_status}", attempt_id),
                )
                await self._mgr.fail(
                    task_id, "parse_failed",
                    parse_result.parse_error or f"parse_status={parse_result.parse_status}",
                )
                raise RuntimeError(
                    f"parse_failed: {parse_result.parse_error or parse_result.parse_status}"
                )
            return parse_result

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            finished = datetime.now(timezone.utc).isoformat()
            error_type = getattr(e, "error_type", "unexpected_error")
            error_msg = str(e)

            # Only update attempt if it was inserted (may fail if pre-attempt errored)
            try:
                await self._db.execute(
                    """UPDATE agent_llm_attempts
                       SET status = 'failed', error_type = %s, error_message = %s, latency_ms = %s, finished_at = %s
                       WHERE id = %s""",
                    (error_type, error_msg, latency, finished, attempt_id),
                )
            except Exception:
                logger.exception("Failed to update attempt %s on error", attempt_id[:8])
            await self._mgr.fail(task_id, error_type, error_msg)
            raise

    # ------------------------------------------------------------------
    # Common submit with idempotency
    # ------------------------------------------------------------------

    async def _submit_with_idempotency(
        self,
        idempotency_key: str | None,
        task_type: str,
        caller_service: str,
        knowledge_domain: str | None,
        pipeline_stage: str,
        request_params: tuple,
        event_message: str,
        *,
        max_attempts: int = 3,
        priority: int = 100,
        metadata: dict | None = None,
    ) -> str:
        """Generic idempotent submit: check key -> insert task + request -> emit event."""
        async with self._submit_lock:
            if idempotency_key:
                row = await self._db.fetchone(
                    """SELECT id FROM agent_llm_tasks
                       WHERE idempotency_key = %s
                         AND status NOT IN ('failed', 'dead_letter', 'cancelled')
                       ORDER BY created_at DESC
                       LIMIT 1""",
                    (idempotency_key,),
                )
                if row:
                    return row["id"]

            # Use a transaction for task + request insert
            async with self._db.pool.connection() as conn:
                async with conn.transaction():
                    task_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    ma = max_attempts

                    await conn.execute(
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

                    request_id = str(uuid.uuid4())
                    await conn.execute(
                        """INSERT INTO agent_llm_requests
                           (id, task_id, provider, model, prompt_template_key, messages_json, input_json,
                            params_json, expected_output_type, output_schema_json, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (request_id, task_id, *request_params, now),
                    )

            await self._bus.emit(task_id, "submitted", event_message)
            return task_id

    # ------------------------------------------------------------------
    # Submit (async)
    # ------------------------------------------------------------------

    async def submit(
        self,
        caller_service: str,
        knowledge_domain: str | None,
        pipeline_stage: str,
        *,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        params: dict | None = None,
        expected_output_type: str | None = None,
        output_schema: dict | None = None,
        idempotency_key: str | None = None,
        metadata: dict | None = None,
        max_attempts: int = 3,
        priority: int = 100,
    ) -> str:
        # Template expansion
        resolved = await self._resolve_template(
            template_key, knowledge_domain, input, messages, expected_output_type, output_schema,
        )
        actual_messages = resolved["messages"] or [{"role": "user", "content": json.dumps(input or {})}]
        actual_expected_type = resolved["expected_output_type"] or "json_object"
        actual_schema = resolved["output_schema"]

        return await self._submit_with_idempotency(
            idempotency_key=idempotency_key,
            task_type="chat",
            caller_service=caller_service,
            knowledge_domain=knowledge_domain,
            pipeline_stage=pipeline_stage,
            request_params=(
                self._provider_name, self._default_model, template_key,
                json.dumps(actual_messages or []),
                json.dumps(input or {}),
                json.dumps(params or {}),
                actual_expected_type,
                json.dumps(actual_schema or {}),
            ),
            event_message="task submitted",
            max_attempts=max_attempts,
            priority=priority,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Submit embedding / rerank (async)
    # ------------------------------------------------------------------

    async def submit_embedding(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        dimensions: int | None = None,
        caller_service: str = "model",
        knowledge_domain: str | None = None,
        pipeline_stage: str = "embedding",
        idempotency_key: str | None = None,
        metadata: dict | None = None,
        max_attempts: int = 2,
        priority: int = 100,
    ) -> str:
        actual_model = model or getattr(self._model_provider, "embedding_model", None) or self._config.embedding_model

        return await self._submit_with_idempotency(
            idempotency_key=idempotency_key,
            task_type="embedding",
            caller_service=caller_service,
            knowledge_domain=knowledge_domain,
            pipeline_stage=pipeline_stage,
            request_params=(
                "embedding", actual_model, None,
                "[]",
                json.dumps({"texts": texts, "model": actual_model, "dimensions": dimensions}),
                "{}", "embedding", "{}",
            ),
            event_message="embedding task submitted",
            max_attempts=max_attempts,
            priority=priority,
            metadata=metadata,
        )

    async def submit_rerank(
        self,
        query: str,
        documents: list[str],
        *,
        model: str | None = None,
        top_n: int | None = None,
        caller_service: str = "model",
        knowledge_domain: str | None = None,
        pipeline_stage: str = "rerank",
        idempotency_key: str | None = None,
        metadata: dict | None = None,
        max_attempts: int = 2,
        priority: int = 100,
    ) -> str:
        actual_model = model or getattr(self._model_provider, "_rerank_model", None) or self._config.rerank_model

        return await self._submit_with_idempotency(
            idempotency_key=idempotency_key,
            task_type="rerank",
            caller_service=caller_service,
            knowledge_domain=knowledge_domain,
            pipeline_stage=pipeline_stage,
            request_params=(
                "rerank", actual_model, None,
                "[]",
                json.dumps({"query": query, "documents": documents, "model": actual_model, "top_n": top_n}),
                "{}", "rerank", "{}",
            ),
            event_message="rerank task submitted",
            max_attempts=max_attempts,
            priority=priority,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Execute (sync) — optimized fast path
    # ------------------------------------------------------------------

    async def execute(
        self,
        caller_service: str,
        knowledge_domain: str | None,
        pipeline_stage: str,
        *,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        params: dict | None = None,
        expected_output_type: str | None = None,
        output_schema: dict | None = None,
        idempotency_key: str | None = None,
        metadata: dict | None = None,
        max_attempts: int = 3,
        priority: int = 100,
        timeout: int | None = None,
    ) -> dict:
        """Sync execute: resolve template → call LLM → return immediately.

        ALL DB writes are fire-and-forget background tasks.
        This is a relay service — the caller should see near-zero overhead beyond the LLM call itself.
        """
        # ---- Phase 1: Resolve template (cached → 0 DB after warm-up) ----
        resolved = await self._resolve_template(
            template_key, knowledge_domain, input, messages, expected_output_type, output_schema,
        )
        actual_messages = resolved["messages"] or [{"role": "user", "content": json.dumps(input or {})}]
        actual_expected_type = resolved["expected_output_type"] or "json_object"
        actual_schema = resolved["output_schema"]

        # ---- Phase 2: Call LLM (the only blocking work) ----
        start = time.monotonic()
        response_format = (
            {"type": "json_object"}
            if actual_expected_type in ("json_object", "json_array")
            else None
        )

        try:
            resp = await self._provider.complete(
                messages=actual_messages, params=params or {},
                response_format=response_format,
            )
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            error_type = getattr(e, "error_type", "unexpected_error")
            error_msg = str(e)
            return {
                "task_id": None,
                "status": "failed",
                "attempts": 0,
                "total_tokens": None,
                "latency_ms": latency,
                "result": None,
                "error": {"error_type": error_type, "error_message": error_msg},
            }

        latency = int((time.monotonic() - start) * 1000)
        parse_result = parse_output(resp.output_text, actual_expected_type, actual_schema)
        parse_ok = parse_result.parse_status == "succeeded"

        # ---- Phase 3: Fire-and-forget all DB writes ----
        task_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        attempt_id = str(uuid.uuid4())
        result_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        lease_dt = datetime.now(timezone.utc) + timedelta(seconds=self._config.lease_duration)
        effective_priority = max(priority, 999)
        final_status = "succeeded" if parse_ok else "failed"

        async def _persist():
            """Background task: write all bookkeeping rows to DB."""
            try:
                async with self._db.pool.connection() as conn:
                    async with conn.transaction():
                        # task row
                        await conn.execute(
                            """INSERT INTO agent_llm_tasks
                               (id, caller_service, knowledge_domain, pipeline_stage, task_type,
                                idempotency_key, status, priority, available_at, attempt_count, max_attempts,
                                created_at, updated_at, started_at, finished_at, lease_expires_at, metadata_json)
                               VALUES (%s, %s, %s, %s, 'chat', %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                task_id, caller_service, knowledge_domain, pipeline_stage,
                                idempotency_key, final_status, effective_priority, now, max_attempts,
                                now, now, now, now, lease_dt.isoformat(), json.dumps(metadata or {}),
                            ),
                        )
                        # request row
                        await conn.execute(
                            """INSERT INTO agent_llm_requests
                               (id, task_id, provider, model, prompt_template_key, messages_json, input_json,
                                params_json, expected_output_type, output_schema_json, created_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                request_id, task_id, self._provider_name, self._default_model, template_key,
                                json.dumps(actual_messages), json.dumps(input or {}),
                                json.dumps(params or {}), actual_expected_type,
                                json.dumps(actual_schema or {}), now,
                            ),
                        )
                        # attempt row (final state directly)
                        if parse_ok:
                            await conn.execute(
                                """INSERT INTO agent_llm_attempts
                                   (id, task_id, request_id, attempt_no, status, started_at, finished_at,
                                    raw_output_text, prompt_tokens, completion_tokens, total_tokens,
                                    latency_ms, raw_response_json)
                                   VALUES (%s, %s, %s, 1, 'succeeded', %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    attempt_id, task_id, request_id, now, now,
                                    resp.output_text, resp.prompt_tokens, resp.completion_tokens,
                                    resp.total_tokens, latency, json.dumps(resp.raw_response or {}),
                                ),
                            )
                        else:
                            await conn.execute(
                                """INSERT INTO agent_llm_attempts
                                   (id, task_id, request_id, attempt_no, status, started_at, finished_at,
                                    raw_output_text, prompt_tokens, completion_tokens, total_tokens,
                                    latency_ms, raw_response_json, error_type, error_message)
                                   VALUES (%s, %s, %s, 1, 'failed', %s, %s, %s, %s, %s, %s, %s, %s,
                                    'parse_failed', %s)""",
                                (
                                    attempt_id, task_id, request_id, now, now,
                                    resp.output_text, resp.prompt_tokens, resp.completion_tokens,
                                    resp.total_tokens, latency, json.dumps(resp.raw_response or {}),
                                    parse_result.parse_error or f"parse_status={parse_result.parse_status}",
                                ),
                            )
                        # result row
                        await conn.execute(
                            """INSERT INTO agent_llm_results
                               (id, task_id, attempt_id, parse_status, parsed_output_json, text_output,
                                parse_error, validation_errors_json, created_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                result_id, task_id, attempt_id, parse_result.parse_status,
                                json.dumps(parse_result.parsed_output if parse_result.parsed_output is not None else {}),
                                parse_result.text_output, parse_result.parse_error,
                                json.dumps(parse_result.validation_errors), now,
                            ),
                        )
                # Emit event (fire-and-forget within fire-and-forget)
                asyncio.ensure_future(self._bus.emit(task_id, final_status, "task completed"))
            except Exception:
                logger.exception("Background persist failed for task %s", task_id[:8])

        asyncio.ensure_future(_persist())

        # ---- Phase 4: Return immediately from memory ----
        if parse_ok:
            return {
                "task_id": task_id,
                "status": "succeeded",
                "attempts": 1,
                "total_tokens": resp.total_tokens,
                "latency_ms": latency,
                "result": {
                    "parse_status": parse_result.parse_status,
                    "parsed_output": parse_result.parsed_output if parse_result.parsed_output else None,
                    "text_output": parse_result.text_output,
                    "validation_errors": parse_result.validation_errors,
                },
                "error": None,
            }
        else:
            return {
                "task_id": task_id,
                "status": "failed",
                "attempts": 1,
                "total_tokens": resp.total_tokens,
                "latency_ms": latency,
                "result": {
                    "parse_status": parse_result.parse_status,
                    "parsed_output": None,
                    "text_output": parse_result.text_output,
                    "validation_errors": parse_result.validation_errors,
                },
                "error": {
                    "error_type": "parse_failed",
                    "error_message": parse_result.parse_error or parse_result.parse_status,
                },
            }

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def _build_execute_response(self, task_id: str) -> dict:
        task = await self._db.fetchone("SELECT status, attempt_count FROM agent_llm_tasks WHERE id = %s", (task_id,))
        if not task:
            return {"task_id": task_id, "status": "unknown", "attempts": 0, "result": None, "error": None}

        result_row = await self._db.fetchone("SELECT parse_status, parsed_output_json, text_output, validation_errors_json FROM agent_llm_results WHERE task_id = %s", (task_id,))
        attempt_row = await self._db.fetchone("SELECT total_tokens, latency_ms FROM agent_llm_attempts WHERE task_id = %s ORDER BY attempt_no DESC LIMIT 1", (task_id,))

        resp = {
            "task_id": task_id,
            "status": task["status"],
            "attempts": task["attempt_count"],
            "total_tokens": attempt_row["total_tokens"] if attempt_row else None,
            "latency_ms": attempt_row["latency_ms"] if attempt_row else None,
        }

        if result_row:
            parsed = _safe_json_parse(result_row["parsed_output_json"])
            validation = _safe_json_parse(result_row["validation_errors_json"], default=[])
            resp["result"] = {
                "parse_status": result_row["parse_status"],
                "parsed_output": parsed if parsed != {} else None,
                "text_output": result_row["text_output"],
                "validation_errors": validation,
            }
        else:
            resp["result"] = None

        if task["status"] in ("dead_letter", "failed"):
            err_row = await self._db.fetchone("SELECT error_type, error_message FROM agent_llm_attempts WHERE task_id = %s AND status = 'failed' ORDER BY attempt_no DESC LIMIT 1", (task_id,))
            resp["error"] = {
                "error_type": err_row["error_type"] if err_row else None,
                "error_message": err_row["error_message"] if err_row else None,
            }
        else:
            resp["error"] = None

        return resp

    async def get_task(self, task_id: str) -> dict | None:
        row = await self._db.fetchone("SELECT * FROM agent_llm_tasks WHERE id = %s", (task_id,))
        if not row:
            return None
        return _map_task_row(row)

    async def cancel(self, task_id: str) -> None:
        await self._mgr.cancel(task_id)

    async def get_result(self, task_id: str) -> dict | None:
        row = await self._db.fetchone("SELECT * FROM agent_llm_results WHERE task_id = %s", (task_id,))
        return _map_result_row(row) if row else None

    async def get_attempts(self, task_id: str) -> list[dict]:
        rows = await self._db.fetchall("SELECT * FROM agent_llm_attempts WHERE task_id = %s ORDER BY attempt_no", (task_id,))
        return [_map_attempt_row(r) for r in rows]

    async def get_events(self, task_id: str) -> list[dict]:
        rows = await self._db.fetchall("SELECT * FROM agent_llm_events WHERE task_id = %s ORDER BY created_at", (task_id,))
        return [_map_event_row(r) for r in rows]


# ------------------------------------------------------------------
# Stable response mapping — shields callers from DB column changes
# ------------------------------------------------------------------

def _safe_json_parse(value, default=None):
    """Parse JSON from DB value. Handles both str (legacy) and dict/list (JSONB auto-parse)."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _map_task_row(row) -> dict:
    """Map agent_llm_tasks row to stable response dict."""
    return {
        "id": row["id"],
        "caller_service": row["caller_service"],
        "knowledge_domain": row["knowledge_domain"],
        "pipeline_stage": row["pipeline_stage"],
        "task_type": row["task_type"],
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
        "priority": row["priority"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "metadata": _safe_json_parse(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _map_result_row(row) -> dict:
    """Map agent_llm_results row to stable response dict."""
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "parse_status": row["parse_status"],
        "parsed_output": _safe_json_parse(row["parsed_output_json"]) or None,
        "text_output": row["text_output"],
        "parse_error": row["parse_error"],
        "validation_errors": _safe_json_parse(row["validation_errors_json"], []),
        "created_at": row["created_at"],
    }


def _map_attempt_row(row) -> dict:
    """Map agent_llm_attempts row to stable response dict."""
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "attempt_no": row["attempt_no"],
        "status": row["status"],
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "latency_ms": row["latency_ms"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _map_event_row(row) -> dict:
    """Map agent_llm_events row to stable response dict."""
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "event_type": row["event_type"],
        "message": row["message"],
        "created_at": row["created_at"],
    }
