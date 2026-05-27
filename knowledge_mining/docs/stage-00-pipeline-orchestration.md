# Stage 0 — Pipeline 编排框架

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Pipeline 编排框架负责：
1. 定义数据契约（所有中间产物的 frozen dataclass）
2. 定义操作协议（Protocol 接口）
3. 提供两种执行模式：顺序式 `MiningPipeline` 和流式并发 `StreamingPipeline`
4. 通过 `PipelineConfig` 实现热插拔（每个 stage 的实现可替换）
5. 在 `run.py` 中串联完整生命周期：ingest → parse → segment → enrich → discourse → retrieval_units → DB 写入 → build → publish

---

## 2. 完整执行流程

```
run.py:run()
│
├── 1. 加载配置
│   ├── MiningConfig (从 .env 读取 PG/LLM/Embedding 配置)
│   ├── resolve_domain(domain_id) → registry → database_url_env → conninfo
│   ├── load_domain_pack(domain_id) → DomainProfile
│   └── _create_dbs(conninfo) → (AssetCoreDB, MiningRuntimeDB)
│
├── 2. 初始化 LLM 服务
│   ├── _init_llm() → {question_generator, enricher, discourse_relation_builder, contextualizer}
│   ├── _init_embedding() → EmbeddingGenerator (LLM Service or Zhipu)
│   └── LlmClient.register_template() × N (从 domain.yaml 注册模板)
│
├── 3. Phase 1a: Ingest + Classify
│   ├── ingest_directory(input_path) → List[RawFileData]
│   ├── 每文件: 计算 doc_key, 比对 hash → NEW/UPDATE/SKIP
│   └── SKIP 文档直接关联已有 snapshot, 不进 pipeline
│
├── 4. Phase 1b: StreamingPipeline (文档级并发)
│   ├── parse_stage      — 1 worker (CPU 密集)
│   ├── segment_stage    — 1 worker (含 build_seg_ids)
│   ├── enrich_stage     — max_workers workers (LLM 调用, I/O 密集)
│   ├── discourse_stage  — min(max_workers, 2) workers (LLM 调用)
│   └── retrieval_units_stage — max_workers workers (LLM 调用)
│
├── 5. Phase 1c: DB 写入 (主线程串行)
│   ├── select_snapshot → document_id + snapshot_id + link_id
│   ├── UPDATE 清理旧 snapshot 数据
│   ├── commit_segments → 逐条 INSERT asset_raw_segments
│   ├── build_relations → 逐条 INSERT asset_raw_segment_relations
│   ├── build_retrieval_units → 逐条 INSERT asset_retrieval_units
│   ├── embedding_generator.embed_batch() → INSERT asset_retrieval_embeddings
│   └── tracker.commit_document()
│
└── 6. Phase 2: Build & Publish
    ├── classify_documents() → NEW/UPDATE/SKIP/REMOVE
    ├── assemble_build() → build_id (全量 or 增量)
    ├── validate_build() (阶段占位, 实际校验在 assemble_build 内)
    └── publish_release() → release_id
```

---

## 3. 核心数据结构

### 3.1 DocumentContext (pipeline.py:36)

```python
@dataclass(frozen=True)
class DocumentContext:
    raw_file: RawFileData | None         # Phase 1a: ingest 产出
    profile: DocumentProfile | None      # Phase 1a: 从 file metadata 构造
    tree: SectionNode | None             # Phase 1b stage 1: parse 产出
    segments: tuple[RawSegmentData, ...] # Phase 1b stage 2-3: segment/enrich 产出
    relations: tuple[SegmentRelationData, ...] # Phase 1b stage 4: discourse 产出
    seg_ids: dict[str, str]              # Phase 1b stage 2: segment UUID 映射
    retrieval_units: tuple[RetrievalUnitData, ...] # Phase 1b stage 5 产出
    error: str | None                    # 任意 stage 失败时设置
    run_document_id: str | None          # 运行时文档 ID
    sequence_id: int                     # 输入顺序 (用于排序输出)
```

