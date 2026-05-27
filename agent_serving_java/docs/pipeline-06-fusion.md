# Pipeline Stage 06: 融合策略 (Fusion)

## 概述

多路检索返回的候选结果可能存在大量重叠（同一检索单元被多条路由召回）。融合阶段负责**去重**和**重排序**，将多路候选合并为统一排序。

支持三种融合策略（策略模式）：

1. **Weighted RRF**（加权倒数排名融合）—— 默认，多路启用时使用
2. **RRF**（标准倒数排名融合）—— 无权重版本
3. **Identity**（直通去重）—— 仅单路启用时使用

## 流程图

```
SearchService 中：
  rawCandidates = orchestrator.execute(...)
        │
        ▼
  根据 routePlan.fusion().method() 选择策略
        │
        ├─ "weighted_rrf" → WeightedRRFFusion
        ├─ "rrf"          → RRFFusion
        └─ 其他           → IdentityFusion
        │
        ▼
  fused = strategy.fuse(rawCandidates, routePlan)
        │
        ▼
  List<RetrievalCandidate> fused  → 送入重排
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `candidates` | List\<RetrievalCandidate\> | Stage 05 | 所有路由的候选汇总（可能含重复） |
| `routePlan` | RetrievalRoutePlan | Stage 03 | 融合方法、k 参数、路由权重 |

## 输出

去重后的 `List<RetrievalCandidate>`，按融合分数降序排列。每个候选的 `ScoreChain.fusionScore` 已更新。

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `pipeline/FusionStrategy.java` | 策略接口 |
| `pipeline/WeightedRRFFusion.java` | **默认策略**，加权 RRF |
| `pipeline/RRFFusion.java` | 标准 RRF |
| `pipeline/IdentityFusion.java` | 直通去重 |
| `domain/FusionConfig.java` | 融合配置 record（method, k） |
| `domain/RouteConfig.java` | 路由权重 weight |

---

## 策略 1：Weighted RRF（默认）

### 公式

```
score(d) = Σ_j  weight_j / (k + rank_j(d))
```

其中：
- `weight_j`：路由 j 的权重（来自 `RouteConfig.weight()`）
- `rank_j(d)`：文档 d 在路由 j 中的排名（1-based）
- `k`：平滑参数，默认 60

### 实现逻辑

```java
// 1. 按路由权重构建 weightMap
Map<String, Double> weightMap = {route_name → weight}

// 2. 按 source 分组，每组内按原始 score 降序排列
Map<String, List<RetrievalCandidate>> bySource

// 3. 计算加权 RRF 分数
for (source, candidates) in bySource:
    weight = weightMap[source]
    for (rank, candidate) in enumerate(candidates, 1):
        rrfScores[uid] += weight / (k + rank)
        candidateSources[uid].add(source)

// 4. 更新 ScoreChain
chain = chain.withFusionScore(fusionScore).withRouteSources(sources)
candidate = candidate.withScore(fusionScore).withScoreChain(chain)

// 5. 按 RRF 分数降序排列
```

### 特点

- 同时出现在多条路由的候选会获得更高分数（多信号确认）
- 权重让不同意图偏好不同路由（如 command_usage 重 entity_exact）
- 跟踪每条候选的 `routeSources`（哪些路由贡献了分数）

### RRF 参数 k 的作用

`k` 越大，排名差异影响越小。k=60 时：

| rank | 贡献（权重=1.0） |
|------|-------------------|
| 1 | 1/61 ≈ 0.0164 |
| 10 | 1/70 ≈ 0.0143 |
| 50 | 1/110 ≈ 0.0091 |

---

## 策略 2：RRF（标准）

### 公式

```
score(d) = Σ_j  1 / (k + rank_j(d))
```

与 Weighted RRF 相同但 `weight_j = 1.0`（所有路由等权）。

### 与 Weighted RRF 的区别

- 不区分路由权重
- 不更新 `ScoreChain.routeSources`
- 不更新 `ScoreChain.fusionScore`

---

## 策略 3：Identity（直通）

### 逻辑

```java
// 1. 按 retrievalUnitId 去重，保留最高分
LinkedHashMap<uid, candidate>  // 保留最高分版本

// 2. 按 score 降序排列
```

### 使用场景

仅当只有 1 条路由启用时（如 dense_vector 不可用，只剩 BM25 + entity 但融合方法被设为 identity）。

## 配置参数

### FusionConfig（record）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `method` | String | `"weighted_rrf"` | 融合方法名 |
| `k` | int | 60 | RRF 平滑参数 |

### 方法选择逻辑（在 RetrievalRouter 中）

```java
long enabledCount = routeConfigs.stream().filter(RouteConfig::enabled).count();
String fusionMethod = enabledCount > 1 ? "weighted_rrf" : "identity";
```

### 路由权重示例（domain.yaml）

```yaml
serving:
  route_policy:
    command_usage:
      lexical_bm25: {weight: 1.0, topK: 50}
      dense_vector: {weight: 0.4, topK: 20}
      entity_exact: {weight: 1.6, topK: 20}
```

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Reciprocal Rank Fusion (RRF)** | Cormack et al., 2009，经典的多源融合算法 |
| **Weighted RRF** | RRF 的加权变体，类似 Learning-to-Rank 的特征权重 |
| **k=60** | 原论文推荐值，在 SIGIR 评测中表现稳定 |
| **Strategy Pattern** | GoF 策略模式，通过配置切换融合算法 |
| **Dedup by ID** | 检索系统标准去重策略，保留最高分 |

## 当前实现的不足

### 1. 权重手动配置

所有权重和 k 值都是人工设定，没有通过离线评估（NDCG@k）或 A/B 测试优化。

**改进方向**：添加基于 eval_questions 的自动化权重调优，或使用 Bayesian Optimization。

### 2. RRF 不考虑分数质量

RRF 只使用排名，忽略原始分数。两个分数差异很大的候选可能排名相同。

**改进方向**：混合策略，将原始分数归一化后与 RRF 分数加权组合。

### 3. IdentityFusion 无 ScoreChain 更新

Identity 策略不更新 fusionScore 和 routeSources，下游无法判断融合质量。

**改进方向**：统一三种策略的 ScoreChain 更新逻辑。

### 4. 融合结果无截断

融合后的候选列表可能很长（3 路各召回 50 条 = 最多 150 条），没有在融合阶段截断。

**改进方向**：在融合后截断到合理数量（如 maxItems × 3），减少后续重排负担。

### 5. 缺少 CombMNZ 或 CombSUM 等替代算法

只实现了 RRF 系列，没有提供基于分数归一化的融合（如 CombMNZ）。

**改进方向**：添加 min-max 归一化 + CombMNZ 作为可选项，在分数分布均匀时效果可能更好。
