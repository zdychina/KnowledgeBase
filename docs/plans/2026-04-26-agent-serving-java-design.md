# agent_serving_java 详细设计文档

> 版本：1.0 | 日期：2026-04-26 | 作者：Claude

---

## 1. 模块定位

`agent_serving_java` 是 CoreMasterKB 的**知识检索服务**，用 Spring Boot 3.2 重写自原 Python 模块 `agent_serving`。

**职责**：接收 Agent 或前端发来的自然语言查询，执行多阶段检索流水线，返回结构化的知识上下文包（`ContextPack`）供下游 LLM 消费。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                   HTTP Client (Agent / Frontend)         │
└──────────────────────────┬──────────────────────────────┘
                           │ POST /api/v1/search
                           ▼
┌─────────────────────────────────────────────────────────┐
│  SearchController  (api层)                              │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  SearchService  (application层 — 流水线编排)             │
│                                                         │
│  1. QueryNormalizer.normalize()                         │
│     ├─ LlmRuntimeClient (可选，HTTP 调外部 LLM 服务)     │
│     └─ 规则引擎（降级）                                  │
│                                                         │
│  2. QueryPlanner.plan()                                 │
│     └─ RulePlannerProvider                              │
│                                                         │
│  3. AssetRepository.resolveActiveScope()                │
│     └─ 查 asset_publish_release + snapshot 表           │
│                                                         │
│  4. RetrieverManager.retrieve()                         │
│     └─ FtsRetriever (fts_bm25)                          │
│                                                         │
│  5. FusionStrategy.fuse()                               │
│     ├─ IdentityFusion（默认）                            │
│     └─ RRFFusion                                        │
│                                                         │
│  6. ScoreReranker.rerank()                              │
│                                                         │
│  7. ContextAssembler.assemble()                         │
│     └─ GraphExpander（BFS 图扩展）                       │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                      ContextPack
```

---

## 3. 包结构

```
com.coremasterkb.serving
├── api/              REST 控制器、全局异常处理
├── application/      用例编排（SearchService、QueryNormalizer、ContextAssembler）
├── pipeline/         流水线组件（Planner、Fusion、Reranker、RetrieverManager）
├── retrieval/        Retriever 接口及实现（FtsRetriever、GraphExpander）
├── repository/       数据访问门面（AssetRepository）
├── mapper/           MyBatis-Plus Mapper 接口 + XML
├── entity/           数据库实体类
├── domain/           纯数据对象（record，无业务逻辑）
├── client/           外部服务客户端（LlmRuntimeClient）
├── config/           Spring 配置（ServingBeans、ServingProperties）
├── constants/        常量（意图、角色、类型名称）
└── util/             工具类（JsonUtils）
```

---

## 4. API 规范

### 4.1 检索接口

```
POST /api/v1/search
Content-Type: application/json
```

---

#### 请求体 `SearchRequest`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | `""` | 自然语言查询文本，直接传入原始问题即可，服务内部完成结构化解析 |
| `scope` | map\<string, any\> | 否 | null | 请求级范围约束，**优先级高于**服务自动识别的 scope。支持的 key：`product`（产品线）、`version`（版本号）、`network_element`（网元类型）。非空时完全覆盖自动识别结果 |
| `entities` | EntityRef[] | 否 | null | 请求级实体约束，**优先级高于**服务自动识别的实体。非空时完全覆盖自动识别结果，用于调用方已明确知道实体时精确检索 |
| `debug` | boolean | 否 | false | 为 true 时，响应体附加 `debug` 字段，包含意图、关键词、融合方法、命中快照 ID 等内部状态，用于排查检索结果问题 |

**EntityRef 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 实体类型。枚举值：`command`（完整命令，如 `ADD USER_GROUP`）、`command_op`（操作词，如 `ADD`）、`product`（产品线）、`network_element`（网元）、`version`（版本号） |
| `name` | string | 实体原始名称，与查询文本中出现的字面量一致 |
| `normalized_name` | string | 标准化名称，用于匹配数据库中的 `entity_refs`。命令类型格式为 `OP_OBJECT`（如 `ADD_USER_GROUP`） |

**请求示例**

最简请求（自然语言直传）：
```json
{
  "query": "AMF如何配置ADD USER_GROUP命令的参数",
  "debug": false
}
```

带范围约束的请求（调用方已知产品线）：
```json
{
  "query": "ADD USER_GROUP命令参数说明",
  "scope": {
    "product": "UDG",
    "version": "V300R001C00"
  },
  "debug": false
}
```

带实体覆盖的请求（调用方已完成实体解析）：
```json
{
  "query": "ADD USER_GROUP命令参数说明",
  "scope": { "product": "UDG" },
  "entities": [
    { "type": "command", "name": "ADD USER_GROUP", "normalized_name": "ADD_USER_GROUP" },
    { "type": "network_element", "name": "AMF", "normalized_name": "AMF" }
  ],
  "debug": true
}
```

---

#### 响应体 `ContextPack`

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | ContextQuery | 服务对查询的结构化解析结果，供调用方了解服务的理解是否准确 |
| `items` | ContextItem[] | 检索到的知识片段列表，已按相关度排序，供 LLM 直接拼入 prompt |
| `relations` | ContextRelation[] | items 中各片段之间的图关系，供调用方构建上下文树或做引用追溯 |
| `sources` | SourceRef[] | items 的来源文档列表，用于生成引用注释或显示出处 |
| `issues` | Issue[] | 检索过程异常信号。非空时调用方应降级处理或提示用户 |
| `suggestions` | string[] | 查询改写建议（当前版本始终为空数组，预留扩展） |
| `debug` | map\<string, any\> | 仅 `debug=true` 时出现，包含内部执行状态 |

**ContextQuery 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `original` | string | 用户原始输入，原样透传 |
| `normalized` | string | 服务对查询的关键词拼接表示（keywords 以空格连接） |
| `intent` | string | 识别出的查询意图。枚举值：`command_usage`（命令用法）、`troubleshoot`（故障排查）、`concept_lookup`（概念查询）、`procedure`（操作步骤）、`general`（通用） |
| `entities` | EntityRef[] | 服务从查询中识别出的实体列表（若请求传入了 entities 覆盖则为覆盖值） |
| `scope` | map | 服务识别出的范围约束（若请求传入了 scope 覆盖则为覆盖值） |
| `keywords` | string[] | 分词并过滤停用词后的关键词列表，用于 FTS 查询构建 |

**ContextItem 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 片段唯一 ID。`kind=retrieval_unit` 时为检索单元 ID；`kind=raw_segment` 时为原始片段 ID |
| `kind` | string | 片段类型。`retrieval_unit`：FTS 直接命中的检索单元；`raw_segment`：通过 source_segment_id 或图扩展得到的原始片段 |
| `role` | string | 片段在本次检索中的角色。`seed`：直接命中的种子片段；`context`：种子对应的原始段落；`support`：图扩展出的邻居片段 |
| `text` | string | 片段正文内容，直接用于 LLM prompt 拼装 |
| `score` | number | 相关度分数。seed 类型为 FTS 原始分经重排调整后的值；context/support 类型固定为 0.0（按位置顺序使用） |
| `title` | string | 片段所属章节标题 |
| `block_type` | string | 文本块结构类型，反映在文档中的排版角色。常见值：`paragraph`（正文段落）、`table`（表格）、`list_item`（列表项）、`heading`（标题）、`code`（代码块）、`toc`（目录）、`link`（链接） |
| `semantic_role` | string | 文本块语义角色，反映在知识体系中的内容含义。常见值：`parameter`（参数说明）、`example`（示例）、`procedure_step`（操作步骤）、`concept`（概念定义）、`note`（注意事项）、`troubleshooting_step`（排障步骤）、`alarm`（告警说明）、`constraint`（约束条件） |
| `source_id` | string | 来源文档 ID，与 `sources` 列表中的 `id` 对应，用于关联引用 |
| `relation_to_seed` | string | 仅 `role=support` 时有值，格式为 `expanded_depth_N`，表示距种子片段的图扩展层数 |
| `source_refs` | map | 扩展引用信息（当前版本为空 map） |
| `metadata` | map | 附加元数据（当前版本为空 map） |

**ContextRelation 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 关系唯一 ID |
| `from_id` | string | 起点片段 ID，对应 ContextItem.id |
| `to_id` | string | 终点片段 ID，对应 ContextItem.id |
| `relation_type` | string | 关系类型。枚举值：`previous`（前一片段）、`next`（后一片段）、`same_section`（同章节）、`same_parent_section`（同父章节）、`section_header_of`（章节标题对应关系） |
| `distance` | integer | 关系距离（当前版本不填充，为 null） |

**SourceRef 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 文档来源 ID，与 ContextItem.source_id 对应 |
| `document_key` | string | 文档唯一业务键 |
| `title` | string | 文档标题 |
| `relative_path` | string | 文档在知识库中的相对路径 |
| `scope_json` | map | 文档归属的范围元数据（如 product、version 等） |
| `metadata` | map | 附加元数据（当前版本为空 map） |

**Issue 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 异常类型。枚举值：`no_result`（无检索结果）、`low_confidence`（全部结果 score < 0.1） |
| `message` | string | 人类可读的异常描述 |
| `detail` | map | 附加细节（当前版本为空 map） |

---

#### 响应示例

**正常响应**（无 debug）：

```json
{
  "query": {
    "original": "AMF如何配置ADD USER_GROUP命令的参数",
    "normalized": "AMF ADD USER_GROUP 配置 参数",
    "intent": "command_usage",
    "entities": [
      { "type": "command", "name": "ADD USER_GROUP", "normalized_name": "ADD_USER_GROUP" },
      { "type": "network_element", "name": "AMF", "normalized_name": "AMF" }
    ],
    "scope": { "network_element": "AMF" },
    "keywords": ["AMF", "ADD", "USER_GROUP", "配置", "参数"]
  },
  "items": [
    {
      "id": "ru-0a1b2c3d",
      "kind": "retrieval_unit",
      "role": "seed",
      "text": "ADD USER_GROUP命令用于在AMF上新增用户组。必选参数：group-name，取值范围为1~32个字符。",
      "score": 1.42,
      "title": "ADD USER_GROUP",
      "block_type": "paragraph",
      "semantic_role": "parameter",
      "source_id": "seg-f1e2d3c4",
      "relation_to_seed": null,
      "source_refs": {},
      "metadata": {}
    },
    {
      "id": "seg-f1e2d3c4",
      "kind": "raw_segment",
      "role": "context",
      "text": "ADD USER_GROUP\n功能说明：在AMF上配置用户组信息，用于承载用户策略。\n命令格式：add user-group group-name <name> [ description <desc> ]",
      "score": 0.0,
      "title": "ADD USER_GROUP",
      "block_type": "paragraph",
      "semantic_role": "procedure_step",
      "source_id": "doc-aabbccdd",
      "relation_to_seed": null,
      "source_refs": {},
      "metadata": {}
    },
    {
      "id": "seg-a9b8c7d6",
      "kind": "raw_segment",
      "role": "support",
      "text": "注意事项：执行ADD USER_GROUP前，需确认已完成基础路由配置，否则命令下发失败。",
      "score": 0.0,
      "title": "ADD USER_GROUP",
      "block_type": "paragraph",
      "semantic_role": "note",
      "source_id": "doc-aabbccdd",
      "relation_to_seed": "expanded_depth_1",
      "source_refs": {},
      "metadata": {}
    }
  ],
  "relations": [
    {
      "id": "rel-11223344",
      "from_id": "seg-f1e2d3c4",
      "to_id": "seg-a9b8c7d6",
      "relation_type": "next",
      "distance": null
    }
  ],
  "sources": [
    {
      "id": "doc-aabbccdd",
      "document_key": "amf-cli-reference-v300r001c00",
      "title": "AMF命令行参考 V300R001C00",
      "relative_path": "amf/cli/amf-cli-reference.md",
      "scope_json": { "product": "UDG", "version": "V300R001C00", "network_element": "AMF" },
      "metadata": {}
    }
  ],
  "issues": [],
  "suggestions": []
}
```

**无结果响应**（知识库未收录相关内容）：

```json
{
  "query": {
    "original": "xyz功能如何配置",
    "normalized": "xyz 功能 配置",
    "intent": "general",
    "entities": [],
    "scope": {},
    "keywords": ["xyz", "功能", "配置"]
  },
  "items": [],
  "relations": [],
  "sources": [],
  "issues": [
    {
      "type": "no_result",
      "message": "No retrieval results found for the query.",
      "detail": {}
    }
  ],
  "suggestions": []
}
```

**debug=true 时附加字段**（在正常响应基础上追加）：

```json
{
  "debug": {
    "intent": "command_usage",
    "keywords": ["AMF", "ADD", "USER_GROUP", "配置", "参数"],
    "scope_constraints": { "network_element": "AMF" },
    "fusion_method": "identity",
    "candidate_count": 10,
    "snapshot_ids": ["snap-001", "snap-002"],
    "release_id": "release-20260401",
    "build_id": "build-20260401-001"
  }
}
```

---

#### 错误响应

| HTTP 状态 | 错误原因 | 典型场景 |
|-----------|----------|----------|
| 503 | `no_active_release`：当前 channel 无激活的知识库版本 | 知识库尚未发布，或发布版本已下线 |
| 500 | `multiple_active_releases`：激活版本数量 > 1 | 数据异常，需运维介入修复 |
| 400 | 请求体解析失败 | `query` 字段缺失或 JSON 格式错误 |

### 4.2 健康检查

```
GET /actuator/health   → 200 { "status": "UP" }
GET /health            → 200
```

---

## 5. 流水线详解

### Step 1 — QueryNormalizer：自然语言 → NormalizedQuery

两层策略，优先 LLM，降级规则：

**LLM 路径**（`serving.llm-service.enabled=true` 时生效）
```
POST {llm-service-url}/api/v1/execute
Body: { "task_type": "query_normalization", "query": "..." }
期望返回: intent / normalized_query / keywords / entities / scope / desired_roles
```
任何异常静默降级，不影响主流程。

**规则路径（降级 / 默认）**

| 子步骤 | 内容 |
|--------|------|
| 实体识别 | 正则匹配命令（`ADD USER_GROUP`）、产品（UDG/UNC/CloudCore）、网元（AMF/SMF/UPF…）、版本（`V\d{3}R\d{3}(C\d{2})?`）；中文操作词（新增→ADD，删除→DEL…） |
| 意图识别 | 关键词匹配 → command_usage / troubleshoot / concept_lookup / procedure / general |
| 范围提取 | 从实体中提取 version / product / network_element → scope map |
| 关键词提取 | 按标点分词，过滤中英文停用词，保留长度 ≥ 2 或单 CJK 字符的词 |
| 意图→角色 | command_usage→[parameter, example, procedure_step]；troubleshoot→[troubleshooting_step, alarm, constraint]；concept_lookup→[concept, note]；procedure→[procedure_step, parameter, example] |

**输出 `NormalizedQuery`**：original / intent / entities / scope / keywords / desiredRoles

---

### Step 2 — QueryPlanner：NormalizedQuery → QueryPlan

`QueryPlanner` 为 Facade，当前实现为 `RulePlannerProvider`（确定性规则，无 LLM 参与）。

逻辑：
- entities / scope：request 覆盖优先，否则取 NormalizedQuery 的值
- 其余字段（intent / keywords / desiredRoles）直接透传
- 四个配置对象使用默认值

**默认配置值**

| 配置 | 参数 | 默认值 |
|------|------|--------|
| `RetrievalBudget` | max_items | 10 |
| | max_expanded | 20 |
| | recall_multiplier | 5 |
| `RetrieverConfig` | enabled_retrievers | `["fts_bm25"]` |
| | fusion_method | `"identity"` |
| | rrf_k | 60 |
| `ExpansionConfig` | enable_relation_expansion | true |
| | max_relation_depth | 2 |
| | relation_types | previous, next, same_section, same_parent_section, section_header_of |

---

### Step 3 — resolveActiveScope：确定知识库版本

```sql
-- 查激活的发布版本（恰好 1 条）
SELECT * FROM asset_publish_release
WHERE status='active' AND channel='default'

