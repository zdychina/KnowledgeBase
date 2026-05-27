"""PDF preprocessing for ingestion: .pdf → plain text string.

Uses pdfminer.six's high-level `extract_text`. Page separators (form-feed,
``\\x0c``) are normalized to blank lines so the downstream paragraph splitter
in `PlainTextParser` treats page boundaries as paragraph boundaries.

Public API:

    pdf_to_text(src) -> str
"""
from __future__ import annotations

from pathlib import Path


def pdf_to_text(src: Path) -> str:
    """Extract plain text from a PDF file.

    Raises FileNotFoundError if `src` does not exist. Any pdfminer parse
    failure (encrypted PDF, malformed structure) propagates as the original
    exception — callers in the ingestion loop catch and log it.
    """
    from pdfminer.high_level import extract_text

    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)

    text = extract_text(str(src))
    return text.replace("\x0c", "\n\n").strip()
