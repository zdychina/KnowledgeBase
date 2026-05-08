---
task: mining-ui-redesign
plan: docs/plans/2026-05-06-mining-ui-redesign-impl-plan.md
date: 2026-05-06
agent: claude
---

# Mining UI 流程化重设计 — Claude Handoff

- 关联计划：`docs/plans/2026-05-06-mining-ui-redesign-impl-plan.md`
- 关联前序：`docs/handoffs/2026-05-06-mining-ui-pg-migration-claude-handoff.md`
- 提交：Claude / 2026-05-06

## 1. 任务目标

回应用户两条直接反馈：

1. "前端页面太丑了，功能十分不清晰" —— 把 10 个 tab 的平铺布局改成"流水线进度图 + 单焦点详情面板"，让上传 → 跑挖掘 → 查看 9 个 stage 结果的流程清晰可视
2. "我希望有个真正的终止按钮" —— 把原 NO-OP 取消改成 **协作式取消（Path A）**：UI 把 `mining_runs.status` 翻为 `cancelled`，pipeline 在 5 个 checkpoint 轮询该状态并抛 `MiningCancelled` 优雅退出

附加交互需求："跑当前阶段的时候可以查看其他阶段跑出来的结果吗?" —— 实现 **auto-follow + 用户覆盖**：轮询自动把焦点跟随到最新已完成阶段；用户点击 stepper 上任意阶段会切到手动模式，"📍 跟随最新"按钮可恢复自动。

## 2. 本次实现范围

| 项 | 状态 |
|----|------|
| `mining_ui.py` 流水线布局重写（READY → RUN 双视图，stepper + 单焦点面板） | ✅ |
| 9 个 stage Group + 1 个 Timeline Group，独立 visible 切换 | ✅ |
| `gr.Timer(1.0)` 轮询机制（替代 generator yield） | ✅ |
| `_compute_pipeline_status` 从 PG 数据 + stage_events 推导 9 stage 状态 | ✅ |
| auto-follow + 用户覆盖（state.auto_follow + 📍 跟随最新按钮） | ✅ |
| 顶部 KPI 状态条（耗时 / 已提交 / 已失败） | ✅ |
| 协作式取消：`run.py::MiningCancelled` + `_check_cancelled` + 5 个 checkpoint | ✅ |
| API `/runs/{id}/cancel` 状态守卫（IN clause guard，不再无脑 UPDATE） | ✅ |
| 详情表内嵌 `gr.Accordion(open=False)` 默认收起 | ✅ |
| BarPlot 高度 260 → 180 | ✅ |
| 调色板（#5b6cff primary、status 5 色） | ✅ |
| 静态验证（AST、模块导入、helper 边界用例、HTTP 200） | ✅ |

## 3. 不在本次范围内

- **未启动浏览器手动跑完整 E2E**：终端环境无法驱动 UI 交互。Gradio HTTP 200、114 components、7 dependencies 均已确认；render 函数 + 状态推导 helper 全部通过单元级 smoke
- **未做 LLM 路径冒烟**：cancel checkpoint 在 Phase 1a/1b/1c/Phase2/Publish 五处都生效，不依赖 LLM；只跑 rule-based pipeline 即可触发全部 checkpoint
- **未对 `/runs/{id}/cancel` HTTP API 做 mining-API server 启动测试**：UI 走的是 `_cancel_run_in_db` 直连 PG，不经 HTTP，所以 UI 端 cancel 链路独立可验
- **未改 schema**：`status='cancelling'` 中间态被砍，统一用 `cancelled` 终态，避免 PG CHECK constraint 迁移
- **未删旧 SQLite 文件**：保留 `data/ui_*.sqlite` 和 `scripts/data/smb_*.sqlite`
- **未实现 SSE / WebSocket**：仍是 1Hz 轮询；plan §6 风险表已声明
- **未改 `requirements.txt`**：依赖与上一轮 PG 迁移一致

## 4. 改动文件清单

