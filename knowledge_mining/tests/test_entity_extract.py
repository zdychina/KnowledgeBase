"""单测：entity_extract 双通道实体抽取（纯函数，无需 DB/LLM）。对应 L4 §15 / N1 重排。

验证 _apply_entity_result（N1 后，本体外概念不再产候选，统一进 entity_refs_json）：
- 通道 A：类型在 active 本体内且置信够 → 普通 ref（带正式类型）；
- 通道 A：类型本体外 → 暂无类型 ref（type='__untyped__'，proposed_type 记原类型）；
- 通道 A：类型合法但置信不足 → 暂无类型 ref（off_schema_reason='low_confidence'）；
- 通道 B：模型自报 out_of_schema → 暂无类型 ref（proposed_type + evidence 透传）；
- allowed_types 为空时不做过滤；无变更返回原对象。
"""
from __future__ import annotations

from knowledge_mining.mining.contracts.models import RawSegmentData
from knowledge_mining.mining.infra.ontology_store import UNTYPED_NODE_TYPE
from knowledge_mining.mining.stages.entity_extract import _apply_entity_result


def _seg() -> RawSegmentData:
    return RawSegmentData(
        document_key="doc-1",
        segment_index=0,
        block_type="paragraph",
        raw_text="UPF 经 N4 接口与 SMF 通信。",
    )


def _untyped(out: RawSegmentData) -> list[dict]:
    return [r for r in out.entity_refs_json if r["type"] == UNTYPED_NODE_TYPE]


def test_in_schema_entity_kept_off_schema_to_untyped() -> None:
    allowed = frozenset({"network_element", "interface"})
    result = {
        "entities": [
            {"name": "UPF", "type": "network_element", "confidence": 0.95},
            {"name": "N4", "type": "interface", "confidence": 0.9},
            {"name": "某私有部件", "type": "vendor_widget", "confidence": 0.9},  # 本体外
        ],
    }
    out = _apply_entity_result(_seg(), result, allowed)

    refs = {(r["type"], r["name"]) for r in out.entity_refs_json}
    assert ("network_element", "UPF") in refs
    assert ("interface", "N4") in refs
    # 本体外概念落成暂无类型 ref，proposed_type 保留模型原判类型
    untyped = _untyped(out)
    item = next(r for r in untyped if r["name"] == "某私有部件")
    assert item["off_schema_reason"] == "off_schema_type"
    assert item["proposed_type"] == "vendor_widget"
    # 不再写 meta["out_of_schema"]
    assert "out_of_schema" not in out.metadata_json


def test_low_confidence_diverted_to_untyped() -> None:
    allowed = frozenset({"network_element"})
    result = {"entities": [{"name": "X网元", "type": "network_element", "confidence": 0.2}]}
    out = _apply_entity_result(_seg(), result, allowed)

    # 低置信不再当正式类型 ref，转暂无类型交 Gate2
    assert ("network_element", "X网元") not in {(r["type"], r["name"]) for r in out.entity_refs_json}
    item = next(r for r in _untyped(out) if r["name"] == "X网元")
    assert item["off_schema_reason"] == "low_confidence"
    assert item["proposed_type"] == "network_element"


def test_missing_confidence_treated_as_ok() -> None:
    allowed = frozenset({"network_element"})
    result = {"entities": [{"name": "SMF", "type": "network_element"}]}  # 无 confidence
    out = _apply_entity_result(_seg(), result, allowed)
    assert ("network_element", "SMF") in {(r["type"], r["name"]) for r in out.entity_refs_json}


def test_channel_b_out_of_schema_to_untyped() -> None:
    allowed = frozenset({"network_element"})
    result = {
        "entities": [{"name": "SMF", "type": "network_element", "confidence": 0.95}],
        "out_of_schema": [
            {"name": "网络切片", "proposed_type": "concept",
             "reason": "核心架构概念", "evidence": "网络切片提供隔离逻辑网络"},
        ],
    }
    out = _apply_entity_result(_seg(), result, allowed)

    assert ("network_element", "SMF") in {(r["type"], r["name"]) for r in out.entity_refs_json}
    item = next(r for r in _untyped(out) if r["name"] == "网络切片")
    assert item["type"] == UNTYPED_NODE_TYPE
    assert item["proposed_type"] == "concept"
    assert item["off_schema_reason"] == "llm_out_of_schema"
    assert item["proposed_reason"] == "核心架构概念"
    assert item["evidence"] == "网络切片提供隔离逻辑网络"


def test_empty_allowed_types_no_filtering() -> None:
    result = {"entities": [{"name": "X", "type": "anything", "confidence": 0.9}]}
    out = _apply_entity_result(_seg(), result, frozenset())

    assert ("anything", "X") in {(r["type"], r["name"]) for r in out.entity_refs_json}
    assert "out_of_schema" not in out.metadata_json


def test_no_changes_returns_same_instance() -> None:
    seg = _seg()
    out = _apply_entity_result(seg, {}, frozenset({"network_element"}))
    assert out is seg
