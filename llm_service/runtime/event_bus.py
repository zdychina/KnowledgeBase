from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from llm_service.db import LlmRuntimeDB


class EventBus:
    def __init__(self, db: LlmRuntimeDB):
        self._db = db

    async def emit(
        self,
        task_id: str,
        event_type: str,
        message: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO agent_llm_events (id, task_id, event_type, message, metadata_json, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (event_id, task_id, event_type, message, json.dumps(metadata or {}), now),
        )
        return event_id
