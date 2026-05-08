"""CLI: Extract documentation archives (.chm / .hdx) into folders of HTML + assets.

This is now a thin wrapper around
`knowledge_mining_zym.mining.ingestion.preprocessing` so there is a single source
of truth for chm/hdx handling. The mining ingestion pipeline calls the same
extraction code automatically when it encounters `.chm`/`.hdx` files.

Usage:
    # single file
    python scripts/data/extract_doc_archive.py path/to/foo.chm
    python scripts/data/extract_doc_archive.py path/to/foo.hdx -o out_dir

    # batch
    python scripts/data/extract_doc_archive.py path/to/dir --batch -o out_dir
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from knowledge_mining_zym.mining.ingestion.preprocessing import (  # noqa: E402
    SUPPORTED_ARCHIVE_EXTS,
    extract_archive,
)


def extract_one(src: Path, out_root: Path) -> Path:
    ext = src.suffix.lower()
    if ext not in SUPPORTED_ARCHIVE_EXTS:
        raise ValueError(f"Unsupported extension {ext!r}: {src}")
    dst = out_root / src.stem
    extract_archive(src, dst)
    return dst


def _count_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract .chm and .hdx documentation archives.",
    )
    parser.add_argument("input", type=Path, help="Input file or directory")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output directory (default: input's parent directory).",
    )
    parser.add_argument(
        "--batch", action="store_true",
        help="Treat input as a directory; recursively extract every .chm/.hdx found.",
    )
    args = parser.parse_args(argv)

    src: Path = args.input
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 2

    out_root: Path = args.output if args.output is not None else (
        src if src.is_dir() else src.parent
    )
    out_root.mkdir(parents=True, exist_ok=True)

    if args.batch or src.is_dir():
        files = sorted(
            p for p in src.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_ARCHIVE_EXTS
        )
        if not files:
            print(f"No .chm/.hdx files found under {src}", file=sys.stderr)
            return 1

        ok = 0
        for f in files:
            print(f"[extract] {f}", flush=True)
            try:
                dst = extract_one(f, out_root)
                print(f"  -> {dst}  ({_count_files(dst)} files)")
                ok += 1
            except Exception as e:
                print(f"  FAILED: {e}", file=sys.stderr)
        print(f"Done: {ok}/{len(files)} archives extracted into {out_root}")
        return 0 if ok == len(files) else 1

    try:
        dst = extract_one(src, out_root)
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(f"Extracted -> {dst}  ({_count_files(dst)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