**设计要点**：
- frozen=True: 不可变, 每次 stage 返回新对象 (`with_updates()`)
- `with_updates()` 实现: 把所有字段复制到 dict → update → 重建 `DocumentContext`
- `error` 一旦被设置, 后续 stage 的 `_worker` 会检查并跳过

### 3.2 PipelineConfig (pipeline.py:77)

```python
@dataclass
class PipelineConfig:
    parser_factory: Callable[[str], Any]  # file_type → Parser
    segmenter: Segmenter | None          # SectionNode → [RawSegmentData]
    enricher: Any | None                 # LlmEnricher
    question_generator: Any | None       # LlmQuestionGenerator
    embedding_generator: Any | None      # EmbeddingGenerator
    discourse_relation_builder: Any | None  # DiscourseRelationBuilder
    contextualizer: Any | None           # LLMContextualizer
    domain_profile: Any | None           # DomainProfile
```

**组装位置**: `run.py:460-469`

---

## 4. 两种执行模式

### 4.1 MiningPipeline (顺序)

`pipeline.py:97-188`

- `process_document()` 按顺序调用: parse → segment → enrich → build_seg_ids → discourse → retrieval_units
- 内嵌 `stage_callback` 用于 runtime tracker
- 每步检查 `ctx.xxx is None` 后短路返回

### 4.2 StreamingPipeline (并发)

`pipeline.py:257-312`

- **线程模型**: 每个 stage 有 N 个 worker thread, 通过 Queue 串联
- **数据流**: `Queue[0] → [parse×1] → Queue[1] → [segment×1] → Queue[2] → [enrich×W] → Queue[3] → ...`
- **sentinel 终止**: 每阶段完成后发 sentinel, worker 退出
- **顺序保证**: 输入带 `sequence_id`, 输出按 `sequence_id` 排序

**Worker 线程 (`_worker`, pipeline.py:198-254)**:
1. 从 in_q 取 DocumentContext
2. 检查 error → 有则直接透传到 out_q
3. `tracker.start_stage()` 发事件
4. 执行 stage 函数
5. 异常时: `tracker.end_stage(status="failed")` + `ctx.with_updates(error=...)`
6. 成功时: `tracker.end_stage()` + result 推入 out_q

**并发度配置** (`run.py:555-561`):
```python
stages = [
    ("parse",           ..., 1),                      # CPU 密集
    ("segment",         ..., 1),                      # CPU 密集
    ("enrich",          ..., max_workers),             # LLM I/O
    ("discourse",       ..., min(max_workers, 2)),     # LLM I/O
    ("retrieval_units", ..., max_workers),             # LLM I/O
]
```

---

## 5. 错误处理

### 5.1 文档级错误

- `_worker` 捕获异常 → `ctx.with_updates(error=err_msg)` → 透传到下游
- Phase 1c 遍历 ctxs 时检查 `ctx.error` → `tracker.fail_document()`
- 部分文档失败不影响整个 run (run 状态仍 `completed`)

### 5.2 全局错误

- `run()` 外层 try-except → `tracker.fail_run()`
- `MiningCancelled`: 协作式取消, 在关键点调用 `_check_cancelled()` 检查 DB 中的 run status

### 5.3 已知缺陷

- stage event 不记录失败状态（`end_stage(status="failed")` 记录了，但 event 表没有对应的 status 列约束问题）
- 无法文档级重跑，需创建新 run
- `with_updates()` 每次重建整个 dict → 大量 segment 数据时的 copy 开销

---

## 6. 取消机制

- `MiningCancelled` 异常: 在 `_check_cancelled()` 中检查 `mining_runs.status = 'cancelled'`
- 检查点: Phase 1a 前, Phase 1b 前
- `_worker` 内不检查取消（已提交的任务仍会执行完成）

