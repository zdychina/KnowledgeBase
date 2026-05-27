"""NiceGUI UI for the knowledge_mining_zym pipeline.

启动方式：
    py -3.10 knowledge_mining_zym/mining_ui.py
然后浏览器打开 http://127.0.0.1:7860

功能：
    1. 上传若干文档（.md/.txt/.html/.pdf/.docx/.chm/.hdx）
       - .chm/.hdx 会在 ingest 阶段自动解压并转成 markdown
    2. 填写 batch 参数（产品、标签、文档类型）
    3. 点击"开始挖掘" → 后端线程跑 run()，前端轮询 PostgreSQL (kb_db) 实时显示阶段
    4. 完成后每个阶段都展示：KPI + 统计图表（ECharts）+ 全量数据表格（AG Grid）

LLM / Embedding 由后端 .env 配置，不通过前端表单暴露：
    LLM_SERVICE_URL                — 本地 llm_service 入口 (默认 http://localhost:8900)
    MINING_LLM_BYPASS_PROXY        — 是否对 LLM URL 跳过系统代理 (默认 true)
    MINING_LLM_ENABLED             — 总开关 (默认 true；置 false 全部走规则)
    EMBEDDING_API_KEY              — embedding API key；缺省则跳过 embedding 阶段
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_no_proxy = os.environ.get("NO_PROXY", "")
for _h in ("localhost", "127.0.0.1", "::1"):
    if _h not in _no_proxy:
        _no_proxy = (_no_proxy + "," + _h).strip(",")
os.environ["NO_PROXY"] = _no_proxy
os.environ["no_proxy"] = _no_proxy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# 日志策略：只在控制台展示 WARNING 及以上 —— 让 LLM 失败信息（submit/poll/fetch 失败、
# 超时、discourse 分析异常等都在 WARNING 级）清晰可见，屏蔽其它噪声。
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
# 第三方库即便在 WARNING 也会刷屏（重连、协议告警等），统一压到 ERROR。
for _noisy in ("httpx", "httpcore", "urllib3", "psycopg", "psycopg.pool", "nicegui"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)
logger = logging.getLogger("mining_ui")
logger.setLevel(logging.INFO)

# Tracks last logged status per stage (+ overall phase under key "__phase__")
# so we only log on transitions, not on every poll tick.
_LAST_LOGGED: dict[str, str] = {}


def _log_progress(stages: dict[str, dict], phase: str) -> None:
    """Log stage status transitions and overall phase changes — once each."""
    if _LAST_LOGGED.get("__phase__") != phase:
        logger.info("phase -> %s", phase)
        _LAST_LOGGED["__phase__"] = phase
    for sid in PIPELINE_STAGE_IDS:
        st = stages.get(sid, {}).get("status", "pending")
        if _LAST_LOGGED.get(sid) == st or st == "pending":
            continue
        dur = stages.get(sid, {}).get("duration_ms")
        tail = f" ({dur} ms)" if dur and st == "done" else ""
        logger.info("stage[%s] -> %s%s", sid, st, tail)
        _LAST_LOGGED[sid] = st


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_mining_llm_settings() -> tuple[str | None, bool, str | None]:
    """Read LLM / embedding settings from environment.

    Returns (llm_base_url, llm_bypass_proxy, embedding_api_key).
    llm_base_url is None when MINING_LLM_ENABLED=false, disabling the entire LLM path.
    """
    if not _env_bool("MINING_LLM_ENABLED", default=True):
        llm_url: str | None = None
    else:
        llm_url = (os.environ.get("LLM_SERVICE_URL") or "http://localhost:8900").strip() or None
    bypass = _env_bool("MINING_LLM_BYPASS_PROXY", default=True)
    emb_key = (os.environ.get("EMBEDDING_API_KEY") or "").strip() or None
    return llm_url, bypass, emb_key


import pandas as pd  # noqa: E402
from nicegui import app, ui  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402

from knowledge_mining_zym.mining.jobs.run import run as mining_run  # noqa: E402
from knowledge_mining_zym.mining.contracts.models import BatchParams  # noqa: E402
from knowledge_mining_zym.mining.infra.pg_config import MiningDbConfig  # noqa: E402

UPLOADS_ROOT = PROJECT_ROOT / "data" / "uploads"
DOMAIN_PACKS_ROOT = PROJECT_ROOT / "knowledge_mining_zym" / "domain_packs"

UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)


def _list_domain_packs() -> list[str]:
    """Discover domain pack ids by listing folders that contain domain.yaml."""
    if not DOMAIN_PACKS_ROOT.is_dir():
        return ["cloud_core_network"]
    ids = sorted(
        p.name for p in DOMAIN_PACKS_ROOT.iterdir()
        if p.is_dir() and (p / "domain.yaml").is_file()
    )
    return ids or ["cloud_core_network"]


# =====================================================================
# DB helpers (PostgreSQL via shared connection pool)
# =====================================================================

_pg_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pg_pool
    if _pg_pool is None:
        cfg = MiningDbConfig()
        _pg_pool = ConnectionPool(
            cfg.conninfo,
            min_size=1,
            max_size=4,
            open=True,
            check=ConnectionPool.check_connection,
            kwargs={"row_factory": dict_row},
        )
    return _pg_pool


class _PGConn:
    """Thin wrapper around a pooled psycopg connection.

    Mimics the sqlite3.Connection.execute(...).fetchall() API used throughout
    this UI, so render functions don't need to switch to cursor context managers.
    Call .close() to return the connection to the pool.
    """

    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._cm = pool.connection()
        self._conn = self._cm.__enter__()

    def execute(self, sql: str, params: tuple | list | None = None) -> "_PGCursor":
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return _PGCursor(cur)

    def close(self) -> None:
        try:
            self._cm.__exit__(None, None, None)
        except Exception:
            pass


class _PGCursor:
    """Wraps a psycopg cursor so .fetchone()/.fetchall() can be chained
    after .execute() — the calling pattern used throughout this UI."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        try:
            return self._cur.fetchone()
        finally:
            self._cur.close()

    def fetchall(self):
        try:
            return self._cur.fetchall()
        finally:
            self._cur.close()


def _open_asset() -> _PGConn:
    return _PGConn(_get_pool())


def _open_runtime() -> _PGConn:
    return _PGConn(_get_pool())


# =====================================================================
# Polling helpers (during run)
# =====================================================================

def _query_latest_run(input_path: str) -> dict | None:
    import psycopg.errors
    conn = _open_runtime()
    try:
        try:
            row = conn.execute(
                "SELECT * FROM mining_runs WHERE input_path = %s ORDER BY started_at DESC LIMIT 1",
                (input_path,),
            ).fetchone()
        except psycopg.errors.UndefinedTable:
            return None
        if not row:
            return None
        events = conn.execute(
            "SELECT stage, status, error_message, created_at FROM mining_run_stage_events "
            "WHERE run_id = %s ORDER BY created_at DESC LIMIT 1",
            (row["id"],),
        ).fetchall()
        latest_event = dict(events[0]) if events else None
        return {"run": dict(row), "latest_event": latest_event}
    finally:
        conn.close()


def _truncate(s: str | None, n: int = 200) -> str:
    if s is None:
        return ""
    s = str(s).replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def _empty_counts_df(key: str) -> pd.DataFrame:
    return pd.DataFrame({key: [], "count": []})


def _counts_df(rows: list, key: str, *, fallback_label: str = "") -> pd.DataFrame:
    if not rows:
        return _empty_counts_df(key)
    return pd.DataFrame(
        [{key: (r[key] if r[key] is not None else fallback_label), "count": r["c"]} for r in rows]
    )


def _bin_token(t: int | None) -> str:
    if t is None:
        return ""
    if t < 50:   return "<50"
    if t < 100:  return "50-99"
    if t < 200:  return "100-199"
    if t < 500:  return "200-499"
    if t < 1000: return "500-999"
    return "1000+"


_BIN_ORDER = ["<50", "50-99", "100-199", "200-499", "500-999", "1000+", ""]


def _bin_distance(d: int | None) -> str:
    if d is None:
        return ""
    if d == 0:    return "0"
    if d == 1:    return "1"
    if d <= 3:    return "2-3"
    if d <= 5:    return "4-5"
    if d <= 10:   return "6-10"
    return "11+"


_DIST_ORDER = ["0", "1", "2-3", "4-5", "6-10", "11+", ""]


def _bin_text_len(n: int) -> str:
    if n < 50:    return "<50"
    if n < 100:   return "50-99"
    if n < 200:   return "100-199"
    if n < 500:   return "200-499"
    if n < 1000:  return "500-999"
    if n < 2000:  return "1000-1999"
    return "2000+"


_TXTLEN_ORDER = ["<50", "50-99", "100-199", "200-499", "500-999", "1000-1999", "2000+"]


def _ordered_bin_df(counter: dict[str, int], order: list[str], key: str) -> pd.DataFrame:
    rows = [{key: b, "count": counter.get(b, 0)} for b in order if b in counter or counter.get(b, 0)]
    if not rows:
        return _empty_counts_df(key)
    return pd.DataFrame(rows)


# =====================================================================
# Per-stage data renderers
# Each renderer returns [summary_md_text, *small_dfs_for_plots, full_df_for_grid]
# These are framework-agnostic — same shape as Gradio version.
# =====================================================================

EMPTY_RUN_TEXT = "_（尚未运行）_"
RUNNING_TEXT = "_（运行中…完成后展示）_"


