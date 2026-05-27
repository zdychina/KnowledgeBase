from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException


@dataclass(slots=True)
class YamlConfigService:
    """Pure YAML reader — config_dir is the single source of truth."""

    config_dir: Path

    # ------------------------------------------------------------------
    # Generic YAML reader
    # ------------------------------------------------------------------

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # ------------------------------------------------------------------
    # Domain registry
    # ------------------------------------------------------------------

    def _load_domain_registry(self) -> dict[str, Any]:
        payload = self._load_yaml(self.config_dir / "domain_registry.yaml")
        return payload.get("domains", {})

    def list_domains(self) -> list[dict[str, Any]]:
        registry = self._load_domain_registry()
        results: list[dict[str, Any]] = []
        for domain_id, entry in registry.items():
            pack = self._load_scenario_pack(domain_id)
            results.append({
                "domain_id": domain_id,
                "display_name": pack.get("display_name", domain_id.replace("_", " ").title()),
                "enabled": bool(entry.get("enabled", True)),
                "default_channel": entry.get("default_channel", "prod"),
                "scenario_pack_ref": entry.get("scenario_pack", domain_id),
                "description": "",
                "owner_team": "platform",
                "metadata_json": {
                    "source": "yaml_readonly",
                    "database_url_env": entry.get("database_url_env"),
                },
            })
        return results

    def get_domain(self, domain_id: str) -> dict[str, Any]:
        registry = self._load_domain_registry()
        entry = registry.get(domain_id)
        if not entry:
            raise HTTPException(status_code=404, detail="domain_not_found")
        pack = self._load_scenario_pack(domain_id)
        return {
            "domain_id": domain_id,
            "display_name": pack.get("display_name", domain_id.replace("_", " ").title()),
            "enabled": bool(entry.get("enabled", True)),
            "default_channel": entry.get("default_channel", "prod"),
            "scenario_pack_ref": entry.get("scenario_pack", domain_id),
            "description": "",
            "owner_team": "platform",
            "metadata_json": {
                "source": "yaml_readonly",
                "database_url_env": entry.get("database_url_env"),
            },
        }

    # ------------------------------------------------------------------
    # Scenario packs
    # ------------------------------------------------------------------

    def _load_scenario_pack(self, domain_id: str) -> dict[str, Any]:
        registry = self._load_domain_registry()
        pack_ref = registry.get(domain_id, {}).get("scenario_pack", domain_id)
        return self._load_yaml(self.config_dir / "scenario_packs" / pack_ref / "domain.yaml")

    def get_scenario(self, domain_id: str, section: str | None = None) -> dict[str, Any]:
        self.get_domain(domain_id)  # 404 if not found
        if section:
            return self._load_scenario_pack(domain_id).get(section, {})
        return self._load_scenario_pack(domain_id)

    # ------------------------------------------------------------------
    # System config
    # ------------------------------------------------------------------

    def get_system_config(self, service_name: str) -> dict[str, Any]:
        path = self.config_dir / "system" / f"{service_name}.yaml"
        result = self._load_yaml(path)
        if not result:
            raise HTTPException(status_code=404, detail="config_not_found")
        return result
