# Pipeline Stage 07: 级联重排 (Cascading Rerank)

## 概述

融合后的候选列表虽然按 RRF 分数排序，但分数不直接反映与查询的语义相关性。重排阶段使用更精细的模型对候选重新打分排序。

采用**级联降级**架构：Model Reranker → LLM Reranker → Score Fallback，保证始终有结果输出。

## 流程图

```
RerankPipeline.rerank(candidates, routePlan, understanding)
  │
  ├─ 1. Model Reranker（ServiceReranker）
  │   ├─ POST /api/v1/models/rerank
  │   ├─ 成功 → result = reranked candidates
  │   └─ 失败/空 → result = null, 继续降级
  │
  ├─ 2. LLM Reranker（仅当 method = "llm" 或 "cascade"）
  │   ├─ POST /api/v1/execute（serving-reranker 模板）
  │   ├─ 成功 → result = reranked candidates
  │   └─ 失败/空 → result = null, 继续降级
  │
  ├─ 3. Score Fallback（始终成功）
  │   └─ 按现有 score 降序排列
  │
  └─ 4. 统一后处理
      ├─ 4a. 注入 rerankScore 到 ScoreChain
      ├─ 4b. 过滤 score < 0.01 的候选
      └─ 4c. 截断到 maxItems（默认 10）
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `candidates` | List\<RetrievalCandidate\> | Stage 06 融合结果 | 候选列表 |
| `routePlan` | RetrievalRoutePlan | Stage 03 | 重排方法、maxItems 配置 |
| `understanding` | QueryUnderstanding | Stage 02 | 原始查询，供 LLM 理解 |

## 输出

### RerankResult（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `candidates` | List\<RetrievalCandidate\> | 重排后候选（截断后） |
| `traces` | List\<RerankTraceStep\> | 每步执行追踪 |

### RerankTraceStep（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `method` | String | 重排方法名 |
| `attempted` | boolean | 是否尝试执行 |
| `success` | boolean | 是否成功 |
| `reason` | String | 失败原因 |
| `latencyMs` | double | 耗时 |
| `inputCount` | int | 输入候选数 |
| `outputCount` | int | 输出候选数 |

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `rerank/RerankPipeline.java` | **核心**，级联编排 + 后处理 |
| `rerank/Reranker.java` | 重排器接口 |
| `rerank/ServiceReranker.java` | 模型重排器（Zhipu rerank API） |
| `rerank/LlmReranker.java` | LLM listwise 重排器 |
| `rerank/ScoreReranker.java` | 分数降序兜底 |
| `domain/RerankConfig.java` | 重排配置（method, fallback） |

---

## 重排器 1：ServiceReranker（模型重排）

### 概述

调用 LLM 服务的专用 rerank 端点，支持批处理。

### 调用格式

```
POST {base-url}/api/v1/models/rerank
{
  "query": "SMF怎么配置ADD UPF",
  "documents": ["title1: text1", "title2: text2", ...],
  "model": "rerank-pro",
  "top_n": 10
}
```

### 特点

- 支持批量：>200 候选时分批处理
- 每个候选格式化为 `"title: text"`（text 最多 1000 字符）
- 返回 rerank 分数

---

## 重排器 2：LlmReranker（LLM 重排）

### 概述

将查询 + Top-N 候选预览发送给 LLM，LLM 返回排序列表和新分数。

### 限制

- 最多处理 20 个候选（`MAX_CANDIDATES = 20`）
- 每个候选文本预览 200 字符

### 调用格式

```
POST {base-url}/api/v1/execute
{
  "pipeline_stage": "reranker",
  "template_key": "serving-reranker",
  "input": {
    "query": "SMF怎么配置ADD UPF",
    "candidates": "[0] (score=0.850) ADD UPF配置: 在SMF上执行ADD UPF命令...\n[1] ...",
    "count": 20
  }
}
```

### 响应解析

```java
// 解析 LLM 返回的 ranking 列表
List<{index: int, score: double}> rankingList

