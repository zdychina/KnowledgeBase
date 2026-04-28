"""Tests for template resolution in service layer."""
import json

import pytest

pytestmark = pytest.mark.asyncio


async def test_resolve_template_expands_messages(db):
    """_resolve_template expands user_prompt_template with input variables."""
    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.service import LLMService
    from llm_service.runtime.template_registry import TemplateRegistry

    cfg = LLMServiceConfig(
        db_path=":memory:",
        provider_api_key="test",
    )
    provider = MockProvider(responses=[{"choices": [{"message": {"content": "ok"}}]}])
    svc = LLMService(db=db, provider=provider, config=cfg)
    reg = TemplateRegistry(db)

    # Create template (string.Template uses $var syntax)
    await reg.create(
        template_key="greeting",
        template_version="1",
        purpose="test",
        system_prompt="You are a friendly assistant.",
        user_prompt_template="Hello $name, please help with $topic.",
        expected_output_type="text",
    )

    # Resolve with template_key + input
    resolved = await svc._resolve_template(
        template_key="greeting",
        input={"name": "Alice", "topic": "Python"},
        messages=None,
        expected_output_type="json_object",
        output_schema=None,
    )

    assert resolved["messages"] is not None
    assert len(resolved["messages"]) == 2
    assert resolved["messages"][0]["role"] == "system"
    assert resolved["messages"][0]["content"] == "You are a friendly assistant."
    assert "Alice" in resolved["messages"][1]["content"]
    assert "Python" in resolved["messages"][1]["content"]
    # Caller explicitly specified json_object → template's "text" does NOT override
    assert resolved["expected_output_type"] == "json_object"


async def test_resolve_template_fills_output_type_from_template(db):
    """When caller doesn't specify expected_output_type, template provides default."""
    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.service import LLMService
    from llm_service.runtime.template_registry import TemplateRegistry

    cfg = LLMServiceConfig(db_path=":memory:", provider_api_key="test")
    provider = MockProvider(responses=[{"choices": [{"message": {"content": "plain text response"}}]}])
    svc = LLMService(db=db, provider=provider, config=cfg)
    reg = TemplateRegistry(db)

    await reg.create(
        template_key="text-tpl",
        template_version="1",
        purpose="text output test",
        user_prompt_template="Say hello to $name",
        expected_output_type="text",
    )

    # Caller passes None (didn't specify) → template fills "text"
    resolved = await svc._resolve_template(
        template_key="text-tpl",
        input={"name": "Bob"},
        messages=None,
        expected_output_type=None,
        output_schema=None,
    )

    assert resolved["expected_output_type"] == "text"
    assert resolved["messages"] is not None
    assert "Bob" in resolved["messages"][-1]["content"]


async def test_resolve_template_caller_messages_take_precedence(db):
    """Caller-provided messages override template expansion."""
    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.service import LLMService
    from llm_service.runtime.template_registry import TemplateRegistry

    cfg = LLMServiceConfig(db_path=":memory:", provider_api_key="test")
    provider = MockProvider(responses=[{"choices": [{"message": {"content": "ok"}}]}])
    svc = LLMService(db=db, provider=provider, config=cfg)
    reg = TemplateRegistry(db)

    await reg.create(
        template_key="test",
        template_version="1",
        purpose="test",
        user_prompt_template="Template content",
        expected_output_type="text",
    )

    caller_messages = [{"role": "user", "content": "My own message"}]
    resolved = await svc._resolve_template(
        template_key="test",
        input=None,
        messages=caller_messages,
        expected_output_type="text",
        output_schema=None,
    )

    # Caller's messages preserved as-is
    assert resolved["messages"] == caller_messages


async def test_execute_metadata_persisted(db):
    """metadata is stored in task row and request row is auto-generated."""
    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.service import LLMService

    cfg = LLMServiceConfig(db_path=":memory:", provider_api_key="test")
    provider = MockProvider(responses=[{"choices": [{"message": {"content": '{"ok": true}'}}]}])
    svc = LLMService(db=db, provider=provider, config=cfg)

    result = await svc.execute(
        "mining", "test",
        messages=[{"role": "user", "content": "hi"}],
        metadata={"caller": "test-case", "run": 1},
    )
    task_id = result["task_id"]

    # Verify metadata on task
    cur = await db.execute("SELECT metadata_json FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    meta = json.loads(row["metadata_json"])
    assert meta["caller"] == "test-case"

    # Verify request row exists with auto-generated UUID
    cur = await db.execute("SELECT id FROM agent_llm_requests WHERE task_id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["id"]  # auto-generated, not empty


async def test_execute_with_text_template_parses_as_text(db):
    """execute with text template: parse_status is succeeded, not failed."""
    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.service import LLMService
    from llm_service.runtime.template_registry import TemplateRegistry

    cfg = LLMServiceConfig(db_path=":memory:", provider_api_key="test")
    provider = MockProvider(responses=[{"choices": [{"message": {"content": "This is plain text."}}]}])
    svc = LLMService(db=db, provider=provider, config=cfg)
    reg = TemplateRegistry(db)

    # Create template with text output type
    await reg.create(
        template_key="text-summary",
        template_version="1",
        purpose="summarize",
        user_prompt_template="Summarize: $text",
        expected_output_type="text",
    )

    # Execute without specifying expected_output_type → template fills "text"
    result = await svc.execute(
        "mining", "summary",
        template_key="text-summary",
        input={"text": "Some content"},
    )

    assert result["status"] == "succeeded"
    assert result["result"]["parse_status"] == "succeeded"
    assert result["result"]["text_output"] == "This is plain text."
