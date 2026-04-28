-- =============================================================================
-- agent_serving_java — PostgreSQL 初始化脚本
-- 基于 databases/asset_core/schemas/001_asset_core.sql
-- 适用版本：PostgreSQL 14+
-- 注意：本脚本不使用外键约束，数据完整性由应用层保证
-- 中文全文检索可选依赖 pg_jieba（不安装时退回 simple 字典）
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 中文分词扩展（可选，需提前安装 pg_jieba 插件）
-- -----------------------------------------------------------------------------
-- CREATE EXTENSION IF NOT EXISTS pg_jieba;


-- =============================================================================
-- 1. 来源批次
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_source_batches (
    id            TEXT        NOT NULL,
    batch_code    TEXT        NOT NULL,
    source_type   TEXT        NOT NULL,   -- manual_upload | folder_scan | api_import | official_vendor | expert_authored | user_import | synthetic_coldstart | other
    description   TEXT,
    created_by    TEXT,
    created_at    TEXT        NOT NULL,
    metadata_json TEXT        NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_source_batches    PRIMARY KEY (id),
    CONSTRAINT uq_asset_source_batches_code UNIQUE (batch_code)
);


-- =============================================================================
-- 2. 文档与快照
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_documents (
    id            TEXT NOT NULL,
    document_key  TEXT NOT NULL,
    document_name TEXT,
    document_type TEXT,                   -- markdown | html | pdf | ...
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    CONSTRAINT pk_asset_documents   PRIMARY KEY (id),
    CONSTRAINT uq_asset_documents_key UNIQUE (document_key)
);

-- 可被多文档共享的内容快照（复用边界为 normalized_content_hash）
CREATE TABLE IF NOT EXISTS asset_document_snapshots (
    id                      TEXT NOT NULL,
    normalized_content_hash TEXT NOT NULL,
    raw_content_hash        TEXT NOT NULL,
    mime_type               TEXT NOT NULL,   -- text/markdown | text/plain | text/html | application/pdf | ...
    title                   TEXT,
    scope_json              TEXT NOT NULL DEFAULT '{}',
    tags_json               TEXT NOT NULL DEFAULT '[]',
    parser_profile_json     TEXT NOT NULL DEFAULT '{}',
    metadata_json           TEXT NOT NULL DEFAULT '{}',
    created_at              TEXT NOT NULL,
    CONSTRAINT pk_asset_document_snapshots       PRIMARY KEY (id),
    CONSTRAINT uq_asset_document_snapshots_hash  UNIQUE (normalized_content_hash)
);

-- 文档-快照关联（含文档级 scope / tags / 路径）
CREATE TABLE IF NOT EXISTS asset_document_snapshot_links (
    id                   TEXT NOT NULL,
    document_id          TEXT NOT NULL,
    document_snapshot_id TEXT NOT NULL,
    source_batch_id      TEXT,
    relative_path        TEXT NOT NULL,
    source_uri           TEXT NOT NULL,
    title                TEXT,
    scope_json           TEXT NOT NULL DEFAULT '{}',
    tags_json            TEXT NOT NULL DEFAULT '[]',
    linked_at            TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_document_snapshot_links PRIMARY KEY (id)
);


-- =============================================================================
-- 3. 原始片段与关系
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_raw_segments (
    id                   TEXT    NOT NULL,
    document_snapshot_id TEXT    NOT NULL,
    segment_key          TEXT    NOT NULL,
    segment_index        INTEGER NOT NULL,
    section_path         TEXT    NOT NULL DEFAULT '[]',
    section_title        TEXT,
    block_type           TEXT    NOT NULL DEFAULT 'unknown',   -- paragraph | heading | table | list | code | blockquote | html_table | raw_html | unknown
    semantic_role        TEXT    NOT NULL DEFAULT 'unknown',   -- concept | parameter | example | note | procedure_step | troubleshooting_step | constraint | alarm | checklist | unknown
    raw_text             TEXT    NOT NULL,
    normalized_text      TEXT    NOT NULL,
    content_hash         TEXT    NOT NULL,
    normalized_hash      TEXT    NOT NULL,
    token_count          INTEGER,
    structure_json       TEXT    NOT NULL DEFAULT '{}',
    source_offsets_json  TEXT    NOT NULL DEFAULT '{}',
    entity_refs_json     TEXT    NOT NULL DEFAULT '[]',
    metadata_json        TEXT    NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_raw_segments         PRIMARY KEY (id),
    CONSTRAINT uq_asset_raw_segments_key     UNIQUE (document_snapshot_id, segment_key)
);

