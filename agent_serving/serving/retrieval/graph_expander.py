"""GraphExpander — SQL BFS over asset_raw_segment_relations.

Expands seed segments from source_refs_json via relation traversal.
Returns expanded segments with distance and relation type metadata.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from agent_serving.serving.schemas.json_utils import (
    parse_source_refs,
    parse_target_ref,
)

logger = logging.getLogger(__name__)


class GraphExpander:
    """BFS graph expander for raw segment relations."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def expand(
        self,
        seed_segment_ids: list[str],
        max_depth: int = 2,
        relation_types: list[str] | None = None,
        max_results: int = 20,
        snapshot_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Expand from seed segments via BFS over relations.

        Args:
            seed_segment_ids: starting segments from source_refs_json.
            max_depth: max BFS depth.
            relation_types: filter to these relation types (None = all).
            max_results: cap on total expanded segments.

        Returns:
            List of dicts with segment data + distance + relation_type.
        """
        if not seed_segment_ids:
            return []

        visited: set[str] = set(seed_segment_ids)
        current_frontier = list(seed_segment_ids)
        all_expanded: list[dict[str, Any]] = []

        for depth in range(1, max_depth + 1):
            if not current_frontier:
                break

            # Get neighbors of current frontier
            neighbors = await self._get_neighbors(
                current_frontier, relation_types, snapshot_ids,
            )

            next_frontier: list[str] = []
            for neighbor in neighbors:
                nid = str(neighbor["neighbor_id"])
                if nid in visited:
                    continue
                visited.add(nid)
                next_frontier.append(nid)

                all_expanded.append({
                    "segment_id": nid,
                    "depth": depth,
                    "relation_type": neighbor["relation_type"],
                    "from_segment_id": str(neighbor["from_id"]),
                })

                if len(all_expanded) >= max_results:
                    return all_expanded

            current_frontier = next_frontier

        return all_expanded

    async def fetch_expanded_segments(
        self,
        expansions: list[dict[str, Any]],
        snapshot_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch full segment data for expanded segment IDs."""
        if not expansions:
            return []

        segment_ids = [e["segment_id"] for e in expansions]
        expansion_map = {e["segment_id"]: e for e in expansions}

        placeholders = ",".join("%s" for _ in segment_ids)
        params: list[str] = list(segment_ids)

        snapshot_filter = ""
        if snapshot_ids:
            snap_ph = ",".join("%s" for _ in snapshot_ids)
            snapshot_filter = f" AND rs.document_snapshot_id IN ({snap_ph})"
            params.extend(snapshot_ids)

        sql = f"""
            SELECT
                rs.id,
                rs.document_snapshot_id,
                rs.raw_text,
                rs.block_type,
                rs.semantic_role,
                rs.section_path,
                rs.entity_refs_json,
                rs.source_offsets_json,
                ds.title AS doc_title,
                d.document_key,
                dsl.relative_path
            FROM asset_raw_segments rs
            LEFT JOIN asset_document_snapshots ds ON rs.document_snapshot_id = ds.id
            LEFT JOIN asset_document_snapshot_links dsl ON ds.id = dsl.document_snapshot_id
            LEFT JOIN asset_documents d ON dsl.document_id = d.id
            WHERE rs.id IN ({placeholders})
            {snapshot_filter}
        """
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            r = dict(row)
            exp = expansion_map.get(str(r["id"]), {})
            r["expansion_depth"] = exp.get("depth", 0)
            r["expansion_relation_type"] = exp.get("relation_type", "")
            r["from_segment_id"] = exp.get("from_segment_id", "")
            results.append(r)

        return results

    async def _get_neighbors(
        self,
        segment_ids: list[str],
        relation_types: list[str] | None = None,
        snapshot_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get neighboring segments via relations table."""
        if not segment_ids:
            return []

        placeholders = ",".join("%s" for _ in segment_ids)
        type_filter = ""

        if relation_types:
            type_placeholders = ",".join("%s" for _ in relation_types)
            type_filter = f" AND rel.relation_type IN ({type_placeholders})"

        # When snapshot_ids provided, join raw_segments to filter by snapshot
        snapshot_join = ""
        snapshot_filter = ""
        if snapshot_ids:
            snap_ph = ",".join("%s" for _ in snapshot_ids)
            snapshot_join = (
                " JOIN asset_raw_segments rs_src ON rel.source_segment_id = rs_src.id"
                " JOIN asset_raw_segments rs_tgt ON rel.target_segment_id = rs_tgt.id"
            )
            snapshot_filter = (
                f" AND rs_src.document_snapshot_id IN ({snap_ph})"
                f" AND rs_tgt.document_snapshot_id IN ({snap_ph})"
            )

        # Build params for UNION ALL: first SELECT + second SELECT
        p1: list[str] = list(segment_ids)
        if relation_types:
            p1.extend(relation_types)
        if snapshot_ids:
            p1.extend(snapshot_ids)
            p1.extend(snapshot_ids)

        p2: list[str] = list(segment_ids)
        if relation_types:
            p2.extend(relation_types)
        if snapshot_ids:
            p2.extend(snapshot_ids)
            p2.extend(snapshot_ids)

        params = p1 + p2

        sql = f"""
            SELECT
                rel.source_segment_id AS from_id,
                rel.target_segment_id AS neighbor_id,
                rel.relation_type
            FROM asset_raw_segment_relations rel
            {snapshot_join}
            WHERE rel.source_segment_id IN ({placeholders})
            {type_filter}
            {snapshot_filter}
            UNION ALL
            SELECT
                rel.target_segment_id AS from_id,
                rel.source_segment_id AS neighbor_id,
                rel.relation_type
            FROM asset_raw_segment_relations rel
            {snapshot_join}
            WHERE rel.target_segment_id IN ({placeholders})
            {type_filter}
            {snapshot_filter}
        """
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params)
            return [dict(row) for row in await cursor.fetchall()]