# Each panel id maps to the operator slots in mining_runs.metadata_json.operators
# that drive it. Order matters for display.
_STAGE_OPERATOR_KEYS: dict[str, list[str]] = {
    "segment": ["segmenter"],
    "enrich": ["enricher"],
    "relations": ["discourse_relation_builder"],
    "units": ["contextualizer", "embedding_generator"],
}

_OPERATOR_LABEL: dict[str, str] = {
    "segmenter": "Segmenter",
    "enricher": "Enricher",
    "discourse_relation_builder": "DiscourseRB",
    "contextualizer": "Contextualizer",
    "embedding_generator": "Embedding",
}


def _operator_kind(class_name: str | None) -> str:
    """Classify an operator class name as 'LLM' / '规则' / '—'."""
    if not class_name:
        return "—"
    lower = class_name.lower()
    if lower.startswith("llm") or lower.startswith("discourse"):
        return "LLM"
    return "规则"


def _extract_operators(run_row: dict | None) -> dict[str, Any] | None:
    """Pull operators map out of mining_runs.metadata_json. Tolerates str/dict shapes."""
    if not run_row:
        return None
    md = run_row.get("metadata_json")
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            return None
    if not isinstance(md, dict):
        return None
    ops = md.get("operators")
    return ops if isinstance(ops, dict) else None


def _operator_badge_md(stage_id: str, operators: dict[str, Any] | None) -> str:
    """Build a markdown badge line for a stage panel showing LLM vs rule.

    `operators` is `mining_runs.metadata_json["operators"]` (or None for older runs).
    Returns "" when the stage has no operators worth showing.
    """
    keys = _STAGE_OPERATOR_KEYS.get(stage_id)
    if not keys:
        return ""
    if not operators:
        return f"> ⚙️ 算子：_未记录（旧 run）_\n\n"
    parts: list[str] = []
    for k in keys:
        info = operators.get(k)
        cls = info.get("class") if isinstance(info, dict) else None
        kind = _operator_kind(cls)
        label = _OPERATOR_LABEL.get(k, k)
        if cls:
            parts.append(f"**{label}**: `{cls}` → {kind}")
        else:
            parts.append(f"**{label}**: _未配置_")
    return "> ⚙️ " + " · ".join(parts) + "\n\n"


def _snapshot_ids(rt: _PGConn, run_id: str) -> tuple[str, ...]:
    rows = rt.execute(
        "SELECT document_snapshot_id FROM mining_run_documents "
        "WHERE run_id = %s AND document_snapshot_id IS NOT NULL",
        (run_id,),
    ).fetchall()
    return tuple(r["document_snapshot_id"] for r in rows)


# ---------- Stage 1: Ingest ----------

def render_ingest(run_id: str) -> list[Any]:
    rt = _open_runtime()
    try:
        rows = rt.execute(
            "SELECT document_key, action, status, raw_content_hash, normalized_content_hash, error_message "
            "FROM mining_run_documents WHERE run_id = %s ORDER BY document_key",
            (run_id,),
        ).fetchall()
        action_rows = rt.execute(
            "SELECT action, COUNT(*) AS c FROM mining_run_documents WHERE run_id = %s GROUP BY action",
            (run_id,),
        ).fetchall()
        status_rows = rt.execute(
            "SELECT status, COUNT(*) AS c FROM mining_run_documents WHERE run_id = %s GROUP BY status",
            (run_id,),
        ).fetchall()
    finally:
        rt.close()

    if not rows:
        return [EMPTY_RUN_TEXT, _empty_counts_df("action"), _empty_counts_df("status"), pd.DataFrame()]

    action_dist = {r["action"] or "": r["c"] for r in action_rows}
    summary = (
        f"### 摄取统计\n\n"
        f"- 共发现 **{len(rows)}** 个文档\n"
        f"- 按 action：{', '.join(f'**{k}**={v}' for k, v in action_dist.items())}\n"
        f"- 失败数：{sum(1 for r in rows if r['status'] == 'failed')}"
    )
    table = pd.DataFrame(
        [
            {
                "document_key": r["document_key"],
                "action": r["action"],
                "status": r["status"],
                "raw_hash": (r["raw_content_hash"] or "")[:12],
                "normalized_hash": (r["normalized_content_hash"] or "")[:12],
                "error_message": _truncate(r["error_message"], 200),
            }
            for r in rows
        ]
    )
    return [summary, _counts_df(action_rows, "action"), _counts_df(status_rows, "status"), table]


# ---------- Stage 2: Parse ----------

