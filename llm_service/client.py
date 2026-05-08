from __future__ import annotations

from typing import Any

import httpx


class LLMClient:
    """Unified client for Mining/Serving to call LLM Service.

    ## Integration Patterns

    ### Mining (batch async via submit + poll)

        client = LLMClient(base_url="http://localhost:8900")

        # Step 1: Create template once (or pre-seed via API)
        # POST /api/v1/templates with template_key="mining-question-gen"

        # Step 2: Submit batch tasks
        task_ids = []
        for section in sections:
            tid = await client.submit(
                caller_domain="mining",
                pipeline_stage="retrieval_units",
                template_key="mining-question-gen",
                input={"section_title": section.title, "content": section.text},
                metadata={
                    "caller_context": {
                        "ref": {"type": "section", "id": section.id},
                        "build_id": build_id,
                    }
                },
            )
            task_ids.append(tid)

        # Step 3: Poll for results (Worker executes in background)
        for tid in task_ids:
            task = await client.get_task(tid)
            if task["status"] == "succeeded":
                result = await client.get_result(tid)
                questions = result["parsed_output_json"]

    ### Serving (sync online enhancement via execute)

        client = LLMClient(base_url="http://localhost:8900")

        # Query rewrite - needs immediate result
        result = await client.execute(
            caller_domain="serving",
            pipeline_stage="normalizer",
            template_key="serving-query-rewrite",
            input={"query": user_query},
            metadata={"caller_context": {"request_id": request_id}},
        )
        rewritten = result["result"]["parsed_output"]

        # Intent/entity extraction
        result = await client.execute(
            caller_domain="serving",
            pipeline_stage="planner",
            template_key="serving-intent-extract",
            input={"query": user_query},
        )

    ### Caller-provided messages (no template)

        result = await client.execute(
            caller_domain="serving",
            pipeline_stage="rerank",
            messages=[
                {"role": "system", "content": "Rerank by relevance."},
                {"role": "user", "content": f"Query: {q}\\nDocs: {docs}"},
            ],
            expected_output_type="json_array",
        )
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8900",
        http_client: httpx.AsyncClient | None = None,
        timeout: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._external_client = http_client is not None
        self._client = http_client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    def _build_submit_payload(
        self,
        caller_domain: str,
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "caller_domain": caller_domain,
            "pipeline_stage": pipeline_stage,
            "max_attempts": max_attempts,
            "priority": priority,
        }
        for k, v in [
            ("template_key", template_key),
            ("input", input),
            ("messages", messages),
            ("params", params),
            ("expected_output_type", expected_output_type),
            ("output_schema", output_schema),
            ("idempotency_key", idempotency_key),
            ("metadata", metadata),
        ]:
            if v is not None:
                payload[k] = v
        return payload

    async def submit(
        self,
        caller_domain: str,
        pipeline_stage: str,
        **kwargs,
    ) -> str:
        """Submit async task. Returns task_id for later polling."""
        payload = self._build_submit_payload(caller_domain, pipeline_stage, **kwargs)
        c = self._get_client()
        resp = await c.post("/api/v1/tasks", json=payload)
        resp.raise_for_status()
        return resp.json()["task_id"]

    async def execute(
        self,
        caller_domain: str,
        pipeline_stage: str,
        **kwargs,
    ) -> dict:
        """Sync execute: submit and block until result."""
        payload = self._build_submit_payload(caller_domain, pipeline_stage, **kwargs)
        c = self._get_client()
        resp = await c.post("/api/v1/execute", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def embed(
        self,
        input: list[str] | str,
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"input": input}
        if model is not None:
            payload["model"] = model
        if dimensions is not None:
            payload["dimensions"] = dimensions
        c = self._get_client()
        resp = await c.post("/api/v1/models/embeddings", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_n: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "query": query,
            "documents": documents,
        }
        if model is not None:
            payload["model"] = model
        if top_n is not None:
            payload["top_n"] = top_n
        c = self._get_client()
        resp = await c.post("/api/v1/models/rerank", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_task(self, task_id: str) -> dict:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    async def cancel(self, task_id: str) -> dict:
        c = self._get_client()
        resp = await c.post(f"/api/v1/tasks/{task_id}/cancel")
        resp.raise_for_status()
        return resp.json()

    async def get_result(self, task_id: str) -> dict:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}/result")
        resp.raise_for_status()
        return resp.json()

    async def get_attempts(self, task_id: str) -> list[dict]:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}/attempts")
        resp.raise_for_status()
        return resp.json()

    async def get_events(self, task_id: str) -> list[dict]:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}/events")
        resp.raise_for_status()
        return resp.json()
