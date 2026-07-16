"""Shared validation helpers for domain-scoped Mining API resources."""

from fastapi import HTTPException


def require_domain(domain: str) -> str:
    """Return a normalized domain or reject a blank business scope."""
    normalized = domain.strip()
    if not normalized:
        raise HTTPException(422, "domain is required")
    return normalized


def ensure_same_domain(actual: str | None, requested: str, resource: str) -> None:
    """Hide a resource when it does not belong to the requested domain."""
    if actual != requested:
        raise HTTPException(404, f"{resource} not found")
