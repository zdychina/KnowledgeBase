"""HTTP adapter for original-file downloads and soft withdrawals."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from knowledge_mining.mining.api.deps import get_document_lifecycle_service
from knowledge_mining.mining.api.domain_scope import require_domain
from knowledge_mining.mining.document_lifecycle import (
    DocumentLifecycleService,
    LifecycleResourceNotFound,
    UnsafeDownloadPath,
    content_disposition,
)


router = APIRouter(prefix="/api/knowledge", tags=["knowledge-lifecycle"])
_NOT_FOUND = "Knowledge asset not found"


def _uniform_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=_NOT_FOUND)


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    domain: str = Query(...),
    service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
):
    domain = require_domain(domain)
    try:
        download = await asyncio.to_thread(
            service.resolve_active_download,
            domain=domain,
            document_id=document_id,
        )
        return FileResponse(
            path=download.path,
            media_type=download.media_type,
            headers={"Content-Disposition": content_disposition(download.filename)},
        )
    except (LifecycleResourceNotFound, UnsafeDownloadPath, FileNotFoundError, OSError):
        raise _uniform_not_found() from None


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    domain: str = Query(...),
    service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
) -> dict:
    domain = require_domain(domain)
    try:
        result = await asyncio.to_thread(
            service.remove_document,
            domain=domain,
            document_id=document_id,
        )
    except LifecycleResourceNotFound:
        raise _uniform_not_found() from None
    return {
        "document_id": document_id,
        "domain": result.domain,
        "removed_count": result.removed_count,
        "build_id": result.build_id,
        "release_id": result.release_id,
    }


@router.delete("/batches/{source_batch_id}")
async def delete_batch(
    source_batch_id: str,
    domain: str = Query(...),
    service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
) -> dict:
    domain = require_domain(domain)
    try:
        result = await asyncio.to_thread(
            service.remove_batch,
            domain=domain,
            source_batch_id=source_batch_id,
        )
    except LifecycleResourceNotFound:
        raise _uniform_not_found() from None
    return {
        "source_batch_id": source_batch_id,
        "domain": result.domain,
        "removed_count": result.removed_count,
        "build_id": result.build_id,
        "release_id": result.release_id,
    }
