# Knowledge Mining FZL — 架构文档

> 离线知识挖掘引擎：原始文档 → 结构化知识资产
> 版本：v3.0（PostgreSQL 后端）| 数据库：asset_core + mining_runtime (PostgreSQL) | Pipeline：9 阶段 | API：FastAPI v3.0.0

## 1. 系统定位

`knowledge_mining_fzl` 将原始技术文档（Markdown、纯文本等）经过 9 阶段 Pipeline 转化为结构化知识资产，存入 PostgreSQL，供 `agent_serving_fzl` 在线检索。

**核心价值：** 把非结构化技术文档变成 Agent 可直接消费的结构化知识。

**与其他版本的关系：**
- `knowledge_mining/` — SQLite 版本（已归档）
- `knowledge_mining_fzl/` — PostgreSQL 版本（当前主线，本目录）
- `knowledge_mining_zym/` — 另一分支实验

## 2. 架构设计

### 2.1 三层模块架构

```
contracts/  ←  infra/  ←  stages/  ←  pipeline.py  ←  jobs/run.py
   │              │           │
   │              │           └── 每个 stage 实现 contracts 中的 Protocol
   │              └── 使用 contracts 中的 models
   └── 零外部依赖（纯 dataclass + Protocol）
```

### 2.2 目录结构

```
knowledge_mining_fzl/mining/
├── contracts/                    # Layer 1: 纯数据模型 + Protocol 接口
│   ├── models.py                 # 12 个 frozen dataclass，对齐 SQL schema
│   └── protocols.py              # 8 个 Protocol（Stage, Segmenter, Enricher, ...）
│
├── infra/                        # Layer 2: 共享基础设施
│   ├── db.py                     # AssetCoreDB + MiningRuntimeDB (PostgreSQL 适配器)
│   ├── pg_config.py              # MiningDbConfig (PG 连接配置)
│   ├── pg_schema.py              # Schema 初始化（DDL 自动执行）
│   ├── mining_config.py          # MiningConfig (pydantic-settings, .env 加载)
│   ├── llm_client.py             # LLM 服务 HTTP 客户端（submit → poll）
│   ├── llm_templates.py          # LLM prompt 模板构建
│   ├── domain_pack.py            # DomainProfile 加载（场景知识外置）
│   ├── embedding.py              # Embedding 生成（llm_service / Zhipu 直连）
│   ├── extractors.py             # EntityExtractor / RoleClassifier 实现
│   ├── text_utils.py             # CJK 分词、归一化、相似度
│   ├── hash_utils.py             # SHA256 快照去重
│   └── structure/                # markdown-it → SectionNode 树
│
├── stages/                       # Layer 3: Pipeline stage 实现
│   ├── parse.py                  # 文档解析（Markdown/Text/Passthrough）
│   ├── segment.py                # 结构化分块（9 block_type + 11 semantic_role）
│   ├── enrich/                   # 实体增强（规则 v1 + LLM v2）
│   ├── relations/                # 关系构建（structural + discourse RST）
│   ├── retrieval_units/          # 检索单元生成（4 种载体）
│   ├── eval.py                   # 数据质量评估
│   └── publishing.py             # Build + Release 发布
│
├── pipeline.py                   # Pipeline 引擎（MiningPipeline + StreamingPipeline）
├── ingestion/                    # 文件扫描 + 预处理
├── snapshot/                     # 共享快照管理
├── runtime/                      # 运行时状态跟踪 + 断点续跑
├── jobs/run.py                   # 编排入口
└── api/                          # REST API (FastAPI)
    ├── app.py                    # FastAPI 应用工厂
    ├── deps.py                   # 依赖注入
    └── routes/
        ├── health.py             # GET /health
        ├── runs.py               # /api/runs CRUD
        ├── knowledge.py          # /api/knowledge 只读查询
        ├── builds.py             # /api/builds, /api/releases
        └── config.py             # /api/config
```

## 3. PostgreSQL 后端

### 3.1 连接配置

