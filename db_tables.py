"""
共享的数据库表定义，供 export_db.py / import_db.py / reset_db.py 使用。

导出顺序：父表先导出，导入时按此顺序（满足外键约束）。
TRUNCATE 顺序：反序（先清子表，再清父表）。
"""
from __future__ import annotations

EXPORT_TABLES = [
    # agent_llm_runtime
    "agent_llm_prompt_templates",
    "agent_llm_tasks",
    "agent_llm_requests",
    "agent_llm_attempts",
    "agent_llm_results",
    "agent_llm_events",
    "agent_llm_model_calls",
    # mining_runtime
    "mining_runs",
    "mining_run_documents",
    "mining_run_stage_events",
    # serving_runtime
    "serving_query_logs",
    "serving_query_cache",
    # asset_core
    "asset_source_batches",
    "asset_documents",
    "asset_document_snapshots",
    "asset_document_snapshot_links",
    "asset_builds",
    "asset_publish_releases",
    "asset_build_document_snapshots",
    "asset_raw_segments",
    "asset_raw_segment_relations",
    "asset_retrieval_units",
    "asset_retrieval_embeddings",
]
