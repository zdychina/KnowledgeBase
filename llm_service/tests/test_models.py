import pytest
from llm_service.models import (
    EmbeddingRequest,
    TaskSubmitRequest,
    ExecuteResponse,
    ParsedResult,
    ErrorInfo,
    RerankRequest,
)


def test_task_submit_request_defaults():
    req = TaskSubmitRequest(
        caller_service="mining",
        knowledge_domain="cloud_core_network",
        pipeline_stage="summary_generation",
    )
    assert req.caller_service == "mining"
    assert req.knowledge_domain == "cloud_core_network"
    assert req.max_attempts == 3
    assert req.priority == 100
    assert req.params is None
    assert req.idempotency_key is None


def test_task_submit_request_validation_rejects_bad_service():
    with pytest.raises(ValueError):
        TaskSubmitRequest(
            caller_service="",
            pipeline_stage="test",
        )

    with pytest.raises(ValueError):
        TaskSubmitRequest(
            caller_service="x" * 65,
            pipeline_stage="test",
        )


def test_task_submit_request_accepts_legacy_caller_domain():
    req = TaskSubmitRequest(
        caller_domain="mining",
        pipeline_stage="test",
    )
    assert req.caller_service == "mining"
    assert req.knowledge_domain is None


def test_execute_response_with_result():
    resp = ExecuteResponse(
        task_id="t-1",
        status="succeeded",
        result=ParsedResult(
            parse_status="succeeded",
            parsed_output={"summary": "hello"},
        ),
        attempts=1,
        total_tokens=100,
        latency_ms=500,
        error=None,
    )
    assert resp.result.parse_status == "succeeded"
    assert resp.result.parsed_output["summary"] == "hello"


def test_execute_response_with_error():
    resp = ExecuteResponse(
        task_id="t-1",
        status="failed",
        result=None,
        attempts=3,
        total_tokens=300,
        latency_ms=1500,
        error=ErrorInfo(
            error_type="provider_error",
            error_message="timeout after 30s",
        ),
    )
    assert resp.error.error_type == "provider_error"


def test_embedding_request_normalizes_scalar_input():
    req = EmbeddingRequest(
        input="alpha",
        caller_service="serving",
        knowledge_domain="generic",
    )
    assert req.input == ["alpha"]
    assert req.caller_service == "serving"
    assert req.knowledge_domain == "generic"


def test_rerank_request_rejects_empty_documents():
    with pytest.raises(ValueError):
        RerankRequest(query="q", documents=[])
