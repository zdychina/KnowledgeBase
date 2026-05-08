"""Text tokenization, normalization, and similarity utilities for v1.2 Mining."""
from __future__ import annotations

import re
import unicodedata


def tokenize_for_search(text: str) -> str:
    """Tokenize text for FTS5 search. Uses jieba for CJK if available."""
    try:
        import jieba
        return " ".join(jieba.cut(text))
    except ImportError:
        return text


def _tokenize(text: str) -> list[str]:
    """Split text into tokens. CJK chars count individually."""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf.lower())
                buf = ""
            tokens.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            if buf:
                tokens.append(buf.lower())
                buf = ""
    if buf:
        tokens.append(buf.lower())
    return tokens


def token_count(text: str) -> int:
    """Count tokens (CJK-aware). CJK chars count individually."""
    return len(_tokenize(text))


def normalize_text(text: str) -> str:
    """Normalize text for dedup: CJK fullwidth→halfwidth, lowercase, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def simhash_fingerprint(text: str, bits: int = 64) -> int:
    """Compute SimHash fingerprint for near-duplicate detection."""
    import hashlib

    tokens = _tokenize(text)
    if not tokens:
        return 0
    v = [0] * bits
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(bits):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(fp1: int, fp2: int, bits: int = 64) -> int:
    """Count differing bits between two fingerprints."""
    x = fp1 ^ fp2
    count = 0
    while x and count < bits:
        count += x & 1
        x >>= 1
    return count


def jaccard_similarity(text1: str, text2: str) -> float:
    """Jaccard similarity of token sets."""
    s1 = set(_tokenize(text1))
    s2 = set(_tokenize(text2))
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)
