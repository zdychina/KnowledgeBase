from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from jsonschema import SchemaError as JsSchemaError, ValidationError as JsValidationError, validate as js_validate


@dataclass
class ParseResult:
    parse_status: str  # succeeded | failed | schema_invalid
    parsed_output: dict | list | None = None
    text_output: str | None = None
    parse_error: str | None = None
    validation_errors: list[str] = field(default_factory=list)


def parse_output(
    raw_text: str | None,
    expected_type: str,
    schema: dict | None = None,
) -> ParseResult:
    if not raw_text:
        return ParseResult(parse_status="failed", parse_error="empty or null response from provider")

    if expected_type == "text":
        return ParseResult(parse_status="succeeded", text_output=raw_text)

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw_text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped).strip()

    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError) as e:
        return ParseResult(parse_status="failed", parse_error=str(e))

    if expected_type == "json_object" and not isinstance(parsed, dict):
        return ParseResult(
            parse_status="failed",
            parse_error=f"expected json_object, got {type(parsed).__name__}",
        )
    if expected_type == "json_array" and not isinstance(parsed, list):
        return ParseResult(
            parse_status="failed",
            parse_error=f"expected json_array, got {type(parsed).__name__}",
        )

    if schema:
        try:
            js_validate(instance=parsed, schema=schema)
        except JsSchemaError as e:
            return ParseResult(
                parse_status="failed",
                parsed_output=parsed,
                parse_error=f"invalid schema: {e.message}",
            )
        except JsValidationError as e:
            return ParseResult(
                parse_status="schema_invalid",
                parsed_output=parsed,
                validation_errors=[e.message],
            )

    return ParseResult(parse_status="succeeded", parsed_output=parsed)
