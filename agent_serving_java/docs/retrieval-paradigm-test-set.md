# 检索范式测试集 — 算子化消融实验

> 配套：可插拔检索算子系统（`com.coremasterkb.serving.operator`）
> 用途：通过一组**消融范式**量化每个检索组件（检索范围 / 重排 / 多路融合）的**单独增益**，对标现有 `/api/v1/search`。
> 状态：11 个范式已写入控制库，发布为 `active` / version 1。
> 本文内容均依据**实际算子实现**（非 PRD 文档）整理。

---

## 1. 这些范式解决什么问题

现有 serving pipeline 是一条固定 11 阶段、硬编码顺序的链，导致：
- 各检索组件（多路检索 / 融合 / 重排）的**单独增益不清楚**；
- 无法快速搭建"只有 embedding""embedding+rerank""多路+融合"等不同检索范式做 A/B 对比。

算子系统把检索拆成可热插拔的算子，用 DAG 自由编排。本测试集用**控制变量法**设计：每个对照组**只变一个变量**，差异即可归因到该组件。

---

## 2. 范式清单（已入库）

控制库 `cloud_core_network_db`，表 `operator_paradigm` + `operator_paradigm_version`。

| 范式 ID | name | DAG | 终点 | 测什么 |
|---------|------|-----|------|--------|
| `pd-1064589e` | A1_dense_raw_text | query_embed → dense(raw_text) → collect | collect | **主基线**：纯向量召回上限 |
| `pd-f88dd966` | A2_fts_only | fts → collect | collect | 纯全文检索 |
| `pd-c104ec6f` | A3_entity_only | query_understanding → entity_exact → collect | collect | 纯实体精确匹配 |
| `pd-6a157e55` | B2_dense_question | dense(**question**) → collect | collect | generated_question 向量 |
| `pd-6671af80` | B3_dense_both | dense(**both**) → collect | collect | raw_text + question 合并 |
| `pd-d79537e7` | C1_dense_model_rerank | dense → **model_rerank** → collect | collect | 模型重排增益 |
| `pd-df0f2c18` | C2_dense_llm_rerank | dense → **llm_rerank** → collect | collect | LLM 重排增益 |
| `pd-a468445a` | D1_multi_rrf | dense ‖ fts → **rrf** → collect | collect | 多路 + 朴素 RRF |
| `pd-59daa022` | D2_multi_weighted_rrf | dense ‖ fts → **weighted_rrf** → collect | collect | 多路 + 加权 RRF |
| `pd-cd4b4e26` | D3_three_route_weighted_rrf | dense ‖ fts ‖ entity → weighted_rrf → collect | collect | 三路融合 |
| `pd-b918d458` | F1_full_replica_assemble | 全链 → model_rerank → **assemble** | contextPack | 复刻现有 pipeline，对标 `/api/v1/search` |

> **ID 注意**：上表 ID 来自当前库实例。若重新 seed，ID 会变；以 `GET /api/v1/paradigm` 或按 name 查库为准。
> `B1`（textKind=raw_text）= 主基线 `A1_dense_raw_text`，未单列。

---

## 3. 对照设计（每次只变一个变量）

| 对照组 | 变量 | 范式 | 回答的问题 |
|--------|------|------|-----------|
| **检索范围** | `dense_vector.textKind` | A1(raw_text) vs B2(question) vs B3(both) | 不同载体向量对召回的影响 |
| **重排增益** | 末端重排算子 | A1(无) vs C1(model) vs C2(llm) | 重排是否值得（含延迟代价） |
| **融合增益** | 路数 / 融合算法 | A1·A2 单路 vs D1·D2 双路 vs D3 三路；D1(rrf) vs D2(weighted) | 多路融合 / 加权是否有用 |
| **生产对标** | 整链 | F1 vs 现有 `/api/v1/search` | 新系统效果 ≥ 现有、延迟可接受 |

跑对照时**固定**：同一 `domain` / `release`、同一组带标注 query、同样 `topK`。

---

## 4. 关键概念

### 4.1 范式 JSON 结构

顶层 `{nodes, edges, output}`，`output` = `{nodeId, slot}`。

- **`query` 是隐式入口 slot**：算子未连线的 `query` 输入自动绑定到请求 query，无需画 Input 节点或连 query 边（`query_embed` / `fts` / `query_understanding` / `*_rerank` 都靠这个）。
- **`scope` 不是隐式入口**：每个检索 / 组装算子的 `scope` 输入**必须**从 `scope_resolve` 节点显式连线，否则编译报 `missing_required_input`。
- 融合算子（`rrf` / `weighted_rrf`）的 `candidates` 是 variadic（`CANDIDATE_LIST_MULTI`），允许多条边连入同一 `toSlot`。

### 4.2 `textKind`（检索范围）

`dense_vector` 算子参数，决定"同一查询向量去匹配哪一类检索单元"。

| textKind | 实际过滤值 | 命中单元 |
|----------|-----------|----------|
| `raw_text`（默认） | `raw_text` | 文档原文正文 |
| `question` | `generated_question` | LLM 生成问题 |
| `both` | `raw_text` + `generated_question` | 两者合并 |

