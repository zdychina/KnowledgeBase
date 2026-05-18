# ActiveScope 生成逻辑详解

> 对应代码：`AssetRepository.resolveActiveScope()`

---

## 一、它解决什么问题

每次检索必须限定在**某个已发布版本**的数据范围内，不能把所有历史版本的文档都检索一遍。`ActiveScope` 就是"当前这次检索允许看哪些数据"的边界描述，后续所有 SQL 查询都用它里面的 `snapshotIds` 做过滤。

---

## 二、数据库表结构（两张表）

```
asset_publish_releases                    asset_build_document_snapshots
──────────────────────────────            ────────────────────────────────────────
id            String  (release主键)       document_snapshot_id  String (快照主键)
status        String  'active'/'inactive' build_id              String (关联release的build)
domain        String  'cloud_core_network'document_id           String (原始文档ID)
channel       String  'prod'/'test'       selection_status      String 'active'/'excluded'
build_id      String  (关联build)
```

**表之间的关系：**

```
asset_publish_releases
  └── build_id ──→ asset_build_document_snapshots (build_id)
                       └── document_snapshot_id
                       └── document_snapshot_id
                       └── document_snapshot_id
                       ...
```

一个 release 对应一个 build，一个 build 包含多个 document snapshot。

---

## 三、完整执行流程

调用入口在 `SearchService` 第 5 阶段：

```java
scope = assetRepository.resolveActiveScope(effectiveDomain, channel);
```

### Step 1 — 参数防御

```java
String effectiveDomain = (domain != null) ? domain : "default";
String effectiveChannel = (channel != null) ? channel : "prod";
```

`domain` 和 `channel` 都做了 null 保护，channel 缺省为 `"prod"`。

---

### Step 2 — 查询该 domain 所有 active release

```java
List<AssetPublishRelease> releases =
    releaseMapper.selectActiveByDomain(effectiveDomain);
```

执行的 SQL：

```sql
SELECT id, status, domain, channel, build_id AS buildId
FROM asset_publish_releases
WHERE status = 'active'
  AND domain = #{domain}      -- 只看指定 domain
```

注意：**SQL 里没有过滤 channel**，只过滤了 `status='active'` 和 `domain`，返回的可能是多个 channel 的 active release 列表。

---

### Step 3 — Java 层按 channel 过滤

```java
List<AssetPublishRelease> filtered = releases.stream()
        .filter(r -> effectiveChannel.equals(r.getChannel()))
        .toList();
```

在 Java 里再按 channel 筛选，只留下目标 channel 的 release。这样设计的原因：SQL 已经拿到的是内存中的少量行，Java 过滤比多一个 SQL 参数更容易测试和调试。

---

### Step 4 — 严格校验：有且仅有 1 个

```java
if (filtered.isEmpty()) {
    throw new IllegalArgumentException("no_active_release");
}
if (filtered.size() > 1) {
    throw new IllegalArgumentException("multiple_active_releases");
}
```

| 情况 | 行为 |
|---|---|
| 0 个 | 抛 `no_active_release` → HTTP 503 |
| 1 个 | 正常继续 |
| >1 个 | 抛 `multiple_active_releases` → HTTP 409，说明数据状态异常 |

这是一个**数据完整性守卫**：系统假设正常运行时每个 domain+channel 有且仅有一个 active release。

---

### Step 5 — 查询该 build 下所有 active 快照

```java
AssetPublishRelease release = filtered.get(0);

List<AssetBuildDocumentSnapshot> snapshots =
    buildSnapshotMapper.selectByBuildIdAndStatus(release.getBuildId(), "active");
```

执行的 SQL：

```sql
SELECT document_snapshot_id, build_id, document_id, selection_status
FROM asset_build_document_snapshots
WHERE build_id = #{buildId}
  AND selection_status = #{selectionStatus}   -- 'active'
```

`selection_status = 'active'` 排除了被"软排除"的文档快照（比如某文档在 build 里被标记为 excluded）。

---

### Step 6 — 组装 ActiveScope

```java
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

return new ActiveScope(release.getId(), release.getBuildId(),
                       snapshotIds, documentSnapshotMap);
```

同一个循环同时填两个数据结构：

| 字段 | 内容 | 用途 |
|---|---|---|
| `releaseId` | release 的主键 ID | debug 信息 |
| `buildId` | build 的 ID | debug 信息 |
| `snapshotIds` | 所有 active 快照 ID 的列表 | **所有检索 SQL 的 `IN (...)` 过滤** |
| `documentSnapshotMap` | `documentId → snapshotId` | `ContextAssembler` 里做引用解析 |

---

## 四、生成出来的 ActiveScope 怎么被使用

### 检索 SQL 里的 `IN (snapshotIds)`

三个检索器的 SQL 都用 `snapshotIds` 作为范围限制：

```sql
-- FtsRetriever / DenseVectorRetriever / ContextAssembler
WHERE ru.document_snapshot_id IN (#{sid1}, #{sid2}, ...)
```

这确保了检索到的内容只来自当前 active release 对应的文档版本，旧版本的数据不会混入。

### `documentSnapshotMap` 的用途

在 `ContextAssembler` 里，已知 `documentId` 需要反查 `snapshotId` 时使用，避免再发一次数据库查询。

---

## 五、完整数据链路图

```
POST /api/v1/search  domain="cloud_core_network"  channel="prod"
        │
        ▼
asset_publish_releases
  WHERE status='active' AND domain='cloud_core_network'
        │
        │  Java 过滤 channel='prod'
        │  校验：有且仅有 1 条
        ▼
  release: { id="R-001", buildId="B-042", channel="prod" }
        │
        │  build_id = "B-042"
        ▼
asset_build_document_snapshots
  WHERE build_id='B-042' AND selection_status='active'
        │
        ▼
  snapshots: [
    { documentSnapshotId="S-101", documentId="D-01" }
    { documentSnapshotId="S-102", documentId="D-02" }
    { documentSnapshotId="S-103", documentId="D-05" }
  ]
        │
        ▼
ActiveScope {
  releaseId           = "R-001"
  buildId             = "B-042"
  snapshotIds         = ["S-101", "S-102", "S-103"]   ← 所有 SQL IN 过滤的参数
  documentSnapshotMap = {"D-01":"S-101", "D-02":"S-102", "D-05":"S-103"}
}
```

---

## 六、设计要点小结

| 设计决策 | 原因 |
|---|---|
| channel 在 Java 过滤而不是 SQL | 便于测试，且 active release 总量很少 |
| 强制 exactly-1 校验 | 多 active release 是数据错误，应快速失败而不是随机取一个 |
| 两次独立查询而不是 JOIN | 逻辑清晰，每次查询职责单一 |
| `selection_status='active'` | 支持 build 内文档软排除，不需要重建整个 release |
| `snapshotIds` 作为统一过滤参数 | 所有检索器共用同一个 scope，保证数据一致性 |
