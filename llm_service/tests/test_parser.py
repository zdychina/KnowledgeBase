from llm_service.runtime.parser import parse_output


def test_parse_json_object_success():
    result = parse_output('{"answer": 42}', expected_type="json_object")
    assert result.parse_status == "succeeded"
    assert result.parsed_output == {"answer": 42}


def test_parse_json_array_success():
    result = parse_output("[1, 2, 3]", expected_type="json_array")
    assert result.parse_status == "succeeded"
    assert result.parsed_output == [1, 2, 3]


def test_parse_text_success():
    result = parse_output("hello world", expected_type="text")
    assert result.parse_status == "succeeded"
    assert result.text_output == "hello world"


def test_parse_json_failure():
    result = parse_output("not json", expected_type="json_object")
    assert result.parse_status == "failed"
    assert result.parse_error is not None


def test_schema_validation_pass():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    result = parse_output('{"name": "test"}', expected_type="json_object", schema=schema)
    assert result.parse_status == "succeeded"


def test_schema_validation_fail():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    result = parse_output('{"age": 10}', expected_type="json_object", schema=schema)
    assert result.parse_status == "schema_invalid"
    assert len(result.validation_errors) > 0


def test_text_type_skips_schema():
    result = parse_output("hello", expected_type="text", schema={"type": "string"})
    assert result.parse_status == "succeeded"


def test_parse_json_with_markdown_fence():
    """LLMs often wrap JSON in ```json ... ``` blocks."""
    raw = '```json\n{"answer": 42}\n```'
    result = parse_output(raw, expected_type="json_object")
    assert result.parse_status == "succeeded"
    assert result.parsed_output == {"answer": 42}


def test_parse_json_array_with_markdown_fence():
    raw = '```json\n[{"q": "hi", "a": "hello"}]\n```'
    result = parse_output(raw, expected_type="json_array")
    assert result.parse_status == "succeeded"
    assert len(result.parsed_output) == 1


def test_parse_empty_input():
    result = parse_output(None, expected_type="json_object")
    assert result.parse_status == "failed"
    assert "empty" in result.parse_error
