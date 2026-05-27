# Agent Serving FZL — 架构文档

> 知识检索服务：查询理解 → 多路检索 → 融合 → 重排 → 上下文组装
> 版本：v0.1.0 | 技术栈：Spring Boot 3.2.5 / Java 17 / MyBatis / PostgreSQL | 92 源文件 + 29 测试

## 1. 系统定位

`agent_serving_fzl` 是在线知识检索服务，从 PostgreSQL 读取 Mining 产出的结构化知识资产，通过 10 步 Pipeline 将用户查询转化为结构化上下文包（ContextPack），供下游 Agent 消费。

**核心价值：** 把 Mining 产出的结构化知识变成 Agent 可精准消费的上下文。

**与其他版本的关系：**
- `agent_serving/` — Python 版本（已归档）
- `agent_serving_fzl/` — Java 版本（当前主线，本目录）

## 2. 技术栈

| 组件 | 版本/工具 |
|------|----------|
| 框架 | Spring Boot 3.2.5 |
| Java | 17 |
| ORM | MyBatis 3.0.3 (XML Mapper) |
| 数据库 | PostgreSQL (HikariCP 连接池) |
| 中文分词 | jieba-analysis 1.0.2 |
| YAML | SnakeYAML |
| JSON | Jackson |
| 构建 | Maven |
| 测试 | JUnit 5 + H2 (单元) / PG (集成) |

## 3. 架构设计

### 3.1 分层架构

```
api/                 → REST Controller（HTTP 入口）
application/         → 业务编排层（SearchService, QU Engine, Router, Assembler）
pipeline/            → 检索编排（RetrievalOrchestrator, Fusion 策略）
retrieval/           → 检索器（FtsRetriever, DenseVector, EntityExact, GraphExpander）
rerank/              → 重排器（ZhipuModel, LlmService, Score fallback）
evidence/            → 证据角色分类
domainpack/          → Domain Pack 读取
infrastructure/      → 外部客户端（LlmClient, EmbeddingClient, ZhipuClient）
repository/          → 数据访问抽象（AssetRepository）
mapper/              → MyBatis Mapper 接口 + XML
entity/              → 数据库实体（对应 Mining 产出的表）
domain/              → 领域模型（纯 record，无外部依赖）
config/              → Spring 配置（Beans, Properties）
observability/       → Trace 收集
```

### 3.2 目录结构

```
agent_serving_fzl/src/main/java/com/coremasterkb/serving/
├── AgentServingApplication.java      # Spring Boot 启动类
├── api/
│   ├── SearchController.java         # POST /api/v1/search
│   ├── HealthController.java         # GET /health
│   └── GlobalExceptionHandler.java   # 全局异常处理
├── application/
│   ├── SearchService.java            # 主编排器：10步 Pipeline
│   ├── QueryUnderstandingEngine.java # 查询理解（LLM + 规则 fallback）
│   ├── RetrievalRouter.java          # 意图感知路由规划
│   └── ContextAssembler.java         # 上下文组装（seed→source→expansion→pack）
├── pipeline/
│   ├── RetrievalOrchestrator.java    # 多路检索编排器
│   ├── FusionStrategy.java           # 融合策略接口
│   ├── RRFFusion.java                # Reciprocal Rank Fusion
│   ├── WeightedRRFFusion.java        # 加权 RRF
│   └── IdentityFusion.java           # 直通（单路时）
├── retrieval/
│   ├── Retriever.java                # 检索器接口
│   ├── FtsRetriever.java             # PostgreSQL ts_rank 全文检索
│   ├── DenseVectorRetriever.java     # 向量余弦相似度检索
│   ├── EntityExactRetriever.java     # 实体精确匹配检索
│   └── GraphExpander.java            # BFS 关系图扩展
├── rerank/
│   ├── Reranker.java                 # 重排器接口
│   ├── RerankPipeline.java           # 级联重排（model→LLM→score）
│   ├── ZhipuModelReranker.java       # Zhipu rerank-pro API
│   ├── LlmServiceReranker.java       # LLM Service rerank 端点
│   ├── LlmReranker.java              # LLM template rerank
│   └── ScoreReranker.java            # 纯分数排序 fallback
├── evidence/
│   └── EvidenceRoleClassifier.java   # 证据角色分类
├── domainpack/
│   ├── DomainPackReader.java         # YAML Domain Pack 加载器
│   └── ServingDomainProfile.java     # Serving 侧 Domain Profile
├── infrastructure/
│   ├── LlmClient.java                # LLM Service HTTP 客户端
│   ├── EmbeddingClient.java          # Embedding 生成（via LLM Service）
│   ├── ZhipuClient.java              # Zhipu API 客户端（rerank）
│   ├── PgConfig.java                 # PG 配置
│   └── ServingTemplates.java         # Serving 侧 prompt 模板
├── repository/
│   └── AssetRepository.java          # 资产数据访问抽象
├── mapper/                           # MyBatis Mapper 接口
│   ├── AssetDocumentMapper.java
│   ├── AssetRawSegmentMapper.java
│   ├── AssetRawSegmentRelationMapper.java
│   ├── AssetRetrievalUnitMapper.java
│   ├── AssetRetrievalEmbeddingMapper.java
│   ├── AssetBuildDocumentSnapshotMapper.java
│   ├── AssetPublishReleaseMapper.java
│   ├── ServingQueryLogMapper.java
│   └── result/                       # Mapper 结果行对象
├── entity/                           # JPA 实体（对应 Mining 表）
├── domain/                           # 纯 record 领域模型（~30 个 record）
├── config/
│   ├── ServingBeans.java             # Spring Bean 显式装配
│   └── ServingProperties.java        # 配置属性（serving.*）
└── observability/
    └── TraceCollector.java           # 请求级 trace 收集
```

