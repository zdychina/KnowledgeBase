"""Live E2E test: real LLM calls through the full mining pipeline.

Requires llm_service running at localhost:8900 with valid provider API key.
Run: python -m pytest knowledge_mining/tests/test_v12_e2e_live.py -v -s
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from knowledge_mining.mining.jobs.run import run
from knowledge_mining.mining.db import AssetCoreDB, MiningRuntimeDB


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict so .get() works."""
    return dict(row)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


# Skip all tests if LLM service is not reachable
_llm_available = False
try:
    import httpx
    resp = httpx.get("http://localhost:8900/health", timeout=3)
    _llm_available = resp.status_code == 200
except Exception:
    pass

requires_llm = pytest.mark.skipif(not _llm_available, reason="LLM service not running on localhost:8900")


# Real APN document — enough structure to trigger all LLM templates
_APN_DOC = """# APN配置指南

## 概述

APN（Access Point Name）是移动通信网络中的重要参数，用于标识分组数据网络。终端设备通过APN来选择对应的网关和外部网络。

APN由两部分组成：
- 网络标识：标识外部网络
- 运营商标识：标识归属运营商

## 配置步骤

### 创建APN配置

使用 ADD APN 命令创建新的APN配置。命令格式如下：

```
ADD APN: APNNAME="cmnet", AUTHTYPE=PAP, USERNAME="user1", PASSWORD="pass123";
```

参数说明：
- APNNAME：接入点名称，必填参数
- AUTHTYPE：认证方式，支持PAP和CHAP
- USERNAME：认证用户名
- PASSWORD：认证密码

### 修改APN配置

使用 MOD APN 命令修改已有的APN配置：

```
MOD APN: APNNAME="cmnet", AUTHTYPE=CHAP;
```

### 查询APN配置

使用 LST APN 命令查询APN配置信息：

```
LST APN: APNNAME="cmnet";
```

查询结果包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| APNNAME | String | 接入点名称 |
| AUTHTYPE | Enum | 认证方式 |
| USERNAME | String | 认证用户名 |
| STATUS | Enum | 当前状态 |

## APN参数详解

APN配置涉及多个关键参数，这些参数直接影响终端的数据业务接入能力。正确配置APN是保障移动数据业务正常运行的前提条件。

认证方式PAP和CHAP的区别：
- PAP：密码明文传输，安全性较低
- CHAP：密码加密传输，安全性较高

## 常见问题排查

### 问题1：APN配置后无法接入

可能原因：
1. APNNAME拼写错误
2. 认证参数不匹配
3. 网关未配置对应APN

解决步骤：
1. 使用 LST APN 检查配置
2. 对比运营商提供的APN参数
3. 检查网关侧配置

### 问题2：CHAP认证失败

可能原因：
1. 共享密钥不一致
2. 用户名密码错误
3. 认证服务器不可达

解决步骤：
1. 确认共享密钥配置
2. 使用测试命令验证认证
3. 检查网络连通性
"""


def _create_test_docs(tmpdir: str) -> str:
    docs_dir = Path(tmpdir) / "docs"
    docs_dir.mkdir()
    (docs_dir / "apn_config.md").write_text(_APN_DOC, encoding="utf-8")
    return str(docs_dir)


