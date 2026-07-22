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
    # serving_runtime（检索服务运行态）——见 OPTIONAL_TABLES
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
    # ontology（本体概念层）——须排在 asset_core 之后：
    # ontology_evidence_nodes / asset_segment_entity_mentions 的 FK
    # 指向 asset_document_snapshots / asset_raw_segments。
    "ontology_versions",
    "ontology_node_types",
    "ontology_relation_types",
    "ontology_entities",
    "ontology_entity_relations",
    "ontology_alias_dictionary",
    "ontology_evidence_nodes",
    "asset_segment_entity_mentions",
    "ontology_candidates",
    # operator（检索范式）——见 OPTIONAL_TABLES
    "operator_paradigm",
    "operator_paradigm_version",
]

# 可能不存在的表：全部由 agent_serving_java 自己创建，Python 侧 reset_db.py 不建。
#   - operator_paradigm*        ParadigmSchemaInitializer，启动时建在非路由的 defaultDataSource 上
#   - serving_query_logs/cache  ServingRuntimeSchemaInitializer，启动时建默认库、
#                               并在 DomainPoolManager 每次建池时建到该域自己的库上
# 因此 Java 从未启动过的库里没有这几张表，export/import 必须容忍其缺失，
# 否则会在纯挖掘库上直接报错。
OPTIONAL_TABLES = {
    "operator_paradigm",
    "operator_paradigm_version",
    "serving_query_logs",
    "serving_query_cache",
}