## 4. 核心 Pipeline：SearchService.search()

10 步完整检索流程：

```
1. Load Domain Profile     ← DomainPackReader
2. Query Understanding     ← QueryUnderstandingEngine (LLM-first, rule fallback)
3. Retrieval Router        ← RetrievalRouter (intent-aware route plan)
4. Resolve Active Scope    ← AssetRepository (active release → snapshot IDs)
5. Generate Query Embedding ← EmbeddingClient (if dense route enabled)
6. Retrieve                ← RetrievalOrchestrator (multi-route parallel)
7. Fuse                    ← FusionStrategy (weighted_rrf / rrf / identity)
8. Rerank                  ← RerankPipeline (cascade: model→LLM→score)
9. Assemble ContextPack    ← ContextAssembler (seed→source→expansion→pack)
10. Build Debug Info       ← TraceCollector (if debug=true)
```

## 5. 各组件详解

### 5.1 QueryUnderstandingEngine

**LLM-first, rule-based fallback。**

| 能力 | LLM 路径 | 规则路径 |
|------|---------|---------|
| 意图识别 | JSON 输出 7 种 intent | 关键词匹配 |
| 实体提取 | JSON 输出 | Domain Pack extractor_rules + 命令正则 + 中文操作词映射 |
| 关键词提取 | JSON 输出 | jieba 分词 + 停用词过滤 |
| Scope 提取 | JSON 输出 | 产品/网元列表正则匹配 |
| SubQuery 分解 | JSON 输出 | 不支持 |
| 证据需求分类 | JSON 输出 | intent→role 映射表 |
| 歧义检测 | JSON 输出 | 不支持 |

7 种意图：`command_usage`, `troubleshooting`, `concept_lookup`, `procedure`, `comparison`, `navigational`, `general`

### 5.2 RetrievalRouter

根据意图生成检索路由计划，包含：
- **Route 配置**：每条路由的 weight 和 top_k（按 intent 差异化）
- **融合策略**：多路时用 `weighted_rrf`，单路时 `identity`
- **重排策略**：需要比较时用 `cascade`，否则 `score`
- **Assembly 配置**：maxItems, relationExpansion, maxRelationDepth 等

默认路由权重：

| 意图 | lexical_bm25 | dense_vector |
|------|-------------|-------------|
| default | 1.0 / top50 | 0.9 / top50 |
| command_usage | 1.2 / top50 | 0.6 / top30 |
| concept_lookup | 0.8 / top50 | 1.1 / top50 |
| troubleshooting | 1.0 / top50 | 0.8 / top40 |
| comparison | 1.0 / top50 | 1.0 / top50 |

