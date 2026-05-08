"""Synchronous HTTP client for llm_service — used by Mining pipeline.

This is a sync wrapper that mirrors llm_service/client.py field names exactly.
Mining pipeline is synchronous, so we use httpx sync client instead of async.

All methods return None on failure (non-blocking for pipeline).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default port matches llm_service QUICKSTART
DEFAULT_BASE_URL = "http://localhost:8900"


class LlmClient:
    """Sync HTTP client for llm_service. Field names match llm_service/client.py."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def submit_task(
        self,
        template_key: str,
        input: dict[str, Any] | None = None,
        caller_domain: str = "mining",
        pipeline_stage: str = "retrieval_units",
        expected_output_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> str | None:
        """Submit async task via POST /api/v1/tasks. Returns task_id or None."""
        payload: dict[str, Any] = {
            "caller_domain": caller_domain,
            "pipeline_stage": pipeline_stage,
            "template_key": template_key,
            "max_attempts": max_attempts,
        }
        if input is not None:
            payload["input"] = input
        if expected_output_type is not None:
            payload["expected_output_type"] = expected_output_type
        if metadata is not None:
            payload["metadata"] = metadata

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self._base_url}/api/v1/tasks", json=payload)
                resp.raise_for_status()
                return resp.json().get("task_id")
        except Exception as e:
            logger.warning("submit_task failed: %s", e)
            return None

    def poll_result(
        self, task_id: str, poll_interval: float = 1.0, timeout: int = 120,
    ) -> list[dict] | None:
        """Poll task until completed. Returns parsed_output list or None.

        Polls GET /api/v1/tasks/{id} for status, then GET /tasks/{id}/result for output.
        """
        deadline = time.time() + timeout
        with httpx.Client(timeout=self._timeout) as client:
            while time.time() < deadline:
                try:
                    # Check task status
                    resp = client.get(f"{self._base_url}/api/v1/tasks/{task_id}")
                    resp.raise_for_status()
                    task_data = resp.json()
                    status = task_data.get("status", "")

                    if status == "succeeded":
                        # Fetch result
                        r_resp = client.get(f"{self._base_url}/api/v1/tasks/{task_id}/result")
                        r_resp.raise_for_status()
                        result = r_resp.json()
                        parsed = result.get("parsed_output")
                        # parsed_output might already be a list/dict
                        if isinstance(parsed, list):
                            return parsed
                        if isinstance(parsed, dict):
                            return [parsed]
                        # Try text_output as fallback
                        text = result.get("text_output")
                        if text:
                            try:
                                return json.loads(text)
                            except json.JSONDecodeError:
                                return None
                        return None

                    if status in ("failed", "dead_letter", "cancelled"):
                        logger.info("Task %s ended with status %s", task_id, status)
                        return None

                    # Still queued/running
                    time.sleep(poll_interval)
                except Exception as e:
                    logger.warning("poll_result error: %s", e)
                    return None

        logger.warning("poll_result timed out for task %s", task_id)
        return None

    def execute(
        self,
        template_key: str,
        input: dict[str, Any] | None = None,
        caller_domain: str = "mining",
        pipeline_stage: str = "retrieval_units",
        expected_output_type: str | None = None,
    ) -> dict | None:
        """Sync execute via POST /api/v1/execute. Returns full response or None."""
        payload: dict[str, Any] = {
            "caller_domain": caller_domain,
            "pipeline_stage": pipeline_stage,
            "template_key": template_key,
        }
        if input is not None:
            payload["input"] = input
        if expected_output_type is not None:
            payload["expected_output_type"] = expected_output_type

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self._base_url}/api/v1/execute", json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("execute failed: %s", e)
            return None

    def register_template(self, template: dict[str, Any]) -> bool:
        """Idempotent template registration via POST /api/v1/templates."""
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self._base_url}/api/v1/templates", json=template)
                return resp.status_code in (200, 201)
        except Exception as e:
            logger.warning("register_template failed: %s", e)
            return False

    def health_check(self) -> bool:
        """Quick health check. Returns True if llm_service is reachable."""
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
