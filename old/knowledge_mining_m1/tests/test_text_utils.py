"""Verify text utility functions."""
from knowledge_mining.mining.text_utils import (
    content_hash,
    hamming_distance,
    jaccard_similarity,
    normalize_text,
    normalized_hash,
    simhash_fingerprint,
    token_count,
)


def test_content_hash_deterministic():
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_content_hash_different():
    h1 = content_hash("hello")
    h2 = content_hash("world")
    assert h1 != h2


def test_normalize_text():
    result = normalize_text("  Hello   World  ")
    assert result == "hello world"


def test_normalize_text_cjk():
    result = normalize_text("５Ｇ　网络")
    assert "5g" in result
    assert "网络" in result


def test_normalized_hash():
    h = normalized_hash("  Hello   World  ")
    assert len(h) == 64


def test_simhash_similar():
    fp1 = simhash_fingerprint("ADD APN命令用于配置APN")
    fp2 = simhash_fingerprint("ADD APN命令用于配置APN。")
    dist = hamming_distance(fp1, fp2)
    assert dist <= 3


def test_simhash_different():
    fp1 = simhash_fingerprint("ADD APN命令用于配置APN")
    fp2 = simhash_fingerprint("网络切片是一种5G核心技术")
    dist = hamming_distance(fp1, fp2)
    assert dist > 10


def test_jaccard():
    s = jaccard_similarity("hello world foo", "hello world bar")
    assert 0.3 < s < 0.7


def test_jaccard_identical():
    assert jaccard_similarity("a b c", "a b c") == 1.0


def test_token_count_ascii():
    assert token_count("hello world") == 2


def test_token_count_cjk():
    count = token_count("５Ｇ网络配置")
    assert count >= 3  # at least some tokens extracted
