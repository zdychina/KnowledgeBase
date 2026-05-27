from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from llm_service.db import LlmRuntimeDB
from llm_service.models import (
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    RerankRequest,
    RerankResponse,
    RerankResult,
)
from llm_service.providers.model_base import ModelProviderProtocol
from llm_service.providers.utils import extract_doc_text

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelService:
    """Synchronous-style model facade exposed over HTTP for mining/serving."""

    def __init__(self, provider: ModelProviderProtocol, db: LlmRuntimeDB | None = None, *,
                 default_embedding_model: str = "embedding-3",
                 default_rerank_model: str = ""):
        self._provider = provider
        self._db = db
        self._default_embedding_model = default_embedding_model
        self._default_rerank_model = default_rerank_model

    async def _record_sync_task(
        self,
        task_type: str,
        model: str,
        caller_service: str,
        knowledge_domain: str | None,
        pipeline_stage: str,
        status: str,
        latency_ms: int | None,
        total_tokens: int | None,
        input_json: dict,
        raw_response: dict | None = None,
        text_output: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Write a full tasks+requests+attempts+results record for sync calls."""
        if self._db is None:
            return
        now = _utcnow()
        task_id = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        attempt_id = uuid.uuid4().hex
        try:
            async with self._db.pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """INSERT INTO agent_llm_tasks
                           (id, caller_service, knowledge_domain, pipeline_stage, task_type, status,
                            priority, attempt_count, max_attempts,
                            created_at, updated_at, started_at, finished_at, metadata_json)
                           VALUES (%s, %s, %s, %s, %s, %s, 100, 1, 1, %s, %s, %s, %s, '{}')""",
                        (task_id, caller_service, knowledge_domain, pipeline_stage, task_type, status,
                         now, now, now, now),
                    )

                    await conn.execute(
                        """INSERT INTO agent_llm_requests
                           (id, task_id, provider, model, messages_json, input_json,
                            params_json, expected_output_type, output_schema_json, created_at, metadata_json)
                           VALUES (%s, %s, 'sync', %s, '[]', %s, '{}', 'text', '{}', %s, '{}')""",
                        (request_id, task_id, model,
                         json.dumps(input_json, ensure_ascii=False), now),
                    )

                    await conn.execute(
                        """INSERT INTO agent_llm_attempts
                           (id, task_id, request_id, attempt_no, status,
                            total_tokens, latency_ms, started_at, finished_at,
                            raw_response_json, error_type, error_message, metadata_json)
                           VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, '{}')""",
                        (attempt_id, task_id, request_id, status,
                         total_tokens, latency_ms, now, now,
                         json.dumps(raw_response or {}, ensure_ascii=False),
                         error_type, error_message),
                    )

                    if status == "succeeded":
                        result_id = uuid.uuid4().hex
                        await conn.execute(
                            """INSERT INTO agent_llm_results
                               (id, task_id, attempt_id, parse_status, parsed_output_json,
                                text_output, parse_error, validation_errors_json, created_at, metadata_json)
                               VALUES (%s, %s, %s, 'not_required', %s, %s, NULL, '[]', %s, '{}')""",
                            (result_id, task_id, attempt_id,
                             json.dumps(raw_response or {}, ensure_ascii=False),
                             text_output, now),
                        )

                    await conn.execute(
                        """INSERT INTO agent_llm_model_calls
                           (id, call_type, model, caller_service, knowledge_domain, pipeline_stage,
                            input_count, status, latency_ms, token_usage, error_message, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            uuid.uuid4().hex,
                            task_type,
                            model,
                            caller_service,
                            knowledge_domain,
                            pipeline_stage,
                            len(input_json.get("texts") or input_json.get("documents") or []),
                            status,
                            latency_ms,
                            total_tokens,
                            error_message,
                            now,
                        ),
                    )
        except Exception:
            logger.exception("Failed to record sync %s task", task_type)

    async def embed(self, body: EmbeddingRequest) -> EmbeddingResponse:
        t0 = datetime.now(timezone.utc)
        model = body.model or self._default_embedding_model
        texts = body.input
        input_json = {"texts": texts, "model": model, "dimensions": body.dimensions}
        try:
            raw = await self._provider.embed(
                texts,
                model=model,
                dimensions=body.dimensions,
            )
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            usage = raw.get("usage") or {}
            token_usage = usage.get("total_tokens") or usage.get("prompt_tokens")

            text_output = "\n".join(texts)
            # Fire-and-forget DB recording
            asyncio.ensure_future(self._record_sync_task(
                task_type="embedding", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="succeeded",
                latency_ms=latency, total_tokens=token_usage,
                input_json=input_json, raw_response=raw, text_output=text_output,
            ))

            data = sorted(raw.get("data", []), key=lambda item: item.get("index") or 0)
            return EmbeddingResponse(
                model=raw.get("model") or model or "",
                data=[
                    EmbeddingData(
                        index=item.get("index") if item.get("index") is not None else idx,
                        embedding=item.get("embedding", []),
                    )
                    for idx, item in enumerate(data)
                ],
                usage=usage,
            )
        except Exception as e:
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            error_type = getattr(e, "error_type", "unexpected_error")
            asyncio.ensure_future(self._record_sync_task(
                task_type="embedding", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="failed",
                latency_ms=latency, total_tokens=None,
                input_json=input_json,
                error_type=error_type, error_message=str(e)[:500],
            ))
            raise

    async def rerank(self, body: RerankRequest) -> RerankResponse:
        t0 = datetime.now(timezone.utc)
        model = body.model or self._default_rerank_model
        input_json = {
            "query": body.query,
            "documents": body.documents,
            "model": model,
            "top_n": body.top_n,
        }
        try:
            raw = await self._provider.rerank(
                body.query,
                body.documents,
                model=model,
                top_n=body.top_n,
            )
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            usage = raw.get("usage") or {}
            token_usage = usage.get("total_tokens")

            lines = [f"Query: {body.query}"]
            for r in raw.get("results", []):
                score = r.get("relevance_score", 0)
                doc = extract_doc_text(r.get("document"))[:100]
                lines.append(f"  [{r.get('index', '?')}] score={score:.4f}: {doc}")
            text_output = "\n".join(lines)

            # Fire-and-forget DB recording
            asyncio.ensure_future(self._record_sync_task(
                task_type="rerank", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="succeeded",
                latency_ms=latency, total_tokens=token_usage,
                input_json=input_json, raw_response=raw, text_output=text_output,
            ))

            return RerankResponse(
                model=raw.get("model") or model or "",
                results=[
                    RerankResult(
                        index=item.get("index") if item.get("index") is not None else idx,
                        relevance_score=float(item.get("relevance_score", 0.0)),
                        document=extract_doc_text(item.get("document")),
                    )
                    for idx, item in enumerate(raw.get("results", []))
                ],
            )
        except Exception as e:
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            error_type = getattr(e, "error_type", "unexpected_error")
            asyncio.ensure_future(self._record_sync_task(
                task_type="rerank", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="failed",
                latency_ms=latency, total_tokens=None,
                input_json=input_json,
                error_type=error_type, error_message=str(e)[:500],
            ))
            raise
