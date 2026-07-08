"""find_duplicate_type 判重纯函数单测：完全重名 / 双向包含 / 命中示例 / 无重复。"""
from __future__ import annotations

from knowledge_mining.mining.infra.ontology_store import find_duplicate_type


def test_exact_name_match_case_and_space_insensitive() -> None:
    existing = [{"name": "网络切片类", "examples": []}]
    assert find_duplicate_type(" 网络切片类 ", existing) == "网络切片类"


def test_bidirectional_containment() -> None:
    # 现有名包含提议名
    assert find_duplicate_type("切片", [{"name": "切片类"}]) == "切片类"
    # 提议名包含现有名
    assert find_duplicate_type("网络切片类", [{"name": "切片类"}]) == "切片类"


def test_match_against_example() -> None:
    existing = [{"name": "网络功能", "examples": ["UPF", "SMF"]}]
    assert find_duplicate_type("upf", existing) == "网络功能"


def test_no_duplicate_returns_none() -> None:
    existing = [{"name": "协议类", "examples": ["PFCP"]}]
    assert find_duplicate_type("接口", existing) is None


def test_blank_proposed_returns_none() -> None:
    assert find_duplicate_type("   ", [{"name": "协议类"}]) is None