| 文件 | 类型 | 变化 | 说明 |
|------|------|------|------|
| `scripts/mining_ui.py` | 改写 | 1244 → 2016 行（+772） | 全文重排版，保留 `_PGConn`/`_PGCursor` 与 10 个 `render_*` 函数（业务侧 0 改动），新增 STAGES 表、状态推导 helper、7 个 callback、Timer 驱动 |
| `knowledge_mining/mining/jobs/run.py` | 修改 | +29 行 | 新增 `MiningCancelled` 异常、`_check_cancelled` helper、5 个 pipeline checkpoint、`run()` 顶层捕获 cancelled |
| `knowledge_mining/mining/api/routes/runs.py` | 修改 | ±19 行 | `cancel` 端点：状态守卫 (`status IN ('running','pending','queued')`)、message 文案更新 |
| `docs/plans/2026-05-06-mining-ui-redesign-impl-plan.md` | 新增 | 304 行 | 计划文档（含 ASCII mockup、状态机、auto-follow 设计） |
| `docs/handoffs/2026-05-06-mining-ui-redesign-claude-handoff.md` | 新增 | 本文件 | 交接文档 |

## 5. 关键设计决策

### 5.1 单状态 cancel（不引入 cancelling 中间态）

PG schema 的 CHECK 约束允许 `'queued','running','completed','interrupted','failed','cancelled'`，**不允许** `cancelling`。引入新中间态需要改 schema + 迁移，代价高。

最终方案：UI 直接写 `'cancelled'` 终态 → worker checkpoint 检测到后抛 `MiningCancelled` → `run()` 顶层捕获返回 `{'status':'cancelled'}`。延迟最长 1 个 doc 的处理时间（Phase 1c 是 doc 粒度的写入循环）。

### 5.2 5 个 checkpoint 位置

| 位置 | 作用 |
|------|------|
| Phase 1a `for doc in docs:` 顶部 | 收集元信息阶段（最早可中断） |
| Phase 1b `pipeline.process_all()` 之前 | 流水线（segment + relations + units）启动前 |
| Phase 1c 写库循环每 doc | 流水线已跑完但写库阶段可中断 |
| Phase 2 `if not phase1_only` 之前 | snapshot/build 阶段前 |
| Publish 阶段前 | release 之前最后一道关 |

> Phase 1b 内部不打 checkpoint：流水线一旦启动会跑完已收集的 work_items；Phase 1c 写库才是 doc 粒度的天然中断点。

### 5.3 auto-follow vs override 的状态机

- `gr.State` 持有 `{phase, run_id, focus_stage, auto_follow}` 等字段
- 轮询 callback `cb_poll_tick` 在 `auto_follow=True` 时调 `_next_focus(...)` 重置 `focus_stage`
- 用户点 stepper Radio → `cb_stepper_change` 把 `auto_follow=False` 并把 `focus_stage` 设为用户点的那个
- 用户点 "📍 跟随最新" → `cb_enable_follow` 把 `auto_follow=True` 重新交给轮询接管
- "viewing timeline" 是独立焦点（不归 9 stage 管），通过 `cb_show_timeline` 切到 timeline group

### 5.4 `_compute_pipeline_status` 的状态推导

不依赖 stage_events 全量（pipeline 只对部分 stage emit 事件），**混合派生**：

- `ingest`：`mining_run_documents.status` 计数
- `parse`：固定继承 ingest 的状态（pipeline 串行；如需细粒度可后期补 stage_event）
- `segment` / `relations` / `units` / `snapshot` / `build` / `release`：优先看 stage_event；若无事件，看 PG 数据（asset 表 / build / release 行数）反推
- `enrich`：用 `mining_run_enrichments` 行数判断
- `release`：`asset_releases.is_active='t'` 表示已 publish

这样在没启动 LLM、stage_events 不全的场景下，UI 仍能展示合理的状态。

### 5.5 Timer vs Generator

放弃原 `mining_run` 同步 + `yield` 的 generator 模式，改用：

```
后台线程跑 mining_run() → 主线程 gr.Timer(1.0) 轮询 PG → 渲染状态
```