-- 片段间结构关系（构成知识图谱边）
CREATE TABLE IF NOT EXISTS asset_raw_segment_relations (
    id                   TEXT             NOT NULL,
    document_snapshot_id TEXT             NOT NULL,
    source_segment_id    TEXT             NOT NULL,
    target_segment_id    TEXT             NOT NULL,
    relation_type        TEXT             NOT NULL,   -- previous | next | same_section | same_parent_section | section_header_of | references | elaborates | condition | contrast | other
    weight               DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    confidence           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    distance             INTEGER,
    metadata_json        TEXT             NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_raw_segment_relations    PRIMARY KEY (id),
    CONSTRAINT uq_asset_raw_segment_relations    UNIQUE (source_segment_id, target_segment_id, relation_type)
);


-- =============================================================================
-- 4. 检索单元（Serving 主检索对象）
-- =============================================================================

-- 一个 raw_segment 可衍生多个 retrieval_unit（如原文单元、上下文增强单元）
CREATE TABLE IF NOT EXISTS asset_retrieval_units (
    id                   TEXT             NOT NULL,
    document_snapshot_id TEXT             NOT NULL,
    unit_key             TEXT             NOT NULL,
    unit_type            TEXT             NOT NULL,   -- raw_text | contextual_text | ...
    target_type          TEXT             NOT NULL,
    target_ref_json      TEXT             NOT NULL DEFAULT '{}',
    title                TEXT,
    text                 TEXT             NOT NULL,   -- 原始正文，返回给 LLM
    search_text          TEXT             NOT NULL,   -- FTS 索引使用的文本（可含上下文增强内容）
    block_type           TEXT             NOT NULL DEFAULT 'unknown',
    semantic_role        TEXT             NOT NULL DEFAULT 'unknown',
    facets_json          TEXT             NOT NULL DEFAULT '{}',   -- {"product":"UDG","version":"V300R001C00"}
    entity_refs_json     TEXT             NOT NULL DEFAULT '[]',
    source_refs_json     TEXT             NOT NULL DEFAULT '{}',
    llm_result_refs_json TEXT             NOT NULL DEFAULT '{}',
    weight               DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source_segment_id    TEXT,                                     -- 来源 raw_segment ID（去重和溯源用）
    created_at           TEXT             NOT NULL,
    metadata_json        TEXT             NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_retrieval_units      PRIMARY KEY (id),
    CONSTRAINT uq_asset_retrieval_units_key  UNIQUE (document_snapshot_id, unit_key)
);

-- 向量嵌入（预留，供向量检索扩展使用）
CREATE TABLE IF NOT EXISTS asset_retrieval_embeddings (
    id                 TEXT    NOT NULL,
    retrieval_unit_id  TEXT    NOT NULL,
    embedding_model    TEXT    NOT NULL,
    embedding_provider TEXT    NOT NULL,
    text_kind          TEXT    NOT NULL,
    embedding_dim      INTEGER NOT NULL,
    embedding_vector   TEXT    NOT NULL,   -- 序列化向量，格式由实现决定
    content_hash       TEXT    NOT NULL,
    created_at         TEXT    NOT NULL,
    metadata_json      TEXT    NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_retrieval_embeddings PRIMARY KEY (id)
);