### 5.3 RetrievalOrchestrator

3 条检索路由（注册在 ServingBeans 中）：

| 路由名 | 检索器 | 说明 |
|--------|--------|------|
| `lexical_bm25` | FtsRetriever | PostgreSQL ts_rank 全文检索 |
| `dense_vector` | DenseVectorRetriever | pgvector 余弦相似度 |
| `entity_exact` | EntityExactRetriever | 实体精确匹配 |

- 无 embedding 时自动跳过 dense_vector
- 每条路由独立执行，异常隔离
- 结果合并后统一进入融合阶段

### 5.4 Fusion 策略

| 策略 | 说明 |
|------|------|
| `weighted_rrf` | 加权 Reciprocal Rank Fusion（默认，多路时） |
| `rrf` | 标准 RRF |
| `identity` | 直通（单路时） |

### 5.5 RerankPipeline（级联重排）

```
ZhipuModelReranker (rerank-pro API)
    ↓ 失败
LlmServiceReranker (LLM Service rerank 端点)
    ↓ 失败
ScoreReranker (纯分数排序)
```

后处理：
1. 将 rerank score 写入 ScoreChain
2. 最低分阈值过滤 (<0.01)
3. 截断到 maxItems

### 5.6 ContextAssembler

10 步组装流程：
1. 从检索候选构建 seed items
2. 解析 source segment IDs
3. 去重 segment IDs
4. 从数据库获取 source segments
5. **Graph Expansion**（BFS 关系图扩展，如果启用）
6. 获取直接关系
7. 去重关系
8. 构建文档来源引用
9. 构建 issues（无结果/低置信度）
10. 组装 ContextPack（合并+截断+过滤）

**GraphExpander**：BFS 遍历 `asset_raw_segment_relations`，支持 depth 限制、relation type 过滤、maxResults 上限。

### 5.7 Domain Pack

`DomainPackReader` 从 `scenario_packs/<domain>/domain.yaml` 加载：
- `extractor_rules`：实体提取正则规则
- `query_understanding`：命令正则、操作词映射、网元/产品列表
- `route_policy`：按 intent 的路由权重覆盖
- `serving`：serving 侧特定配置

默认 domain：`cloud_core_network`

## 6. 数据访问层

### 6.1 读取的 Mining 表

| Mapper | 对应 Mining 表 | 用途 |
|--------|---------------|------|
| AssetPublishReleaseMapper | asset_publish_releases | 获取 active release |
| AssetBuildDocumentSnapshotMapper | asset_build_document_snapshots | 获取 build 包含的 snapshot |
| AssetDocumentMapper | asset_documents | 文档基本信息 |
| AssetRawSegmentMapper | asset_raw_segments | 段落全文检索 |
| AssetRawSegmentRelationMapper | asset_raw_segment_relations | 关系图扩展 |
| AssetRetrievalUnitMapper | asset_retrieval_units | 检索单元查询 |
| AssetRetrievalEmbeddingMapper | asset_retrieval_embeddings | 向量检索 |
| ServingQueryLogMapper | serving_query_log | 查询日志（Serving 自己的表） |

### 6.2 Scope Resolution

```
domain → asset_publish_releases (active, channel=default)
       → asset_builds
       → asset_build_document_snapshots
       → snapshot_ids (用于所有后续查询的过滤条件)
```

## 7. REST API

Spring Boot，端口 8081。

### 7.1 搜索

**POST /api/v1/search**

请求：
```json
{
  "query": "SMF ADD UPF 的步骤是什么",
  "scope": {},
  "entities": [],
  "debug": true,
  "domain": "cloud_core_network",
  "mode": "evidence"
}
```

响应：
```json
{
  "query": { "text": "...", "intent": "...", "entities": [...], "keywords": [...] },
  "items": [{ "id": "...", "kind": "retrieval_unit", "role": "seed", "text": "...", "score": 0.95 }],
  "relations": [{ "id": "...", "fromId": "...", "toId": "...", "type": "..." }],
  "sources": [{ "id": "...", "documentKey": "...", "title": "..." }],
  "evidence_groups": [{ "snapshotId": "...", "itemIds": [...], "relationIds": [...] }],
  "issues": [],
  "suggestions": [],
  "debug": { ... }
}
```