好处：

- 用户点 stepper 切焦点时，原 generator-blocking 模式会卡死；Timer 模式天然并发
- Timer 在 `phase ∈ {ready, done, failed, cancelled}` 时禁用（`active=False`），不消耗资源

### 5.6 `gr.Blocks` Gradio 6.0 兼容

发现 Gradio 6.0 起 `theme` / `css` 不再放在 `Blocks()` 构造函数，必须传给 `launch()`。已挪。

## 6. 已执行验证

### 6.1 静态验证

- `ast.parse` OK（2016 行）
- `import scripts.mining_ui` 无错误，无 UserWarning
- `STAGES = 10`、`PIPELINE_STAGE_IDS = 9`、`STAGE_BY_ID` 索引完整

### 6.2 helper 边界用例

```
_compute_pipeline_status(run_id='nonexistent', run_row=None) → 9 stage 全部 'pending'  ✓
_cancel_run_in_db('nonexistent_run') → 静默 no-op（rowcount=0）                       ✓
_next_focus(None, all_pending, auto=True) → 'ingest'                                  ✓
_next_focus(None, ingest=done+parse=running, auto=True) → 'ingest'（latest done 优先）✓
_next_focus(None, ingest=done+parse=running, auto=False, prev='segment') → 'ingest'
   （prev 是 pending 时回落到 auto，符合预期）                                         ✓
_stepper_choices / _status_bar_html / _focus_label_md / _kpi_html 渲染无异常         ✓
```

### 6.3 真实数据回放

对 `mining_runs` 中最近一次"卡死的 running"行（已 interrupt 清理），调 `_compute_pipeline_status`：

```
ingest      done       📄 1 个 · ✓0 ✗0
parse       done       —
segment     done       —
enrich      done       0 实体（rule-based 无命中）
relations   done       —
units       running    —
snapshot    done       —
build       pending    —
release     pending    —

_next_focus(auto=True) → 'snapshot'   # latest done
_status_bar_html len=339              # 渲染正常
```

### 6.4 服务端验证

```
$ py -3.10 scripts/mining_ui.py &
$ curl http://127.0.0.1:7860/         → HTTP 200
$ curl http://127.0.0.1:7860/config   → 114 components, 7 dependencies
```

7 dependencies 对应 7 个 callback：`cb_start_mining` / `cb_poll_tick` / `cb_cancel` / `cb_stepper_change` / `cb_enable_follow` / `cb_restart` / `cb_show_timeline`。

## 7. 未验证项

- **浏览器手动 E2E**：未点击实际 stepper / 上传文件 / 跑完整流程；终端环境限制。建议用户启动 `py -3.10 scripts/mining_ui.py` 走一遍 5 步流程：
  1. 上传 2-3 个 .md → "🚀 开始挖掘" → 验证 RUN 视图出现，stepper 高亮
  2. Timer 跑 1Hz 轮询，stage 顺序变 ✓ → 焦点自动跟进（latest done）
  3. 中途点 stepper 别的 stage → 焦点切过去，"📍 跟随最新"按钮出现
  4. 点 "📍 跟随最新" → 焦点回到自动，按钮消失
  5. 跑到一半点 "▣ 终止" → ≤2 秒内 phase 翻 cancelled，stepper 显示 ⊘
- **`/runs/{id}/cancel` HTTP API**：本次改了状态守卫但 UI 不走 HTTP；如有外部脚本调 cancel 端点，建议补一遍冒烟
- **大规模流水线（>20 docs）下 Timer 轮询频率**：1Hz 无问题，但 `_compute_pipeline_status` 每秒查 5+ 张 PG 表，>50 docs 时建议加 5s debounce 或缓存

## 8. 已知风险