-- 查该版本下所有激活的文档快照
SELECT * FROM asset_build_document_snapshot
WHERE build_id=? AND selection_status='active'
```

输出 `ActiveScope`：releaseId / buildId / snapshotIds[] / documentSnapshotMap

`snapshotIds` 是后续所有查询的数据隔离边界。

---

### Step 4 — RetrieverManager：多路召回

按 `QueryPlan.retrieverConfig.enabledRetrievers` 列表逐个调用，结果合并。

**FtsRetriever（当前唯一实现，name=`fts_bm25`）**

```
keywords → tokenize() → 过滤停用词
→ 拼 FTS OR 表达式："token1 OR token2 OR token3"
→ SQL: asset_retrieval_unit FTS 搜索
   LIMIT = max_items(10) × recall_multiplier(5) = 50
   WHERE snapshot_id IN (snapshotIds)
→ 返回 List<RetrievalCandidate>
   { retrievalUnitId, ftsScore, source="fts_bm25", metadata{text, title, block_type, semantic_role, ...} }
```

注：注释中提及 PostgreSQL `websearch_to_tsquery`，当前配置 `serving.fts.strategy=sqlite`，实际 SQL 在 XML mapper 中定义。

---

### Step 5 — FusionStrategy：多路结果融合

| 策略 | 触发条件 | 算法 |
|------|----------|------|
| `IdentityFusion` | fusion_method=identity（默认） | 原样返回，保持原顺序 |
| `RRFFusion` | fusion_method=rrf | 按 source 分组 → 各组内按 score 排名 → `score = Σ(1/(k+rank))` → 合并排序 |

RRF 在多 Retriever 场景（如未来同时启用向量检索 + FTS）时才发挥作用；单 Retriever 时两种策略效果相同。

---

### Step 6 — ScoreReranker：分数重排

4 个阶段串行执行：

| 阶段 | 操作 |
|------|------|
| Stage 1 去重 | 同一 `source_segment_id` 的 raw_text / contextual_text 单元保留最高分 |
| Stage 2 降权 | block_type 为 heading / toc / link 的候选 score × 0.3 |
| Stage 3 加权 | semantic_role 命中 desiredRoles → +0.3；block_type 命中 desiredBlockTypes → +0.15；facets 匹配 scope → +0.2；实体命中 entity_refs → +0.25 |
| Stage 4 截断 | 按 score 降序排列，截取前 max_items(10) 条 |

---

### Step 7 — ContextAssembler：组装 ContextPack

10 个子步骤：

```
Step 1  buildSeedItems        候选列表 → ContextItem(role=seed)
Step 2  resolveSourceSegIds   从 metadata 取 source_segment_id（兼容 source_refs_json / target_ref_json）
Step 3  fetchSourceSegments   SQL 查 source segment 详情
Step 4  buildSourceItems      source segments → ContextItem(role=context)
Step 5  GraphExpander.expand  BFS 图扩展（depth=2，5种关系类型），每层一次 SQL
Step 6  buildExpandedItems    扩展片段 → ContextItem(role=support, relation_to_seed=expanded_depth_N)
Step 7  buildRelations        查 seed+expanded 之间的关系边 → ContextRelation[]
Step 8  deduplicateRelations  按 relation.id 去重
Step 9  buildSources          收集 document_id → 查文档元数据 → SourceRef[]
Step 10 buildIssues           无结果 → issue(no_result)；全部 score<0.1 → issue(low_confidence)

