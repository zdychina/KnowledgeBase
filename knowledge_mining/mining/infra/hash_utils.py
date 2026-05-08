"""Conservative snapshot hash utilities for the v1.1 mining pipeline."""
from __future__ import annotations

import hashlib


def normalize_for_snapshot(raw_content: str) -> str:
    """Conservative normalization for snapshot sharing boundary.

    Steps (ONLY these, nothing more):
    1. CRLF -> LF
    2. Strip trailing whitespace per line
    3. Remove empty lines
    4. Join back with LF

    Does NOT: remove comments, do semantic cleaning, do encoding conversion.
    """
    lines = raw_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    non_empty = [line.rstrip() for line in lines if line.strip()]
    return "\n".join(non_empty)


def compute_snapshot_hash(raw_content: str) -> str:
    """SHA256(normalize_for_snapshot(raw_content)) — for normalized_content_hash."""
    normalized = normalize_for_snapshot(raw_content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_raw_hash(raw_content_bytes: bytes) -> str:
    """SHA256(raw bytes) — for raw_content_hash."""
    return hashlib.sha256(raw_content_bytes).hexdigest()


def content_hash(text: str) -> str:
    """SHA256(text) — for segment content_hash."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_hash(text: str) -> str:
    """SHA256(text.lower().strip()) — for segment normalized_hash."""
    return hashlib.sha256(text.lower().strip().encode("utf-8")).hexdigest()
