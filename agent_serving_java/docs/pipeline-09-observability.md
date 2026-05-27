# Pipeline Stage 09: 可观测性与调试 (Observability & Debug)

## 概述

整个检索管线通过两级可观测机制记录运行状态：

1. **TraceCollector**：阶段级计时器，记录每个管线阶段的耗时和输出摘要
2. **RouteTrace / RerankTraceStep**：路由级和重排级追踪，记录每条路由/重排器的执行详情
3. **Debug 模式**：`request.debug=true` 时，将所有追踪信息附加到响应中

## 流程图

```
SearchService.search()
  │
  ├─ TraceCollector trace = new TraceCollector()    ← 创建 per-request 追踪器
  │
  ├─ trace.startStage("query_understanding")
  │   └─ trace.endStage("query_understanding", "intent=command_usage, 2 entities")
  │
  ├─ trace.startStage("retrieval_router")
  │   └─ trace.endStage("retrieval_router", "routes=3, fusion=weighted_rrf")
  │
  ├─ trace.startStage("resolve_scope")
  │   └─ trace.endStage("resolve_scope", "snapshots=5")
  │
  ├─ trace.startStage("embedding")       [可选]
  │   └─ trace.endStage("embedding", "dim=1024")
  │
  ├─ trace.startStage("retrieve")
  │   └─ trace.endStage("retrieve", "candidates=53")
  │
  ├─ trace.startStage("fusion")
  │   └─ trace.endStage("fusion", "fused=38, method=weighted_rrf")
  │
  ├─ trace.startStage("rerank")
  │   └─ trace.endStage("rerank", "ranked=10")
  │
  ├─ trace.startStage("assembly")
  │   └─ trace.endStage("assembly", "items=20")
  │
  └─ request.debug=true ?
      ├─ 是 → 构建 debug map，附加到 ContextPack
      └─ 否 → 直接返回 ContextPack
```

## Trace 数据结构

### Trace（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `requestId` | String | 请求 ID（可为空） |
| `stages` | List\<TraceStage\> | 各阶段记录 |
| `totalDurationMs` | double | 总耗时毫秒 |

### TraceStage（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | String | 阶段名称 |
| `inputSummary` | String | 输入摘要（当前为空） |
| `outputSummary` | String | 输出摘要 |
| `durationMs` | double | 耗时毫秒 |
| `error` | String | 错误信息（空字符串表示无错误） |

### RouteTrace（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | String | 路由名 |
| `attempted` | boolean | 是否尝试 |
| `candidateCount` | int | 候选数 |
| `skippedReason` | String | 跳过原因 |
| `latencyMs` | double | 耗时 |

### RerankTraceStep（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `method` | String | 重排方法 |
| `attempted` | boolean | 是否尝试 |
| `success` | boolean | 是否成功 |
| `reason` | String | 失败原因 |
| `latencyMs` | double | 耗时 |
| `inputCount` | int | 输入候选数 |
| `outputCount` | int | 输出候选数 |

## Debug 输出格式

当 `request.debug=true` 时，`ContextPack.debug` 包含：

```json
{
  "understanding": {
    "original_query": "SMF怎么配置ADD UPF",
    "intent": "command_usage",
    "source": "rule",
    "keywords": ["SMF", "UPF", "配置"],
    "entities_count": 2
  },
  "route_plan": {
    "routes_count": 3,
    "fusion_method": "weighted_rrf",
    "rerank_method": "score"
  },
  "domain_context": {
    "domain": "cloud_core_network",
    "channel": "prod",
    "database": "PG_JDBC_URL",
    "scenario_pack": "cloud_core_network",
    "release_id": "rel-xxx",
    "build_id": "build-xxx",
    "snapshot_count": 5
  },
  "trace": {
    "request_id": "",
    "total_duration_ms": 342.5,
    "stages": [
      {"name": "query_understanding", "duration_ms": 12.3, "summary": "intent=command_usage, 2 entities"},
      {"name": "retrieval_router", "duration_ms": 0.1, "summary": "routes=3, fusion=weighted_rrf"},
      {"name": "resolve_scope", "duration_ms": 5.2, "summary": "snapshots=5"},
      {"name": "embedding", "duration_ms": 89.4, "summary": "dim=1024"},
      {"name": "retrieve", "duration_ms": 198.7, "summary": "candidates=53"},
      {"name": "fusion", "duration_ms": 0.3, "summary": "fused=38, method=weighted_rrf"},
      {"name": "rerank", "duration_ms": 0.2, "summary": "ranked=10"},
      {"name": "assembly", "duration_ms": 35.1, "summary": "items=20"}
    ]
  },
  "candidate_count": 10,
  "fusion_method": "weighted_rrf",
  "query_embedding_dim": 1024,
  "route_traces": [
    {"route": "lexical_bm25", "attempted": true, "candidate_count": 19, "skipped_reason": "", "latency_ms": 45.2},
    {"route": "dense_vector", "attempted": true, "candidate_count": 19, "skipped_reason": "", "latency_ms": 138.5},
    {"route": "entity_exact", "attempted": true, "candidate_count": 15, "skipped_reason": "", "latency_ms": 12.1}
  ]
}
```

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `observability/TraceCollector.java` | 阶段级计时器 |
| `domain/Trace.java` | Trace record |
| `domain/TraceStage.java` | TraceStage record |
| `domain/RouteTrace.java` | 路由追踪 record |
| `rerank/RerankPipeline.java` | 包含 RerankTraceStep 内部 record |
| `application/SearchService.java` | 组装所有 debug 信息 |