def _dump_audit(result, asset_db_path, runtime_db_path):
    """Print full pipeline audit to stdout for the audit MD."""
    db = AssetCoreDB(asset_db_path)
    rdb = MiningRuntimeDB(runtime_db_path)
    db.open()
    rdb.open()

    print("\n" + "=" * 60)
    print("PIPELINE AUDIT")
    print("=" * 60)
    print(f"\nRun result: {json.dumps(result, indent=2, ensure_ascii=False)}")

    # Run details
    run_data = _row_to_dict(rdb.get_run(result["run_id"]))
    print(f"\n--- mining_runs ---")
    print(f"  status={run_data['status']}  committed={run_data['committed_count']}  failed={run_data['failed_count']}")

    # Stage events
    events = _rows_to_dicts(rdb.get_stage_events(result["run_id"]))
    print(f"\n--- mining_run_stage_events ({len(events)} events) ---")
    for e in events:
        print(f"  [{e['status']}] {e['stage']}: {e.get('output_summary', '')} ({e.get('duration_ms', '?')}ms)")

    # Segments
    if result.get("build_id"):
        snapshots = _rows_to_dicts(db.get_build_snapshots(result["build_id"]))
        snap_id = snapshots[0]["document_snapshot_id"] if snapshots else None
    else:
        snap_id = None

    if snap_id:
        segments = _rows_to_dicts(db.get_segments_by_snapshot(snap_id))
        print(f"\n--- asset_raw_segments ({len(segments)} segments) ---")
        for s in segments:
            print(f"  [{s['block_type']}/{s['semantic_role']}] idx={s['segment_index']} title={s.get('section_title', '')}")
            print(f"    text: {s['raw_text'][:80]}...")

        relations = _rows_to_dicts(db.get_relations_by_snapshot(snap_id))
        print(f"\n--- asset_raw_segment_relations ({len(relations)} relations) ---")
        rel_types = {}
        for r in relations:
            rel_types[r["relation_type"]] = rel_types.get(r["relation_type"], 0) + 1
        print(f"  Types: {json.dumps(rel_types, ensure_ascii=False)}")
        for r in relations[:10]:
            print(f"  {r['relation_type']}: {r['source_segment_id'][:8]}.. -> {r['target_segment_id'][:8]}..")

        units = _rows_to_dicts(db.get_retrieval_units_by_snapshot(snap_id))
        print(f"\n--- asset_retrieval_units ({len(units)} units) ---")
        unit_types = {}
        for u in units:
            unit_types[u["unit_type"]] = unit_types.get(u["unit_type"], 0) + 1
        print(f"  Types: {json.dumps(unit_types, ensure_ascii=False)}")

        # Show generated_question units with provenance
        gen_q = [u for u in units if u["unit_type"] == "generated_question"]
        print(f"\n  Generated Questions (LLM): {len(gen_q)}")
        for q in gen_q[:5]:
            llm_refs = json.loads(q.get("llm_result_refs_json") or "{}")
            src_refs = json.loads(q.get("source_refs_json") or "{}")
            print(f"    Q: {q['title']}")
            print(f"      llm_result_refs: {llm_refs}")
            print(f"      source_refs.raw_segment_ids: {src_refs.get('raw_segment_ids', 'MISSING')}")

        # Show raw_text units with LLM context
        ctx_units = [u for u in units if u["unit_type"] == "raw_text"
                     and "context_description" in (json.loads(u.get("metadata_json") or "{}"))]
        print(f"\n  Raw text units with LLM context: {len(ctx_units)}")
        for cu in ctx_units[:3]:
            meta = json.loads(cu.get("metadata_json") or "{}")
            llm_refs = json.loads(cu.get("llm_result_refs_json") or "{}")
            print(f"    {cu['title']}")
            print(f"      context: {meta.get('context_description', '')[:60]}")
            print(f"      llm_result_refs: {llm_refs}")

    db.close()
    rdb.close()
    print("=" * 60)


