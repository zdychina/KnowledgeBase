# Pipeline Stage 04: 作用域解析与 Embedding 生成

## 概述

本阶段完成两个独立但并行的准备工作：

1. **作用域解析**：根据 domain + channel 确定当前活跃的 release → build → document snapshots，为后续检索提供数据可见范围
2. **Query Embedding 生成**：将用户查询文本转为向量，供 dense_vector 路由使用

## 流程图

```
SearchService.search() 中 Stage 4
  │
  ├─ resolveActiveScope(domain, channel)
  │   │
  │   ├─ 1. 查询 active release
  │   │     └─ SELECT FROM asset_publish_releases WHERE status='active' AND domain=?
  │   │
  │   ├─ 2. 过滤 channel（可能多个 active release 在不同 channel）
  │   │     ├─ 0 个 → throw no_active_release
  │   │     └─ >1 个 → throw multiple_active_releases
  │   │
  │   ├─ 3. 查询 build 下的 active snapshots
  │   │     └─ SELECT FROM asset_build_document_snapshots WHERE build_id=? AND status='active'
  │   │
  │   └─ 4. 构建 ActiveScope
  │         ├─ releaseId
  │         ├─ buildId
  │         ├─ snapshotIds: [id, ...]
  │         └─ documentSnapshotMap: {documentId → snapshotId}
  │
  ├─ [并行] Embedding 生成（仅当 dense_vector 路由启用时）
  │   │
  │   ├─ 检查 dense_vector 路由是否 enabled
  │   ├─ 检查 EmbeddingClient.isConfigured()
  │   ├─ embeddingClient.embed(queryText)
  │   │   ├─ llmClient.embed([queryText], model, dimensions)
  │   │   ├─ POST /api/v1/models/embeddings
  │   │   └─ 解析 response.data[0].embedding → float[]
  │   │
  │   └─ 失败 → queryEmbedding = null，dense_vector 路由自动跳过
  │
  └─ 输出
      ├─ ActiveScope: 限定检索范围
      └─ float[] queryEmbedding: 供 DenseVectorRetriever 使用
```

## 输入

| 输入 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `effectiveDomain` | String | SearchService 从 request/default 解析 | 域名称 |
| `channel` | String | request 或 registry 默认值 | 发布通道 |
| `routePlan` | RetrievalRoutePlan | Stage 03 | 判断 dense_vector 是否启用 |
| `request.query()` | String | Stage 01 | 用户查询文本 |

## 输出

### ActiveScope（record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `releaseId` | String | 当前活跃 release ID |
| `buildId` | String | release 关联的 build ID |
| `snapshotIds` | List\<String\> | 活跃 document snapshot ID 列表（默认空 List） |
| `documentSnapshotMap` | Map\<String, String\> | document ID → snapshot ID 映射（默认空 Map） |

compact constructor 保证 null safety：`snapshotIds` 和 `documentSnapshotMap` 不为 null。

### queryEmbedding

| 字段 | 类型 | 说明 |
|------|------|------|
| `queryEmbedding` | `float[]` | 查询向量，1024 维。可为 null（dense_vector 不可用时） |

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `repository/AssetRepository.java` | **核心**，`resolveActiveScope()` 方法 |
| `domain/ActiveScope.java` | 作用域 record |
| `infrastructure/EmbeddingClient.java` | Embedding 封装，调用 LlmClient |
| `infrastructure/LlmClient.java` | LLM 服务客户端，`embed()` 方法 |
| `entity/AssetPublishRelease.java` | release 实体 |
| `entity/AssetBuildDocumentSnapshot.java` | build snapshot 实体 |
| `mapper/AssetPublishReleaseMapper.xml` | `selectActiveByDomain` SQL |
| `mapper/AssetBuildDocumentSnapshotMapper.java` | `selectByBuildIdAndStatus` 接口 |
| `application/SearchService.java` | 调用入口，trace 记录 |

## 数据库表结构

### asset_publish_releases

```sql
SELECT id, status, domain, channel, build_id AS buildId
FROM asset_publish_releases
WHERE status = 'active' AND domain = #{domain}
```

每个 domain + channel 最多一个 active release（否则抛 `multiple_active_releases`）。

### asset_build_document_snapshots

```sql
SELECT ... FROM asset_build_document_snapshots
WHERE build_id = #{buildId} AND status = 'active'
```

一个 build 下可能有多个 document snapshot（每篇文档一个 snapshot）。

## 配置参数

### application.yml

```yaml
serving:
  embedding:
    model: ${EMBEDDING_MODEL:embedding-3}
    dimensions: ${EMBEDDING_DIMENSIONS:1024}
  llm:
    base-url: ${LLM_SERVICE_URL:http://localhost:8900}
```

### Embedding 请求格式

```
POST {base-url}/api/v1/models/embeddings
{
  "input": ["用户查询文本"],
  "model": "embedding-3",
  "dimensions": 1024,
  "caller_service": "serving",
  "knowledge_domain": "cloud_core_network"
}
```

响应格式：

```json
{
  "data": [
    {
      "embedding": [0.012, -0.034, ...],  // 1024 个 float
      "index": 0
    }
  ]
}
```

## 具体实现细节

### 1. 作用域解析流程

