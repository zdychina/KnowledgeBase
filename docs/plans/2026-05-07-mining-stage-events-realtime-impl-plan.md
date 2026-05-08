# Mining Stage 事件实时化实现计划

- 任务：TASK-20260421-v11-knowledge-mining
- 日期：2026-05-07
- 作者：Claude

## 1. 任务目标

把 `mining_run_stage_events` 表里"内存阶段"的事件时间戳从"DB 写入时刻"还原成"stage 真实执行时刻"，并补全 StreamingPipeline 各 stage 缺失的事件，让 UI、断点续跑、性能分析、失败定位看到的都是真相。

## 2. 当前实现回顾

### 2.1 现状

- `knowledge_mining_zym/mining/jobs/run.py:469-479` 用 `StreamingPipeline` 把 6 个内存阶段（parse / segment / enrich / relations / discourse / retrieval_units）跑成 worker 线程流水线。
- `knowledge_mining_zym/mining/pipeline.py:240-268` 的 `_worker` 不发任何事件——`stage_callback` 形参在 StreamingPipeline 路径上从未被调用，是 dead code（残留自旧版同步 `MiningPipeline`）。
- `knowledge_mining_zym/mining/jobs/run.py:535-609` 在 Phase 1c 主线程串行写库时，借用 `segment` / `build_relations` / `build_retrieval_units` 这几个名字补埋点，注释也明说"track at commit time since pipeline ran in streaming"。

### 2.2 由此产生的问题

1. **事件时间戳偏离真实执行时间**：`segment` 事件 `started_at` 实际是"segment 数据写库开始"，时间晚于 enrich、relations、discourse、retrieval_units 在内存里完成的时刻。UI stepper 上看见 enrich 比 segment 还早完成。
2. **enrich / parse / discourse 在数据库里完全没有事件**：UI 永远显示"pending"或者从 asset 数据反推。
3. **失败定位变弱**：worker 抛错时没事件可记，只能进 ctx.error，UI 看不到具体哪个 stage 哪个文档挂了。
4. **断点续跑判定不可靠**：以"事件表是否存在 done 事件"为续跑依据时，会误判已完成。

## 3. 设计决策

### 3.1 事件源 = worker，写库不再发同名事件

- 内存阶段的事件由 `StreamingPipeline` 的 worker 在执行 stage 函数前后发送。事件名直接用 stage 名（`parse` / `segment` / `enrich` / `relations` / `discourse` / `retrieval_units`）。
- Phase 1c 写库的事件改名为 `*_persist`（见 3.4），与内存事件不撞车。
- 删除 `pipeline.py` 中已死的 `stage_callback` 分支，避免后续误用。

### 3.2 `DocumentContext` 加 `run_document_id`

- 现有 `DocumentContext` 已有 `sequence_id`，再加 `run_document_id: str | None`。
- `run.py` 在 Phase 1a 拿到 `rd_id` 后通过 `ctx.with_updates(run_document_id=rd_id)` 注入。
- worker 用 `ctx.run_document_id` 调 `tracker.start_stage(run_id, stage_name, rd_id)` —— 满足 OpenTelemetry 风格的"事件归属到具体文档"。

### 3.3 worker 中间件

`pipeline.py` 改造 `_worker`：

```python
def _worker(stage_name, fn, in_q, out_q, run_id, tracker):
    while True:
        ctx = in_q.get()
        if ctx is _SENTINEL:
            break
        rd_id = ctx.run_document_id
        evt = tracker.start_stage(run_id, stage_name, rd_id) if (tracker and rd_id) else None
        try:
            ctx = fn(ctx)
            if evt is not None:
                tracker.end_stage(evt, run_id, stage_name)
        except Exception as e:
            if evt is not None:
                tracker.fail_stage(evt, run_id, stage_name, str(e)[:500])
            ctx = ctx.with_updates(error=str(e))
        out_q.put(ctx)
```

`StreamingPipeline.__init__` 增加 `run_id: str` 与 `tracker: MiningRunTracker | None` 两个参数，传给所有 worker。

### 3.4 Phase 1c 写库事件改名