-- =============================================================================
-- 5. 构建与发布版本
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_builds (
    id              TEXT NOT NULL,
    build_code      TEXT NOT NULL,
    status          TEXT NOT NULL,   -- queued | running | succeeded | failed | cancelled
    build_mode      TEXT NOT NULL,
    source_batch_id TEXT,
    parent_build_id TEXT,
    mining_run_id   TEXT,
    summary_json    TEXT NOT NULL DEFAULT '{}',
    validation_json TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    finished_at     TEXT,
    CONSTRAINT pk_asset_builds       PRIMARY KEY (id),
    CONSTRAINT uq_asset_builds_code  UNIQUE (build_code)
);

-- Build 中每个文档选用的快照清单
CREATE TABLE IF NOT EXISTS asset_build_document_snapshots (
    build_id             TEXT NOT NULL,
    document_id          TEXT NOT NULL,
    document_snapshot_id TEXT NOT NULL,
    selection_status     TEXT NOT NULL,   -- active | excluded
    reason               TEXT NOT NULL,
    metadata_json        TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_build_document_snapshots PRIMARY KEY (build_id, document_id)
);

-- 发布版本（控制哪个 build 对哪个 channel 可见）
CREATE TABLE IF NOT EXISTS asset_publish_releases (
    id                  TEXT NOT NULL,
    release_code        TEXT NOT NULL,
    build_id            TEXT NOT NULL,
    channel             TEXT NOT NULL,
    status              TEXT NOT NULL,   -- active | inactive | archived
    previous_release_id TEXT,
    released_by         TEXT,
    release_notes       TEXT,
    activated_at        TEXT,
    deactivated_at      TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT pk_asset_publish_releases       PRIMARY KEY (id),
    CONSTRAINT uq_asset_publish_releases_code  UNIQUE (release_code)
);


-- =============================================================================
-- 6. 索引
-- =============================================================================

-- ---- asset_documents ----
CREATE INDEX IF NOT EXISTS idx_asset_documents_type
    ON asset_documents (document_type);

-- ---- asset_document_snapshots ----
CREATE INDEX IF NOT EXISTS idx_asset_document_snapshots_raw_hash
    ON asset_document_snapshots (raw_content_hash);

