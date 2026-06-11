"""Archive extraction — ZIP, CHM, HDX.

CHM uses Windows hh.exe or 7z to decompress into individual HTML files.
HDX (Huawei HedEx) is a ZIP variant extracted via stdlib.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    """Result of archive extraction."""
    extracted_files: list[str] = field(default_factory=list)
    error: str | None = None


def _is_safe_path(member_path: str, dest_dir: Path) -> bool:
    """Check that extracting member_path under dest_dir won't escape dest_dir."""
    resolved = (dest_dir / member_path).resolve()
    return resolved.is_relative_to(dest_dir.resolve())


def _fix_zip_filename(info: zipfile.ZipInfo) -> str:
    """Handle Chinese filenames in ZIP archives.

    ZIP files created on Windows may encode filenames in GBK instead of UTF-8.
    The UTF-8 flag (bit 11) in flag_bits indicates whether the filename is UTF-8.
    """
    raw_name = info.filename
    if not raw_name:
        return raw_name
    if info.flag_bits & 0x800:
        return raw_name
    try:
        raw_bytes = raw_name.encode("cp437")
        return raw_bytes.decode("gbk")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return raw_name


def extract_zip(archive_path: Path, dest_dir: Path) -> ExtractResult:
    """Extract a ZIP archive with path-traversal protection and Chinese filename support."""
    extracted: list[str] = []

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                safe_name = _fix_zip_filename(info)
                member_path = Path(safe_name).as_posix()

                if not _is_safe_path(member_path, dest_dir):
                    return ExtractResult(
                        error=f"Path traversal detected in ZIP member: {safe_name}",
                    )

                out_path = dest_dir / member_path
                out_path.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(info) as src, open(out_path, "wb") as dst:
                    dst.write(src.read())

                extracted.append(member_path)

    except zipfile.BadZipFile as exc:
        return ExtractResult(error=f"Bad ZIP file: {exc}")
    except Exception as exc:
        return ExtractResult(error=f"ZIP extraction failed: {exc}")

    return ExtractResult(extracted_files=extracted)


def extract_chm(archive_path: Path, dest_dir: Path) -> ExtractResult:
    """Extract a .chm file into dest_dir. Prefers Windows hh.exe; falls back to 7z."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    hh = shutil.which("hh")
    if hh is None:
        candidate = Path(r"C:\Windows\hh.exe")
        if candidate.exists():
            hh = str(candidate)

    if hh is not None:
        subprocess.run(
            [hh, "-decompile", str(dest_dir.resolve()), str(archive_path.resolve())],
            check=False,
            capture_output=True,
        )
        if any(dest_dir.iterdir()):
            return _list_extracted(dest_dir)

    sevenz = shutil.which("7z") or shutil.which("7z.exe")
    if sevenz is not None:
        result = subprocess.run(
            [sevenz, "x", str(archive_path), f"-o{dest_dir}", "-y"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0 and any(dest_dir.iterdir()):
            return _list_extracted(dest_dir)
        return ExtractResult(
            error=f"7z failed for {archive_path}: {result.stderr.decode('utf-8', errors='replace')}"
        )

    return ExtractResult(error="No CHM extractor available. Need Windows hh.exe or 7-Zip on PATH.")


def extract_hdx(archive_path: Path, dest_dir: Path) -> ExtractResult:
    """Extract a .hdx file (Huawei HedEx zip archive)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(archive_path):
        return ExtractResult(error=f"{archive_path} is not a valid zip archive (.hdx)")
    # HDX is just a ZIP — reuse extract_zip
    return extract_zip(archive_path, dest_dir)


def _list_extracted(directory: Path) -> ExtractResult:
    """List all files under directory relative to it."""
    files = [
        str(p.relative_to(directory)).replace("\\", "/")
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    ]
    return ExtractResult(extracted_files=files)


def extract_archive(archive_path: Path, dest_dir: Path) -> ExtractResult:
    """Extract an archive. On success, deletes the original archive file."""
    ext = archive_path.suffix.lower()

    if ext == ".zip":
        result = extract_zip(archive_path, dest_dir)
    elif ext == ".chm":
        result = extract_chm(archive_path, dest_dir)
    elif ext == ".hdx":
        result = extract_hdx(archive_path, dest_dir)
    else:
        return ExtractResult(
            error=f"不支持自动解压 {ext} 格式",
        )

    if result.error is None and result.extracted_files:
        try:
            archive_path.unlink()
            logger.info(
                "Extracted %s → %d files, archive deleted",
                archive_path.name, len(result.extracted_files),
            )
        except OSError as exc:
            logger.warning("Failed to delete archive %s: %s", archive_path, exc)

    return result
