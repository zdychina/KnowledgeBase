"""TraceCollector — non-invasive per-request trace collection.

Usage:
    trace = TraceCollector()
    trace.start_stage("query_understanding")
    ... do work ...
    trace.end_stage("query_understanding", output_summary="intent=command_usage, 2 entities")
    full_trace = trace.build_trace(request_id="req-123")
"""
from __future__ import annotations

import time
from typing import Any

from agent_serving.serving.schemas.models import Trace, TraceStage


class TraceCollector:
    """Collects timing and metadata for each pipeline stage."""

    def __init__(self) -> None:
        self._stages: dict[str, dict[str, Any]] = {}
        self._stage_order: list[str] = []
        self._start_time = time.monotonic()

    def start_stage(self, name: str) -> None:
        self._stages[name] = {"start": time.monotonic()}
        self._stage_order.append(name)

    def end_stage(
        self,
        name: str,
        output_summary: str = "",
        error: str = "",
    ) -> None:
        stage = self._stages.get(name)
        if stage is None:
            return
        stage["end"] = time.monotonic()
        stage["duration_ms"] = (stage["end"] - stage["start"]) * 1000
        stage["output_summary"] = output_summary
        stage["error"] = error

    def build_trace(self, request_id: str = "") -> Trace:
        stages: list[TraceStage] = []
        for name in self._stage_order:
            info = self._stages.get(name, {})
            stages.append(TraceStage(
                name=name,
                output_summary=info.get("output_summary", ""),
                duration_ms=info.get("duration_ms", 0.0),
                error=info.get("error", ""),
            ))
        total_ms = (time.monotonic() - self._start_time) * 1000
        return Trace(
            request_id=request_id,
            stages=stages,
            total_duration_ms=total_ms,
        )