def render_parse(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        rd_rows = rt.execute(
            "SELECT document_id, document_snapshot_id, document_key FROM mining_run_documents "
            "WHERE run_id = %s AND document_snapshot_id IS NOT NULL",
            (run_id,),
        ).fetchall()
        if not rd_rows:
            return [EMPTY_RUN_TEXT, _empty_counts_df("doc"), _empty_counts_df("depth"), pd.DataFrame()]

        doc_section_counts: list[dict] = []
        depth_counter: dict[str, int] = {}
        section_rows: list[dict] = []

        for rd in rd_rows:
            snap_id = rd["document_snapshot_id"]
            doc_key = rd["document_key"]
            doc_short = doc_key.rsplit("/", 1)[-1][:40]

            sec_rows = asset.execute(
                "SELECT section_path, section_title, COUNT(*) AS c "
                "FROM asset_raw_segments WHERE document_snapshot_id = %s "
                "GROUP BY section_path, section_title ORDER BY MIN(segment_index)",
                (snap_id,),
            ).fetchall()
            doc_section_counts.append({"doc": doc_short, "count": len(sec_rows)})
            for r in sec_rows:
                try:
                    path = json.loads(r["section_path"]) if r["section_path"] else []
                    depth = len(path)
                except Exception:
                    depth = 0
                depth_key = f"L{depth}"
                depth_counter[depth_key] = depth_counter.get(depth_key, 0) + 1
                section_rows.append(
                    {
                        "doc": doc_short,
                        "depth": depth,
                        "section_path": _truncate(" / ".join(map(str, path)) if path else "(根)", 120),
                        "section_title": _truncate(r["section_title"], 80),
                        "segment_count": r["c"],
                    }
                )

        total_sections = sum(d["count"] for d in doc_section_counts)
        max_depth = max((s["depth"] for s in section_rows), default=0)
        summary = (
            f"### 解析统计\n\n"
            f"- 文档数：**{len(rd_rows)}**\n"
            f"- 识别小节总数：**{total_sections}**\n"
            f"- 最大层级：**L{max_depth}**"
        )
        depth_keys = sorted(depth_counter.keys(), key=lambda k: int(k[1:]))
        depth_df = pd.DataFrame([{"depth": k, "count": depth_counter[k]} for k in depth_keys])
        return [
            summary,
            pd.DataFrame(doc_section_counts),
            depth_df,
            pd.DataFrame(section_rows),
        ]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 3: Segment ----------

def render_segment(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        snap_ids = _snapshot_ids(rt, run_id)
        if not snap_ids:
            return [
                EMPTY_RUN_TEXT,
                _empty_counts_df("block_type"),
                _empty_counts_df("token_bin"),
                pd.DataFrame(),
            ]
        ph = ",".join(["%s"] * len(snap_ids))

        bt = asset.execute(
            f"SELECT block_type, COUNT(*) AS c FROM asset_raw_segments "
            f"WHERE document_snapshot_id IN ({ph}) GROUP BY block_type ORDER BY c DESC",
            snap_ids,
        ).fetchall()
        all_segs = asset.execute(
            f"SELECT s.segment_index, s.block_type, s.semantic_role, s.section_title, "
            f"       s.token_count, s.raw_text, ds.title AS doc_title "
            f"FROM asset_raw_segments s "
            f"JOIN asset_document_snapshots ds ON s.document_snapshot_id = ds.id "
            f"WHERE s.document_snapshot_id IN ({ph}) "
            f"ORDER BY s.document_snapshot_id, s.segment_index",
            snap_ids,
        ).fetchall()

        token_counter: dict[str, int] = {}
        total_tokens = 0
        for r in all_segs:
            b = _bin_token(r["token_count"])
            token_counter[b] = token_counter.get(b, 0) + 1
            total_tokens += r["token_count"] or 0

        summary = (
            f"### 分块统计\n\n"
            f"- 段落总数：**{len(all_segs)}**\n"
            f"- token 总量：**{total_tokens:,}**\n"
            f"- 平均 token：**{(total_tokens / len(all_segs)):.1f}**" if all_segs else "（无）"
        )
        token_df = _ordered_bin_df(token_counter, _BIN_ORDER, "token_bin")
        full_df = pd.DataFrame(
            [
                {
                    "doc": _truncate(r["doc_title"], 30),
                    "#": r["segment_index"],
                    "block_type": r["block_type"],
                    "semantic_role": r["semantic_role"],
                    "section_title": _truncate(r["section_title"], 50),
                    "tokens": r["token_count"],
                    "raw_text": _truncate(r["raw_text"], 200),
                }
                for r in all_segs
            ]
        )
        return [summary, _counts_df(bt, "block_type"), token_df, full_df]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 4: Enrich ----------

def render_enrich(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        snap_ids = _snapshot_ids(rt, run_id)
        if not snap_ids:
            return [
                EMPTY_RUN_TEXT,
                _empty_counts_df("semantic_role"),
                _empty_counts_df("entity_type"),
                _empty_counts_df("count_per_seg"),
                pd.DataFrame(),
            ]
        ph = ",".join(["%s"] * len(snap_ids))

        roles = asset.execute(
            f"SELECT semantic_role, COUNT(*) AS c FROM asset_raw_segments "
            f"WHERE document_snapshot_id IN ({ph}) GROUP BY semantic_role ORDER BY c DESC",
            snap_ids,
        ).fetchall()
        total_segs = sum(r["c"] for r in roles)
        unknown_segs = next((r["c"] for r in roles if r["semantic_role"] == "unknown"), 0)
        classified_segs = total_segs - unknown_segs
        classify_rate = (classified_segs / total_segs * 100) if total_segs else 0.0

        seg_rows = asset.execute(
            f"SELECT s.segment_index, s.section_title, s.entity_refs_json, s.raw_text, "
            f"       ds.title AS doc_title "
            f"FROM asset_raw_segments s "
            f"JOIN asset_document_snapshots ds ON s.document_snapshot_id = ds.id "
            f"WHERE s.document_snapshot_id IN ({ph}) AND s.entity_refs_json != '[]' "
            f"ORDER BY s.segment_index",
            snap_ids,
        ).fetchall()

        type_counter: dict[str, int] = {}
        per_seg_counter: dict[str, int] = {}
        entity_table: list[dict] = []
        total_entities = 0

        for r in seg_rows:
            try:
                ents = json.loads(r["entity_refs_json"])
            except Exception:
                ents = []
            n = len(ents)
            total_entities += n
            bucket = "1" if n == 1 else "2" if n == 2 else "3" if n == 3 else "4-5" if n <= 5 else "6-10" if n <= 10 else "11+"
            per_seg_counter[bucket] = per_seg_counter.get(bucket, 0) + 1
            for e in ents:
                # DB schema: {"type": "...", "name": "..."} (see RawSegmentData.entity_refs_json).
                # Tolerate richer shapes if a future enricher emits them.
                etype = e.get("type") or e.get("entity_type") or ""
                ename = e.get("name") or e.get("canonical") or e.get("text") or ""
                type_counter[etype] = type_counter.get(etype, 0) + 1
                entity_table.append(
                    {
                        "doc": _truncate(r["doc_title"], 30),
                        "seg#": r["segment_index"],
                        "entity_type": etype,
                        "name": _truncate(ename, 80),
                        "section": _truncate(r["section_title"], 40),
                    }
                )

        entity_hint = (
            "" if total_entities > 0
            else "\n\n> ℹ️ 实体提取无产出。rule-based 提取器靠领域包正则（命令/IP/参数等），"
                 "对非命令类文档常无命中；可在 .env 设置 MINING_LLM_ENABLED=true + LLM_SERVICE_URL 启用 LLM enricher 补强。"
        )
        summary = (
            f"### 增强统计\n\n"
            f"#### semantic_role 分类\n"
            f"- 段落总数：**{total_segs}**\n"
            f"- 已分类（非 unknown）：**{classified_segs}**（**{classify_rate:.1f}%**）\n"
            f"- 分类种类：**{sum(1 for r in roles if r['semantic_role'] != 'unknown' and r['c'] > 0)}** 种\n\n"
            f"#### 实体提取\n"
            f"- 含实体的段落：**{len(seg_rows)}**\n"
            f"- 实体引用总数：**{total_entities}**\n"
            f"- 实体类型数：**{len(type_counter)}**"
            f"{entity_hint}"
        )
        type_df = pd.DataFrame(
            sorted(({"entity_type": k, "count": v} for k, v in type_counter.items()), key=lambda x: -x["count"])
        ) if type_counter else _empty_counts_df("entity_type")
        per_seg_order = ["1", "2", "3", "4-5", "6-10", "11+"]
        per_seg_df = pd.DataFrame(
            [{"count_per_seg": k, "count": per_seg_counter.get(k, 0)} for k in per_seg_order if per_seg_counter.get(k)]
        ) if per_seg_counter else _empty_counts_df("count_per_seg")
        entity_df = pd.DataFrame(entity_table) if entity_table else pd.DataFrame()
        return [summary, _counts_df(roles, "semantic_role"), type_df, per_seg_df, entity_df]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 5: Relations ----------

def render_relations(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        snap_ids = _snapshot_ids(rt, run_id)
        if not snap_ids:
            return [
                EMPTY_RUN_TEXT,
                _empty_counts_df("relation_type"),
                _empty_counts_df("distance_bin"),
                pd.DataFrame(),
            ]
        ph = ",".join(["%s"] * len(snap_ids))

        types = asset.execute(
            f"SELECT relation_type, COUNT(*) AS c FROM asset_raw_segment_relations "
            f"WHERE document_snapshot_id IN ({ph}) GROUP BY relation_type ORDER BY c DESC",
            snap_ids,
        ).fetchall()
        all_rels = asset.execute(
            f"""SELECT r.relation_type, r.weight, r.confidence, r.distance,
                       s1.segment_index AS src_idx, s1.raw_text AS src_text,
                       s2.segment_index AS tgt_idx, s2.raw_text AS tgt_text
                  FROM asset_raw_segment_relations r
                  JOIN asset_raw_segments s1 ON r.source_segment_id = s1.id
                  JOIN asset_raw_segments s2 ON r.target_segment_id = s2.id
                 WHERE r.document_snapshot_id IN ({ph})
                 ORDER BY s1.segment_index, r.relation_type""",
            snap_ids,
        ).fetchall()

        dist_counter: dict[str, int] = {}
        total_dist = 0
        with_dist = 0
        for r in all_rels:
            b = _bin_distance(r["distance"])
            dist_counter[b] = dist_counter.get(b, 0) + 1
            if r["distance"] is not None:
                total_dist += abs(r["distance"])
                with_dist += 1

        avg_dist = (total_dist / with_dist) if with_dist else 0.0
        summary = (
            f"### 关系统计\n\n"
            f"- 关系总数：**{len(all_rels)}**\n"
            f"- 关系类型数：**{len(types)}**\n"
            f"- 平均距离：**{avg_dist:.1f}** （{with_dist} 条带 distance）"
        )
        full_df = pd.DataFrame(
            [
                {
                    "relation_type": r["relation_type"],
                    "src#": r["src_idx"],
                    "src_text": _truncate(r["src_text"], 80),
                    "tgt#": r["tgt_idx"],
                    "tgt_text": _truncate(r["tgt_text"], 80),
                    "weight": round(r["weight"] or 0, 2),
                    "conf": round(r["confidence"] or 0, 2),
                    "dist": r["distance"],
                }
                for r in all_rels
            ]
        )
        return [
            summary,
            _counts_df(types, "relation_type"),
            _ordered_bin_df(dist_counter, _DIST_ORDER, "distance_bin"),
            full_df,
        ]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 6: Retrieval Units ----------

def render_retrieval_units(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        snap_ids = _snapshot_ids(rt, run_id)
        if not snap_ids:
            return [
                EMPTY_RUN_TEXT,
                _empty_counts_df("unit_type"),
                _empty_counts_df("target_type"),
                _empty_counts_df("text_len_bin"),
                pd.DataFrame(),
            ]
        ph = ",".join(["%s"] * len(snap_ids))

        ut = asset.execute(
            f"SELECT unit_type, COUNT(*) AS c FROM asset_retrieval_units "
            f"WHERE document_snapshot_id IN ({ph}) GROUP BY unit_type ORDER BY c DESC",
            snap_ids,
        ).fetchall()
        tt = asset.execute(
            f"SELECT target_type, COUNT(*) AS c FROM asset_retrieval_units "
            f"WHERE document_snapshot_id IN ({ph}) GROUP BY target_type ORDER BY c DESC",
            snap_ids,
        ).fetchall()
        all_units = asset.execute(
            f"SELECT u.unit_type, u.target_type, u.title, u.text, u.search_text, "
            f"       u.block_type, u.semantic_role, u.weight, ds.title AS doc_title "
            f"FROM asset_retrieval_units u "
            f"JOIN asset_document_snapshots ds ON u.document_snapshot_id = ds.id "
            f"WHERE u.document_snapshot_id IN ({ph}) "
            f"ORDER BY u.document_snapshot_id, u.unit_type, u.id",
            snap_ids,
        ).fetchall()

        len_counter: dict[str, int] = {}
        total_text = 0
        for r in all_units:
            n = len(r["text"] or "")
            total_text += n
            b = _bin_text_len(n)
            len_counter[b] = len_counter.get(b, 0) + 1

        avg_len = (total_text / len(all_units)) if all_units else 0.0
        summary = (
            f"### 检索单元统计\n\n"
            f"- 单元总数：**{len(all_units)}**\n"
            f"- 单元类型数：**{len(ut)}** / 目标类型数：**{len(tt)}**\n"
            f"- 平均文本长度：**{avg_len:.0f}** 字符"
        )
        full_df = pd.DataFrame(
            [
                {
                    "doc": _truncate(r["doc_title"], 30),
                    "unit_type": r["unit_type"],
                    "target_type": r["target_type"],
                    "block_type": r["block_type"],
                    "semantic_role": r["semantic_role"],
                    "title": _truncate(r["title"], 60),
                    "text": _truncate(r["text"], 200),
                    "weight": round(r["weight"] or 0, 2),
                }
                for r in all_units
            ]
        )
        return [
            summary,
            _counts_df(ut, "unit_type"),
            _counts_df(tt, "target_type"),
            _ordered_bin_df(len_counter, _TXTLEN_ORDER, "text_len_bin"),
            full_df,
        ]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 7: Snapshot ----------

def render_snapshot(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        rd_rows = rt.execute(
            "SELECT document_id, document_snapshot_id, document_key, action FROM mining_run_documents "
            "WHERE run_id = %s AND document_id IS NOT NULL",
            (run_id,),
        ).fetchall()
        if not rd_rows:
            return [EMPTY_RUN_TEXT, _empty_counts_df("action"), _empty_counts_df("mime_type"), pd.DataFrame()]

        action_counter: dict[str, int] = {}
        mime_counter: dict[str, int] = {}
        rows: list[dict] = []
        for rd in rd_rows:
            snap = asset.execute(
                "SELECT normalized_content_hash, mime_type, title FROM asset_document_snapshots WHERE id = %s",
                (rd["document_snapshot_id"],),
            ).fetchone()
            action = rd["action"] or ""
            action_counter[action] = action_counter.get(action, 0) + 1
            mime = (snap["mime_type"] if snap else "") or ""
            mime_counter[mime] = mime_counter.get(mime, 0) + 1
            rows.append(
                {
                    "document_key": _truncate(rd["document_key"], 80),
                    "action": action,
                    "doc_id": (rd["document_id"] or "")[:12],
                    "snapshot_id": (rd["document_snapshot_id"] or "")[:12],
                    "mime": mime,
                    "title": _truncate(snap["title"], 60) if snap else "",
                    "norm_hash": (snap["normalized_content_hash"][:12] if snap else ""),
                }
            )

        summary = (
            f"### 快照统计\n\n"
            f"- 已绑定 document 的记录：**{len(rd_rows)}**\n"
            f"- action 分布：{', '.join(f'**{k}**={v}' for k, v in action_counter.items())}"
        )
        action_df = pd.DataFrame([{"action": k, "count": v} for k, v in action_counter.items()])
        mime_df = pd.DataFrame([{"mime_type": k, "count": v} for k, v in mime_counter.items()])
        return [summary, action_df, mime_df, pd.DataFrame(rows)]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 8: Build ----------

def render_build(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        run_row = rt.execute("SELECT build_id FROM mining_runs WHERE id = %s", (run_id,)).fetchone()
        if not run_row or not run_row["build_id"]:
            return [EMPTY_RUN_TEXT, _empty_counts_df("reason"), pd.DataFrame()]
        build_id = run_row["build_id"]
        b = asset.execute(
            "SELECT id, build_code, build_mode, status, domain, created_at, finished_at, summary_json "
            "FROM asset_builds WHERE id = %s",
            (build_id,),
        ).fetchone()
        if not b:
            return [EMPTY_RUN_TEXT, _empty_counts_df("reason"), pd.DataFrame()]

        reason_rows = asset.execute(
            "SELECT reason, COUNT(*) AS c FROM asset_build_document_snapshots "
            "WHERE build_id = %s GROUP BY reason ORDER BY c DESC",
            (build_id,),
        ).fetchall()
        bds_rows = asset.execute(
            "SELECT bds.reason, bds.selection_status, ds.title, ds.mime_type, ds.normalized_content_hash "
            "FROM asset_build_document_snapshots bds "
            "JOIN asset_document_snapshots ds ON bds.document_snapshot_id = ds.id "
            "WHERE bds.build_id = %s ORDER BY bds.reason",
            (build_id,),
        ).fetchall()

        summary = (
            f"### 构建信息\n\n"
            f"- build_id：`{b['id']}`\n"
            f"- build_code：`{b['build_code']}`\n"
            f"- 领域：**{b['domain']}**\n"
            f"- 模式：**{b['build_mode']}** | 状态：**{b['status']}**\n"
            f"- 创建：{b['created_at']} | 完成：{b['finished_at'] or '-'}\n"
            f"- 包含快照数：**{len(bds_rows)}**"
        )
        full_df = pd.DataFrame(
            [
                {
                    "reason": r["reason"],
                    "selection_status": r["selection_status"],
                    "title": _truncate(r["title"], 60),
                    "mime": r["mime_type"],
                    "norm_hash": (r["normalized_content_hash"] or "")[:12],
                }
                for r in bds_rows
            ]
        )
        return [summary, _counts_df(reason_rows, "reason"), full_df]
    finally:
        rt.close()
        asset.close()


# ---------- Stage 9: Release ----------

def render_release(run_id: str) -> list[Any]:
    rt = _open_runtime()
    asset = _open_asset()
    try:
        run_row = rt.execute("SELECT build_id FROM mining_runs WHERE id = %s", (run_id,)).fetchone()
        if not run_row or not run_row["build_id"]:
            return ["_（未生成 build，无 release）_", pd.DataFrame()]
        rels = asset.execute(
            "SELECT id, release_code, domain, channel, status, activated_at, deactivated_at, "
            "       released_by, release_notes "
            "FROM asset_publish_releases WHERE build_id = %s "
            "ORDER BY COALESCE(activated_at, '') DESC",
            (run_row["build_id"],),
        ).fetchall()
        if not rels:
            return ["_（本次未 publish_release，可能 phase1_only 或失败被阻断）_", pd.DataFrame()]
        summary = f"### Release 列表（{len(rels)} 条）\n"
        full_df = pd.DataFrame(
            [
                {
                    "release_id": (r["id"] or "")[:12],
                    "release_code": r["release_code"],
                    "domain": r["domain"],
                    "channel": r["channel"],
                    "status": r["status"],
                    "activated_at": r["activated_at"] or "-",
                    "deactivated_at": r["deactivated_at"] or "-",
                    "released_by": r["released_by"] or "-",
                    "notes": _truncate(r["release_notes"], 100),
                }
                for r in rels
            ]
        )
        return [summary, full_df]
    finally:
        rt.close()
        asset.close()


# ---------- Timeline ----------

def render_timeline(run_id: str) -> list[Any]:
    rt = _open_runtime()
    try:
        events = rt.execute(
            "SELECT stage, status, duration_ms, output_summary, error_message, created_at "
            "FROM mining_run_stage_events WHERE run_id = %s ORDER BY created_at",
            (run_id,),
        ).fetchall()
    finally:
        rt.close()
    if not events:
        return [EMPTY_RUN_TEXT, _empty_counts_df("stage"), pd.DataFrame()]

    dur_per_stage: dict[str, int] = {}
    for e in events:
        if e["duration_ms"] is not None:
            dur_per_stage[e["stage"]] = dur_per_stage.get(e["stage"], 0) + (e["duration_ms"] or 0)

    total_ms = sum(dur_per_stage.values())
    summary = (
        f"### 阶段事件\n\n"
        f"- 事件总数：**{len(events)}**\n"
        f"- 涉及阶段数：**{len(dur_per_stage)}**\n"
        f"- 总耗时：**{total_ms:,} ms**"
    )
    dur_df = pd.DataFrame(
        sorted(({"stage": k, "ms": v} for k, v in dur_per_stage.items()), key=lambda x: -x["ms"])
    ) if dur_per_stage else pd.DataFrame({"stage": [], "ms": []})
    full_df = pd.DataFrame(
        [
            {
                "time": (e["created_at"] or "")[-12:-3],
                "stage": e["stage"],
                "status": e["status"],
                "ms": e["duration_ms"],
                "output": _truncate(e["output_summary"], 100),
                "error": _truncate(e["error_message"], 100),
            }
            for e in events
        ]
    )
    return [summary, dur_df, full_df]


# =====================================================================
# Stage spec — declarative description of each panel's plots and value-axis key
# =====================================================================

# Each plot spec: (title, x_axis_column, y_axis_column)
STAGE_SPECS: list[dict[str, Any]] = [
    {"id": "ingest", "label": "Ingest 摄取", "short": "Ingest", "render": render_ingest,
     "plots": [("按 action 分布", "action", "count"),
               ("按 status 分布", "status", "count")]},
    {"id": "parse", "label": "Parse 解析", "short": "Parse", "render": render_parse,
     "plots": [("每文档小节数", "doc", "count"),
               ("小节层级分布", "depth", "count")]},
    {"id": "segment", "label": "Segment 分块", "short": "Segment", "render": render_segment,
     "plots": [("block_type 分布", "block_type", "count"),
               ("token_count 分布", "token_bin", "count")]},
    {"id": "enrich", "label": "Enrich 增强", "short": "Enrich", "render": render_enrich,
     "plots": [("semantic_role 分布", "semantic_role", "count"),
               ("实体类型分布", "entity_type", "count"),
               ("每段实体数分布", "count_per_seg", "count")]},
    {"id": "relations", "label": "Relations 关系", "short": "Relations", "render": render_relations,
     "plots": [("relation_type 分布", "relation_type", "count"),
               ("距离分布", "distance_bin", "count")]},
    {"id": "units", "label": "Retrieval Units", "short": "Units", "render": render_retrieval_units,
     "plots": [("unit_type 分布", "unit_type", "count"),
               ("target_type 分布", "target_type", "count"),
               ("文本长度分布", "text_len_bin", "count")]},
    {"id": "snapshot", "label": "Snapshot 快照", "short": "Snapshot", "render": render_snapshot,
     "plots": [("action 分布", "action", "count"),
               ("mime_type 分布", "mime_type", "count")]},
    {"id": "build", "label": "Build 构建", "short": "Build", "render": render_build,
     "plots": [("reason 分布", "reason", "count")]},
    {"id": "release", "label": "Release 发布", "short": "Release", "render": render_release,
     "plots": []},
    {"id": "timeline", "label": "事件时间线", "short": "Timeline", "render": render_timeline,
     "plots": [("按阶段累计耗时", "stage", "ms")]},
]
STAGE_BY_ID = {s["id"]: s for s in STAGE_SPECS}
STAGE_IDS = [s["id"] for s in STAGE_SPECS]
PIPELINE_STAGE_IDS = [sid for sid in STAGE_IDS if sid != "timeline"]


def _empty_render_for(spec: dict[str, Any]) -> list[Any]:
    """Default placeholder per stage when run not started."""
    n_plots = len(spec["plots"])
    keys_for_plots = [p[1] for p in spec["plots"]]
    out: list[Any] = [EMPTY_RUN_TEXT]
    for k in keys_for_plots:
        out.append(_empty_counts_df(k))
    out.append(pd.DataFrame())
    return out


def _safe_render(spec: dict[str, Any], run_id: str | None) -> list[Any]:
    if not run_id:
        return _empty_render_for(spec)
    try:
        return spec["render"](run_id)
    except Exception as e:
        out = _empty_render_for(spec)
        out[0] = f"❌ 渲染失败：{type(e).__name__}: {e}"
        return out


# =====================================================================
# Per-stage status derivation (status + KPI) from PG
# =====================================================================

def _stage_event_status(events_by_stage: dict[str, dict], names: tuple[str, ...]) -> str | None:
    seen = "none"
    for name in names:
        ev = events_by_stage.get(name)
        if not ev:
            continue
        if ev["status"] == "completed":
            return "completed"
        if ev["status"] == "failed":
            return "failed"
        if ev["status"] == "started":
            seen = "started"
    return seen if seen != "none" else None


def _compute_pipeline_status(run_id: str, run_row: dict) -> dict[str, dict]:
    """Compute per-stage UI status: pending / running / done / failed / cancelled."""
    if run_row is None:
        return {sid: {"status": "pending", "kpi": None, "duration_ms": None}
                for sid in PIPELINE_STAGE_IDS}
    rt = _open_runtime()
    asset = _open_asset()
    overall_status = run_row["status"]
    is_terminal = overall_status in ("completed", "failed", "cancelled")
    try:
        ev_rows = rt.execute(
            "SELECT stage, status, duration_ms, error_message, created_at "
            "FROM mining_run_stage_events "
            "WHERE run_id = %s ORDER BY created_at",
            (run_id,),
        ).fetchall()
        events_by_stage: dict[str, dict] = {}
        for r in ev_rows:
            cur = events_by_stage.get(r["stage"])
            if cur is None or (cur["status"] == "started" and r["status"] in ("completed", "failed")):
                events_by_stage[r["stage"]] = dict(r)

        snap_ids = _snapshot_ids(rt, run_id)
        snap_ph = ",".join(["%s"] * len(snap_ids)) if snap_ids else None

        doc_rows = rt.execute(
            "SELECT status, action FROM mining_run_documents WHERE run_id = %s",
            (run_id,),
        ).fetchall()
        n_docs = len(doc_rows)
        n_docs_failed = sum(1 for r in doc_rows if r["status"] == "failed")
        n_docs_committed = sum(1 for r in doc_rows if r["status"] == "committed")

        n_segments = 0
        n_enriched_segs = 0
        n_relations = 0
        n_units = 0
        n_snapshots = 0
        if snap_ph:
            n_segments = (asset.execute(
                f"SELECT COUNT(*) AS c FROM asset_raw_segments WHERE document_snapshot_id IN ({snap_ph})",
                snap_ids,
            ).fetchone() or {"c": 0})["c"]
            n_enriched_segs = (asset.execute(
                f"SELECT COUNT(*) AS c FROM asset_raw_segments "
                f"WHERE document_snapshot_id IN ({snap_ph}) AND entity_refs_json != '[]'",
                snap_ids,
            ).fetchone() or {"c": 0})["c"]
            n_relations = (asset.execute(
                f"SELECT COUNT(*) AS c FROM asset_raw_segment_relations WHERE document_snapshot_id IN ({snap_ph})",
                snap_ids,
            ).fetchone() or {"c": 0})["c"]
            n_units = (asset.execute(
                f"SELECT COUNT(*) AS c FROM asset_retrieval_units WHERE document_snapshot_id IN ({snap_ph})",
                snap_ids,
            ).fetchone() or {"c": 0})["c"]
            n_snapshots = (asset.execute(
                f"SELECT COUNT(*) AS c FROM asset_document_snapshots WHERE id IN ({snap_ph})",
                snap_ids,
            ).fetchone() or {"c": 0})["c"]

        build_id = run_row.get("build_id")
        n_releases = 0
        if build_id:
            n_releases = (asset.execute(
                "SELECT COUNT(*) AS c FROM asset_publish_releases WHERE build_id = %s",
                (build_id,),
            ).fetchone() or {"c": 0})["c"]
    finally:
        rt.close()
        asset.close()

    # In-memory stage events (emitted by StreamingPipeline workers, post 2026-05-07).
    # Fall back to legacy persist-time names for runs created before that change.
    parse_evt = events_by_stage.get("parse")
    seg_evt = events_by_stage.get("segment") or events_by_stage.get("segment_persist")
    enrich_evt = events_by_stage.get("enrich")
    rel_evt = (events_by_stage.get("relations")
               or events_by_stage.get("relations_persist")
               or events_by_stage.get("build_relations"))
    snap_evt = events_by_stage.get("select_snapshot")
    ru_evt = (events_by_stage.get("retrieval_units")
              or events_by_stage.get("retrieval_units_persist")
              or events_by_stage.get("build_retrieval_units"))
    ab_evt = events_by_stage.get("assemble_build")
    pr_evt = events_by_stage.get("publish_release")

    def derive(has_data: bool, evt: dict | None, *, started_others: bool = False) -> tuple[str, int | None]:
        if evt and evt["status"] == "failed":
            return ("failed", evt.get("duration_ms"))
        if evt and evt["status"] == "completed":
            return ("done", evt.get("duration_ms"))
        if has_data:
            return ("done" if is_terminal else "running", None)
        if evt and evt["status"] == "started":
            return ("running", None)
        if started_others or overall_status == "running":
            return ("pending", None)
        if overall_status == "cancelled":
            return ("cancelled", None)
        if overall_status == "failed" and not has_data:
            return ("pending", None)
        return ("pending", None)

    stages: dict[str, dict] = {}
    if n_docs > 0:
        st = "failed" if (n_docs_failed > 0 and n_docs_committed == 0 and overall_status == "failed") else "done"
        kpi = f"📄 {n_docs} 个 · ✓{n_docs_committed} ✗{n_docs_failed}"
    else:
        st = "running" if overall_status == "running" else "pending"
        kpi = "—"
    stages["ingest"] = {"status": st, "kpi": kpi, "duration_ms": None}

    parse_st, parse_dur = derive(n_segments > 0, parse_evt or seg_evt)
    stages["parse"] = {"status": parse_st, "kpi": f"≈{n_segments} 段" if n_segments else "—", "duration_ms": parse_dur}

    seg_st, seg_dur = derive(n_segments > 0, seg_evt)
    stages["segment"] = {"status": seg_st, "kpi": f"{n_segments} 段" if n_segments else "—", "duration_ms": seg_dur}

    if enrich_evt and enrich_evt.get("status") == "completed":
        en_st, en_dur = "done", enrich_evt.get("duration_ms")
        en_kpi = f"{n_enriched_segs} 段含实体" if n_enriched_segs > 0 else "0 实体（rule-based 无命中）"
    elif enrich_evt and enrich_evt.get("status") == "failed":
        en_st, en_dur, en_kpi = "failed", enrich_evt.get("duration_ms"), "—"
    elif n_enriched_segs > 0:
        en_st, en_dur, en_kpi = "done", None, f"{n_enriched_segs} 段含实体"
    elif rel_evt and rel_evt.get("status") == "completed":
        en_st, en_dur, en_kpi = "done", None, "0 实体（rule-based 无命中）"
    elif enrich_evt and enrich_evt.get("status") == "started":
        en_st, en_dur, en_kpi = "running", None, "—"
    elif n_segments > 0:
        en_st = "running" if overall_status == "running" else "pending"
        en_dur, en_kpi = None, "—"
    else:
        en_st = "running" if overall_status == "running" else "pending"
        en_dur, en_kpi = None, "—"
    stages["enrich"] = {"status": en_st, "kpi": en_kpi, "duration_ms": en_dur}

    rel_st, rel_dur = derive(n_relations > 0, rel_evt)
    stages["relations"] = {"status": rel_st, "kpi": f"{n_relations} 条" if n_relations else "—", "duration_ms": rel_dur}

    ru_st, ru_dur = derive(n_units > 0, ru_evt)
    stages["units"] = {"status": ru_st, "kpi": f"{n_units} 单元" if n_units else "—", "duration_ms": ru_dur}

    snap_st, snap_dur = derive(n_snapshots > 0, snap_evt)
    stages["snapshot"] = {"status": snap_st, "kpi": f"{n_snapshots} 快照" if n_snapshots else "—", "duration_ms": snap_dur}

    has_build = bool(build_id)
    bd_st, bd_dur = derive(has_build, ab_evt)
    stages["build"] = {"status": bd_st, "kpi": f"build {build_id[:8]}" if has_build and build_id else "—", "duration_ms": bd_dur}

    rel2_st, rel2_dur = derive(n_releases > 0, pr_evt)
    stages["release"] = {"status": rel2_st, "kpi": f"{n_releases} release" if n_releases else "—", "duration_ms": rel2_dur}

    if overall_status == "cancelled":
        for sid, sd in stages.items():
            if sd["status"] in ("pending", "running"):
                sd["status"] = "cancelled"

    return stages


# =====================================================================
# UI helpers
# =====================================================================

_STATUS_GLYPH = {
    "done": "✓", "running": "⟳", "pending": "○", "failed": "✗", "cancelled": "⊘",
}
_STATUS_COLOR = {
    "done": "#10b981", "running": "#3b82f6", "pending": "#94a3b8",
    "failed": "#ef4444", "cancelled": "#f59e0b",
}
_STATUS_LABEL = {
    "done": "已完成", "running": "运行中", "pending": "等待中",
    "failed": "失败", "cancelled": "已取消",
}


def _fmt_duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    m, s = divmod(ms // 1000, 60)
    return f"{m}m{s:02d}s"


def _phase_from_run(run_row: dict | None) -> str:
    if run_row is None:
        return "running"
    s = run_row["status"]
    if s == "completed":
        return "done"
    if s == "failed":
        return "failed"
    if s == "cancelled":
        return "cancelled"
    return "running"


def _elapsed_seconds(started_at, finished_at) -> int:
    if not started_at:
        return 0
    try:
        from datetime import timezone
        start = started_at if isinstance(started_at, datetime) else datetime.fromisoformat(str(started_at))
        if finished_at:
            end = finished_at if isinstance(finished_at, datetime) else datetime.fromisoformat(str(finished_at))
        else:
            end = datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, int((end - start).total_seconds()))
    except Exception:
        return 0


def _progress_pct(stages: dict[str, dict]) -> int:
    done = sum(1 for sid in PIPELINE_STAGE_IDS if stages.get(sid, {}).get("status") == "done")
    return int(done / len(PIPELINE_STAGE_IDS) * 100)


def _status_bar_html(
    run_row: dict | None,
    stages: dict[str, dict],
    phase: str,
    domain: str | None = None,
) -> str:
    if run_row is None:
        dom_suffix = f"（领域 <code>{domain}</code>）" if domain else ""
        return f'<div class="status-bar">⏳ 启动中…{dom_suffix}</div>'
    elapsed = _elapsed_seconds(run_row.get("started_at"), run_row.get("finished_at"))
    mm, ss = divmod(elapsed, 60)
    pct = _progress_pct(stages)
    rid = (str(run_row.get("id") or ""))[:8]
    if phase == "running":
        icon, label, color = "🏃", "运行中", "#3b82f6"
    elif phase == "done":
        icon, label, color = "✅", "完成", "#10b981"
    elif phase == "failed":
        icon, label, color = "❌", "失败", "#ef4444"
    elif phase == "cancelled":
        icon, label, color = "⊘", "已取消", "#f59e0b"
    else:
        icon, label, color = "•", phase, "#94a3b8"
    domain_html = (
        f'  <span class="sb-meta">领域 <code>{domain}</code></span>'
        if domain else ""
    )
    return (
        f'<div class="status-bar">'
        f'  <span class="sb-badge" style="background:{color}1a;color:{color};">{icon} {label}</span>'
        f'  <span class="sb-meta">run <code>{rid}</code></span>'
        f'{domain_html}'
        f'  <span class="sb-meta">⏱ {mm}:{ss:02d}</span>'
        f'  <span class="sb-meta">进度 {pct}%</span>'
        f'  <div class="sb-bar"><div class="sb-bar-fill" style="width:{pct}%;background:{color};"></div></div>'
        f'</div>'
    )


def _kpi_html(stage_id: str, stages: dict[str, dict]) -> str:
    sd = stages.get(stage_id, {})
    st = sd.get("status", "pending")
    glyph = _STATUS_GLYPH.get(st, "•")
    color = _STATUS_COLOR.get(st, "#94a3b8")
    dur = _fmt_duration(sd.get("duration_ms"))
    kpi = sd.get("kpi", "—")
    return (
        f'<div class="kpi-row">'
        f'  <div class="kpi-card"><div class="kpi-num" style="color:{color};">{glyph}</div>'
        f'    <div class="kpi-label">{_STATUS_LABEL.get(st, st)}</div></div>'
        f'  <div class="kpi-card"><div class="kpi-num">{dur}</div>'
        f'    <div class="kpi-label">耗时</div></div>'
        f'  <div class="kpi-card"><div class="kpi-num">{kpi}</div>'
        f'    <div class="kpi-label">本阶段产出</div></div>'
        f'</div>'
    )


def _stepper_btn_html(spec: dict, stages: dict[str, dict], focused: bool) -> str:
    sid = spec["id"]
    sd = stages.get(sid, {})
    st = sd.get("status", "pending")
    glyph = _STATUS_GLYPH.get(st, "○")
    color = _STATUS_COLOR.get(st, "#94a3b8")
    if st == "running":
        extra = "运行中…"
    elif st == "done":
        extra = _fmt_duration(sd.get("duration_ms"))
    elif st == "failed":
        extra = "失败"
    elif st == "cancelled":
        extra = "已取消"
    else:
        extra = "待运行"
    kpi = sd.get("kpi", "—")
    kpi_part = f'<div class="step-kpi">{kpi}</div>' if (kpi and kpi != "—" and st in ("done", "running", "failed")) else ''
    focus_class = " step-focused" if focused else ""
    return (
        f'<div class="step-btn step-{st}{focus_class}">'
        f'  <div class="step-glyph" style="color:{color};">{glyph}</div>'
        f'  <div class="step-name">{spec["short"]}</div>'
        f'  <div class="step-extra">{extra}</div>'
        f'  {kpi_part}'
        f'</div>'
    )


# =====================================================================
# ECharts / AG Grid option builders
# =====================================================================

def _bar_option(df: pd.DataFrame, x_col: str, y_col: str, title: str) -> dict:
    if df is None or df.empty:
        xs, ys = [], []
    else:
        xs = df[x_col].astype(str).tolist() if x_col in df.columns else []
        ys = df[y_col].tolist() if y_col in df.columns else []
    return {
        "title": {
            "text": title,
            "left": "center",
            "textStyle": {"fontSize": 13, "fontWeight": "normal", "color": "#475569"},
        },
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 50, "right": 20, "top": 40, "bottom": 40, "containLabel": True},
        "xAxis": {
            "type": "category",
            "data": xs,
            "axisLabel": {"fontSize": 11, "color": "#64748b", "interval": 0, "rotate": 30 if any(len(str(x)) > 6 for x in xs) else 0},
            "axisLine": {"lineStyle": {"color": "#cbd5e1"}},
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {"fontSize": 11, "color": "#64748b"},
            "splitLine": {"lineStyle": {"color": "#e2e8f0"}},
        },
        "series": [{
            "type": "bar",
            "data": ys,
            "itemStyle": {"color": "#5b6cff", "borderRadius": [4, 4, 0, 0]},
            "barMaxWidth": 40,
        }],
    }


def _grid_options(df: pd.DataFrame) -> dict:
    # NiceGUI 3.x + AG Grid 34 在 update_grid() 里用 options.theme 查表，
    # 且我们走 clear()+update() 路径会抹掉 __init__ 注入的 theme/autoSizeStrategy，
    # 所以这里每次都把它们带回来。
    base = {
        "theme": "quartz",
        "autoSizeStrategy": {"type": "fitGridWidth"},
    }
    if df is None or df.empty:
        return {
            **base,
            "columnDefs": [{"field": "(无数据)"}],
            "rowData": [],
        }
    cols = []
    for c in df.columns:
        col_def = {
            "field": str(c),
            "headerName": str(c),
            "filter": True,
            "sortable": True,
            "resizable": True,
            "minWidth": 80,
        }
        cols.append(col_def)
    rows = df.fillna("").to_dict("records")
    return {
        **base,
        "columnDefs": cols,
        "rowData": rows,
        "defaultColDef": {"flex": 1, "minWidth": 80, "resizable": True},
        "rowHeight": 28,
        "headerHeight": 32,
    }


# =====================================================================
# State
# =====================================================================

@dataclass
class MiningState:
    phase: str = "ready"  # ready / running / done / failed / cancelled
    run_id: str | None = None
    input_path: str | None = None
    focus_stage: str | None = None
    auto_follow: bool = True
    started_at_local: float | None = None
    domain_pack: str | None = None
    stages: dict[str, dict] = field(
        default_factory=lambda: {sid: {"status": "pending", "kpi": "—", "duration_ms": None}
                                 for sid in PIPELINE_STAGE_IDS}
    )
    files: list[Path] = field(default_factory=list)


STATE = MiningState()
_RUN_LOCK = threading.Lock()


def _next_focus(prev: str | None, stages: dict[str, dict], auto_follow: bool) -> str:
    valid = [sid for sid in PIPELINE_STAGE_IDS if stages.get(sid, {}).get("status") != "pending"]
    if not auto_follow and prev and prev in PIPELINE_STAGE_IDS and (
        stages.get(prev, {}).get("status") != "pending"
    ):
        return prev
    last_done = None
    first_running = None
    for sid in PIPELINE_STAGE_IDS:
        st = stages.get(sid, {}).get("status")
        if st == "done":
            last_done = sid
        if st == "running" and first_running is None:
            first_running = sid
    return last_done or first_running or (valid[0] if valid else PIPELINE_STAGE_IDS[0])


def _cancel_run_in_db(run_id: str) -> None:
    pool = _get_pool()
    with pool.connection() as conn:
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE mining_runs SET status = 'cancelled', finished_at = %s "
            "WHERE id = %s AND status IN ('running', 'pending', 'queued')",
            (now, run_id),
        )


# =====================================================================
# CSS
# =====================================================================

CUSTOM_CSS = """
body { background: #f5f7fb; font-family: "Inter", -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
.nicegui-content { max-width: 1480px; margin: 0 auto; padding: 16px; }

.app-header { display: flex; align-items: baseline; gap: 12px; padding: 4px 0 16px 0; border-bottom: 1px solid #e6e8f0; margin-bottom: 16px; }
.app-header .title { font-size: 22px; font-weight: 700; color: #1f2937; letter-spacing: -0.01em; }
.app-header .subtitle { color: #6b7280; font-size: 13px; }

.section-card { background: #fff; border-radius: 12px; padding: 16px 18px; border: 1px solid #e6e8f0; box-shadow: 0 1px 2px rgba(15,23,42,0.04); }
.section-title { font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }

/* Buttons */
.btn-primary { background: #5b6cff !important; color: #fff !important; font-weight: 600 !important; border-radius: 10px !important; box-shadow: 0 1px 4px rgba(91,108,255,0.25) !important; }
.btn-primary:hover { background: #4a59e8 !important; }
.btn-danger-outline { background: #fff !important; color: #ef4444 !important; border: 1px solid #ef4444 !important; border-radius: 8px !important; font-weight: 600 !important; }
.btn-danger-outline:hover { background: #fef2f2 !important; }
.btn-ghost { background: #fff !important; color: #475569 !important; border: 1px solid #cbd5e1 !important; border-radius: 8px !important; font-size: 12px !important; font-weight: 500 !important; }
.btn-ghost:hover { background: #f8fafc !important; }

/* Status bar */
.status-bar { display: flex; align-items: center; gap: 14px; padding: 10px 14px; background: #fff; border-radius: 12px; border: 1px solid #e6e8f0; box-shadow: 0 1px 2px rgba(15,23,42,0.04); font-size: 13px; }
.status-bar .sb-badge { padding: 4px 10px; border-radius: 6px; font-weight: 600; font-size: 12px; }
.status-bar .sb-meta { color: #475569; }
.status-bar .sb-meta code { background: #f1f5f9; padding: 1px 6px; border-radius: 4px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.status-bar .sb-bar { flex: 1 1 auto; height: 6px; background: #e6e8f0; border-radius: 3px; overflow: hidden; min-width: 80px; }
.status-bar .sb-bar-fill { height: 100%; transition: width 0.3s ease; }

/* Stepper */
.stepper-row { display: flex; flex-wrap: wrap; gap: 8px; }
.step-btn { flex: 1 1 0; min-width: 130px; padding: 10px 12px; background: #f8fafc; border: 1px solid #e6e8f0; border-radius: 10px; cursor: pointer; transition: all .15s ease; user-select: none; }
.step-btn:hover { background: #f1f5f9; border-color: #cbd5e1; }
.step-btn .step-glyph { font-size: 16px; font-weight: 700; line-height: 1; }
.step-btn .step-name { font-size: 13px; font-weight: 600; color: #1f2937; margin-top: 4px; }
.step-btn .step-extra { font-size: 11px; color: #64748b; margin-top: 2px; }
.step-btn .step-kpi { font-size: 11px; color: #475569; margin-top: 4px; padding-top: 4px; border-top: 1px dashed #e2e8f0; }
.step-focused { background: #eef2ff !important; border-color: #5b6cff !important; box-shadow: 0 0 0 2px rgba(91,108,255,0.15); }
.step-running { background: #eff6ff; border-color: #93c5fd; }
.step-done { background: #ecfdf5; border-color: #6ee7b7; }
.step-failed { background: #fef2f2; border-color: #fca5a5; }
.step-cancelled { background: #fffbeb; border-color: #fcd34d; }

/* KPI strip */
.kpi-row { display: flex; gap: 12px; margin: 0 0 14px 0; }
.kpi-card { flex: 1 1 0; min-width: 110px; background: #fff; border-radius: 10px; padding: 14px 16px; border: 1px solid #e6e8f0; box-shadow: 0 1px 2px rgba(15,23,42,0.04); }
.kpi-card .kpi-num { font-size: 22px; font-weight: 700; color: #1f2937; margin-bottom: 4px; letter-spacing: -0.01em; }
.kpi-card .kpi-label { font-size: 12px; color: #6b7280; }

/* Chart container */
.chart-card { background: #fff; border-radius: 10px; padding: 8px; border: 1px solid #e6e8f0; box-shadow: 0 1px 2px rgba(15,23,42,0.04); }
"""


# =====================================================================
# StagePanel — encapsulates one stage's UI components
# =====================================================================

class StagePanel:
    """Holds references to the components of one stage panel.

    The panel container is created hidden; render(data) updates the components.
    """

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.id = spec["id"]
        # Outer container — we'll toggle visibility on this.
        self.container = ui.column().classes("w-full gap-3")
        self.container.set_visibility(False)
        with self.container:
            self.kpi_html = ui.html(_kpi_html(self.id, {})) if self.id != "timeline" else None
            self.summary_md = ui.markdown(EMPTY_RUN_TEXT)
            n_plots = len(spec["plots"])
            self.charts: list[ui.echart] = []
            if n_plots > 0:
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    for (title, x, y) in spec["plots"]:
                        with ui.card().classes("chart-card flex-1 min-w-[280px] p-2"):
                            chart = ui.echart(_bar_option(None, x, y, title)).classes("w-full h-[220px]")
                            self.charts.append(chart)
            with ui.expansion("展开明细表格", icon="table_view").classes("w-full"):
                # 固定高度 + 内部滚动，避开 autoHeight 在 expansion 中首次宽度为 0 时的 viewport 错位。
                self.grid = ui.aggrid(_grid_options(None)).classes("w-full").style("height: 480px")

    def render(
        self,
        data: list[Any],
        stages_state: dict[str, dict],
        operators: dict[str, Any] | None = None,
    ):
        """Update components with new data. data shape: [summary, *small_dfs, full_df]."""
        if self.kpi_html is not None:
            self.kpi_html.set_content(_kpi_html(self.id, stages_state))
        # data[0] is the summary string; prepend operator badge for stages that have one.
        summary_text = data[0] if data else EMPTY_RUN_TEXT
        body = summary_text or EMPTY_RUN_TEXT
        badge = _operator_badge_md(self.id, operators)
        self.summary_md.set_content(badge + body if badge else body)
        # data[1..n_plots] are small DFs; data[-1] is the full DF (if there is a table slot)
        n_plots = len(self.spec["plots"])
        for i, (title, x, y) in enumerate(self.spec["plots"]):
            if 1 + i < len(data):
                df = data[1 + i]
            else:
                df = None
            new_opts = _bar_option(df, x, y, title)
            self.charts[i].options.clear()
            self.charts[i].options.update(new_opts)
            self.charts[i].update()
        # full grid (last element in data, if more than n_plots+1)
        if len(data) >= n_plots + 2:
            full_df = data[-1]
        elif len(data) == n_plots + 1:
            # only summary + plots, no separate grid (e.g., release sometimes)
            full_df = None
        else:
            full_df = None
        new_grid_opts = _grid_options(full_df)
        self.grid.options.clear()
        self.grid.options.update(new_grid_opts)
        self.grid.update()

    def show(self):
        self.container.set_visibility(True)

    def hide(self):
        self.container.set_visibility(False)


# =====================================================================
# Page layout & handlers
# =====================================================================

ui.add_css(CUSTOM_CSS, shared=True)


@ui.page("/")
def main_page():
    # ---- Header ----
    with ui.row().classes("app-header w-full"):
        ui.html('<span class="title">🛠️ Knowledge Mining Studio</span>'
                '<span class="subtitle">v2.0 · NiceGUI · PostgreSQL backend</span>')

    # ---- READY area ----
    ready_card = ui.card().classes("section-card w-full")
    with ready_card:
        with ui.row().classes("w-full gap-4 no-wrap items-stretch"):
            # Left: upload + parameters
            with ui.column().classes("flex-1 min-w-[380px] gap-3"):
                ui.html('<div class="section-title">📎 上传文档</div>')
                upload = ui.upload(
                    label="拖入或点击上传 .md/.txt/.html/.pdf/.docx/.chm/.hdx",
                    multiple=True,
                    auto_upload=True,
                    on_upload=lambda e: _on_file_upload(e),
                ).classes("w-full").props('color=indigo flat bordered')

                ui.html('<div class="section-title">🏷️ Batch 参数</div>')
                product = ui.input("产品名", value="UI-Test").props("dense outlined").classes("w-full")
                tags = ui.input("标签（逗号分隔）", value="ui,test").props("dense outlined").classes("w-full")
                doc_type = ui.select(
                    options=[
                        "procedure", "feature", "command", "troubleshooting",
                        "alarm", "constraint", "checklist", "expert_note",
                        "project_note", "standard", "training", "reference", "other",
                    ],
                    value="procedure",
                    label="document_type",
                ).props("dense outlined").classes("w-full")
                pack_choices = _list_domain_packs()
                pack_default = "cloud_core_network" if "cloud_core_network" in pack_choices else pack_choices[0]
                domain_pack = ui.select(
                    options=pack_choices,
                    value=pack_default,
                    label="domain_pack",
                ).props("dense outlined").classes("w-full")

            # Right: prompt + start button
            with ui.column().classes("flex-1 min-w-[300px] gap-3 justify-between"):
                with ui.column().classes("gap-2"):
                    ui.html('<div class="section-title">✅ 准备开始</div>')
                    ui.markdown(
                        "上传文件并选择领域包后，点击下方按钮开始 9 阶段挖掘流水线。\n\n"
                        "运行期间：实时显示阶段进度 / 阶段产出 / 可终止 / 可点 stepper 切换查看任一已完成阶段的结果。"
                    ).classes("text-sm text-gray-600")
                start_btn = ui.button("▶  开始挖掘", on_click=lambda: on_start()).classes(
                    "btn-primary w-full"
                ).props("size=lg unelevated")

    # ---- RUN area ----
    run_card = ui.card().classes("section-card w-full")
    run_card.set_visibility(False)
    with run_card:
        # Top: status bar + actions
        with ui.row().classes("w-full items-center gap-3"):
            status_bar = ui.html(_status_bar_html(None, {}, "running", STATE.domain_pack)).classes("flex-1")
            cancel_btn = ui.button("▣  终止", on_click=lambda: on_cancel()).classes("btn-danger-outline").props("flat")
            restart_btn = ui.button("🔄  上传新批次重跑", on_click=lambda: on_restart()).classes("btn-primary").props("unelevated")
            restart_btn.set_visibility(False)

        # Stepper
        ui.html('<div class="section-title" style="margin-top:8px;">流程进度</div>')
        stepper_btns: dict[str, ui.element] = {}
        with ui.row().classes("w-full stepper-row"):
            for spec in STAGE_SPECS:
                if spec["id"] == "timeline":
                    continue
                sid = spec["id"]
                btn = ui.html(_stepper_btn_html(spec, STATE.stages, focused=False))
                btn.on("click", lambda _, sid=sid: on_stepper_click(sid))
                stepper_btns[sid] = btn

        # Focus row
        with ui.row().classes("w-full items-center justify-between"):
            focus_label = ui.markdown("### 当前焦点")
            with ui.row().classes("gap-2"):
                follow_btn = ui.button("📍  跟随最新", on_click=lambda: on_follow()).classes("btn-ghost").props("flat dense")
                timeline_btn = ui.button("⏱  事件时间线", on_click=lambda: on_timeline()).classes("btn-ghost").props("flat dense")

        # Stage panels container
        panels: dict[str, StagePanel] = {}
        with ui.column().classes("w-full gap-3"):
            for spec in STAGE_SPECS:
                panels[spec["id"]] = StagePanel(spec)

    # =====================================================================
    # Handlers (closures over UI element refs)
    # =====================================================================

    async def _on_file_upload(e):
        """ui.upload callback — save uploaded file to a temp staging area and remember its path.

        NiceGUI 3.x exposes the upload as e.file (FileUpload), with async .save()/.read().
        """
        target_dir = UPLOADS_ROOT / "_staging"
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / e.file.name
        await e.file.save(dst)
        STATE.files.append(dst)
        ui.notify(f"已上传 {e.file.name}", type="positive", position="bottom-right")

    def refresh_ui():
        """Synchronize UI components with STATE."""
        if STATE.phase == "ready":
            ready_card.set_visibility(True)
            run_card.set_visibility(False)
        else:
            ready_card.set_visibility(False)
            run_card.set_visibility(True)

        # Status bar
        run_row = None
        if STATE.input_path:
            snap = _query_latest_run(STATE.input_path)
            run_row = snap["run"] if snap else None
        status_bar.set_content(_status_bar_html(run_row, STATE.stages, STATE.phase, STATE.domain_pack))

        # Pull operator info once per refresh (used by segment / enrich / etc panels).
        operators = _extract_operators(run_row)

        # Stepper buttons
        for sid, btn in stepper_btns.items():
            spec = STAGE_BY_ID[sid]
            focused = (sid == STATE.focus_stage)
            btn.set_content(_stepper_btn_html(spec, STATE.stages, focused))

        # Focus label
        if STATE.focus_stage:
            spec = STAGE_BY_ID.get(STATE.focus_stage)
            if spec:
                st = STATE.stages.get(STATE.focus_stage, {}).get("status", "pending")
                glyph = _STATUS_GLYPH.get(st, "•")
                follow = " · 📍 自动跟随最新已完成阶段" if STATE.auto_follow else ""
                focus_label.set_content(f"### {glyph} 当前焦点 · {spec['label']}{follow}")
        else:
            focus_label.set_content("### 当前焦点")

        # Panel visibility + render
        for sid, panel in panels.items():
            if sid == STATE.focus_stage:
                panel.show()
                data = _safe_render(panel.spec, STATE.run_id)
                panel.render(data, STATE.stages, operators)
            else:
                panel.hide()

        # Buttons
        is_terminal = STATE.phase in ("done", "failed", "cancelled")
        cancel_btn.set_visibility(STATE.phase == "running")
        restart_btn.set_visibility(is_terminal)

    def on_start():
        if not STATE.files:
            ui.notify("请先上传文件", type="warning")
            return
        if not _RUN_LOCK.acquire(blocking=False):
            ui.notify("已经有挖掘任务在执行", type="warning")
            return

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = UPLOADS_ROOT / ts
        target.mkdir(parents=True, exist_ok=True)
        for src in STATE.files:
            try:
                shutil.copy(src, target / src.name)
            except Exception:
                traceback.print_exc()

        product_v = (product.value or "").strip()
        tags_v = (tags.value or "").strip()
        doc_type_v = (doc_type.value or "").strip()
        domain_pack_v = (domain_pack.value or "cloud_core_network").strip() or "cloud_core_network"
        llm_base_url, llm_bypass_proxy, embedding_api_key = _resolve_mining_llm_settings()

        def worker():
            logger.info("worker started: input=%s domain=%s", target, domain_pack_v)
            try:
                mining_run(
                    input_path=target,
                    batch_params=BatchParams(
                        default_source_type="folder_scan",
                        default_document_type=doc_type_v or None,
                        batch_scope=({"products": [product_v]} if product_v else {}),
                        tags=[t.strip() for t in tags_v.split(",") if t.strip()],
                    ),
                    domain_pack=domain_pack_v,
                    llm_base_url=llm_base_url,
                    llm_bypass_proxy=llm_bypass_proxy,
                    embedding_api_key=embedding_api_key,
                )
                logger.info("worker finished normally")
            except Exception as e:
                logger.exception("worker crashed: %s", e)
            finally:
                _RUN_LOCK.release()
                logger.info("worker released run lock")

        threading.Thread(target=worker, daemon=True).start()

        _LAST_LOGGED.clear()
        STATE.phase = "running"
        STATE.input_path = str(target)
        STATE.started_at_local = time.time()
        STATE.auto_follow = True
        STATE.focus_stage = PIPELINE_STAGE_IDS[0]
        STATE.run_id = None
        STATE.domain_pack = domain_pack_v
        STATE.stages = {sid: {"status": "pending", "kpi": "—", "duration_ms": None} for sid in PIPELINE_STAGE_IDS}
        refresh_ui()

    def poll_tick():
        if STATE.phase != "running":
            return
        input_path = STATE.input_path
        if not input_path:
            return
        snap = _query_latest_run(input_path)
        if snap is None:
            return
        run_row = snap["run"]
        STATE.run_id = run_row["id"]
        new_phase = _phase_from_run(run_row)
        STATE.phase = new_phase
        STATE.stages = _compute_pipeline_status(STATE.run_id, run_row)
        _log_progress(STATE.stages, new_phase)
        if STATE.auto_follow:
            STATE.focus_stage = _next_focus(STATE.focus_stage, STATE.stages, True)
        refresh_ui()

    def on_cancel():
        if not STATE.run_id:
            ui.notify("尚未拿到 run_id，请稍等再点", type="warning")
            return
        try:
            _cancel_run_in_db(STATE.run_id)
            ui.notify("已发送终止信号，worker 将在最近一次检查点退出", type="info")
        except Exception as e:
            ui.notify(f"发送终止失败：{e}", type="negative")
        cancel_btn.set_visibility(False)

    def on_stepper_click(sid: str):
        if sid not in PIPELINE_STAGE_IDS:
            return
        STATE.focus_stage = sid
        STATE.auto_follow = False
        refresh_ui()

    def on_follow():
        STATE.auto_follow = True
        if STATE.input_path:
            snap = _query_latest_run(STATE.input_path)
            if snap:
                STATE.stages = _compute_pipeline_status(snap["run"]["id"], snap["run"])
                STATE.focus_stage = _next_focus(None, STATE.stages, True)
        refresh_ui()

    def on_timeline():
        STATE.focus_stage = "timeline"
        STATE.auto_follow = False
        refresh_ui()

    def on_restart():
        STATE.phase = "ready"
        STATE.run_id = None
        STATE.input_path = None
        STATE.focus_stage = None
        STATE.auto_follow = True
        STATE.started_at_local = None
        STATE.domain_pack = None
        STATE.stages = {sid: {"status": "pending", "kpi": "—", "duration_ms": None} for sid in PIPELINE_STAGE_IDS}
        STATE.files = []
        upload.reset()
        refresh_ui()

    # ---- Polling timer (1Hz) ----
    ui.timer(1.0, poll_tick)

    # ---- Initial render ----
    refresh_ui()


# =====================================================================
# Main
# =====================================================================

def _shutdown():
    global _pg_pool
    if _pg_pool is not None:
        try:
            _pg_pool.close()
        except Exception:
            pass
        _pg_pool = None


app.on_shutdown(_shutdown)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="127.0.0.1",
        port=7860,
        title="Knowledge Mining Studio",
        show=False,
        reload=False,
        dark=False,
        favicon="🛠️",
    )
