# Pipeline Stage 03: 检索路由决策 (Retrieval Router)

## 概述

本阶段根据查询理解输出的 **intent**（意图），决定使用哪些检索路径、各自的权重和召回量。核心思想是**意图驱动的自适应路由**：不同意图对三路检索的依赖程度不同。

## 流程图

```
QueryUnderstanding.intent + scope
  │
  ▼
RetrievalRouter.route(understanding, profile)
  │
  ├─ 1. 查找 intent 对应的路由策略
  │     ├─ profile.routePolicy[intent] 存在? → 使用域配置
  │     └─ 否则 → BUILTIN_ROUTES[intent] 或 BUILTIN_ROUTES["default"]
  │
  ├─ 2. 为每路生成 RouteConfig(name, enabled, weight, topK)
  │
  ├─ 3. 决定 fusion 方法
  │     └─ 路由数 > 1 → "weighted_rrf"，否则 → "identity"
  │
  ├─ 4. 决定 rerank 方法
  │     └─ evidenceNeed.needsComparison → "cascade"，否则 → "score"
  │
  └─ 5. 输出 RetrievalRoutePlan
        ├─ routes: [RouteConfig, ...]
        ├─ filters: scope Map
        ├─ fusion: FusionConfig(method="weighted_rrf", k=60)
        ├─ rerank: RerankConfig(method, fallback)
        ├─ assembly: AssemblyConfig.defaults()
        └─ expansion: ExpansionConfig.defaults()
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `understanding` | QueryUnderstanding | Stage 02 | 主要是 `intent` 和 `scope` |
| `profile` | ServingDomainProfile | DomainPackReader | 包含 `routePolicy` 路由策略 |

## 输出

**`RetrievalRoutePlan`**（record），包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `routes` | List\<RouteConfig\> | 各路由配置 |
| `filters` | Map\<String, Object\> | 来自 understanding.scope 的过滤条件 |
| `fusion` | FusionConfig | 融合方法和参数 |
| `rerank` | RerankConfig | 重排方法和降级策略 |
| `assembly` | AssemblyConfig | 组装配置 |
| `expansion` | ExpansionConfig | 图扩展配置 |

**`RouteConfig`**（record）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | String | 路由名：`lexical_bm25`、`dense_vector`、`entity_exact` |
| `enabled` | boolean | 是否启用（当前全部 true） |
| `weight` | double | 融合时的权重 |
| `topK` | int | 最大召回条数 |

**`FusionConfig`**：`method`（`weighted_rrf` / `rrf` / `identity`），`k`（RRF 参数，固定 60）

**`RerankConfig`**：`method`（`cascade` / `score`），`fallback`（降级方法）

**`AssemblyConfig`**：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `sourceDrilldown` | true | 是否下钻源文档 |
| `relationExpansion` | true | 是否通过关系扩展 |
| `maxItems` | 10 | 最大组装条数 |
| `maxExpanded` | 10 | 扩展后最大条数 |
| `maxRelationDepth` | 2 | 关系遍历最大深度 |
| `relationTypes` | 13 种 | 遍历的关系类型 |

**`ExpansionConfig`**：与 AssemblyConfig 类似但独立，`enableRelationExpansion=true`、`maxRelationDepth=2`。

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `application/RetrievalRouter.java` | **核心**，intent → 路由策略映射 |
| `domain/RetrievalRoutePlan.java` | 输出 record |
| `domain/RouteConfig.java` | 单路配置 record |
| `domain/FusionConfig.java` | 融合配置 record |
| `domain/RerankConfig.java` | 重排配置 record |
| `domain/AssemblyConfig.java` | 组装配置 record，含默认关系类型列表 |
| `domain/ExpansionConfig.java` | 扩展配置 record |
| `domainpack/ServingDomainProfile.java` | 提供 `getRoutePolicyForIntent()` |
| `scenario_packs/cloud_core_network/domain.yaml` | serving.route_policy 配置 |

## 路由策略详表

### 域配置策略（scenario_packs/cloud_core_network/domain.yaml）

| Intent | lexical_bm25 | dense_vector | entity_exact |
|--------|-------------|-------------|-------------|
| **default** | w=1.0, k=50 | w=0.8, k=50 | w=1.0, k=20 |
| **command_usage** | w=1.0, k=50 | w=0.4, k=20 | **w=1.6**, k=20 |
| **concept_lookup** | w=1.0, k=50 | **w=1.3**, k=60 | w=0.5, k=15 |
| **troubleshooting** | **w=1.2**, k=60 | w=0.7, k=30 | w=1.1, k=30 |
| **procedure** | w=1.1, k=50 | w=0.8, k=40 | w=1.0, k=25 |
| **comparison** | w=1.0, k=50 | **w=1.2**, k=60 | w=0.7, k=20 |
| **navigational** | w=0.8, k=20 | w=0.3, k=10 | **w=1.5**, k=10 |
| **general** | w=1.0, k=50 | w=1.0, k=50 | w=0.8, k=20 |

### 设计逻辑

- **command_usage**：命令查询是精确匹配场景，`entity_exact` 权重最高 (1.6)，`dense_vector` 最低 (0.4)——语义相似对命令帮助不大
- **concept_lookup**：概念查询依赖语义理解，`dense_vector` 权重最高 (1.3)
- **troubleshooting**：故障排查依赖关键词匹配，`lexical_bm25` 权重最高 (1.2)
- **comparison**：对比查询需要语义理解，`dense_vector` 权重高 (1.2)
- **navigational**：导航定位最依赖精确实体匹配，`entity_exact` 权重最高 (1.5)

### 代码内置默认策略（BUILTIN_ROUTES）

当域配置不存在或未匹配到 intent 时的降级策略：

| Intent | lexical_bm25 | dense_vector | entity_exact |
|--------|-------------|-------------|-------------|
| default | w=1.0, k=50 | w=0.9, k=50 | w=0.8, k=20 |
| command_usage | w=1.2, k=50 | w=0.6, k=30 | **w=1.5**, k=20 |
| concept_lookup | w=0.8, k=50 | **w=1.1**, k=50 | *(不启用)* |
| troubleshooting | w=1.0, k=50 | w=0.8, k=40 | w=0.7, k=15 |
| comparison | w=1.0, k=50 | w=1.0, k=50 | *(不启用)* |

注意内置策略中 `concept_lookup` 和 `comparison` 没有 `entity_exact` 路由。

## 具体实现细节

### 1. 路由策略查找优先级

```java
// 1. 先看 profile.routePolicy[intent]
Map<String, Map<String, Double>> policyForIntent = profile.getRoutePolicyForIntent(intent);
if (policyForIntent != null && !policyForIntent.isEmpty()) {
    routeWeights = policyForIntent;    // 用域配置
} else {
    routeWeights = BUILTIN_ROUTES.getOrDefault(intent, BUILTIN_ROUTES.get("default"));
}
```

`ServingDomainProfile.getRoutePolicyForIntent()` 先按精确 intent 查找，找不到则用 `"default"` 策略。

### 2. Fusion 方法选择

```java
long enabledCount = routeConfigs.stream().filter(RouteConfig::enabled).count();
String fusionMethod = enabledCount > 1 ? "weighted_rrf" : "identity";
```

只有 1 路启用时用 `identity`（直接透传），多路启用时用 `weighted_rrf`（加权倒数排名融合）。

### 3. Rerank 方法选择

```java
String rerankMethod = "score";  // 默认纯分数重排
if (understanding.evidenceNeed().needsComparison()) {
    rerankMethod = "cascade";   // 对比类查询用级联重排（LLM + 分数）
}
```

### 4. RRF 参数 k=60

`FusionConfig` 中 `k` 固定为 60。RRF 公式中 k 用于平滑排名影响：`score = 1 / (k + rank)`。k 越大，排名差异的影响越小。

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Intent-aware Retrieval** | 意图驱动的检索路由，类似搜索中的 query type detection → vertical selection |
| **Multi-route Fusion** | 多路召回 + 融合是工业搜索标准架构（Google/Bing 的 multi-signal retrieval） |
| **Reciprocal Rank Fusion (RRF)** | 1995 年提出的经典融合算法，无需归一化分数即可跨源融合 |
| **Domain Pack 外置策略** | 类似 Elasticsearch 的 index settings / search template，策略与代码分离 |
| **Route Weight Tuning** | 权重可调参，类似 Learning-to-Rank 的特征权重 |

## 当前实现的不足

### 1. 没有动态路由选择

当前所有配置的路由都 `enabled=true`，即使某路对特定意图几乎无用（如 navigational 的 dense_vector w=0.3）。没有真正"关闭"不相关路由的能力。

**改进方向**：设置权重阈值（如 < 0.2），低于阈值的路由自动 disabled，减少无效计算。

### 2. 权重是手动配置的

所有权重和 topK 都是人工设定，没有通过离线评估（如 NDCG@k）或在线 A/B 测试优化。

**改进方向**：添加基于 eval_questions 的自动化权重调优脚本，或使用 Bayesian Optimization 搜索最优权重。

### 3. 缺少查询复杂度分级

所有查询都走相同的路由逻辑，没有根据查询复杂度（简单/中等/复杂）调整策略。如简单的实体查询（"SMF"）和复杂的对比查询（"SMF和AMF在计费流程上的区别"）应该有不同的处理。

**改进方向**：基于 entity 数量、query 长度、subQuery 数量划分查询复杂度等级，不同等级使用不同策略。

### 4. scope filters 透传但未被路由使用

`RetrievalRoutePlan.filters` 来自 `understanding.scope()`，但在后续 orchestrator 中似乎没有被用于预过滤。scope 信息只在 DenseVectorRetriever 中有限使用。

**改进方向**：将 scope 转化为各路检索的 WHERE 子句，如 BM25 也应支持 product 级过滤。

### 5. AssemblyConfig 和 ExpansionConfig 重复

两个 config 都有 `maxRelationDepth` 和 `relationTypes`，且默认值相同。概念上容易混淆。

**改进方向**：合并为单一 ExpansionConfig，或明确区分两者职责。

### 6. 没有路由级别的超时配置

各路共享相同的超时（RestTemplate 全局 60s）。dense_vector 通常比 entity_exact 慢得多，应该有独立的超时控制。

**改进方向**：在 RouteConfig 中添加 `timeoutMs` 字段，orchestrator 按路由分别超时控制。

### 7. BUILTIN_ROUTES 和 Domain Pack 策略存在不一致

内置策略中 concept_lookup 和 comparison 不包含 entity_exact 路由，但域配置中包含了。这导致没有 scenario pack 时行为不同。

**改进方向**：统一内置策略和域配置的默认值，或让内置策略完全匹配域配置的 default。