```java
public ActiveScope resolveActiveScope(String domain, String channel) {
    // 参数 fallback
    String effectiveDomain = (domain != null) ? domain : "default";
    String effectiveChannel = (channel != null) ? channel : "prod";

    // 查询 active releases
    List<AssetPublishRelease> releases = releaseMapper.selectActiveByDomain(effectiveDomain);

    // 过滤 channel
    List<AssetPublishRelease> filtered = releases.stream()
            .filter(r -> effectiveChannel.equals(r.getChannel()))
            .toList();

    // 校验唯一性
    if (filtered.isEmpty())     throw new IllegalArgumentException("no_active_release");
    if (filtered.size() > 1)    throw new IllegalArgumentException("multiple_active_releases");

    // 获取 build 下的 snapshots
    AssetPublishRelease release = filtered.get(0);
    List<AssetBuildDocumentSnapshot> snapshots =
            buildSnapshotMapper.selectByBuildIdAndStatus(release.getBuildId(), "active");

    // 构建 ActiveScope
    List<String> snapshotIds = new ArrayList<>();
    Map<String, String> documentSnapshotMap = new HashMap<>();
    for (AssetBuildDocumentSnapshot snap : snapshots) {
        if (snap.getDocumentSnapshotId() != null) {
            snapshotIds.add(snap.getDocumentSnapshotId());
        }
        if (snap.getDocumentId() != null && snap.getDocumentSnapshotId() != null) {
            documentSnapshotMap.put(snap.getDocumentId(), snap.getDocumentSnapshotId());
        }
    }
    return new ActiveScope(release.getId(), release.getBuildId(), snapshotIds, documentSnapshotMap);
}
```

### 2. Embedding 生成流程

在 `SearchService` 中的调用逻辑：

```java
// 仅在 dense_vector 路由启用且 EmbeddingClient 可用时生成
boolean denseEnabled = routePlan.routes().stream()
        .anyMatch(r -> "dense_vector".equals(r.name()) && r.enabled());

if (denseEnabled && embeddingClient.isConfigured()) {
    queryEmbedding = embeddingClient.embed(request.query());
    // 失败 → log.warn，不中断管线
}
```

`EmbeddingClient.embed()` 实现：

```java
public float[] embed(String text) {
    Map<String, Object> response = llmClient.embed(List.of(text), model, dimensions);
    List<Map<String, Object>> data = (List<Map<String, Object>>) response.get("data");
    if (data != null && !data.isEmpty()) {
        List<Number> embedding = (List<Number>) data.get(0).get("embedding");
        if (embedding != null) {
            float[] result = new float[embedding.size()];
            for (int i = 0; i < embedding.size(); i++) {
                result[i] = embedding.get(i).floatValue();
            }
            return result;
        }
    }
    return null;
}
```

### 3. Trace 记录

```java
trace.startStage("resolve_scope");
scope = resolveActiveScope(effectiveDomain, channel);
trace.endStage("resolve_scope", "snapshots=" + scope.snapshotIds().size());

trace.startStage("embedding");
queryEmbedding = embeddingClient.embed(request.query());
trace.endStage("embedding", "dim=" + (queryEmbedding != null ? queryEmbedding.length : 0));
```

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Release-based Scoping** | 类似 CI/CD 的发布模型，检索限定在已发布的 snapshot 上，避免读到未完成数据 |
| **Snapshot Isolation** | 类似数据库 MVCC，每次发布生成一组不可变 snapshot，检索结果稳定一致 |
| **Lazy Embedding** | 仅在需要时才调用 embedding 服务，避免无效 LLM 调用 |
| **Domain + Channel 多维度** | 类似 SaaS 多租户 + 环境隔离（prod/staging/dev） |
| **Graceful Degradation** | embedding 失败时管线继续，dense_vector 路由自动跳过 |

## 当前实现的不足

### 1. 没有 snapshot 缓存

每次请求都查询 `asset_publish_releases` 和 `asset_build_document_snapshots`。如果发布不频繁，这些查询结果可以缓存。

**改进方向**：添加带 TTL 的 scope 缓存（如 60s），新发布后主动失效。

### 2. Embedding 无缓存

相同查询每次都调用 LLM embedding 服务，浪费 token 和延迟。

**改进方向**：添加 query → embedding 的 LRU 缓存（TTL=5min），高频查询命中缓存。

### 3. 作用域解析与 embedding 无法真正并行

当前代码虽然是两个独立操作，但在 SearchService 中是串行执行的。

**改进方向**：使用 `CompletableFuture` 并行执行 scope 解析和 embedding 生成。

### 4. EmbeddingClient 直接强转类型

`(List<Map<String, Object>>) response.get("data")` 和 `(List<Number>) data.get(0).get("embedding")` 直接强转，如果 LLM 返回格式异常会抛 ClassCastException。

**改进方向**：添加类型检查和容错处理。

### 5. snapshotIds 可能为空但不报错

如果 release 存在但 build 下没有任何 active snapshot，返回空的 `ActiveScope`，后续检索会返回 0 结果，但用户无法区分是"没有发布数据"还是"确实没找到"。

**改进方向**：在 scope 解析阶段检查 snapshotIds 为空的情况，在 debug 中给出提示。

### 6. release 查询缺少索引确认

`selectActiveByDomain` 按 `status + domain` 查询，如果数据量大，需要确认有联合索引。

**改进方向**：添加 `(status, domain, channel)` 联合索引。
