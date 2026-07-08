-- CoreMasterKB Ontology Concept Layer Schema v1.0 - PostgreSQL
--
-- 本体（ontology）概念层表组。对应实现设计 L2 §3。
-- 分四组：规则层(TBox) / 事实层(ABox) / 出处(provenance) / 进化轨(candidates)。
-- 依赖 asset_core 的 asset_document_snapshots / asset_raw_segments（须先于本文件建表）。
-- 全部 idempotent：CREATE ... IF NOT EXISTS。

-- =============================================================================
-- 1) 本体规则层（domain-scoped，慢变，人审写入）
-- =============================================================================

-- 本体版本快照：抽取只认当前 active 那版
CREATE TABLE IF NOT EXISTS ontology_versions (
    id              TEXT PRIMARY KEY,
    domain_id       TEXT NOT NULL,
    version_no      INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'active', 'superseded')
    ),
    source          TEXT NOT NULL,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    note            TEXT,
    UNIQUE (domain_id, version_no)
);

-- 同一 domain 同时只允许一个 active 版本
CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_versions_domain_active
    ON ontology_versions(domain_id)
    WHERE status = 'active';

-- 节点类型（点规则），MVP 全是 layer='concept'
CREATE TABLE IF NOT EXISTS ontology_node_types (
    id                  TEXT PRIMARY KEY,
    ontology_version_id TEXT NOT NULL REFERENCES ontology_versions(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    layer               TEXT NOT NULL DEFAULT 'concept',
    is_strong           BOOLEAN NOT NULL DEFAULT false,
    definition          TEXT,
    examples_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (ontology_version_id, name)
);

-- 关系类型（边规则），含 head/tail 类型约束
CREATE TABLE IF NOT EXISTS ontology_relation_types (
    id                  TEXT PRIMARY KEY,
    ontology_version_id TEXT NOT NULL REFERENCES ontology_versions(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    layer               TEXT NOT NULL DEFAULT 'concept',
    is_directed         BOOLEAN NOT NULL DEFAULT true,
    inverse_name        TEXT,
    allowed_pairs_json  JSONB NOT NULL DEFAULT '[]'::jsonb,
    definition          TEXT,
    UNIQUE (ontology_version_id, name)
);

-- =============================================================================
-- 2) 本体事实层（domain-scoped，快变，机器抽 + 人审消歧）
-- =============================================================================

-- canonical 对象（消歧后的领域实体档案，一个真实东西只一条）
CREATE TABLE IF NOT EXISTS ontology_entities (
    id                        TEXT PRIMARY KEY,
    domain_id                 TEXT NOT NULL,
    canonical_name            TEXT NOT NULL,
    node_type                 TEXT NOT NULL,
    layer                     TEXT NOT NULL DEFAULT 'concept',
    aliases_json              JSONB NOT NULL DEFAULT '[]'::jsonb,
    attributes_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_ontology_version_id TEXT REFERENCES ontology_versions(id) ON DELETE SET NULL,
    mention_count             INTEGER NOT NULL DEFAULT 0,
    document_count            INTEGER NOT NULL DEFAULT 0,
    UNIQUE (domain_id, node_type, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_ontology_entities_domain_type
    ON ontology_entities(domain_id, node_type);

-- 事实边（领域级，出处强制非空）
CREATE TABLE IF NOT EXISTS ontology_entity_relations (
    id                  TEXT PRIMARY KEY,
    domain_id           TEXT NOT NULL,
    head_entity_id      TEXT NOT NULL REFERENCES ontology_entities(id) ON DELETE CASCADE,
    tail_entity_id      TEXT NOT NULL REFERENCES ontology_entities(id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL,
    confidence          REAL NOT NULL DEFAULT 0.7,
    source_refs_json    JSONB NOT NULL,
    ontology_version_id TEXT REFERENCES ontology_versions(id) ON DELETE SET NULL,
    has_conflict        BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT chk_der_source_refs CHECK (jsonb_array_length(source_refs_json) > 0),
    CONSTRAINT chk_der_no_self CHECK (head_entity_id <> tail_entity_id),
    UNIQUE (domain_id, head_entity_id, tail_entity_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_der_head
    ON ontology_entity_relations(head_entity_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_der_tail
    ON ontology_entity_relations(tail_entity_id, relation_type);

-- 别名词典（消歧产出，可种子自本体种子文件）
CREATE TABLE IF NOT EXISTS ontology_alias_dictionary (
    id               TEXT PRIMARY KEY,
    domain_id        TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    canonical_name   TEXT NOT NULL,
    node_type        TEXT,
    source           TEXT,
    UNIQUE (domain_id, alias_normalized)
);

-- =============================================================================
-- 3) 出处（provenance，强约束的核心）
-- =============================================================================

-- 任一对象/边/mention → 片段 → 文档快照 的可追溯链
CREATE TABLE IF NOT EXISTS ontology_evidence_nodes (
    id                   TEXT PRIMARY KEY,
    domain_id            TEXT NOT NULL,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    segment_id           TEXT NOT NULL REFERENCES asset_raw_segments(id) ON DELETE CASCADE,
    quote                TEXT,
    target_kind          TEXT NOT NULL CHECK (target_kind IN ('entity', 'relation', 'mention')),
    target_id            TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ev_target
    ON ontology_evidence_nodes(target_kind, target_id);

CREATE INDEX IF NOT EXISTS idx_ev_segment
    ON ontology_evidence_nodes(segment_id);

-- =============================================================================
-- 4) 文章级 mention（doc-scoped，= PRD EPIC-3 的 asset_entity_mentions 扩展）
-- =============================================================================

CREATE TABLE IF NOT EXISTS asset_segment_entity_mentions (
    id                   TEXT PRIMARY KEY,
    document_snapshot_id TEXT NOT NULL REFERENCES asset_document_snapshots(id) ON DELETE CASCADE,
    segment_id           TEXT NOT NULL REFERENCES asset_raw_segments(id) ON DELETE CASCADE,
    node_type            TEXT NOT NULL,
    mention_text         TEXT NOT NULL,
    canonical_name       TEXT,
    resolved_entity_id   TEXT REFERENCES ontology_entities(id) ON DELETE SET NULL,
    resolve_status       TEXT NOT NULL DEFAULT 'pending' CHECK (
        resolve_status IN ('auto', 'human', 'pending', 'rejected')
    ),
    confidence           REAL DEFAULT 1.0,
    metadata_json        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_mention_canon
    ON asset_segment_entity_mentions(canonical_name, node_type);

CREATE INDEX IF NOT EXISTS idx_mention_seg
    ON asset_segment_entity_mentions(segment_id);

CREATE INDEX IF NOT EXISTS idx_mention_status
    ON asset_segment_entity_mentions(resolve_status);

-- =============================================================================
-- 5) 候选本体（进化轨，逃生口/归纳产出）
-- =============================================================================

CREATE TABLE IF NOT EXISTS ontology_candidates (
    id              TEXT PRIMARY KEY,
    domain_id       TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('node_type', 'relation_type')),
    layer           TEXT NOT NULL DEFAULT 'concept',
    proposed_name   TEXT NOT NULL,
    payload_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    source          TEXT NOT NULL,
    evidence_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
    score           REAL,
    status          TEXT NOT NULL DEFAULT 'proposed' CHECK (
        status IN ('proposed', 'queued', 'accepted', 'rejected')
    ),
    review_note     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cand_status
    ON ontology_candidates(domain_id, status);

-- =============================================================================
-- 6) 复用现有表：mining_runs 加两列（断点续跑用）
--    与 003_mining_runtime_domain.sql 同风格，ADD COLUMN IF NOT EXISTS 幂等。
-- =============================================================================

ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS subloop_stage TEXT;
ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS ontology_version_id TEXT;