## 具体实现细节

### TraceCollector 实现

```java
public class TraceCollector {
    private final long startNanos = System.nanoTime();
    private final List<TraceStage> stages = new ArrayList<>();
    private final Map<String, Long> stageStartTimes = new HashMap<>();

    public void startStage(String name) {
        stageStartTimes.put(name, System.nanoTime());
    }

    public void endStage(String name, String outputSummary) {
        Long startTime = stageStartTimes.remove(name);
        double durationMs = startTime != null
                ? (System.nanoTime() - startTime) / 1_000_000.0 : 0.0;
        stages.add(new TraceStage(name, "", outputSummary, durationMs, ""));
    }

    public Trace buildTrace(String requestId) {
        double totalDuration = (System.nanoTime() - startNanos) / 1_000_000.0;
        return new Trace(requestId, List.copyOf(stages), totalDuration);
    }
}
```

### 阶段名称汇总

| 阶段名 | 对应 Pipeline Stage | 记录位置 |
|--------|---------------------|----------|
| `query_understanding` | Stage 02 | SearchService:95 |
| `retrieval_router` | Stage 03 | SearchService:103 |
| `resolve_scope` | Stage 04 | SearchService:136 |
| `embedding` | Stage 04（可选） | SearchService:149 |
| `retrieve` | Stage 05 | SearchService:160 |
| `fusion` | Stage 06 | SearchService:167 |
| `rerank` | Stage 07 | SearchService:178 |
| `assembly` | Stage 08 | SearchService:184 |

### 日志级别

| 级别 | 场景 |
|------|------|
| INFO | 请求开始（domain, channel, db）、请求完成（items 数） |
| WARN | Embedding 失败、Model/LLM reranker 失败、pg_trgm 不可用 |
| DEBUG | trigram/LIKE 降级触发 |
| ERROR | 多个 active release |

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **OpenTelemetry Traces** | 类似的 span 模型：每个操作一个 span，记录名称、耗时、属性 |
| **Debug Mode** | 类似 Elasticsearch 的 `explain` 参数，开发调试时开启 |
| **Per-request Timing** | 标准的请求级性能分析，类似 APM 工具的 trace view |
| **Route Traces** | 类似分布式追踪的 service map，显示各路由的执行状态 |

## 当前实现的不足

### 1. 没有 request ID

`TraceCollector` 支持传入 requestId，但 `SearchService` 传的是空字符串。无法关联日志和请求。

**改进方向**：使用 UUID 或 snowflake 生成 per-request ID，传播到所有日志。

### 2. TraceCollector 非线程安全

`stageStartTimes` 使用 HashMap，如果阶段并行执行会有并发问题。

**改进方向**：使用 `ConcurrentHashMap`，或确保只在单线程中使用。

### 3. 没有 metrics 暴露

只有 trace 和日志，没有 Prometheus/Grafana metrics。无法做 SLI 监控（如 P99 延迟、成功率）。

**改进方向**：添加 Micrometer metrics：`search_total`、`search_duration_seconds`、`route_candidates` 等。

### 4. debug 信息缺少 rerank traces

`route_traces` 已包含路由追踪，但 rerank pipeline 的 `RerankTraceStep` 没有暴露到 debug 输出。

**改进方向**：在 SearchService 中保存 `RerankResult.traces` 并添加到 debug map。

### 5. 无结构化日志

日志使用 `log.info/warn`，但格式不统一，不适合日志聚合系统（如 ELK）。

**改进方向**：使用 JSON 格式日志，包含 request_id、domain、intent 等结构化字段。

### 6. 无分布式追踪集成

没有集成 OpenTelemetry/Jaeger/Zipkin，无法追踪跨服务调用（如 LLM service 调用）。

**改进方向**：集成 Spring Cloud Sleuth 或 OpenTelemetry Java Agent。

### 7. Trace 不记录输入摘要

`TraceStage.inputSummary` 始终为空字符串，只有 `outputSummary`。

**改进方向**：在 `startStage` 时记录输入摘要（如 query text、candidate count）。

### 8. 没有 slow query 告警

没有设置延迟阈值，无法自动检测慢请求。

**改进方向**：设置阈值（如 >2s），超过时 log.warn 并添加到 issues。