---

## 7. 增量处理

### 7.1 文档级增量

Phase 1a 中:
1. 对每个文件计算 `normalized_content_hash`
2. 查询 `asset_document_snapshot_links` JOIN `asset_document_snapshots` 找最新 snapshot 的 hash
3. hash 相同 → `action = "SKIP"` → 直接复用旧 snapshot
4. hash 不同 → `action = "UPDATE"` → 重新跑 pipeline + 清理旧 snapshot 数据

### 7.2 构建级增量

Phase 2 中:
1. `classify_documents()` 标记每文档 NEW/UPDATE/SKIP/REMOVE
2. `assemble_build()` 检测是否有 previous active build
   - 有: 增量构建 (保留旧 snapshot, 替换更新的)
   - 无: 全量构建
3. `publish_release()` 激活新 build

---

## 8. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/pipeline.py` | 386 | PipelineConfig, DocumentContext, MiningPipeline, StreamingPipeline, stage 函数 |
| `mining/jobs/run.py` | ~800 | 入口函数 run()/publish(), _run_pipeline(), _init_llm(), _init_embedding() |
| `mining/contracts/models.py` | 407 | 全部数据对象: RawFileData, SectionNode, ContentBlock, RawSegmentData, SegmentRelationData, RetrievalUnitData, MiningRunData 等 |
| `mining/contracts/protocols.py` | 85 | Protocol 接口: Segmenter, Enricher, QuestionGenerator, Contextualizer |
| `mining/infra/mining_config.py` | — | 从 .env 读取配置 (PG/LLM/Embedding/domain) |
| `mining/infra/pg_config.py` | — | PostgreSQL 连接配置 |
| `mining/infra/db.py` | — | AssetCoreDB + MiningRuntimeDB (DB adapter) |
| `mining/runtime.py` | — | RuntimeTracker (stage events, run/document 状态管理) |
| `mining/snapshot.py` | — | select_or_create_snapshot (文档快照管理) |

---

## 9. 工业化参考

| 参考 | 说明 |
|------|------|
| Apache Airflow DAG | 类似的 DAG 编排, 但我们是嵌入式轻量方案 |
| Unstructured.io Partition | 文档 → element 的 partition + chunking 管线 |
| LlamaIndex IngestionPipeline | 同样是 transform → embed 管线, 可插拔 |
| LangChain LCEL | 顺序/并发 chain 编排 |
| Prefect / Dask | 分布式 task 编排, 但我们用线程 + Queue 更轻量 |
| Scikit-learn Pipeline | fit → transform 流水线模式, 我们加了并发 |

---

## 10. 当前不足

1. **`with_updates()` 性能**: 每次调用重建 dict, 拷贝所有字段（包括大 segments tuple），高频调用场景有 GC 压力
2. **缺少背压**: 如果 enrich 很快但 segment 慢, Queue 会堆积; 无 Queue maxsize 限制
3. **Stage event 与文档错误脱节**: stage event 记录了 failed 状态, 但文档级只能看 error_message
4. **无断点续传**: run 中断后无法从某个 stage 恢复 (有 ResumePlan 数据结构但未实现)
5. **线程而非协程**: 使用 threading.Thread + Queue, 无法利用 async I/O (LLM HTTP 调用天然适合 async)
6. **DB 写入串行**: Phase 1c 在主线程逐文档串行写入, 大 batch 时是瓶颈
7. **PipelineConfig 用 Any**: enricher/question_generator 等字段类型是 `Any`, 无编译期类型检查
8. **无中间结果缓存**: 如果 pipeline 在 discourse 阶段失败, 前面 enrich 的 LLM 结果丢失
9. **缺少 stage 级重试**: LLM 调用失败时无自动重试机制, 直接标记文档失败
10. **commit 手动管理**: 多处 `runtime_db.commit()`, 异常路径可能遗漏或重复
