from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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
from llm_service.runtime.persist_writer import PersistWriter, SyncModelRecord

if TYPE_CHECKING:
    from llm_service.db import LlmRuntimeDB

logger = logging.getLogger(__name__)


class ModelService:
    """Synchronous-style model facade exposed over HTTP for mining/serving."""

    def __init__(self, provider: ModelProviderProtocol, db: LlmRuntimeDB | None = None, *,
                 persist_writer: PersistWriter | None = None,
                 default_embedding_model: str = "",
                 default_rerank_model: str = "",
                 default_embedding_dimensions: int | None = None):
        self._provider = provider
        self._db = db
        self._persist_writer = persist_writer
        self._default_embedding_model = default_embedding_model
        self._default_rerank_model = default_rerank_model
        self._default_embedding_dimensions = default_embedding_dimensions

    def _enqueue_record(self, record: SyncModelRecord) -> None:
        """Push record to PersistWriter queue (non-blocking, fire-and-forget)."""
        if self._persist_writer is not None:
            self._persist_writer.enqueue(record)

    async def embed(self, body: EmbeddingRequest) -> EmbeddingResponse:
        t0 = datetime.now(timezone.utc)
        model = body.model or self._default_embedding_model
        dimensions = body.dimensions or self._default_embedding_dimensions
        texts = body.input
        input_json = {"texts": texts, "model": model, "dimensions": dimensions}
        try:
            raw = await self._provider.embed(
                texts,
                model=model,
                dimensions=dimensions,
            )
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            usage = raw.get("usage") or {}
            token_usage = usage.get("total_tokens") or usage.get("prompt_tokens")

            text_output = "\n".join(texts)
            self._enqueue_record(SyncModelRecord(
                task_type="embedding", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="succeeded",
                latency_ms=latency, total_tokens=token_usage,
                input_json=json.dumps(input_json, ensure_ascii=False),
                raw_response_json=json.dumps(raw or {}, ensure_ascii=False),
                text_output=text_output,
                now=datetime.now(timezone.utc).isoformat(),
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
            self._enqueue_record(SyncModelRecord(
                task_type="embedding", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="failed",
                latency_ms=latency, total_tokens=None,
                input_json=json.dumps(input_json, ensure_ascii=False),
                error_type=error_type, error_message=str(e)[:500],
                now=datetime.now(timezone.utc).isoformat(),
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

            self._enqueue_record(SyncModelRecord(
                task_type="rerank", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="succeeded",
                latency_ms=latency, total_tokens=token_usage,
                input_json=json.dumps(input_json, ensure_ascii=False),
                raw_response_json=json.dumps(raw or {}, ensure_ascii=False),
                text_output=text_output,
                now=datetime.now(timezone.utc).isoformat(),
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
            self._enqueue_record(SyncModelRecord(
                task_type="rerank", model=model,
                caller_service=body.caller_service or "model",
                knowledge_domain=body.knowledge_domain,
                pipeline_stage=body.pipeline_stage,
                status="failed",
                latency_ms=latency, total_tokens=None,
                input_json=json.dumps(input_json, ensure_ascii=False),
                error_type=error_type, error_message=str(e)[:500],
                now=datetime.now(timezone.utc).isoformat(),
            ))
            raise