-- ---- asset_document_snapshot_links ----
CREATE INDEX IF NOT EXISTS idx_asset_dsl_document
    ON asset_document_snapshot_links (document_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_dsl_snapshot
    ON asset_document_snapshot_links (document_snapshot_id, linked_at);

CREATE INDEX IF NOT EXISTS idx_asset_dsl_batch
    ON asset_document_snapshot_links (source_batch_id);

-- ---- asset_raw_segments ----
CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_snapshot
    ON asset_raw_segments (document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_raw_segments_normalized_hash
    ON asset_raw_segments (normalized_hash);

-- ---- asset_raw_segment_relations ----
-- selectRelationsForSegments / selectNeighbors（双向边查询）
CREATE INDEX IF NOT EXISTS idx_asset_rsr_snapshot_type
    ON asset_raw_segment_relations (document_snapshot_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_asset_rsr_source
    ON asset_raw_segment_relations (source_segment_id);

CREATE INDEX IF NOT EXISTS idx_asset_rsr_target
    ON asset_raw_segment_relations (target_segment_id);

-- ---- asset_retrieval_units ----
CREATE INDEX IF NOT EXISTS idx_asset_ru_snapshot
    ON asset_retrieval_units (document_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_asset_ru_block_role
    ON asset_retrieval_units (block_type, semantic_role);

CREATE INDEX IF NOT EXISTS idx_asset_ru_source_segment
    ON asset_retrieval_units (source_segment_id);

-- FTS GIN 索引（核心检索索引，对应 SQLite 的 asset_retrieval_units_fts）
-- 使用 'simple' 字典（语言无关，适合英文命令名和数字）
-- 安装 pg_jieba 后将 'simple' 替换为 'jieba' 并重建此索引以支持中文分词
CREATE INDEX IF NOT EXISTS idx_asset_ru_fts
    ON asset_retrieval_units
    USING GIN (to_tsvector('simple', COALESCE(search_text, '')));

-- ---- asset_retrieval_embeddings ----
CREATE INDEX IF NOT EXISTS idx_asset_retrieval_embeddings_unit
    ON asset_retrieval_embeddings (retrieval_unit_id);

-- ---- asset_builds ----
CREATE INDEX IF NOT EXISTS idx_asset_builds_status
    ON asset_builds (status, created_at);

-- ---- asset_build_document_snapshots ----
-- resolveActiveScope: WHERE build_id=? AND selection_status='active'
CREATE INDEX IF NOT EXISTS idx_asset_bds_build_status
    ON asset_build_document_snapshots (build_id, selection_status);

CREATE INDEX IF NOT EXISTS idx_asset_bds_snapshot
    ON asset_build_document_snapshots (document_snapshot_id);

-- ---- asset_publish_releases ----
-- resolveActiveScope: WHERE channel=? AND status='active'
CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_channel_status
    ON asset_publish_releases (channel, status);

CREATE INDEX IF NOT EXISTS idx_asset_publish_releases_build
    ON asset_publish_releases (build_id);


-- =============================================================================
-- 7. 查询日志
-- =============================================================================

-- 记录每次 /api/v1/search 请求的查询内容、解析结果和响应摘要
CREATE TABLE IF NOT EXISTS serving_query_logs (
    id                  TEXT    NOT NULL,

    -- 原始输入
    query_text          TEXT    NOT NULL,             -- SearchRequest.query 原始文本
    channel             TEXT    NOT NULL,             -- 查询的知识库频道，当前固定 'default'

    -- 查询解析结果（来自 NormalizedQuery）
    intent              TEXT,                         -- 识别出的意图：command_usage | troubleshoot | concept_lookup | procedure | general
    normalizer_source   TEXT,                         -- 归一化来源：'llm' | 'rules'
    keywords_json       TEXT    NOT NULL DEFAULT '[]', -- 关键词列表 JSON 数组
    entities_json       TEXT    NOT NULL DEFAULT '[]', -- 识别出的实体 JSON 数组
    scope_json          TEXT    NOT NULL DEFAULT '{}', -- 范围约束 JSON 对象

    -- 命中的知识库版本（来自 ActiveScope）
    release_id          TEXT,                         -- asset_publish_releases.id
    build_id            TEXT,                         -- asset_builds.id
    snapshot_count      INTEGER,                      -- 本次查询覆盖的快照数量

    -- 响应摘要（来自 ContextPack）
    result_item_count   INTEGER,                      -- 返回的 items 总数（seed + context + support）
    result_seed_count   INTEGER,                      -- 其中 seed 类型数量
    result_has_result   TEXT    NOT NULL DEFAULT 'true', -- 'true' | 'false'，是否有召回结果
    result_issues_json  TEXT    NOT NULL DEFAULT '[]', -- issues 列表 JSON 数组

    -- 返回结果详情（来自 ContextPack，不存正文以控制行大小）
    -- 每条 item：{id, kind, role, score, block_type, semantic_role, source_id, relation_to_seed}
    result_items_json       TEXT    NOT NULL DEFAULT '[]',
    -- 每条 source：{id, document_key, title, relative_path}
    result_sources_json     TEXT    NOT NULL DEFAULT '[]',
    -- 每条 relation：{id, from_id, to_id, relation_type, distance}
    result_relations_json   TEXT    NOT NULL DEFAULT '[]'

    -- 性能
    duration_ms         INTEGER,                      -- 请求总耗时（毫秒）

    -- 元数据
    queried_at          TEXT    NOT NULL,             -- 查询时间，ISO 8601
    metadata_json       TEXT    NOT NULL DEFAULT '{}',

    CONSTRAINT pk_serving_query_logs PRIMARY KEY (id)
);

-- ---- serving_query_logs ----
-- 按时间范围查询日志
CREATE INDEX IF NOT EXISTS idx_sql_queried_at
    ON serving_query_logs (queried_at);

-- 按意图统计分布
CREATE INDEX IF NOT EXISTS idx_sql_intent
    ON serving_query_logs (intent, queried_at);

-- 按频道 + 版本过滤
CREATE INDEX IF NOT EXISTS idx_sql_channel_release
    ON serving_query_logs (channel, release_id);

-- 快速筛选无结果查询
CREATE INDEX IF NOT EXISTS idx_sql_has_result
    ON serving_query_logs (result_has_result, queried_at);


-- =============================================================================
-- 8. 示例种子数据（开发/测试用，生产环境删除）
-- =============================================================================

/*
INSERT INTO asset_documents (id, document_key, document_name, document_type, created_at) VALUES
    ('doc-001', 'amf-cli-reference-v300r001c00', 'AMF命令行参考', 'markdown', '2026-04-27T00:00:00Z');

INSERT INTO asset_document_snapshots
    (id, normalized_content_hash, raw_content_hash, mime_type, title, scope_json, created_at) VALUES
    ('snap-001', 'hash-norm-001', 'hash-raw-001', 'text/markdown',
     'AMF命令行参考 V300R001C00',
     '{"product":"UDG","version":"V300R001C00","network_element":"AMF"}',
     '2026-04-27T00:00:00Z');

INSERT INTO asset_document_snapshot_links
    (id, document_id, document_snapshot_id, relative_path, source_uri, linked_at) VALUES
    ('dsl-001', 'doc-001', 'snap-001',
     'amf/cli/amf-cli-reference.md', 'file://amf-cli-reference.md',
     '2026-04-27T00:00:00Z');

INSERT INTO asset_builds
    (id, build_code, status, build_mode, created_at) VALUES
    ('build-001', 'BUILD-20260427-001', 'succeeded', 'full', '2026-04-27T00:00:00Z');

INSERT INTO asset_build_document_snapshots
    (build_id, document_id, document_snapshot_id, selection_status, reason) VALUES
    ('build-001', 'doc-001', 'snap-001', 'active', 'initial build');

INSERT INTO asset_publish_releases
    (id, release_code, build_id, channel, status, activated_at) VALUES
    ('release-001', 'RELEASE-20260427-001', 'build-001', 'default', 'active',
     '2026-04-27T00:00:00Z');

INSERT INTO asset_raw_segments
    (id, document_snapshot_id, segment_key, segment_index,
     block_type, semantic_role, raw_text, normalized_text,
     content_hash, normalized_hash) VALUES
    ('seg-001', 'snap-001', 'seg-001', 1,
     'paragraph', 'parameter',
     'ADD USER_GROUP命令用于在AMF上新增用户组。必选参数：group-name，取值范围1~32个字符。',
     'add user_group命令用于在amf上新增用户组。必选参数：group-name，取值范围1~32个字符。',
     'chash-001', 'nhash-001');

INSERT INTO asset_retrieval_units
    (id, document_snapshot_id, unit_key, unit_type, target_type,
     text, search_text, block_type, semantic_role,
     facets_json, source_segment_id, created_at) VALUES
    ('ru-001', 'snap-001', 'ru-001', 'raw_text', 'segment',
     'ADD USER_GROUP命令用于在AMF上新增用户组。必选参数：group-name，取值范围1~32个字符。',
     'ADD USER_GROUP命令用于在AMF上新增用户组。必选参数：group-name，取值范围1~32个字符。',
     'paragraph', 'parameter',
     '{"product":"UDG","version":"V300R001C00","network_element":"AMF"}',
     'seg-001', '2026-04-27T00:00:00Z');
*/