`MiningDbConfig` (pydantic-settings) 从 `.env` 读取：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PG_HOST` | `localhost` | PostgreSQL 主机 |
| `PG_PORT` | `5432` | PostgreSQL 端口 |
| `PG_DBNAME` | `coremasterkb` | 数据库名 |
| `PG_USER` | `postgres` | 用户名 |
| `PG_PASSWORD` | _(空)_ | 密码 |
| `PG_POOL_MIN` | `2` | 连接池最小连接数 |
| `PG_POOL_MAX` | `10` | 连接池最大连接数 |

### 3.2 双库边界

| 数据库 | 职责 | 写入方 |
|--------|------|--------|
| `asset_core` | 知识资产：documents, snapshots, segments, relations, units, embeddings, builds, releases | Mining 写，Serving 只读 |
| `mining_runtime` | 过程状态：runs, run_documents, stage_events | Mining 写 |

**CQRS 边界：** Mining 是写入端，Serving 只通过 `asset_publish_releases` 找到 active release 后只读查询。

### 3.3 Schema 管理

`pg_schema.py` 在启动时自动执行 DDL：
- `databases/asset_core/schemas/002_asset_core_postgresql.sql`
- `databases/mining_runtime/schemas/002_mining_runtime_postgresql.sql`

幂等执行：已存在的表和索引会跳过。

### 3.4 连接池

- **Pipeline 模式**：同步 `psycopg_pool.ConnectionPool`，在 `run()` 入口创建，结束时关闭
- **API 模式**：异步 `psycopg_pool.AsyncConnectionPool`，在 FastAPI lifespan 创建

## 4. Pipeline 配置

### 4.1 MiningConfig

`MiningConfig` (pydantic-settings) 从 `.env` 读取：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_SERVICE_URL` | `http://localhost:8900` | LLM 服务地址 |
| `MINING_LLM_BYPASS_PROXY` | `false` | 是否绕过系统代理 |
| `EMBEDDING_MODEL` | `embedding-3` | Embedding 模型名 |
| `EMBEDDING_DIMENSIONS` | _(空)_ | Embedding 向量维度 |
| `DOMAIN_PACK` | `cloud_core_network` | 默认 Domain Pack ID |
| `MAX_WORKERS` | `4` | Streaming Pipeline 并发度 |

## 5. Pipeline 详解

### 5.1 两阶段 Pipeline

**Phase 1: Document Mining（文档级，StreamingPipeline 并发执行）**

```
ingest → parse → segment → enrich → relations → discourse → retrieval_units → select_snapshot
```

**Phase 2: Build & Publish（全局串行）**

```
assemble_build → validate_build → publish_release
```

### 5.2 StreamingPipeline

`StreamingPipeline` 采用 Queue-based parallel 架构：

```
Queue[0] → [parse×1] → Queue[1] → [segment×1] → Queue[2] → [enrich×N]
→ Queue[3] → [relations×1] → Queue[4] → [discourse×min(N,2)]
→ Queue[5] → [retrieval_units×N] → Queue[6]
```

特点：
- 每个 stage 在独立线程中运行
- `enrich` 和 `retrieval_units` 支持 N 个并发 worker
- `_SENTINEL` 模式优雅关闭
- `sequence_id` 保证输出顺序与输入一致
- 协作式取消：每个 stage 间检查 `mining_runs.status` 是否为 `cancelled`

### 5.3 DocumentContext（不可变状态传递）

每个文档的 Pipeline 状态通过 `DocumentContext` (frozen dataclass) 传递：

| 字段 | 类型 | 说明 |
|------|------|------|
| `raw_file` | `RawFileData` | 原始文件数据 |
| `profile` | `DocumentProfile` | 文档元信息 |
| `tree` | `SectionNode` | 解析后的文档树 |
| `segments` | `tuple[RawSegmentData, ...]` | 分块结果 |
| `relations` | `tuple[SegmentRelationData, ...]` | 关系数据 |
| `seg_ids` | `dict[str, str]` | segment_key → segment_id 映射 |
| `retrieval_units` | `tuple[RetrievalUnitData, ...]` | 检索单元 |
| `error` | `str \| None` | 错误信息 |
| `run_document_id` | `str \| None` | 运行时文档 ID |
| `sequence_id` | `int` | 输入序号（保序用） |

通过 `with_updates(**kwargs)` 创建新实例，保证不可变性。

## 6. 九阶段详解

