# DEPRECATED — domain_packs/

This directory is **deprecated** and will not be actively maintained.

Domain configuration has been migrated to the unified `scenario_packs/` directory:

- **Registry**: `domain_registry.yaml` (repo root) — single source of truth
- **Domain YAML**: `scenario_packs/<domain>/domain.yaml` — partitioned structure (ontology/mining/serving)
- **Loader**: `knowledge_mining/mining/infra/domain_pack.py` reads from `scenario_packs/` via registry

## Migration

Old path:
```
knowledge_mining/domain_packs/cloud_core_network/domain.yaml
```

New path:
```
scenario_packs/cloud_core_network/domain.yaml
```

The loader falls back to this directory if `scenario_packs/` doesn't have the domain, but this fallback will be removed in a future release.

## When to remove

Delete this directory once all consumers have migrated to the new path and no fallback is needed.
