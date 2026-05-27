from __future__ import annotations

from llm_service.db import LlmRuntimeDB


async def find_existing_task(
    db: LlmRuntimeDB,
    idempotency_key: str,
) -> str | None:
    """Return task_id if an active/succeeded task exists for this key.

    Priority: latest succeeded > latest running > latest queued > None (allow new).
    Only failed/dead_letter/cancelled tasks are ignored.
    """
    for status in ("succeeded", "running", "queued"):
        row = await db.fetchone(
            "SELECT id FROM agent_llm_tasks WHERE idempotency_key = %s AND status = %s ORDER BY created_at DESC LIMIT 1",
            (idempotency_key, status),
        )
        if row:
            return row["id"]

    return None