**实现要点（与 PRD 不一致处）**：参数名叫 `textKind`，但真实 SQL（`OperatorEmbeddingMapper.xml`）过滤的是 **`asset_retrieval_units.unit_type`**，不是 embedding 自己的 `text_kind` 列——因为后者在资产数据里统一是 `'full'`，无法区分载体。`DISTINCT ON (retrieval_unit_id)` 保证一个单元多条 embedding 时不产生重复候选。

### 4.3 加权融合 `weighted_rrf.weights`

按候选的 **source 名**分组（不是节点 id）：

| 算子 | source 名 |
|------|-----------|
| `dense_vector` | `dense_vector` |
| `fts`（tsvector 主路） | `lexical_bm25`（降级路 `trigram_fallback` / `like_fallback`） |
| `entity_exact` | `entity_exact` |

### 4.4 两个输出算子：`collect` vs `assemble`

| | `collect`（收集候选） | `assemble`（组装上下文） |
|--|----------------------|--------------------------|
| 定位 | 测试用终点 | 生产用终点 |
| 输入 slot | `candidates` | `candidates` + `understanding` + `scope` |
| 输出类型 | `CANDIDATE_LIST` | `CONTEXT_PACK` |
| 做的事 | 按 maxItems **截断**，原样返回 | 下钻 + 图扩展 + 证据分组 + 压缩 |
| 顶层响应 key | `candidates`（数组） | `contextPack`（对象） |

**为什么两个都要**：评测必须测"裸"检索结果。`collect` 是恒等透传，输出可干净归因、可算 IR 指标；`assemble` 会做图扩展（无中生有加入未召回段落）、压缩截断（丢条目），并把结果重组成分区对象、丢掉逐候选分数——用它测会把"组装能力"混进"检索能力"，指标失真。故：**`collect` 用来测，`assemble` 用来上线。**

### 4.5 输出 JSON 结构对比

**collect** → 均质候选数组，每项 5 字段，带 `scoreChain`：
```json
{
  "candidates": [
    {
      "id": "ru-8f3a...",
      "score": 0.83,
      "source": "dense_vector",
      "scoreChain": {"rawScore": 0.83, "fusionScore": 0.0, "rerankScore": 0.0, "routeSources": ["dense_vector"]},
      "metadata": {"text": "...", "title": "...", "unit_type": "raw_text", "document_snapshot_id": "...", "...": "..."}
    }
  ]
}
```

**assemble** → 单个 `ContextPack` 对象，8 个分区，与 `/api/v1/search` 同构：
```json
{
  "contextPack": {
    "query": { },
    "items": [ ],
    "relations": [ ],
    "sources": [ ],
    "evidenceGroups": [ ],
    "issues": [ ],
    "suggestions": [ ],
    "debug": { }
  }
}
```

> `debug=true` 时，两种响应顶层都追加 `trace`（各算子耗时/输入输出摘要）、`domain`、`channel`。

### 4.6 为什么需要 `collect`，不直接用 `assemble`

两个算子服务于两个不同目的，而 `assemble` 的加工恰恰会**破坏评测所需的信号**。若只保留 `assemble`，算子系统最核心的诉求——量化每个检索组件的增益——就做不成了。

**根本原因：评测要的是"裸"检索结果。** 消融实验必须"只测被试组件、其余不变"。`collect` 是恒等透传（只截断、不改内容/顺序），输出即检索/融合/重排链的真实结果，可干净归因、可算 recall / precision / MRR / NDCG。

**`assemble` 为什么会污染指标**（它调 `ContextAssembler` 做 `seed → 下钻 → 图扩展 → 证据分组 → 压缩`）：

1. **图扩展"无中生有"** —— 沿关系图加入检索器**根本没召回**的段落；用它算 precision 等于把"组装能力"算进"检索能力"，归因失真。
2. **压缩 / token 预算丢条目** —— 为塞进 LLM 上下文而合并、截断；recall 被"组装丢了多少"污染，而非反映检索真实召回。
3. **结构变了，没法算指标** —— 输出从"按 `retrieval_unit_id` 排序、带 `score` 的扁平列表"变成 `items / sources / evidenceGroups / relations` 的分区对象，**顶层连逐候选分数都没有**，标准 IR 指标无从计算。
4. **变量不止一个** —— 测"rerank 有没有用"时，`assemble` 又在 rerank 之后叠了第二层变换，两个变量混在一起。

> 一句话：`assemble` 测的是"检索 + 组装"的合成效果，`collect` 才能测纯检索。

**其它现实理由**：

- **输入成本 / 失败面更小**：`assemble` 强制要 `understanding` + `scope` 两个额外输入，还要跑下钻 DB 查询、图 BFS、可能的 LLM 压缩。测"只有 embedding"的范式根本不需要这些；`collect` 只要 `candidates` 一个输入，链更短、更不易出错。
- **对标对象不同**：`assemble` 输出与 `/api/v1/search` 同构，是为了**生产范式能和现有 pipeline 对标**；测试范式要对标的是**标注真值**（标注通常打在检索单元/文档粒度，不是组装后的上下文粒度），`collect` 的扁平候选正好对得上。

