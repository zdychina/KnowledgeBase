import pytest

pytestmark = pytest.mark.asyncio


async def test_mock_provider_returns_preset_response():
    from llm_service.providers.mock import MockProvider

    provider = MockProvider(
        responses=[{"choices": [{"message": {"content": '{"answer": 42}'}}]}]
    )
    resp = await provider.complete(
        messages=[{"role": "user", "content": "test"}],
        params={},
    )
    assert resp.output_text == '{"answer": 42}'
    assert provider.provider_name == "mock"


async def test_mock_provider_cycles_responses():
    from llm_service.providers.mock import MockProvider

    provider = MockProvider(
        responses=[
            {"choices": [{"message": {"content": "first"}}]},
            {"choices": [{"message": {"content": "second"}}]},
        ]
    )
    r1 = await provider.complete(messages=[], params={})
    r2 = await provider.complete(messages=[], params={})
    assert r1.output_text == "first"
    assert r2.output_text == "second"


async def test_mock_provider_can_raise_error():
    from llm_service.providers.mock import MockProvider
    from llm_service.providers.base import ProviderError

    provider = MockProvider(error=ProviderError("timeout", "connection timed out"))
    with pytest.raises(ProviderError):
        await provider.complete(messages=[], params={})


async def test_openai_compatible_builds_correct_url():
    from llm_service.providers.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="test-key",
        model="llama3",
    )
    assert provider.provider_name == "openai_compatible"
    assert provider.default_model == "llama3"


async def test_anthropic_provider_properties():
    from llm_service.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )
    assert provider.provider_name == "anthropic"
    assert provider.default_model == "claude-sonnet-4-20250514"
    await provider.close()


async def test_anthropic_converts_system_messages():
    from llm_service.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="test", model="claude-sonnet-4-20250514")
    system, msgs = provider._convert_messages([
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "How are you?"},
    ])
    assert system == "You are helpful."
    assert len(msgs) == 3
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "user"
    await provider.close()


async def test_anthropic_json_object_fallback_extracts_json():
    """When model ignores tool_use and returns plain text with JSON inside,
    the provider should extract the JSON portion."""
    from unittest.mock import AsyncMock, patch
    from llm_service.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        api_key="test-key",
        model="test-model",
        base_url="http://localhost:12345/v1/messages",
    )
    fake_response = {
        "content": [{"type": "text", "text": 'Here is the result: {"answer": 42}'}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: fake_response

    with patch.object(provider._client, "post", return_value=mock_resp):
        resp = await provider.complete(
            messages=[{"role": "user", "content": "test"}],
            params={},
            response_format={"type": "json_object"},
        )
    assert resp.output_text == '{"answer": 42}'
    await provider.close()


async def test_anthropic_json_object_tool_use_returns_input():
    """When model returns tool_use block, provider should serialize the input."""
    from unittest.mock import AsyncMock, patch
    from llm_service.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        api_key="test-key",
        model="test-model",
        base_url="http://localhost:12345/v1/messages",
    )
    fake_response = {
        "content": [
            {
                "type": "tool_use",
                "name": "structured_output",
                "input": {"result": "hello"},
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: fake_response

    with patch.object(provider._client, "post", return_value=mock_resp):
        resp = await provider.complete(
            messages=[{"role": "user", "content": "test"}],
            params={},
            response_format={"type": "json_object"},
        )
    import json
    assert json.loads(resp.output_text) == {"result": "hello"}
    await provider.close()


async def test_anthropic_json_object_uses_empty_schema_when_none_provided():
    """Default behavior: no schema in response_format → empty input_schema
    (just enough to trigger tool_use). Backward-compat guard."""
    from unittest.mock import AsyncMock, patch
    from llm_service.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="k", model="m", base_url="http://x/v1/messages")
    captured_body = {}

    def capture_post(url, json=None, headers=None):
        captured_body.update(json or {})
        mock = AsyncMock()
        mock.status_code = 200
        mock.json = lambda: {"content": [], "usage": {}}
        return mock

    with patch.object(provider._client, "post", side_effect=capture_post):
        await provider.complete(
            messages=[{"role": "user", "content": "x"}],
            params={},
            response_format={"type": "json_object"},
        )
    tools = captured_body.get("tools", [])
    assert len(tools) == 1
    assert tools[0]["name"] == "structured_output"
    # Empty default schema still triggers tool_use
    assert tools[0]["input_schema"] == {"type": "object", "properties": {}}
    await provider.close()


async def test_anthropic_json_object_passes_schema_to_tool_use():
    """When response_format carries a schema, it must be plumbed into tool_use.input_schema
    so the model receives stronger constraints than the empty default."""
    from unittest.mock import AsyncMock, patch
    from llm_service.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="k", model="m", base_url="http://x/v1/messages")
    captured_body = {}
    expected_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    def capture_post(url, json=None, headers=None):
        captured_body.update(json or {})
        mock = AsyncMock()
        mock.status_code = 200
        mock.json = lambda: {"content": [], "usage": {}}
        return mock

    with patch.object(provider._client, "post", side_effect=capture_post):
        await provider.complete(
            messages=[{"role": "user", "content": "x"}],
            params={},
            response_format={"type": "json_object", "schema": expected_schema},
        )
    tools = captured_body.get("tools", [])
    assert len(tools) == 1
    assert tools[0]["input_schema"] == expected_schema
    await provider.close()

