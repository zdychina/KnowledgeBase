"""Dual-database adapter for v1.1 Mining pipeline.

Provides two independent adapters:
- AssetCoreDB — reads/writes asset_core.sqlite (documents, snapshots, segments, retrieval units, builds, releases)
- MiningRuntimeDB — reads/writes mining_runtime.sqlite (runs, run_documents, stage_events)

Both adapters read DDL from the canonical SQL schema files under databases/
and expose typed CRUD operations for each table.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    MiningRunData,
    MiningRunDocumentData,
    StageEvent,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]  # knowledge_mining/mining/ -> CoreMasterKB/
_ASSET_CORE_DDL = _REPO_ROOT / "databases" / "asset_core" / "schemas" / "001_asset_core.sqlite.sql"
_MINING_RUNTIME_DDL = _REPO_ROOT / "databases" / "mining_runtime" / "schemas" / "001_mining_runtime.sqlite.sql"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _json_dumps(obj: Any) -> str:
    if obj is None:
        return "{}"
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str) -> Any:
    if not raw:
        return {}
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Base helper
# ---------------------------------------------------------------------------

class _DB:
    """Thin SQLite connection wrapper that auto-initializes from a DDL file."""

    def __init__(self, db_path: str | Path, ddl_path: Path) -> None:
        self.db_path = Path(db_path)
        self._ddl_path = ddl_path
        self._conn: sqlite3.Connection | None = None

    # -- connection lifecycle --

    def open(self) -> None:
        if self._conn is not None:
            return
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        ddl = self._ddl_path.read_text(encoding="utf-8")
        self._conn.executescript(ddl)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DB not opened — call .open() first")
        return self._conn

    # -- helpers --

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def _fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._execute(sql, params).fetchall()

    def commit(self) -> None:
        self.conn.commit()


# ===================================================================
# AssetCoreDB
# ===================================================================

class AssetCoreDB(_DB):
    """Adapter for asset_core.sqlite — Mining writes content assets here."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path, _ASSET_CORE_DDL)

    # -- source batches --

    def upsert_source_batch(
        self,
        batch_id: str,
        batch_code: str,
        source_type: str,
        description: str | None = None,
        created_by: str | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        now = _utcnow()
        self._execute(
            """INSERT INTO asset_source_batches (id, batch_code, source_type, description, created_by, created_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET batch_code=excluded.batch_code, source_type=excluded.source_type""",
            (batch_id, batch_code, source_type, description, created_by, now, _json_dumps(metadata_json)),
        )
        return batch_id

    def get_source_batch(self, batch_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_source_batches WHERE id = ?", (batch_id,))

    def find_batch_by_code(self, batch_code: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_source_batches WHERE batch_code = ?", (batch_code,))

    # -- documents --

    def upsert_document(
        self,
        document_id: str,
        document_key: str,
        document_name: str | None = None,
        document_type: str | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        now = _utcnow()
        self._execute(
            """INSERT INTO asset_documents (id, document_key, document_name, document_type, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(document_key) DO UPDATE SET
                   document_name = COALESCE(excluded.document_name, asset_documents.document_name),
                   document_type = COALESCE(excluded.document_type, asset_documents.document_type),
                   metadata_json = excluded.metadata_json""",
            (document_id, document_key, document_name, document_type, _json_dumps(metadata_json), now),
        )
        # ON CONFLICT may keep the OLD id — read back the actual row id
        row = self._fetchone("SELECT id FROM asset_documents WHERE document_key = ?", (document_key,))
        return row["id"] if row else document_id

    def get_document_by_key(self, document_key: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_documents WHERE document_key = ?", (document_key,))

    def get_document(self, document_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_documents WHERE id = ?", (document_id,))

    # -- snapshots --

    def upsert_snapshot(
        self,
        snapshot_id: str,
        normalized_content_hash: str,
        raw_content_hash: str,
        mime_type: str,
        title: str | None = None,
        scope_json: dict | None = None,
        tags_json: list | None = None,
        parser_profile_json: dict | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        now = _utcnow()
        self._execute(
            """INSERT INTO asset_document_snapshots
                   (id, normalized_content_hash, raw_content_hash, mime_type, title,
                    scope_json, tags_json, parser_profile_json, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(normalized_content_hash) DO UPDATE SET
                   raw_content_hash = excluded.raw_content_hash,
                   title = COALESCE(excluded.title, asset_document_snapshots.title)""",
            (
                snapshot_id, normalized_content_hash, raw_content_hash, mime_type, title,
                _json_dumps(scope_json), _json_dumps(tags_json),
                _json_dumps(parser_profile_json), _json_dumps(metadata_json), now,
            ),
        )
        # ON CONFLICT may keep the OLD id — read back the actual row id
        row = self._fetchone(
            "SELECT id FROM asset_document_snapshots WHERE normalized_content_hash = ?",
            (normalized_content_hash,),
        )
        return row["id"] if row else snapshot_id

    def get_snapshot_by_hash(self, normalized_content_hash: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM asset_document_snapshots WHERE normalized_content_hash = ?",
            (normalized_content_hash,),
        )

    def get_snapshot(self, snapshot_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_document_snapshots WHERE id = ?", (snapshot_id,))

    # -- snapshot links --

    def insert_snapshot_link(
        self,
        link_id: str,
        document_id: str,
        document_snapshot_id: str,
        source_batch_id: str | None,
        relative_path: str,
        source_uri: str,
        title: str | None = None,
        scope_json: dict | None = None,
        tags_json: list | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        now = _utcnow()
        self._execute(
            """INSERT INTO asset_document_snapshot_links
                   (id, document_id, document_snapshot_id, source_batch_id, relative_path,
                    source_uri, title, scope_json, tags_json, linked_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                link_id, document_id, document_snapshot_id, source_batch_id, relative_path,
                source_uri, title, _json_dumps(scope_json), _json_dumps(tags_json), now,
                _json_dumps(metadata_json),
            ),
        )
        return link_id

    def get_active_link(self, document_id: str) -> sqlite3.Row | None:
        """Get the most recent snapshot link for a document."""
        return self._fetchone(
            "SELECT * FROM asset_document_snapshot_links WHERE document_id = ? ORDER BY linked_at DESC LIMIT 1",
            (document_id,),
        )

    def get_links_by_snapshot(self, snapshot_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM asset_document_snapshot_links WHERE document_snapshot_id = ?",
            (snapshot_id,),
        )

    # -- raw segments --

    def insert_raw_segment(
        self,
        segment_id: str,
        document_snapshot_id: str,
        segment_key: str,
        segment_index: int,
        block_type: str = "unknown",
        semantic_role: str = "unknown",
        section_path: str | list | None = None,
        section_title: str | None = None,
        raw_text: str = "",
        normalized_text: str = "",
        content_hash: str = "",
        normalized_hash: str = "",
        token_count: int | None = None,
        structure_json: dict | None = None,
        source_offsets_json: dict | None = None,
        entity_refs_json: list | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        sp = section_path if isinstance(section_path, str) else _json_dumps(section_path)
        self._execute(
            """INSERT INTO asset_raw_segments
                   (id, document_snapshot_id, segment_key, segment_index, block_type, semantic_role,
                    section_path, section_title, raw_text, normalized_text, content_hash, normalized_hash,
                    token_count, structure_json, source_offsets_json, entity_refs_json, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                segment_id, document_snapshot_id, segment_key, segment_index, block_type, semantic_role,
                sp, section_title, raw_text, normalized_text, content_hash, normalized_hash,
                token_count, _json_dumps(structure_json), _json_dumps(source_offsets_json),
                _json_dumps(entity_refs_json), _json_dumps(metadata_json),
            ),
        )
        return segment_id

    def delete_segments_by_snapshot(self, document_snapshot_id: str) -> int:
        cur = self._execute(
            "DELETE FROM asset_raw_segments WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        )
        return cur.rowcount

    def get_segments_by_snapshot(self, document_snapshot_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM asset_raw_segments WHERE document_snapshot_id = ? ORDER BY segment_index",
            (document_snapshot_id,),
        )

    def count_segments_by_snapshot(self, document_snapshot_id: str) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) as cnt FROM asset_raw_segments WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        )
        return row["cnt"] if row else 0

    # -- segment relations --

    def insert_segment_relation(
        self,
        relation_id: str,
        document_snapshot_id: str,
        source_segment_id: str,
        target_segment_id: str,
        relation_type: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        distance: int | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        self._execute(
            """INSERT INTO asset_raw_segment_relations
                   (id, document_snapshot_id, source_segment_id, target_segment_id,
                    relation_type, weight, confidence, distance, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                relation_id, document_snapshot_id, source_segment_id, target_segment_id,
                relation_type, weight, confidence, distance, _json_dumps(metadata_json),
            ),
        )
        return relation_id

    def delete_relations_by_snapshot(self, document_snapshot_id: str) -> int:
        cur = self._execute(
            "DELETE FROM asset_raw_segment_relations WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        )
        return cur.rowcount

    def get_relations_by_snapshot(self, document_snapshot_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM asset_raw_segment_relations WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        )

    # -- retrieval units --

    def insert_retrieval_unit(
        self,
        unit_id: str,
        document_snapshot_id: str,
        unit_key: str,
        unit_type: str,
        target_type: str,
        target_ref_json: dict | None = None,
        title: str | None = None,
        text: str = "",
        search_text: str = "",
        block_type: str = "unknown",
        semantic_role: str = "unknown",
        facets_json: dict | None = None,
        entity_refs_json: list | None = None,
        source_refs_json: dict | None = None,
        llm_result_refs_json: dict | None = None,
        source_segment_id: str | None = None,
        weight: float = 1.0,
        metadata_json: dict | None = None,
    ) -> str:
        now = _utcnow()
        self._execute(
            """INSERT INTO asset_retrieval_units
                   (id, document_snapshot_id, unit_key, unit_type, target_type, target_ref_json,
                    title, text, search_text, block_type, semantic_role,
                    facets_json, entity_refs_json, source_refs_json, llm_result_refs_json,
                    source_segment_id, weight, created_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                unit_id, document_snapshot_id, unit_key, unit_type, target_type,
                _json_dumps(target_ref_json), title, text, search_text, block_type, semantic_role,
                _json_dumps(facets_json), _json_dumps(entity_refs_json),
                _json_dumps(source_refs_json), _json_dumps(llm_result_refs_json),
                source_segment_id, weight, now, _json_dumps(metadata_json),
            ),
        )
        return unit_id

    def delete_retrieval_units_by_snapshot(self, document_snapshot_id: str) -> int:
        cur = self._execute(
            "DELETE FROM asset_retrieval_units WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        )
        return cur.rowcount

    def get_retrieval_units_by_snapshot(self, document_snapshot_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM asset_retrieval_units WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        )

    # -- builds --

    def insert_build(
        self,
        build_id: str,
        build_code: str,
        status: str = "building",
        build_mode: str = "full",
        source_batch_id: str | None = None,
        parent_build_id: str | None = None,
        mining_run_id: str | None = None,
        summary_json: dict | None = None,
        validation_json: dict | None = None,
    ) -> str:
        now = _utcnow()
        self._execute(
            """INSERT INTO asset_builds
                   (id, build_code, status, build_mode, source_batch_id, parent_build_id,
                    mining_run_id, summary_json, validation_json, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                build_id, build_code, status, build_mode, source_batch_id, parent_build_id,
                mining_run_id, _json_dumps(summary_json), _json_dumps(validation_json), now,
            ),
        )
        return build_id

    def update_build_status(
        self,
        build_id: str,
        status: str,
        finished_at: str | None = None,
        summary_json: dict | None = None,
        validation_json: dict | None = None,
    ) -> None:
        fa = finished_at or _utcnow()
        self._execute(
            """UPDATE asset_builds SET status = ?, finished_at = ?,
               summary_json = COALESCE(?, summary_json),
               validation_json = COALESCE(?, validation_json)
               WHERE id = ?""",
            (status, fa, _json_dumps(summary_json), _json_dumps(validation_json), build_id),
        )

    def get_build(self, build_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_builds WHERE id = ?", (build_id,))

    def get_active_build(self) -> sqlite3.Row | None:
        """Get the latest active/validated build (for incremental merge)."""
        return self._fetchone(
            "SELECT * FROM asset_builds WHERE status IN ('validated', 'published') ORDER BY created_at DESC LIMIT 1"
        )

    # -- build document snapshots --

    def upsert_build_document_snapshot(
        self,
        build_id: str,
        document_id: str,
        document_snapshot_id: str,
        selection_status: str = "active",
        reason: str = "add",
        metadata_json: dict | None = None,
    ) -> None:
        self._execute(
            """INSERT INTO asset_build_document_snapshots
                   (build_id, document_id, document_snapshot_id, selection_status, reason, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(build_id, document_id) DO UPDATE SET
                   document_snapshot_id = excluded.document_snapshot_id,
                   selection_status = excluded.selection_status,
                   reason = excluded.reason,
                   metadata_json = excluded.metadata_json""",
            (build_id, document_id, document_snapshot_id, selection_status, reason, _json_dumps(metadata_json)),
        )

    def get_build_snapshots(self, build_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM asset_build_document_snapshots WHERE build_id = ?",
            (build_id,),
        )

    # -- publish releases --

    def insert_release(
        self,
        release_id: str,
        release_code: str,
        build_id: str,
        channel: str = "default",
        status: str = "staging",
        previous_release_id: str | None = None,
        released_by: str | None = None,
        release_notes: str | None = None,
        metadata_json: dict | None = None,
    ) -> str:
        self._execute(
            """INSERT INTO asset_publish_releases
                   (id, release_code, build_id, channel, status, previous_release_id,
                    released_by, release_notes, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                release_id, release_code, build_id, channel, status, previous_release_id,
                released_by, release_notes, _json_dumps(metadata_json),
            ),
        )
        return release_id

    def activate_release(self, release_id: str) -> None:
        """Activate a release: retire any current active, then set this one active."""
        now = _utcnow()
        # retire current active for same channel
        release = self._fetchone("SELECT channel FROM asset_publish_releases WHERE id = ?", (release_id,))
        if release is None:
            raise ValueError(f"Release {release_id} not found")
        channel = release["channel"]
        self._execute(
            "UPDATE asset_publish_releases SET status = 'retired', deactivated_at = ? WHERE channel = ? AND status = 'active'",
            (now, channel),
        )
        self._execute(
            "UPDATE asset_publish_releases SET status = 'active', activated_at = ? WHERE id = ?",
            (now, release_id),
        )

    def get_active_release(self, channel: str = "default") -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM asset_publish_releases WHERE channel = ? AND status = 'active'",
            (channel,),
        )

    def get_release(self, release_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM asset_publish_releases WHERE id = ?", (release_id,))


# ===================================================================
# MiningRuntimeDB
# ===================================================================

class MiningRuntimeDB(_DB):
    """Adapter for mining_runtime.sqlite — Mining process-state truth source."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path, _MINING_RUNTIME_DDL)

    # -- mining runs --

    def insert_run(self, data: MiningRunData) -> str:
        self._execute(
            """INSERT INTO mining_runs
                   (id, source_batch_id, input_path, status, build_id,
                    total_documents, new_count, updated_count, skipped_count,
                    failed_count, committed_count, started_at, finished_at,
                    error_summary, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.id, data.source_batch_id, data.input_path, data.status, data.build_id,
                data.total_documents, data.new_count, data.updated_count, data.skipped_count,
                data.failed_count, data.committed_count, data.started_at or _utcnow(),
                data.finished_at, data.error_summary, _json_dumps(data.metadata_json),
            ),
        )
        return data.id

    def update_run_status(
        self,
        run_id: str,
        status: str,
        finished_at: str | None = None,
        error_summary: str | None = None,
        build_id: str | None = None,
        **counters: int,
    ) -> None:
        parts = ["status = ?"]
        params: list[Any] = [status]
        if finished_at is not None:
            parts.append("finished_at = ?")
            params.append(finished_at)
        if error_summary is not None:
            parts.append("error_summary = ?")
            params.append(error_summary)
        if build_id is not None:
            parts.append("build_id = ?")
            params.append(build_id)
        for col in ("total_documents", "new_count", "updated_count", "skipped_count", "failed_count", "committed_count"):
            if col in counters:
                parts.append(f"{col} = ?")
                params.append(counters[col])
        params.append(run_id)
        self._execute(f"UPDATE mining_runs SET {', '.join(parts)} WHERE id = ?", tuple(params))

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self._fetchone("SELECT * FROM mining_runs WHERE id = ?", (run_id,))

    def get_interrupted_runs(self) -> list[sqlite3.Row]:
        return self._fetchall("SELECT * FROM mining_runs WHERE status = 'interrupted' ORDER BY started_at")

    # -- run documents --

    def insert_run_document(self, data: MiningRunDocumentData) -> str:
        self._execute(
            """INSERT INTO mining_run_documents
                   (id, run_id, document_key, raw_content_hash, normalized_content_hash,
                    action, status, document_id, document_snapshot_id, error_message,
                    started_at, finished_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.id, data.run_id, data.document_key, data.raw_content_hash,
                data.normalized_content_hash, data.action, data.status,
                data.document_id, data.document_snapshot_id, data.error_message,
                data.started_at, data.finished_at, _json_dumps(data.metadata_json),
            ),
        )
        return data.id

    def update_run_document(
        self,
        rd_id: str,
        status: str | None = None,
        document_id: str | None = None,
        document_snapshot_id: str | None = None,
        error_message: str | None = None,
        finished_at: str | None = None,
        metadata_json: dict | None = None,
    ) -> None:
        parts: list[str] = []
        params: list[Any] = []
        if status is not None:
            parts.append("status = ?")
            params.append(status)
        if document_id is not None:
            parts.append("document_id = ?")
            params.append(document_id)
        if document_snapshot_id is not None:
            parts.append("document_snapshot_id = ?")
            params.append(document_snapshot_id)
        if error_message is not None:
            parts.append("error_message = ?")
            params.append(error_message)
        if finished_at is not None:
            parts.append("finished_at = ?")
            params.append(finished_at)
        if metadata_json is not None:
            parts.append("metadata_json = ?")
            params.append(_json_dumps(metadata_json))
        if not parts:
            return
        params.append(rd_id)
        self._execute(f"UPDATE mining_run_documents SET {', '.join(parts)} WHERE id = ?", tuple(params))

    def get_run_documents(self, run_id: str) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM mining_run_documents WHERE run_id = ? ORDER BY id",
            (run_id,),
        )

    def get_run_document_by_key(self, run_id: str, document_key: str) -> sqlite3.Row | None:
        return self._fetchone(
            "SELECT * FROM mining_run_documents WHERE run_id = ? AND document_key = ?",
            (run_id, document_key),
        )

    # -- stage events --

    def insert_stage_event(self, data: StageEvent) -> str:
        self._execute(
            """INSERT INTO mining_run_stage_events
                   (id, run_id, run_document_id, stage, status, duration_ms,
                    output_summary, error_message, created_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.id, data.run_id, data.run_document_id, data.stage, data.status,
                data.duration_ms, data.output_summary, data.error_message,
                data.created_at or _utcnow(), _json_dumps(data.metadata_json),
            ),
        )
        return data.id

    def get_stage_events(self, run_id: str, run_document_id: str | None = None) -> list[sqlite3.Row]:
        if run_document_id:
            return self._fetchall(
                "SELECT * FROM mining_run_stage_events WHERE run_id = ? AND run_document_id = ? ORDER BY created_at",
                (run_id, run_document_id),
            )
        return self._fetchall(
            "SELECT * FROM mining_run_stage_events WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        )

    def get_last_stage_status(self, run_id: str, run_document_id: str | None, stage: str) -> str | None:
        """Return the status of the most recent event for a stage, or None if never started."""
        row = self._fetchone(
            """SELECT status FROM mining_run_stage_events
               WHERE run_id = ? AND stage = ? AND (run_document_id = ? OR (? IS NULL AND run_document_id IS NULL))
               ORDER BY created_at DESC LIMIT 1""",
            (run_id, stage, run_document_id, run_document_id),
        )
        return row["status"] if row else None

    def get_committed_document_keys(self, run_id: str) -> frozenset[str]:
        """Return document_keys that are committed in this run (for resume skip list)."""
        rows = self._fetchall(
            "SELECT document_key FROM mining_run_documents WHERE run_id = ? AND status = 'committed'",
            (run_id,),
        )
        return frozenset(r["document_key"] for r in rows)

    def get_failed_document_keys(self, run_id: str) -> frozenset[str]:
        rows = self._fetchall(
            "SELECT document_key FROM mining_run_documents WHERE run_id = ? AND status IN ('failed', 'processing')",
            (run_id,),
        )
        return frozenset(r["document_key"] for r in rows)