**结论**：范式输出类型由终点算子决定（PRD 决策 5），同一套算子因此服务两类消费者——`collect` 用来测（评测系统算指标），`assemble` 用来上线（喂 LLM / 前端）。缺了 `collect`，系统就只能"出成品上下文"，失去量化检索质量的能力，而那正是这套系统要解决的头号问题。

### 4.7 范式与 domain 的关系

**简短结论：范式定义本身不区分 domain，但每次执行会绑定一个 domain。** 两层分开看：

**① 定义 / 存储 —— 域无关（全局）**
- 范式表 `operator_paradigm` / `operator_paradigm_version` 存在 `defaultDataSource` 控制库，是域无关的全局配置（见 §7）。
- `ParadigmMapper` 的 CRUD 都在**未设 `DomainContext`** 的线程上跑，路由 DataSource 回落到控制库。
- 范式 DAG 里没有任何 domain 字段，是一份**跨域可复用的模板**，所有 domain 共享同一份定义。

**② 执行 —— domain 是每次调用的运行时参数**
- domain 由请求 body 传入（`RunArgs.domain`），缺省用 `serving.default-domain`。
- `ParadigmExecutor` 每个节点执行前 `DomainContext.set(ctx.domain())`，检索算子（`entity_graph` / `fts` / `dense_vector` / `entity_exact`）因此打到**该 domain 自己的库**；`domainPoolManager.getDataSource(domain)` 先做连通性校验。
- domain 还驱动：`scope_resolve`（`domain + channel` → 生效 release / 快照范围）、`query_understanding`（按 domain 取 profile）、LLM `setKnowledgeDomain(domain)`。

**一句话**：范式 = 跨 domain 通用的检索流程模板；domain = 调用时注入的执行上下文，决定"这套流程跑在哪个域的数据上"。同一个范式可对多个 domain 分别 `search`，无需复制。若要"不同 domain 用不同流程"，当前做法是**建多个范式**（按 name 区分），而非在单个范式内分域配置。

---

## 5. 如何调用

前置：`agent_serving_java`（8081）已启动，PostgreSQL + 已发布 release 就绪；向量 / 重排算子依赖 `llm_service`（8900）。

### 5.1 按 ID 执行已发布范式（测试系统入口）

```
POST http://localhost:8081/api/v1/paradigm/{id}/search?version={N?}
body: {"query": "SMF 会话建立流程", "domain": "cloud_core_network", "channel": "...", "debug": false}
```
不带 `version` 用 `current_version`。例：textKind 三向对比调 `pd-1064589e` / `pd-6a157e55` / `pd-6671af80`。

### 5.2 内联执行（不落库，便于试验改图）

```
POST http://localhost:8081/api/v1/paradigm/run
body: {"paradigm": {nodes, edges, output}, "query": "...", "domain": "..."}
```

### 5.3 仅编译校验

```
POST http://localhost:8081/api/v1/paradigm/validate
body: {"paradigm": {nodes, edges, output}}   → {valid, errors}
```

> **代理提示**：从脚本调用本机服务时务必**绕过系统 HTTP 代理**（否则 localhost 请求会被拦成 502）。

---

## 6. 范式管理 API 速查

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/paradigm` | 建草稿 `{name, description?, graph?}` → 返回 id |
| GET | `/api/v1/paradigm` | 列出全部 |
| GET | `/api/v1/paradigm/{id}` | 查范式（含草稿 + current_version） |
| PUT | `/api/v1/paradigm/{id}` | 更新草稿 `{graph}` |
| POST | `/api/v1/paradigm/{id}/publish` | 发布（编译校验 → 不可变版本 → active） |
| POST | `/api/v1/paradigm/{id}/rollback?version=N` | 回滚 current_version |
| POST | `/api/v1/paradigm/{id}/archive` | 归档 |
| DELETE | `/api/v1/paradigm/{id}` | 删除（须先归档） |
| GET | `/api/v1/operator/catalog` | 算子目录（前端画布渲染） |

---

## 7. 数据落地

```
operator_paradigm          -- 元数据 + 可编辑草稿(draft_graph_json), current_version, status
operator_paradigm_version  -- 每次发布的不可变快照(graph_json), UNIQUE(paradigm_id, version)
```
位于 `defaultDataSource` 库（本环境 = `cloud_core_network_db`），域无关的全局配置。启动时由 `ParadigmSchemaInitializer` 幂等建表。

本测试集由 seed 脚本按 name 幂等写入，`created_by='claude-seed'`，未触碰现有 `test_*` 范式。

---

## 8. 相关文档

- 需求：[`docs/requirements/2026-06-22-pluggable-retrieval-operator-system-prd.md`](requirements/2026-06-22-pluggable-retrieval-operator-system-prd.md)
- 实施计划：[`docs/requirements/2026-06-22-pluggable-retrieval-operator-system-plan.md`](requirements/2026-06-22-pluggable-retrieval-operator-system-plan.md)
- 现有 pipeline：`docs/pipeline-01..09-*.md`
- 算子源码：`src/main/java/com/coremasterkb/serving/operator/`