### 7.2 健康检查

**GET /health**

## 8. 配置

### 8.1 application.yml

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `server.port` | 8081 | 服务端口 |
| `spring.datasource.url` | `localhost:5432/coremasterkb` | PostgreSQL 连接 |
| `serving.scenario-packs-dir` | `../scenario_packs` | Domain Pack 目录 |
| `serving.default-domain` | `cloud_core_network` | 默认域 |
| `serving.llm.base-url` | _(空)_ | LLM Service URL |
| `serving.zhipu.api-key` | _(空)_ | Zhipu API Key |
| `serving.zhipu.rerank-model` | `rerank-pro` | Rerank 模型 |
| `serving.embedding.model` | `embedding-3` | Embedding 模型 |
| `serving.embedding.dimensions` | 1024 | 向量维度 |
| `serving.rerank.model` | `rerank-pro` | Rerank 模型名 |

### 8.2 ServingProperties

通过 `serving.*` 前缀绑定，支持嵌套 record：
- `serving.llm.*` — LLM 连接
- `serving.zhipu.*` — Zhipu API
- `serving.embedding.*` — Embedding 配置
- `serving.rerank.*` — Rerank 配置

## 9. 外部依赖

| 依赖 | 地址 | 用途 |
|------|------|------|
| PostgreSQL | 同 Mining 数据库 | 知识资产读取 |
| LLM Service | `:8900` | 查询理解 + Rerank + Embedding |
| Zhipu API | `open.bigmodel.cn` | Rerank (rerank-pro) |

## 10. 测试

Maven 分层测试：
- **Level 1**：`mvn test` — 单元测试（H2 内存库）
- **Level 2**：`mvn verify` — PG 集成测试（需真实 PG）
- **Level 3**：`mvn verify -Pe2e` — E2E 系统测试

## 11. 如何运行

```bash
# 构建
cd agent_serving_fzl
mvn clean package -DskipTests

# 运行
java -jar target/agent-serving-0.1.0.jar

# 或开发模式
mvn spring-boot:run

# 环境变量
export PG_HOST=localhost
export PG_PORT=5432
export PG_DBNAME=coremasterkb
export PG_USER=kb_user
export PG_PASSWORD=xxx
export LLM_SERVICE_URL=http://localhost:8900
export RERANK_API_KEY=xxx
```

## 12. 已知问题与演进方向

### 已实现 vs Python 版对齐

| Python Serving 功能 | Java 状态 |
|---------------------|----------|
| Query Understanding (LLM+Rule) | 已实现 |
| Intent-aware Routing | 已实现 |
| Multi-route Retrieval (BM25+Vector+Entity) | 已实现 |
| RRF Fusion | 已实现 |
| Cascade Rerank | 已实现 |
| Context Assembly (seed→source→expansion) | 已实现 |
| Graph Expansion (BFS) | 已实现 |
| Domain Pack | 已实现 |
| Debug/Trace | 已实现 |
| Query Log | Mapper 已定义 |
| HyDE | 未实现 |
| Community Summary | 未实现 |
| Multi-channel Release | 部分实现 |

### 演进方向

1. **Smart Retrieval**：HyDE 假设文档增强、query expansion by LLM
2. **Graph-aware Retrieval**：利用 relation graph 做 context-aware 路由
3. **Multi-domain**：支持多域查询、跨域检索
4. **评测体系**：对接 serving demo testset，量化检索质量
5. **Streaming**：SSE 流式响应支持

## 13. 相关文档

- [Mining 架构文档](../knowledge_mining_fzl/README.md)
- [Serving 当前实现审查](../.dev/2026-04-29-serving-current-implementation-overview.md)
- [V12 Evolution Backlog](../.dev/2026-04-22-v12-evolution-backlog.md)
- [检索演进指南](../.dev/2026-04-22-coremasterkb-retrieval-evolution-guide.md)
- [Serving Demo 测试集](../.dev/2026-05-07-serving-demo-testset-业务感知.md)
- [V14 工业化演进路线图](../docs/plans/2026-05-09-v14-industrial-evolution-roadmap.md)
- [多域统一计划](../.dev/2026-05-11-multi-domain-unification-plan.md)
