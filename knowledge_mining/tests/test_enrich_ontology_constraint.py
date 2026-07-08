"""单测：enrich 篇章本职（语义角色 + 内容质量；纯函数，无需 DB/LLM）。

实体抽取与逃生口已拆到 entity_extract 阶段（见 test_entity_extract.py，L4 §15），
本文件只验证 enrich 的 _apply_llm_result 现在只处理：
- semantic_role（受 valid_roles 约束）；
- document_type → meta["llm_document_type"]；
- content_assessment → meta["content_assessment"]；
- 不再产 entity_refs_json / out_of_schema。
"""
from __future__ import annotations

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.stages.enrich import _apply_llm_result


def _seg() -> RawSegmentData:
    return RawSegmentData(
        document_key="doc-1",
        segment_index=0,
        block_type="paragraph",
        raw_text="UPF 经 N4 接口与 SMF 通信。",
    )


def test_semantic_role_applied_within_valid_roles() -> None:
    result = {"semantic_role": "procedure_step"}
    out = _apply_llm_result(_seg(), result, frozenset({"procedure_step", "concept"}))
    assert out.semantic_role == "procedure_step"


def test_semantic_role_rejected_outside_valid_roles() -> None:
    seg = _seg()
    result = {"semantic_role": "bogus_role"}
    out = _apply_llm_result(seg, result, frozenset({"concept"}))
    assert out.semantic_role == seg.semantic_role  # 未采用


def test_document_type_and_assessment_into_meta() -> None:
    result = {
        "document_type": "reference",
        "content_assessment": {"is_substantive": True, "is_navigation": False,
                               "assessment_reason": "含实体功能描述"},
    }
    out = _apply_llm_result(_seg(), result, None)
    assert out.metadata_json["llm_document_type"] == "reference"
    assert out.metadata_json["content_assessment"]["is_substantive"] is True


def test_enrich_no_longer_produces_entities() -> None:
    # 即便 LLM 误返回 entities/out_of_schema，enrich 也不再处理它们
    result = {"entities": [{"name": "SMF", "type": "network_element"}],
              "out_of_schema": [{"name": "X", "type": "concept"}]}
    out = _apply_llm_result(_seg(), result, None)
    assert list(out.entity_refs_json) == []
    assert "out_of_schema" not in out.metadata_json


def test_no_changes_returns_same_instance() -> None:
    seg = _seg()
    out = _apply_llm_result(seg, {}, frozenset({"concept"}))
    assert out is seg