@requires_llm
class TestLiveLLMPipeline:
    """Full pipeline with real LLM service — all 4 templates exercised."""

    def test_full_llm_pipeline(self):
        """Full pipeline: parse -> segment -> LLM enrich -> relations -> LLM discourse -> LLM retrieval units -> build."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = _create_test_docs(tmpdir)
            asset_db_path = os.path.join(tmpdir, "asset_core.sqlite")
            runtime_db_path = os.path.join(tmpdir, "mining_runtime.sqlite")

            result = run(
                docs_dir,
                asset_core_db_path=asset_db_path,
                mining_runtime_db_path=runtime_db_path,
                llm_base_url="http://localhost:8900",
            )

            _dump_audit(result, asset_db_path, runtime_db_path)

            # === Run-level assertions ===
            assert result["status"] == "completed", f"Expected completed, got {result['status']}"
            assert result["committed_count"] >= 1
            assert result["build_id"] is not None

            db = AssetCoreDB(asset_db_path)
            db.open()

            snapshots = _rows_to_dicts(db.get_build_snapshots(result["build_id"]))
            snap_id = snapshots[0]["document_snapshot_id"]
            segments = _rows_to_dicts(db.get_segments_by_snapshot(snap_id))
            relations = _rows_to_dicts(db.get_relations_by_snapshot(snap_id))
            units = _rows_to_dicts(db.get_retrieval_units_by_snapshot(snap_id))

            # === Segment-level: LLM enricher should classify semantic_role ===
            non_heading = [s for s in segments if s["block_type"] != "heading"]
            roles = {s["semantic_role"] for s in non_heading}
            print(f"\nSemantic roles (LLM classified): {roles}")
            assert len(roles - {"unknown"}) > 0, (
                f"All segments have semantic_role='unknown' — LLM enricher not working. Roles: {roles}"
            )

            # === Relation-level: LLM discourse relations should exist ===
            discourse_types = {
                "evidences", "causes", "results_in", "backgrounds", "conditions",
                "summarizes", "justifies", "enables", "contrasts_with", "parallels", "sequences",
                "elaborates",
            }
            discourse_rels = [r for r in relations if r["relation_type"] in discourse_types]
            print(f"Discourse relations (LLM): {len(discourse_rels)}")
            # NOTE: discourse relations are best-effort — they may be 0 for short docs

            # === Retrieval unit-level: LLM question generation ===
            gen_q = [u for u in units if u["unit_type"] == "generated_question"]
            assert len(gen_q) > 0, "Should have LLM-generated questions"
            print(f"Generated questions: {len(gen_q)}")

            for q in gen_q:
                llm_refs = json.loads(q.get("llm_result_refs_json") or "{}")
                src_refs = json.loads(q.get("source_refs_json") or "{}")
                assert llm_refs.get("source") == "llm_runtime", f"Bad llm_result_refs: {llm_refs}"
                assert "task_id" in llm_refs, f"Missing task_id in llm_result_refs: {llm_refs}"
                assert "raw_segment_ids" in src_refs, f"Missing raw_segment_ids in source_refs: {src_refs}"

            # === Retrieval unit-level: LLM contextual retrieval (v1.3: folded into raw_text) ===
            ctx_enhanced = [u for u in raw_text_units
                           if "context_description" in (json.loads(u.get("metadata_json") or "{}"))]
            print(f"Raw text units with LLM context: {len(ctx_enhanced)}")
            assert len(ctx_enhanced) > 0, "Should have raw_text units enriched with LLM context"

            for cu in ctx_enhanced:
                llm_refs = json.loads(cu.get("llm_result_refs_json") or "{}")
                assert llm_refs.get("source") == "contextual_retrieval", f"Bad contextual refs: {llm_refs}"
                assert "task_id" in llm_refs, f"Missing task_id in contextual llm_result_refs: {llm_refs}"

            # === v1.3 density check ===
            total_units = len(units)
            density = total_units / len(segments)
            print(f"Unit density: {density:.1f}x ({total_units} units / {len(segments)} segments)")
            # No contextual_text units should exist (merged into raw_text)
            assert not any(u["unit_type"] == "contextual_text" for u in units), (
                "v1.3 should not produce contextual_text units — merged into raw_text"
            )

            # === All raw_text units should have raw_segment_ids in source_refs ===
            raw_text_units = [u for u in units if u["unit_type"] == "raw_text"]
            for u in raw_text_units:
                src_refs = json.loads(u.get("source_refs_json") or "{}")
                assert "raw_segment_ids" in src_refs, f"raw_text unit missing raw_segment_ids: {u['unit_key']}"

            # === Stage events ===
            rdb = MiningRuntimeDB(runtime_db_path)
            rdb.open()
            events = _rows_to_dicts(rdb.get_stage_events(result["run_id"]))
            stages = {e["stage"] for e in events}
            assert "segment" in stages
            assert "build_relations" in stages
            assert "build_retrieval_units" in stages
            assert "select_snapshot" in stages
            assert "assemble_build" in stages
            rdb.close()

            db.close()

    def test_llm_enricher_classifies_roles(self):
        """Verify LLM enricher assigns semantic_role (not all 'unknown')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = _create_test_docs(tmpdir)
            result = run(
                docs_dir,
                asset_core_db_path=os.path.join(tmpdir, "asset_core.sqlite"),
                mining_runtime_db_path=os.path.join(tmpdir, "mining_runtime.sqlite"),
                llm_base_url="http://localhost:8900",
            )

            db = AssetCoreDB(os.path.join(tmpdir, "asset_core.sqlite"))
            db.open()
            snapshots = _rows_to_dicts(db.get_build_snapshots(result["build_id"]))
            snap_id = snapshots[0]["document_snapshot_id"]
            segments = _rows_to_dicts(db.get_segments_by_snapshot(snap_id))

            non_heading = [s for s in segments if s["block_type"] != "heading"]
            roles = {s["semantic_role"] for s in non_heading}
            db.close()

            # LLM should assign roles like concept, parameter, procedure_step, etc.
            classified = roles - {"unknown"}
            assert len(classified) >= 2, (
                f"LLM enricher should assign diverse roles, got: {roles}"
            )

    def test_llm_question_generation_with_task_ids(self):
        """Verify question generation produces questions with task_id provenance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = _create_test_docs(tmpdir)
            result = run(
                docs_dir,
                asset_core_db_path=os.path.join(tmpdir, "asset_core.sqlite"),
                mining_runtime_db_path=os.path.join(tmpdir, "mining_runtime.sqlite"),
                llm_base_url="http://localhost:8900",
            )

            db = AssetCoreDB(os.path.join(tmpdir, "asset_core.sqlite"))
            db.open()
            snapshots = _rows_to_dicts(db.get_build_snapshots(result["build_id"]))
            snap_id = snapshots[0]["document_snapshot_id"]
            units = _rows_to_dicts(db.get_retrieval_units_by_snapshot(snap_id))
            db.close()

            gen_q = [u for u in units if u["unit_type"] == "generated_question"]
            assert len(gen_q) > 0

            # Every question should have task_id in llm_result_refs_json
            for q in gen_q:
                refs = json.loads(q["llm_result_refs_json"])
                assert "task_id" in refs, f"Question missing task_id: {refs}"

            # Questions should be real Chinese questions (not template output)
            for q in gen_q[:3]:
                text = q["text"]
                assert len(text) > 5, f"Question too short: {text}"

    def test_llm_contextualizer_enhances_units(self):
        """Verify contextualizer enriches raw_text units with LLM context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = _create_test_docs(tmpdir)
            result = run(
                docs_dir,
                asset_core_db_path=os.path.join(tmpdir, "asset_core.sqlite"),
                mining_runtime_db_path=os.path.join(tmpdir, "mining_runtime.sqlite"),
                llm_base_url="http://localhost:8900",
            )

            db = AssetCoreDB(os.path.join(tmpdir, "asset_core.sqlite"))
            db.open()
            snapshots = _rows_to_dicts(db.get_build_snapshots(result["build_id"]))
            snap_id = snapshots[0]["document_snapshot_id"]
            units = _rows_to_dicts(db.get_retrieval_units_by_snapshot(snap_id))
            db.close()

            # v1.3: LLM context is in raw_text units, not separate contextual_text units
            ctx_units = [u for u in units if u["unit_type"] == "raw_text"
                         and "context_description" in json.loads(u.get("metadata_json") or "{}")]
            assert len(ctx_units) > 0, "Should have raw_text units enriched with LLM context"

            for cu in ctx_units:
                refs = json.loads(cu["llm_result_refs_json"])
                assert refs.get("source") == "contextual_retrieval"
                assert "task_id" in refs, f"Missing task_id: {refs}"

                meta = json.loads(cu["metadata_json"])
                assert len(meta.get("context_description", "")) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
