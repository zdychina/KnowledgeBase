"""Domain-scoped download and soft-withdrawal services.

This module deliberately has no FastAPI dependency.  It is used by the HTTP
adapter, but keeps the active-release boundary, source-file validation, and
withdrawal semantics testable on their own.
"""
from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from knowledge_mining.mining.infra.db import AssetCoreDB
from knowledge_mining.mining.stages.withdrawal import (
    ActiveResourceNotFound,
    WithdrawalResult,
    withdraw_document as _withdraw_document,
    withdraw_source_batch as _withdraw_source_batch,
)


class UnsafeDownloadPath(ValueError):
    """A stored source URI is not a regular managed upload file."""


class LifecycleResourceNotFound(LookupError):
    """The requested resource is not currently visible in this domain."""


@dataclass(frozen=True)
class ActiveDownload:
    path: Path
    filename: str
    media_type: str


_WINDOWS_REPARSE_POINT = 0x400
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def resolve_managed_file(upload_root: Path, source_uri: str | Path) -> Path:
    """Resolve one stored source URI without following any managed-path link.

    Both lexical and resolved containment are checked. Every component below
    the upload root is inspected with ``lstat`` so a symlink/junction is
    rejected even when it resolves to another location inside the same root.
    """
    try:
        raw_root = Path(upload_root)
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise UnsafeDownloadPath

        raw_candidate = Path(source_uri)
        if ".." in raw_candidate.parts:
            raise UnsafeDownloadPath
        if not raw_candidate.is_absolute():
            raw_candidate = root / raw_candidate

        # abspath collapses '.' without resolving links, which lets the lstat
        # walk below inspect the exact stored path rather than its final target.
        lexical_candidate = Path(os.path.abspath(os.fspath(raw_candidate)))
        try:
            relative = lexical_candidate.relative_to(root)
        except ValueError as exc:
            raise UnsafeDownloadPath from exc

        current = root
        if _is_link_or_reparse(current):
            raise UnsafeDownloadPath
        for part in relative.parts:
            current = current / part
            if _is_link_or_reparse(current):
                raise UnsafeDownloadPath

        candidate = lexical_candidate.resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise UnsafeDownloadPath from exc

        info = candidate.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeDownloadPath
        return candidate
    except UnsafeDownloadPath:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise UnsafeDownloadPath from exc


def safe_download_name(value: str | None) -> str:
    """Return a path-free filename that cannot inject response headers."""
    raw = str(value or "download").replace("\\", "/").rsplit("/", 1)[-1]
    raw = "".join(ch for ch in raw if ord(ch) >= 32 and ord(ch) != 127)
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", raw).strip().strip(".")
    return cleaned or "download"


def content_disposition(filename: str) -> str:
    """Build an attachment header with ASCII and RFC 5987 filenames."""
    filename = safe_download_name(filename)
    fallback = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    fallback = safe_download_name(fallback or "download").replace('"', "_")
    encoded = quote(filename.encode("utf-8"), safe="")
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{encoded}"
    )


_ACTIVE_DOWNLOAD_SQL = """
SELECT documents.document_name,
       snapshots.title,
       snapshots.mime_type,
       selected_link.source_uri
FROM asset_publish_releases AS releases
JOIN asset_builds AS builds
  ON builds.id = releases.build_id
 AND builds.domain = releases.domain
JOIN asset_build_document_snapshots AS selections
  ON selections.build_id = builds.id
 AND selections.selection_status = 'active'
JOIN asset_documents AS documents
  ON documents.id = selections.document_id
 AND documents.domain = releases.domain
JOIN asset_document_snapshots AS snapshots
  ON snapshots.id = selections.document_snapshot_id
 AND snapshots.domain = releases.domain
LEFT JOIN asset_source_batches AS batches
  ON batches.id = selections.source_batch_id
 AND batches.domain = releases.domain
JOIN LATERAL (
    SELECT links.source_uri,
           links.linked_at,
           links.id
    FROM asset_document_snapshot_links AS links
    WHERE links.document_id = selections.document_id
      AND links.document_snapshot_id = selections.document_snapshot_id
      AND links.source_batch_id
          IS NOT DISTINCT FROM selections.source_batch_id
    ORDER BY links.linked_at DESC, links.id DESC
    LIMIT 1
) AS selected_link ON TRUE
WHERE releases.domain = %s
  AND releases.channel = %s
  AND releases.status = 'active'
  AND documents.id = %s
  AND (selections.source_batch_id IS NULL OR batches.id IS NOT NULL)
LIMIT 1
"""


