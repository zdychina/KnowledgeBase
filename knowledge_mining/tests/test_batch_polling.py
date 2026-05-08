"""Test batch polling: verify poll_all for question gen & contextualizer."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from knowledge_mining.mining.contracts.models import RawSegmentData


def _make_segments(n: int = 3) -> list[RawSegmentData]:
    """Create test segments."""
    return [
        RawSegmentData(
            document_key="doc:/test.md",
            segment_index=i,
            raw_text=f"Content for segment {i}. " * 10,
            section_title=f"Section {i}",
            block_type="paragraph",
            token_count=50,
        )
        for i in range(n)
    ]


class TestQuestionGeneratorBatchPolling:
    @patch("knowledge_mining.mining.stages.retrieval_units.LlmQuestionGenerator.__init__", return_value=None)
    def test_generate_batch_uses_poll_all(self, mock_init):
        """generate_batch should call poll_all, not serial poll_result."""
        from knowledge_mining.mining.stages.retrieval_units import LlmQuestionGenerator

        gen = LlmQuestionGenerator.__new__(LlmQuestionGenerator)
        gen._client = MagicMock()
        gen._timeout = 30
        gen._last_task_ids = {}
        gen._profile = None

        # Mock submit to return task_ids
        gen._client.submit_task.side_effect = [
            "task-1", "task-2", "task-3",
        ]

        # Mock poll_all to return results for all tasks
        gen._client.poll_all.return_value = {
            "doc:/test.md#0": [{"question": "What is segment 0?"}],
            "doc:/test.md#1": [{"question": "What is segment 1?"}],
            "doc:/test.md#2": [{"question": "What is segment 2?"}],
        }

        segments = _make_segments(3)
        results = gen.generate_batch(segments)

        # poll_all should have been called once
        gen._client.poll_all.assert_called_once()
        call_args = gen._client.poll_all.call_args[0][0]
        assert len(call_args) == 3

        # Results should map seg_key -> questions
        assert "doc:/test.md#0" in results
        assert results["doc:/test.md#0"] == ["What is segment 0?"]

        # task_ids should be stored for provenance
        assert "doc:/test.md#0" in gen.last_task_ids
        assert gen.last_task_ids["doc:/test.md#0"] == "task-1"

    def test_generate_batch_empty_segments(self):
        """generate_batch with empty input should return empty dict."""
        from knowledge_mining.mining.stages.retrieval_units import LlmQuestionGenerator

        gen = LlmQuestionGenerator.__new__(LlmQuestionGenerator)
        gen._client = MagicMock()
        gen._timeout = 30
        gen._last_task_ids = {}
        gen._profile = None

        results = gen.generate_batch([])
        assert results == {}
        gen._client.poll_all.assert_not_called()


class TestContextualizerBatchPolling:
    @patch("knowledge_mining.mining.stages.retrieval_units.LLMContextualizer.__init__", return_value=None)
    def test_contextualize_uses_poll_all(self, mock_init):
        """contextualize should call poll_all, not serial poll_result."""
        from knowledge_mining.mining.stages.retrieval_units import LLMContextualizer

        ctxer = LLMContextualizer.__new__(LLMContextualizer)
        ctxer._client = MagicMock()
        ctxer._timeout = 30
        ctxer._last_task_ids = {}

        ctxer._client.submit_task.side_effect = ["task-a", "task-b"]
        ctxer._client.poll_all.return_value = {
            "doc:/test.md#0": [{"context": "Intro section of test document"}],
            "doc:/test.md#1": [{"context": "Body section covering details"}],
        }

        segments = _make_segments(2)
        results = ctxer.contextualize(segments, "Full document text here")

        ctxer._client.poll_all.assert_called_once()
        assert "doc:/test.md#0" in results
        assert results["doc:/test.md#0"] == "Intro section of test document"

        # task_ids stored for provenance
        assert ctxer.last_task_ids["doc:/test.md#0"] == "task-a"

    def test_contextualize_skips_empty_segments(self):
        """Empty segments should not be submitted."""
        from knowledge_mining.mining.stages.retrieval_units import LLMContextualizer

        ctxer = LLMContextualizer.__new__(LLMContextualizer)
        ctxer._client = MagicMock()
        ctxer._timeout = 30
        ctxer._last_task_ids = {}

        segments = [
            RawSegmentData(document_key="doc:/a.md", segment_index=0, raw_text=""),
            RawSegmentData(document_key="doc:/a.md", segment_index=1, raw_text="  "),
        ]

        results = ctxer.contextualize(segments, "doc text")
        assert results == {}
        ctxer._client.submit_task.assert_not_called()