| 阶段 | 输入 | 输出 | 核心逻辑 |
|------|------|------|---------|
| S1 Ingest | 文件夹路径 | `list[RawFileData]` | 递归扫描，双重 hash，跳过未变文件 |
| S2 Parse | RawFileData.content | SectionNode 树 | Markdown/Text/Passthrough 工厂 |
| S3 Segment | SectionNode + DocumentProfile | `list[RawSegmentData]` | Heading 独立成段，9 block_type + 11 semantic_role |
| S4 Enrich | Segments | 增强后 Segments | 实体提取 + 角色分类（v1 规则 / v2 LLM） |
| S5 Relations | Segments + ID 映射 | `list[SegmentRelationData]` | 结构关系（同层、父子、顺序） |
| S5b Discourse | Segments + seg_ids | 额外 RST 关系 | LLM 驱动的语篇关系（24 种 RST 标签） |
| S6 Retrieval Units | Segments + LLM | `list[RetrievalUnitData]` | raw_text + contextual_text + entity_card + generated_question |
| S7 Snapshot | 文档内容/配置 | (doc_id, snapshot_id) | 三层模型 + SHA256 去重 |
| S8 Build | Snapshot 决策列表 | build_id | 自动 full/incremental 判断 |
| S9 Release | build_id | release_id | 激活新 release，退役旧 release |

## 7. LLM 集成架构

```
Mining Pipeline
  → llm_client.py (submit batch → poll results)
  → LLM Service (:8900, PostgreSQL-backed worker pool)
  → Provider (DeepSeek / OpenAI / Zhipu)
```

LLM 集成点：

| 阶段 | LLM 用途 | 模式 | 状态 |
|------|---------|------|------|
| enrich | 语义实体提取 + 角色分类 | Batch async | 已实现 (LlmEnricher, v2) |
| relations | 语篇关系提取（24 RST labels） | Batch async | 已实现 (DiscourseRelationBuilder) |
| retrieval_units | 问题生成（generated_question） | Batch async | 已实现 (LlmQuestionGenerator) |
| retrieval_units | 上下文增强（Contextual Retrieval） | Batch async | 已实现 (LLMContextualizer) |

**降级策略：** LLM Service 不可用时自动降级为规则版本（RuleBasedEnricher），不阻塞主流程。

**Embedding 生成：** 优先通过 llm_service 的 embedding 端点，fallback 到直连 Zhipu API。

## 8. Domain Pack（场景知识外置）

`domain_packs/<domain>/domain.yaml` 承载场景特定知识：

```yaml
entity_types: [command, network_element, parameter, ...]
strong_entity_types: [command, network_element]
retrieval_policy:
  max_questions_per_segment: 2
  generated_question_enabled_roles: [concept, procedure_step, parameter]
  skip_block_types_for_question: [heading]
  contextual_retrieval: "on"  # on / off
```

DomainProfile 在 Pipeline 启动时一次性加载，所有 stage 通过 `cfg.domain_profile` 访问。

当前内置 Domain Pack：`cloud_core_network`（云核心网）。

## 9. Shared Snapshot 模型

```
document (逻辑身份) → snapshot (内容快照, hash 唯一) → link (映射)
```

- 归一化：CRLF → LF → 去尾空白 → 去空行 → SHA256
- 相同内容共享 snapshot
- `NEW`：创建 document + snapshot
- `UPDATE`：创建新 snapshot，清理旧 snapshot 的 segments/relations/units
- `SKIP`：直接复用现有 snapshot

## 10. Build & Release 生命周期

```
Run → Snapshot Decisions → classify_documents → assemble_build → validate → publish_release
```

- **Build**：自动判断 full/incremental，将所有 snapshot 组装为可发布版本
- **Release**：激活新 release 并退役旧 release（支持 channel 概念）
- **质量门**：`demo_quality_summary()` 计算构建质量摘要（非阻塞）
- **部分失败处理**：`publish_on_partial_failure=True` 时，即使有文档失败也发布

## 11. REST API

FastAPI v3.0.0，端口 8901，PostgreSQL 后端。

### 11.1 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 数据库连接状态 |

### 11.2 运行管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/runs` | 启动 Mining Run（异步，后台线程执行） |
| GET | `/api/runs` | 列出所有 Run |
| GET | `/api/runs/{id}` | 获取 Run 详情 |
| GET | `/api/runs/{id}/stages` | 获取 Run 的 stage 事件 |
| GET | `/api/runs/{id}/documents` | 获取 Run 的文档列表 |
| POST | `/api/runs/{id}/cancel` | 协作式取消 Run |
| POST | `/api/runs/{id}/publish` | 发布 Run 的 Build |

