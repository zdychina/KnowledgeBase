from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite


_ALLOWED_UPDATE_COLUMNS = frozenset({
    "template_key", "template_version", "purpose", "system_prompt",
    "user_prompt_template", "expected_output_type", "output_schema_json",
    "status", "metadata_json",
})


class TemplateRegistry:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def create(
        self,
        template_key: str,
        template_version: str,
        purpose: str,
        user_prompt_template: str,
        expected_output_type: str,
        system_prompt: str | None = None,
        output_schema_json: str = "{}",
        status: str = "active",
    ) -> str:
        tpl_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO agent_llm_prompt_templates
               (id, template_key, template_version, purpose, system_prompt, user_prompt_template,
                expected_output_type, output_schema_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tpl_id, template_key, template_version, purpose, system_prompt,
                user_prompt_template, expected_output_type, output_schema_json, status, now,
            ),
        )
        await self._db.commit()
        return tpl_id

    async def get(self, tpl_id: str) -> dict | None:
        cur = await self._db.execute("SELECT * FROM agent_llm_prompt_templates WHERE id = ?", (tpl_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_key(self, template_key: str) -> dict | None:
        cur = await self._db.execute(
            "SELECT * FROM agent_llm_prompt_templates WHERE template_key = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (template_key,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        cur = await self._db.execute("SELECT * FROM agent_llm_prompt_templates ORDER BY created_at DESC")
        return [dict(r) for r in await cur.fetchall()]

    async def update(self, tpl_id: str, **fields) -> None:
        # Safe: column names validated against static allowlist, not user input.
        sets = []
        values = []
        for k, v in fields.items():
            if k not in _ALLOWED_UPDATE_COLUMNS:
                raise ValueError(f"invalid column: {k}")
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return
        values.append(tpl_id)
        await self._db.execute(
            f"UPDATE agent_llm_prompt_templates SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await self._db.commit()

    async def archive(self, tpl_id: str) -> None:
        await self.update(tpl_id, status="archived")