| 当前事件名 | 新事件名 | 含义 |
|---|---|---|
| `segment` | `segment_persist` | segment 数据写入 PG 的耗时 |
| `build_relations` | `relations_persist` | relations 数据写入 PG 的耗时 |
| `build_retrieval_units` | `retrieval_units_persist` | retrieval units / embeddings 写入 PG 的耗时 |

`select_snapshot` / `assemble_build` / `validate_build` / `publish_release` 是天然主线程串行的，名字保持不变。

### 3.5 并发安全

- `MiningRunTracker` 内部已经走 PG 连接池，PG 本身保证写入并发安全；worker 多线程并发 INSERT 不会出错。
- 可选优化：tracker 事件落库改成 lock-free 队列 + 主线程 flusher。本次**不做**，等并发热点出现再优化。

### 3.6 兼容性 / 迁移

- `mining_run_stage_events.stage` 字段是字符串，不需要 schema 变更。
- 改名只影响新生成的 run；历史 run 仍然保留 `segment` / `build_relations` / `build_retrieval_units` 旧值。UI 渲染逻辑要兼容两套（见 3.7）。

### 3.7 UI 对齐

- `scripts/mining_ui.py:917` 的 `STAGE_SPECS` 不变（驱动 stepper 的还是内存 stage 名）。
- `scripts/mining_ui.py:1004` 处读事件计算 stage 状态的逻辑要兼容老 run：内存 stage 的状态优先看新事件名；如果完全没有新事件名（老 run），fallback 到旧名。

## 4. 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `knowledge_mining_zym/mining/pipeline.py` | 修改 | `DocumentContext` 加 `run_document_id`；`StreamingPipeline.__init__` 加 `run_id` / `tracker` 参数；`_worker` 包事件埋点；删除 dead `stage_callback` 分支 |
| `knowledge_mining_zym/mining/jobs/run.py` | 修改 | Phase 1a 给 ctx 注入 `run_document_id`；构造 `StreamingPipeline` 时传 `run_id` / `tracker`；Phase 1c 写库事件改名 `*_persist` |
| `knowledge_mining_zym/mining/runtime/__init__.py` | 修改（必要时） | 确认 `start_stage` / `end_stage` / `fail_stage` 多线程并发调用的安全性，无锁需要补 |
| `scripts/mining_ui.py` | 修改 | 状态推断逻辑兼容新旧事件名 |
| `knowledge_mining_zym/tests/test_stage_events.py` | 新增测试 | 验证内存阶段事件按真实执行顺序入库 |
| `knowledge_mining_zym/tests/test_pipeline_ordering.py` | 新增测试 | 构造 enrich 比 segment 慢的场景，断言事件顺序符合 stage 拓扑 |

## 5. 验证

- `pytest knowledge_mining_zym/tests/test_stage_events.py -v` 全部通过
- `pytest knowledge_mining_zym/tests/test_pipeline_ordering.py -v` 全部通过
- `pytest knowledge_mining_zym/tests/` 全量回归通过
- 启动 mining_ui 端到端跑一次，UI 上 9 阶段 stepper 状态推进顺序正确，无 enrich 早于 segment 的回归现象。
- `select * from mining_run_stage_events where run_id = '<新跑>' order by created_at` 检查事件名集合：`parse` / `segment` / `enrich` / `relations` / `discourse` / `retrieval_units` / `segment_persist` / `relations_persist` / `retrieval_units_persist` / `select_snapshot` / `assemble_build` / `validate_build` / `publish_release`。

## 6. 不在本次范围

- 把 stage 事件接入 OpenTelemetry / 外部观测体系
- `MiningRunTracker` 改造成 lock-free 异步落库
- Phase 1c 写库事件并到 `commit_document`（评估后续是否需要继续简化）
- run-level status truth source（README P0 单独议题，不在此处一并改）

## 7. 已知风险

- worker 多线程并发调 `tracker.start_stage` 时，PG 连接池需要确认每个调用拿到独立 cursor。`runtime/__init__.py` 当前实现若依赖共享游标会出错，需要补锁或换 connection per call。
- 历史 run 的 stage 名残留导致 UI 兼容代码"两套并存"，下个版本要清理；当前作为过渡保留。
- 若 `tracker` 调用本身比 stage 函数慢（极端情况），并发 worker 可能造成事件 INSERT 排队。视实际跑情况决定是否走 3.5 的 flusher 优化。