### 11.3 知识资产查询（只读）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/stats` | 知识库统计信息 |
| GET | `/api/knowledge/documents` | 文档列表 |
| GET | `/api/knowledge/documents/{id}` | 文档详情 |
| GET | `/api/knowledge/documents/{id}/segments` | 文档的 segments |
| GET | `/api/knowledge/documents/{id}/units` | 文档的检索 units |
| GET | `/api/knowledge/segments` | 全局 segments 查询 |
| GET | `/api/knowledge/units` | 全局 retrieval units 查询 |
| GET | `/api/knowledge/relations` | 全局 relations 查询 |

### 11.4 Build & Release

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/builds` | 构建列表 |
| GET | `/api/builds/{id}` | 构建详情 |
| GET | `/api/releases` | 发布列表 |
| GET | `/api/releases/active` | 当前激活的 release |

### 11.5 配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 当前配置（domain pack, LLM 状态等） |

## 12. 如何运行

### 12.1 环境准备

```bash
# PostgreSQL 数据库
createdb coremasterkb

# .env 配置
PG_HOST=localhost
PG_PORT=5432
PG_DBNAME=coremasterkb
PG_USER=postgres
PG_PASSWORD=your_password
LLM_SERVICE_URL=http://localhost:8900
```

### 12.2 启动 API 服务

```bash
python -m knowledge_mining.mining.api
# 或
uvicorn knowledge_mining.mining.api.app:create_app --host 0.0.0.0 --port 8901 --factory
```

### 12.3 编程方式调用

```python
from knowledge_mining.mining.jobs.run import run, publish

# 完整 pipeline
result = run("/path/to/input/folder")
# result: {"run_id": "...", "status": "completed", "build_id": "...", "release_id": "..."}

# 仅 Phase 1（不构建不发布）
result = run("/path/to/input", phase1_only=True)

# 手动发布
publish(result["run_id"])

# 指定 domain pack
result = run("/path/to/input", domain_pack="cloud_core_network")

# 调整并发度
result = run("/path/to/input", max_workers=8)
```

## 13. 数据质量体系

### 已实现

- **Content Quality Gate**：LLM 驱动的内容质量评估（入模前拦截导航/目录/稀疏片段）
- **Question Post-Validation**：LLM 输出后校验可回答性
- **Qn Prefix Removal**：generated_question.title 不含 Q1/Q2 前缀
- **Retrieval Unit Budget**：raw_text ≥ 55%, generated_question ≤ 20%
- **LLM Provenance**：task_id 全链路追溯
- **Data Quality Eval**：真实数据库产物级评估
- **Demo Quality Summary**：构建级质量摘要（segment/relation/unit 数量统计）

## 14. 已知问题与演进方向

### 已知问题

| 优先级 | 问题 | 说明 |
|--------|------|------|
| P0 | Heading Fragmentation | ~30% segments <10 token，heading 独立成段过于碎片化 |
| P0 | O(n²) Relations | `same_parent_section` 关系在 37 个 segment 中产生 422 条关系 |
| P1 | Retrieval Unit 重复 | raw_text 和 contextual_text 内容高度重叠 |
| P1 | 中文文本处理 | CJK 分词和归一化不够精细 |
| P1 | 质量门未接入 Release Gate | `demo_quality_summary` 存在但不是发布必要条件 |
| P2 | Domain Pack 不是唯一合同源 | 部分模块仍绕过 DomainProfile 私读 YAML |

### 演进路线图

详见 `docs/plans/2026-05-09-v14-industrial-evolution-roadmap.md`

**V14 工业化演进（5 个子项目）：**
1. Segment Quality — 解决 heading fragmentation
2. Relation Quality — 解决 O(n²) 爆炸，引入有意义的语义关系
3. Retrieval Unit Redesign — 重新设计检索单元载体
4. Smart Retrieval — Serving 侧智能检索（HyDE, graph expansion）
5. Evaluation — 评测体系

## 15. 相关文档

- [Asset Core Schema (PostgreSQL)](../databases/asset_core/schemas/002_asset_core_postgresql.sql)
- [Mining Runtime Schema (PostgreSQL)](../databases/mining_runtime/schemas/002_mining_runtime_postgresql.sql)
- [V14 工业化演进路线图](../docs/plans/2026-05-09-v14-industrial-evolution-roadmap.md)
- [Mining 当前实现审查](../.dev/2026-04-29-mining-current-implementation-overview.md)
- [V12 Evolution Backlog](../.dev/2026-04-22-v12-evolution-backlog.md)
- [Serving 检索架构](../agent_serving_fzl/README.md)
- [多域统一计划](../.dev/2026-05-11-multi-domain-unification-plan.md)