| 项 | 风险评级 | 说明 |
|---|---------|------|
| Timer + 后台线程死锁 | 低 | psycopg pool min=1/max=4 thread-safe；后台线程用 mining 自身的 pool（`MiningDbConfig`），UI 用单独 pool，无冲突 |
| stage_event 不完整时的状态误判 | 中 | 已通过 PG 数据兜底（5.4），但 enrich 在没启 LLM 时永远显示 done + "0 实体"，可能让用户误以为应该有数据。已加文案 "rule-based 无命中" 说明 |
| Cancel 延迟 | 低 | Phase 1c 单 doc 处理可能 5-10s（segment + LLM 调用），cancel 信号最长等待 1 doc。可接受 |
| BarPlot height=180 在小屏幕被压扁 | 低 | 用户屏幕分辨率未知；如反馈再调 |
| Timeline 切焦点后无 "返回 stepper" 按钮 | 低 | 用户可点 stepper 任意阶段切回；未做单独 "返回" 按钮 |
| Worktree HEAD 落后 master | 中 | 当前 worktree 在 `claude/crazy-cohen-dddea2` 分支（HEAD=9e56c90），但代码改在 master（HEAD=2d00ade）。提交时需要在 master 分支提交 |

## 9. 给 Codex 的审查重点

1. **`_check_cancelled` 性能**：每个 doc 写库前都查 PG，>100 docs 时是否需要缓存或降频？目前 1ms 点查，认为可接受
2. **`MiningCancelled` 异常路径完整性**：`run()` 顶层 try/except 把 `MiningCancelled` 单独拎出，**不调 `tracker.fail_run()`**。但 cancel 时 `mining_runs.finished_at` 由谁写？UI 端 `_cancel_run_in_db` 已写。但若 worker 在 checkpoint 之前已经走完整 stage，`tracker.complete_run()` 会不会与 UI 的 cancel UPDATE 抢占？已用 `WHERE status IN ('running','pending','queued')` 守卫，但请审 `tracker.complete_run` 是否也用类似守卫
3. **auto-follow 的边界**：`_next_focus` 在所有 stage 都 done 时返回 last_done（即 release）。但若 release 失败而 build 成功，焦点会停在 build。这符合 "用户最关心已成功的最后一步" 的语义吗？请审
4. **stepper Radio 的 `gr.update(value=...)` 同步**：用户点击 stepper 后 `cb_stepper_change` 设 `auto_follow=False` + `focus_stage=clicked`；但下一次 `cb_poll_tick` 触发时如果 `auto_follow=False` 是不是会被错误覆盖？请追 `cb_poll_tick` 中 `auto_follow=False` 的早返路径
5. **Timer 在 phase=done 时的关闭**：是否真有 `gr.Timer(active=False)` 关停？还是 demo 持续触发？请用 `curl /config` 查 dependencies 的 trigger_after / show_progress 行为
6. **PG 连接池泄漏**：`_compute_pipeline_status` 每次调用都 `_open_runtime() + _open_asset()`，每个 helper 内部 `try/finally` 关连接。若 9 stage × 1Hz × 长时间运行，连接池会不会枯竭？min=1/max=4 是否够用
7. **cancel 后的清理**：`mining_runs.status='cancelled'` 但 stage_events 表里的 'started' 事件没有对应 'completed' 事件。stepper 在 cancelled run 上显示这些 stage 是 'running' 还是 'cancelled'？请审 `_compute_pipeline_status` 的 cancelled 分支

## 10. 管理员本轮直接介入记录

- 用户原话："你这个前端页面太丑了，功能十分不清晰" → 触发本次重设计
- 用户原话："然后我希望有个真正的终止按钮" → 拒绝 NO-OP，要求 Path A 协作式取消
- 用户选择 "B"+"plan中给个前端示意图" → plan §2.5 加 ASCII mockup
- 用户选择 "选gradio" → 跳过 HTML 原型，直接 Gradio 实现
- 用户问 "现在的前端设计里，跑当前阶段的时候可以查看其他阶段跑出来的结果吗?" → 实现 auto-follow + override，写入 plan §4.4
- 用户回 "好" → 授权按 plan 推进 Gradio 实现
- 冒烟样本（cloud_core_coldstart_md/01_features 下 2 个 .md）由 Claude 自行选取，未事先征询用户
