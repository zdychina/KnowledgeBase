"""IP whitelist middleware — blocks requests from non-whitelisted IPs."""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path

import yaml
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Always-allowed paths (health checks, whitelist management itself)
_SKIP_PATHS: frozenset[str] = frozenset({
    "/health",
    "/api/v1/admin/reload-ip-whitelist",
})


class IpWhitelistConfig:
    """Thread-safe, reloadable IP whitelist state."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self._networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

    def load(self, config_path: Path) -> None:
        if not config_path.exists():
            logger.info("IP whitelist config not found at %s — whitelist disabled", config_path)
            self.enabled = False
            self._networks = []
            return

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.enabled = bool(data.get("enabled", False))
        raw_ips: list[str] = data.get("allowed_ips") or []

        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for entry in raw_ips:
            entry = entry.strip()
            if not entry:
                continue
            try:
                # Try parsing as CIDR network first
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                logger.warning("Invalid IP/network in whitelist: %s", entry)

        self._networks = networks
        logger.info(
            "IP whitelist %s — %d entries loaded",
            "ENABLED" if self.enabled else "DISABLED",
            len(self._networks),
        )

    def is_allowed(self, client_ip: str) -> bool:
        if not self.enabled:
            return True
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        return any(addr in net for net in self._networks)


class IpWhitelistMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces IP whitelist on every request."""

    def __init__(self, app, *, config_path: Path) -> None:
        super().__init__(app)
        self._config_path = config_path
        self._state = IpWhitelistConfig()
        self._state.load(config_path)

    def reload(self) -> dict[str, object]:
        """Reload whitelist from disk. Called via admin API."""
        self._state.load(self._config_path)
        return {
            "enabled": self._state.enabled,
            "allowed_ips": [str(n) for n in self._state._networks],
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip whitelist check for management endpoints
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Determine client IP — respect X-Forwarded-For from trusted proxy
        client_ip = self._resolve_client_ip(request)

        if not self._state.is_allowed(client_ip):
            logger.warning("IP whitelist blocked request from %s — %s %s", client_ip, request.method, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied — IP not whitelisted", "client_ip": client_ip},
            )

        return await call_next(request)

    @staticmethod
    def _resolve_client_ip(request: Request) -> str:
        """Extract the real client IP, respecting one level of proxy."""
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Leftmost IP is the original client
            return xff.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"
