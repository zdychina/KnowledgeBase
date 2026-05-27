# Pipeline Stage 02: 查询理解 (Query Understanding)

## 概述

本阶段是检索管线的"大脑"，负责将用户原始自然语言查询解析为结构化表示。采用 **LLM-first + rule-fallback** 双路径策略：优先调用 LLM 服务获取深度理解，失败时自动降级到规则引擎。

## 流程图

```
用户查询 "SMF怎么配置ADD UPF"
  │
  ▼
QueryUnderstandingEngine.understand(query, profile)
  │
  ├─ LLM 可用？
  │   ├─ 是 → tryLlmUnderstand(query)
  │   │        ├─ LlmClient.execute("query_understanding", "serving-query-understanding", {query})
  │   │        ├─ 解析 llm_service 响应信封 → parsed_output
  │   │        ├─ parseLlmOutput() → QueryUnderstanding(source="llm")
  │   │        └─ 异常 → 返回 null，降级
  │   │
  │   └─ 否 → ruleUnderstand(query, profile)
  │            ├─ extractEntities()   ← 命令正则 + 中文操作映射 + Domain Pack 规则
  │            ├─ extractScope()      ← 网元/产品名匹配
  │            ├─ detectIntent()      ← 关键词匹配 + 命令实体优先
  │            ├─ extractKeywords()   ← jieba 分词 + 停用词过滤
  │            └─ → QueryUnderstanding(source="rule")
  │
  ▼
QueryUnderstanding (record)
  - originalQuery: "SMF怎么配置ADD UPF"
  - intent: "command_usage"
  - entities: [EntityRef("network_element","SMF","SMF"), EntityRef("command","ADD UPF","ADD UPF")]
  - keywords: ["SMF", "UPF", "配置"]
  - scope: {network_elements: ["SMF","UPF"]}
  - subQueries: []
  - evidenceNeed: EvidenceNeed(preferredRoles=[parameter,example,procedure_step])
  - ambiguities: []
  - source: "llm" 或 "rule"
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `query` | String | SearchRequest.query | 用户原始查询文本 |
| `profile` | ServingDomainProfile | DomainPackReader | 域配置：实体类型、提取规则、网元列表 |

## 输出

**`QueryUnderstanding`**（record），包含：

| 字段 | 类型 | 说明 | LLM 独有 |
|------|------|------|-----------|
| `originalQuery` | String | 原始查询文本 | |
| `intent` | String | 意图分类，7 种取值（见下表） | |
| `subQueries` | List\<SubQuery\> | 子查询分解 | ✓ |
| `entities` | List\<EntityRef\> | 识别的实体列表 | |
| `scope` | Map\<String, Object\> | 作用域约束（products、network_elements） | |
| `keywords` | List\<String\> | 关键词列表 | |
| `evidenceNeed` | EvidenceNeed | 证据需求描述 | |
| `ambiguities` | List\<String\> | 检测到的歧义 | ✓ |
| `source` | String | 来源标识：`"llm"` 或 `"rule"` | |

**7 种意图**：

| 意图 | 含义 | 典型查询 |
|------|------|----------|
| `command_usage` | 命令使用/配置 | "ADD UPF怎么配" |
| `troubleshooting` | 故障排查 | "SMF注册失败怎么排查" |
| `concept_lookup` | 概念查询 | "什么是AMF" |
| `procedure` | 操作步骤 | "如何创建切片" |
| `comparison` | 对比分析 | "SMF和AMF的区别" |
| `navigational` | 导航定位 | "UPF配置在哪里" |
| `general` | 通用/兜底 | 其他所有查询 |

**`EntityRef`**（record）：

| 字段 | 说明 |
|------|------|
| `type` | 实体类型：`network_element`、`command`、`product` 等 |
| `name` | 原始匹配文本 |
| `normalizedName` | 标准化名称（通常大写） |

**`EvidenceNeed`**（record）：

| 字段 | 说明 |
|------|------|
| `preferredRoles` | 偏好的 evidence 语义角色列表 |
| `preferredBlocks` | 偏好的 block 类型列表 |
| `needsComparison` | 是否需要对比型回答 |
| `needsCitation` | 是否需要引用来源 |

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `application/QueryUnderstandingEngine.java` | **核心引擎**，LLM-first + rule-fallback 双路径 |
| `domain/QueryUnderstanding.java` | 输出 record |
| `domain/SubQuery.java` | 子查询 record |
| `domain/EntityRef.java` | 实体引用 record |
| `domain/EvidenceNeed.java` | 证据需求 record |
| `domain/ServingConstants.java` | 意图常量、LLM intent 到内部 intent 的映射 |
| `infrastructure/LlmClient.java` | LLM 服务调用客户端，封装 REST 调用、健康检查、模板注册 |
| `infrastructure/EmbeddingClient.java` | Embedding 客户端，调用 LlmClient.embed() |
| `infrastructure/ServingTemplates.java` | LLM prompt 模板定义（query_understanding + reranker） |
| `domainpack/ServingDomainProfile.java` | 域配置：提供 extractor_rules、queryUnderstanding 参数 |

## 配置参数

### LLM 服务配置（application.yml）

```yaml
serving:
  llm:
    base-url: ${LLM_SERVICE_URL:http://localhost:8900}
  embedding:
    model: ${EMBEDDING_MODEL:embedding-3}
    dimensions: ${EMBEDDING_DIMENSIONS:1024}
```

### Domain Pack 配置（scenario_packs/<domain>/domain.yaml）

```yaml
query_understanding:
  command_regex: "(ADD|MOD|DEL|SET|SHOW|LST|DSP|REG|DEREG)\\s+([A-Z][A-Z0-9_]*)"
  op_map:
    新增: ADD
    修改: MOD
    删除: DEL
    # ...
  network_elements:
    - AMF
    - SMF
    - UPF
    # ...
  products:
    - UDG
    - UNC
```

### 内置硬编码

| 参数 | 当前值 | 说明 |
|------|--------|------|
| 意图关键词集 | 6 组 × 5-7 个中文关键词 | 用于 rule path 的意图检测 |
| 停用词 | 中英各 ~30 个 | jieba 分词后的过滤词 |
| 默认网元列表 | AMF/SMF/UPF 等 12 个 | scope 提取的匹配目标 |
| 默认产品列表 | UDG/UNC/CloudCore | scope 提取的匹配目标 |
| 默认命令正则 | `(ADD\|MOD\|...\)\s+([A-Z]...)` | 命令格式匹配 |
| 默认中文操作映射 | 新增→ADD 等 ~12 条 | 中文描述到命令前缀的映射 |
| 健康检查缓存 TTL | 30 秒 | LlmClient 缓存健康检查结果 |

## 具体实现细节

### 1. LLM 路径

调用 `llm_service` 的模板执行接口 `POST /api/v1/execute`：

```
请求体:
{
  "pipeline_stage": "query_understanding",
  "template_key": "serving-query-understanding",
  "input": {"query": "用户查询"},
  "caller_service": "serving",
  "knowledge_domain": "cloud_core_network"
}
```

模板系统在 `ensureTemplates()` 启动时注册（`POST /api/v1/templates`），prompt 模板包含：
- system_prompt：定义角色和输出格式（JSON Schema）
- user_prompt_template：`分析以下查询：\n\n$query`
- output_schema_json：严格定义输出的 JSON 结构
- example：格式参考示例

LLM 返回的 intent 使用 `LLM_INTENT_TO_INTERNAL` 映射表标准化（如 `conceptual` → `concept_lookup`）。

### 2. 规则路径

当 LLM 不可用时，按以下顺序执行：

#### 2a. 实体提取 `extractEntities()`

三层策略：
1. **Domain Pack 规则**：遍历 `extractor_rules`，每个规则包含 `pattern`（正则）和 `entity_type`，在查询中匹配
2. **命令正则**：`DEFAULT_COMMAND_RE` 匹配 `ADD UPF`、`MOD AMF` 等命令格式
3. **中文操作映射**：`DEFAULT_OP_MAP` 将"新增/修改/删除"等中文动词映射到 `ADD/MOD/DEL`，然后尝试在后续文本中找到英文目标

#### 2b. 作用域提取 `extractScope()`

- 构建 `network_elements` 和 `products` 的 word-boundary 正则模式（预编译缓存）
- 在查询中匹配，结果存入 `scope.products` 和 `scope.network_elements`
- 使用 `TreeSet` 去重排序

#### 2c. 意图检测 `detectIntent()`

优先级顺序：
1. **命令实体优先**：如果提取到 `command` 类型实体 → `command_usage`
2. **关键词匹配**（按优先级）：
   - comparison → troubleshooting → procedure → concept_lookup → navigational → general

#### 2d. 关键词提取 `extractKeywords()`

1. 去除查询中的命令模式
2. jieba 分词（`ThreadLocal<JiebaSegmenter>`，避免每次创建）
3. 过滤停用词（中英 ~60 个）
4. 过滤 <2 字符的非 CJK token

### 3. LlmClient 通信细节

- **健康检查**：`GET /health`，30 秒缓存
- **模板执行**：`POST /api/v1/execute`，携带 `pipeline_stage` + `template_key` + `input`
- **Embedding**：`POST /api/v1/models/embeddings`
- **Rerank**：`POST /api/v1/models/rerank`
- **响应解包**：`unwrapResponse()` 处理 `{success, data: {...}}` 信封格式
- RestTemplate 全局超时：connect=5s, read=60s

### 4. EmbeddingClient

封装 LlmClient 的 embed 接口：
- 输入：单个文本字符串
- 输出：`float[]` 向量数组
- 从 llm_service 响应的 `data[0].embedding` 字段提取
- `isConfigured()` 委托 `llmClient.isAvailable()`

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **LLM-first + Rule Fallback** | 典型的 Graceful Degradation 模式，也见于 Alexa/Elsa 等 NLU 系统 |
| **Prompt Template 注册** | 类似 LangChain 的 prompt template 管理，模板与服务端解耦 |
| **JSON Schema 约束输出** | 使用 structured output / function calling 约束 LLM 输出格式，减少解析错误 |
| **jieba 分词** | 中文 NLP 标准分词器，作为 tokenization 基础设施 |
| **Intent Taxonomy** | 7 级意图分类体系，类似 Rasa NLU 的 intent 设计 |
| **Word-boundary 正则** | 用 `(?<![A-Za-z0-9_])` 和 `(?![A-Za-z0-9_])` 确保精确匹配实体名，避免子串误匹配 |
| **健康检查缓存** | 避免每次请求都检查 LLM 可用性，TTL=30s 是合理的折中 |

## 当前实现的不足

### 1. 规则路径无子查询分解能力

LLM 路径能输出 `subQueries` 和 `ambiguities`，但规则路径这两个字段永远为空。对于复杂查询（如"SMF和AMF的区别，以及如何配置"），规则路径无法分解。

**改进方向**：在规则路径中添加基于标点/连词的简单分句策略。

### 2. 意图检测过于简单

关键词匹配只有 6 个固定集合，每种意图约 5-7 个关键词。对变体表达（如"解释下"、"讲讲"）覆盖率低。

**改进方向**：使用 TF-IDF 或小型分类模型替代硬编码关键词。

### 3. 实体提取缺少模糊匹配

当前实体提取使用精确正则，无法处理拼写错误（如"smg" vs "smf"）或大小写变体（虽然用了 CASE_INSENSITIVE）。

**改进方向**：添加编辑距离或拼音匹配作为 fuzzy fallback。

### 4. 停用词列表硬编码

中英文停用词各约 30 个，写死在代码中。不同域可能需要不同的停用词（如通信域的"配置"可能是停用词）。

**改进方向**：将停用词移至 Domain Pack 配置。

### 5. LLM 输出解析缺乏健壮性

`parseLlmOutput()` 直接按类型强转 `(List<Map<String, Object>>)` ，如果 LLM 输出格式不完全符合预期（如 `entities` 是 null 而非空数组），会抛异常导致整个 LLM 路径失败。

**改进方向**：使用 `getOrDefault` + 空安全处理，或引入 JSON Schema 验证库。

### 6. 无意图置信度

当前 intent 是硬性分类，没有置信度分数。如果查询模糊（既像概念查询又像操作步骤），无法量化不确定度。

**改进方向**：LLM 路径可以让 LLM 输出 confidence 字段；规则路径可以基于关键词匹配数计算得分。

### 7. jieba 分词器的线程安全

使用了 `ThreadLocal<JiebaSegmenter>` 保证线程安全，但 JiebaSegmenter 初始化较慢（加载词典）。首次请求延迟可能较高。

**改进方向**：在 `@PostConstruct` 中预热一个 segmenter 实例。

### 8. LLM 响应缓存缺失

相同查询重复调用 LLM 没有缓存机制。对于高频查询（如"什么是SMF"），每次都走 LLM 浪费 token。

**改进方向**：添加 query → QueryUnderstanding 的 LRU 缓存（TTL=5min）。