最终合并：items = seed + source + expanded，总数截断至 max_items + max_expanded = 30
```

---

## 6. 领域对象速查

```
SearchRequest          — 入参
NormalizedQuery        — 标准化查询（intent/entities/scope/keywords/desiredRoles）
QueryPlan              — 检索指令（budget/expansion/retrieverConfig/rerankerConfig）
ActiveScope            — 激活的知识库版本（releaseId/buildId/snapshotIds）
RetrievalCandidate     — 单条召回结果（id/score/source/metadata）
ContextPack            — 最终输出
  ├── ContextQuery     — 结构化查询元数据
  ├── ContextItem      — 知识片段（kind: retrieval_unit | raw_segment）
  ├── ContextRelation  — 片段间关系边
  ├── SourceRef        — 来源文档
  └── Issue            — 异常信号
```

---

## 7. 配置说明

`application.yml` 中 `serving.*` 命名空间（由 `ServingProperties` 绑定）：

```yaml
serving:
  llm-service:
    enabled: false                    # true 时启用 LLM 辅助归一化
    base-url: http://localhost:8900   # LLM 运行时服务地址
    timeout-ms: 3000                  # 请求超时（ms）
  fts:
    strategy: sqlite                  # FTS 实现策略
```

数据库连接配置遵循 MyBatis-Plus 标准配置（`spring.datasource.*`）。

---

## 8. 扩展点

| 扩展点 | 接口 | 新增方式 |
|--------|------|----------|
| 新增召回器（如向量检索） | `Retriever` | 实现接口，注册为 Bean，加入 `RetrieverManager` 的列表 |
| 新增融合策略 | `FusionStrategy` | 实现接口，在 `SearchService.selectFusion()` 中按 method 名路由 |
| 新增重排器 | `Reranker` | 实现接口，替换 `SearchService` 中注入的 `ScoreReranker` |
| 新增规划策略 | `PlannerProvider` | 实现接口，替换 `QueryPlanner` 中注入的 `RulePlannerProvider` |
| 替换 LLM 归一化 | `LlmRuntimeClient` | 修改 `execute()` 的端点或协议 |

---

## 9. 关键设计决策

| 决策 | 原因 |
|------|------|
| LLM 归一化可选且降级透明 | LLM 服务不可用时不应阻断检索，规则引擎作为保底 |
| snapshotIds 作为所有 SQL 的隔离边界 | 知识库按发布版本管理，查询只能访问激活快照，防止跨版本污染 |
| RetrievalBudget 控制三层数量 | max_items 控制最终输出，recall_multiplier 放大召回确保重排有足够候选，max_expanded 限制图扩展不过度膨胀 |
| GraphExpander 在 Assembler 而非 Retriever 中执行 | 图扩展依赖 Reranker 输出的 top-N 种子，属于组装阶段而非召回阶段 |
| ScoreReranker 先去重再加权 | 同一原始片段可能被不同检索单元命中，去重后再打分避免分数叠加导致排名失真 |