def resolve_active_download(
    asset_db: AssetCoreDB,
    *,
    upload_root: Path,
    domain: str,
    channel: str,
    document_id: str,
) -> ActiveDownload:
    """Resolve the original file selected by the current active release."""
    row = asset_db._fetchone(  # lifecycle query intentionally stays local
        _ACTIVE_DOWNLOAD_SQL, (domain, channel, document_id)
    )
    if not row or not row.get("source_uri"):
        raise LifecycleResourceNotFound
    try:
        path = resolve_managed_file(upload_root, row["source_uri"])
    except UnsafeDownloadPath as exc:
        raise LifecycleResourceNotFound from exc
    return ActiveDownload(
        path=path,
        filename=safe_download_name(
            row.get("document_name") or row.get("title") or path.name
        ),
        media_type=row.get("mime_type") or "application/octet-stream",
    )


_ACTIVE_BATCHES_SQL = """
SELECT selections.source_batch_id,
       batches.batch_code,
       latest_run.mining_run_id,
       COUNT(DISTINCT selections.document_id) AS active_document_count,
       batches.created_at,
       selections.source_batch_id IS NOT NULL AS deletable,
       selections.source_batch_id IS NULL AS unclassified
FROM asset_publish_releases AS releases
JOIN asset_builds AS builds
  ON builds.id = releases.build_id
 AND builds.domain = releases.domain
JOIN asset_build_document_snapshots AS selections
  ON selections.build_id = builds.id
 AND selections.selection_status = 'active'
JOIN asset_documents AS documents
  ON documents.id = selections.document_id
 AND documents.domain = releases.domain
JOIN asset_document_snapshots AS snapshots
  ON snapshots.id = selections.document_snapshot_id
 AND snapshots.domain = releases.domain
LEFT JOIN asset_source_batches AS batches
  ON batches.id = selections.source_batch_id
 AND batches.domain = releases.domain
LEFT JOIN LATERAL (
    SELECT runs.id AS mining_run_id
    FROM mining_runs AS runs
    WHERE runs.source_batch_id = selections.source_batch_id
      AND runs.domain = releases.domain
    ORDER BY runs.started_at DESC, runs.id DESC
    LIMIT 1
) AS latest_run ON TRUE
WHERE releases.domain = %s
  AND releases.channel = %s
  AND releases.status = 'active'
GROUP BY selections.source_batch_id,
         batches.batch_code,
         latest_run.mining_run_id,
         batches.created_at
ORDER BY batches.created_at DESC NULLS LAST,
         selections.source_batch_id NULLS LAST
LIMIT %s OFFSET %s
"""


def list_active_batches(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    channel: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return asset_db._fetchall(
        _ACTIVE_BATCHES_SQL, (domain, channel, limit, offset)
    )


def remove_document(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    channel: str,
    document_id: str,
    actor: str,
) -> WithdrawalResult:
    try:
        return _withdraw_document(
            asset_db,
            domain=domain,
            channel=channel,
            document_id=document_id,
            actor=actor,
        )
    except ActiveResourceNotFound as exc:
        raise LifecycleResourceNotFound from exc


def remove_batch(
    asset_db: AssetCoreDB,
    *,
    domain: str,
    channel: str,
    source_batch_id: str,
    actor: str,
) -> WithdrawalResult:
    try:
        return _withdraw_source_batch(
            asset_db,
            domain=domain,
            channel=channel,
            source_batch_id=source_batch_id,
            actor=actor,
        )
    except ActiveResourceNotFound as exc:
        raise LifecycleResourceNotFound from exc


class DocumentLifecycleService:
    """Bind one domain database, release channel, and managed upload root."""

    def __init__(
        self,
        asset_db: AssetCoreDB,
        *,
        upload_root: Path,
        channel: str,
        actor: str = "mining-api",
    ) -> None:
        self.asset_db = asset_db
        self.upload_root = Path(upload_root)
        self.channel = channel
        self.actor = actor

    def resolve_active_download(
        self, *, domain: str, document_id: str
    ) -> ActiveDownload:
        return resolve_active_download(
            self.asset_db,
            upload_root=self.upload_root,
            domain=domain,
            channel=self.channel,
            document_id=document_id,
        )

    def list_active_batches(
        self, *, domain: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        return list_active_batches(
            self.asset_db,
            domain=domain,
            channel=self.channel,
            limit=limit,
            offset=offset,
        )

    def remove_document(
        self, *, domain: str, document_id: str
    ) -> WithdrawalResult:
        return remove_document(
            self.asset_db,
            domain=domain,
            channel=self.channel,
            document_id=document_id,
            actor=self.actor,
        )

    def remove_batch(
        self, *, domain: str, source_batch_id: str
    ) -> WithdrawalResult:
        return remove_batch(
            self.asset_db,
            domain=domain,
            channel=self.channel,
            source_batch_id=source_batch_id,
            actor=self.actor,
        )