// 按 rankingList 重新排列
// 未被 LLM 排名的候选保留原始顺序
// topN 之后的候选直接追加
```

### 候选预览构建

```java
private String buildItemsText(List<RetrievalCandidate> candidates) {
    for (i, c) in candidates:
        textPreview = truncate(text, 200)
        sb.append("[%d] (score=%.3f) %s: %s%n", i, c.score(), title, textPreview)
}
```

---

## 重排器 3：ScoreReranker（分数兜底）

### 逻辑

```java
candidates.stream()
    .sorted(Comparator.comparingDouble(RetrievalCandidate::score).reversed())
    .toList();
```

**始终成功**，不返回 null。

---

## 统一后处理

### 4a. ScoreChain 注入

```java
chain = new ScoreChain(chain.rawScore(), chain.fusionScore(), c.score(), chain.routeSources());
```

将当前 score 记录为 `rerankScore`，保留原始 rawScore 和 fusionScore。

### 4b. 分数过滤

```java
MIN_RERANK_SCORE = 0.01
result = result.stream().filter(c -> c.score() >= 0.01).collect(...)
```

过滤掉极低分候选。

### 4c. 截断

```java
int maxItems = routePlan.assembly().maxItems();  // 默认 10
if (result.size() > maxItems) result = result.subList(0, maxItems);
```

## 重排方法选择

```java
// 在 RerankPipeline 中
String method = resolveRerankMethod(routePlan);  // 来自 routePlan.rerank().method()

// 在 RetrievalRouter 中（决定 method）
String rerankMethod = "score";  // 默认
if (understanding.evidenceNeed().needsComparison()) {
    rerankMethod = "cascade";   // 对比类查询用级联重排
}
```

| 条件 | method | 实际行为 |
|------|--------|----------|
| 对比类查询 | `cascade` | 尝试 model → LLM → score |
| 其他查询 | `score` | 直接 score fallback |

## 配置参数

### RerankConfig（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `method` | String | `cascade` / `llm` / `score` |
| `fallback` | String | 降级方法 |

### application.yml

```yaml
serving:
  rerank:
    model: ${RERANK_MODEL:rerank-pro}
```

### LlmReranker 常量

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_CANDIDATES | 20 | LLM 最大处理候选数 |
| TEXT_PREVIEW_CHARS | 200 | 文本预览长度 |

### RerankPipeline 常量

| 参数 | 值 | 说明 |
|------|-----|------|
| MIN_RERANK_SCORE | 0.01 | 最低分数阈值 |
| DEFAULT_MAX_ITEMS | 10 | 默认截断数量 |

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Cascading Fallback** | 类似 Resilience4j 的 fallback chain，逐级降级保证可用 |
| **Listwise Reranking** | LLM 端到端重排（如 RankGPT），比 pointwise 更准确 |
| **Score Thresholding** | 最低分过滤，避免低质量结果进入上下文 |
| **top-N Truncation** | 标准截断策略，控制下游上下文长度 |
| **Rerank Tracing** | 每步追踪延迟和成功/失败，用于观测和调优 |

## 当前实现的不足

### 1. 重排方法选择过于简单

只有 `needsComparison` 触发 cascade，其他一律 score fallback。实际很多查询（如 troubleshooting）也会从模型重排中受益。

**改进方向**：对所有查询默认尝试 model reranker，失败再降级。`method` 只控制是否允许 LLM reranker。

### 2. LLM Reranker 仅处理 Top 20

超过 20 个候选只对前 20 重排，后面的保持原序。可能导致高质量但排在后面的候选被忽略。

**改进方向**：分批处理（20 一批），或先粗排到 50 再精排 20。

### 3. ServiceReranker 批处理逻辑不透明

>200 候选时分批，但批处理间的分数归一化策略不明确。

**改进方向**：确保跨批分数可比（如 min-max 归一化），或限制最大候选数避免分批。

### 4. 无 rerank 缓存

相同查询 + 相同候选的 rerank 结果没有缓存。

**改进方向**：添加 query + candidate_hash → reranked 的缓存。

### 5. ScoreChain 不记录 reranker 类型

ScoreChain 记录了 rawScore、fusionScore、rerankScore，但不记录用了哪个 reranker。

**改进方向**：在 ScoreChain 或 metadata 中记录实际使用的 reranker method。

### 6. 固定 MIN_RERANK_SCORE=0.01

阈值硬编码，不同场景可能需要不同阈值。

**改进方向**：将 MIN_RERANK_SCORE 移到 RerankConfig 配置中。
