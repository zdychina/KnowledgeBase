# Mining UI 重新设计实现计划（B-Full）

- 任务归属：`TASK-20260421-v11-knowledge-mining`
- 文件路径：`docs/plans/2026-05-06-mining-ui-redesign-impl-plan.md`
- 起草：Claude / 2026-05-06
- 触发背景：用户反馈当前 UI（PG 迁移后）"太丑、功能不清晰"，希望"上传 + 选领域后确定文件，后面逐阶段跑，需要清晰的过程提示：现在到哪一步、有哪些已经产出可以展示"

## 1. 任务目标

把 `scripts/mining_ui.py` 从"10 个并列 Tab + 一次刷全部"重构为"三态向导式流程 + 顶部 Stepper 步骤条 + 单一 Active Panel"，让用户始终看到：

1. **现在在哪一步**（横向 Stepper，状态机：pending → running → done/failed）
2. **每步的产出**（当前焦点阶段的 KPI 卡片 + 图 + 可折叠明细表）
3. **明确的流程节点**（READY → RUNNING → DONE 三段视图，按钮和参数面板按状态显隐）

不改 mining 流水线（仍然一次性跑完），只重做 UI 层。

## 2. 设计示意图

### 2.1 State 0 — READY（上传后、未开始）

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ 🛠️  Knowledge Mining Studio                                                    │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│   ┌─────────────────────┐  ┌───────────────────────────────────────────────┐   │
│   │  📎 文件上传 (3)    │  │  已选 3 个文件 · 共 142 KB                     │   │
│   │  ┌───────────────┐  │  │  ─────────────────────────────────────────    │   │
│   │  │ [拖入 / 选择] │  │  │   ▸ gwfd_010224_n4.md          42 KB          │   │
│   │  └───────────────┘  │  │   ▸ gwfd_010310_dnn.md         38 KB          │   │
│   │                     │  │   ▸ gwfd_010311_qos.md         62 KB          │   │
│   │  🏷️ Batch 参数      │  │                                                │   │
│   │  产品   UI-Test     │  │  Domain Pack    cloud_core_network            │   │
│   │  标签   ui,test     │  │  LLM            ❌ 未启用                      │   │
│   │  类型   procedure ▾ │  │  Embedding      ❌ 未启用                      │   │
│   │  Domain cloud..  ▾ │  │                                                │   │
│   │                     │  │            ┌───────────────────────┐           │   │
│   │  ☐ 启用 LLM         │  │            │   ▶  开始挖掘          │           │   │
│   │  ☐ 启用 Embedding   │  │            └───────────────────────┘           │   │
│   └─────────────────────┘  └───────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
```

要点：左 sidebar 输入参数 / 右"确认面板"反映当前选择 + 大按钮。视觉锚点：开始按钮居中突出。

### 2.2 State 1 — RUNNING（执行中，1s 轮询）

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ 🛠️ Knowledge Mining Studio    run a3f9...│ ⏱ 0:23│ 进度 33%│ ▣ 终止          │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌────────────────────────── Stepper（横向 9 阶段） ──────────────────────────┐ │
│  │  ✓ Ingest    ✓ Parse    ⟳ Segment   ◯ Enrich   ◯ Relations  ◯ Units      │ │
│  │   1.2s        2.4s       1.8s ...    —          —            —           │ │
│  │  ◯ Snapshot  ◯ Build    ◯ Release                                         │ │
│  │   —           —          —                                                │ │
│  └─────────────────────────────────────────────────────────────────────────────┘│
│                                                                                │
│  当前焦点 → ⟳ Segment 分块                              [自动跟随最新 ✓]       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                       │  │
│  │  │ 段落数  │  │ token   │  │ 平均    │  │ 用时    │                        │  │
│  │  │  54     │  │ 12,300  │  │ 228     │  │ 1.8s    │                        │  │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘                       │  │
│  │                                                                            │  │
│  │  ┌──── block_type 分布 ───┐    ┌──── token 分布 ────┐                      │  │
│  │  │     [bar plot]          │    │     [bar plot]     │                     │  │
│  │  └─────────────────────────┘    └────────────────────┘                     │  │
│  │                                                                            │  │
│  │  ▸ 展开明细表格（54 行）                                                    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────┘
```

要点：

- 顶部状态条：run_id / 已用时 / 进度百分比 / 终止按钮
- Stepper 9 阶段并列：完成（✓ 绿）/ 运行中（⟳ 蓝色脉冲）/ 待运行（◯ 灰）/ 失败（✗ 红）
- 单 Active Panel：默认自动跟随最新完成的阶段；用户可点 stepper 任一已完成阶段切换焦点
- 上传/参数 sidebar **整体折叠**为顶部状态条上的一个 "▸ 查看本次参数" 链接

### 2.3 State 2 — DONE（全部完成）

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ 🛠️ Knowledge Mining Studio   ✅ 完成   run a3f9...│ 用时 23s│ 100%            │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌────────────────────────── Stepper（全绿） ─────────────────────────────────┐ │
│  │  ✓ Ingest  ✓ Parse  ✓ Segment  ✓ Enrich  ✓ Relations  ✓ Units            │ │
│  │   1.2s     2.4s     1.8s        0.3s     4.7s         2.1s              │ │
│  │  ✓ Snapshot  ✓ Build  ✓ Release                                          │ │
│  │   0.6s        1.0s     0.2s                                              │ │
│  └────────────────────────────────────────────────────────────────────────────┘│
│                                                                                │
│  ↑ 点击任一阶段查看产出                                                         │
│                                                                                │
│  当前焦点 → ✓ Release 发布          ┌─────────────────────┐                    │
│                                     │ 🔄 上传新批次重跑   │                    │
│  ┌──── KPI 卡片 + 图 + 表 ────┐    └─────────────────────┘                    │
│  │  …                          │                                              │
│  └─────────────────────────────┘                                              │
└────────────────────────────────────────────────────────────────────────────────┘
```

要点：

- Stepper 全绿、显示每阶段耗时
- 提供"上传新批次重跑"按钮回到 State 0
- 默认焦点切到 Release（最终产出），用户也可点回任一阶段查看

### 2.4 State 1' — FAILED（中途失败）

```
│  ✓ Ingest  ✓ Parse  ✗ Segment   ◯ Enrich  …                                  │
│   1.2s     2.4s      0.4s ❌     —                                            │
│                                                                               │
│  当前焦点 → ✗ Segment 分块                                                     │
│  ❌ 错误：<error message from mining_run_stage_events.error_message>           │
│  …                                                                            │
```

要点：失败阶段红色 ✗，焦点自动切到失败阶段，error_message 高亮显示。

### 2.5 State 1'' — CANCELLED（用户主动终止）

```
│ 🛠️ Knowledge Mining Studio  ⊘ 已取消  run a3f9...│ 用时 7s│ 进度 22%          │
│                                                                                │
│  ✓ Ingest    ✓ Parse    ⊘ Segment   ⊘ Enrich   ⊘ Relations  ⊘ Units          │
│   1.2s        2.4s       —           —           —            —              │
│  ⊘ Snapshot  ⊘ Build    ⊘ Release                                             │
│                                                                                │
│  ⊘ 用户已终止本次挖掘 · Segment 阶段未完成                                      │
│  当前焦点 → ✓ Parse（最后一个完成的阶段）  ┌─────────────────────┐              │
│                                            │ 🔄 上传新批次重跑   │              │
│                                            └─────────────────────┘              │
```

要点：取消用 **橙色 ⊘** 区别于失败的 **红色 ✗**；已完成阶段保留 ✓ 绿；焦点自动定位到"最后一个完成的阶段"，让用户能看到取消前的产出。

## 3. 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `scripts/mining_ui.py` | 重写 layout + state 流 | 主体改动 |
| `knowledge_mining/mining/jobs/run.py` | 加协作式取消检查点 | 在 stage / document 边界轮询 PG 中 `mining_runs.status='cancelling'` 信号，主动抛 `MiningCancelled` 终止 |
| `knowledge_mining/mining/api/routes/runs.py` | 修取消 API 语义 | 把 `status` 从直接置 `cancelled` 改成置 `cancelling`，由 worker 看到信号收尾后再写最终 `cancelled` |

无新增文件、无依赖变更。

## 4. 关键实现点

### 4.1 状态机

引入 `gr.State` 对象 `app_state`：

```python
{
  "phase": "ready" | "running" | "done" | "failed",
  "run_id": str | None,
  "focus_stage": str | None,   # 用户选中或 auto-follow 的当前阶段
  "auto_follow": bool,         # 是否自动跟随最新完成阶段
  "stages": {                  # 9 阶段状态字典，由 polling 更新
    "ingest": {"status": "done", "duration_ms": 1200, "error": None},
    ...
  },
  "started_at": float | None,
}
```

### 4.2 Stepper 渲染

- 用 `gr.HTML(elem_id="stepper")` 作为展示载体，callback 返回新 HTML 字符串
- HTML 内部用 `<div class="step done">…</div>` + CSS 控制颜色 / 脉冲动画
- 9 个阶段并列，每个内含：图标 + 名称 + 耗时（done） / "running…" / "—"

### 4.3 焦点切换交互

- Stepper 下方放一个 `gr.Radio(choices=stage_labels, label=None, elem_id="stage-selector")`
- CSS 将该 Radio 渲染为不可见（实际通过点击 `gr.HTML` 内部按钮触发——但 Gradio 不支持 HTML emit click 到 Python）
- **回退方案（推荐）**：保留 `gr.Radio` 显示为水平按钮组，作为"切换焦点"的真实控件；上方 `gr.HTML` 仅作为视觉装饰
- 简化：**Stepper 与 Radio 合二为一**——用 Radio 做唯一交互层，CSS 把 Radio 渲染成 stepper 样式（每个 option 显示状态图标 + 时长）。这是最干净的方案

### 4.4 Active Panel 渲染 + 焦点切换交互（auto-follow）

- 下方 panel 用 `gr.Group(visible=...)` 包裹每个阶段的组件集合
- 焦点切换时只显示对应 group，其他 hidden
- 每秒轮询时，**只对当前焦点阶段调用 render，其他阶段组件不更新**

**焦点行为**（`app_state.focus_stage` + `app_state.auto_follow`）：

- **auto-follow 默认开启**：每次 polling 比对 stages 字典，发现"最新刚转为 done"的阶段时，把 `focus_stage` 自动切到它，让用户立刻看到刚跑完的产出
- **用户点击覆盖**：用户在 Stepper 上点任一阶段（已完成 / 运行中），把该阶段设为 `focus_stage`，并把 `auto_follow=False` 锁定焦点
- **重新挂回 auto-follow**：UI 上提供"📍 跟随最新"小按钮（顶栏右侧），点击恢复 `auto_follow=True`；run 进入 done / failed / cancelled 终态时也自动恢复
- **运行中阶段可点**：点击当前正在跑的 stage，焦点切到它，看到的是"运行中 + 已写入 PG 的部分行"，每秒刷新；点击已完成阶段则展示终态结果
- **未开始阶段不可点**：Stepper 上 `pending` 项 disabled，避免空 panel 干扰
- 所有阶段的 `gr.Group` 始终保留在 DOM（仅切 `visible`），避免组件 reset / 数据丢失

### 4.5 KPI 卡片

- 用 `gr.HTML` 显示 4 个数字卡片（数字 + 标签）
- 每个 render 函数额外返回 KPI 字典 → callback 转成 HTML

### 4.6 视觉

- 整体用浅灰背景 (`#f5f7fb`)，主内容区白底卡片化、圆角 12px
- 字号：H1 28 / H2 18 / 正文 14
- 调色板：主色 `#5b6cff`（替换原紫色 hero）/ 状态色 done `#10b981` / running `#3b82f6` / failed `#ef4444` / pending `#94a3b8`
- 移除当前过重的 hero banner，改为顶部 32px 高的窄 header
- BarPlot 高度从 260 → 180，并去掉 title（卡片已经表达上下文）

### 4.7 sidebar 折叠

- State READY：sidebar 完整可见
- State RUNNING / DONE：sidebar 折叠到右上角"▸ 本次参数"链接，点击展开 modal-like Accordion
- 用 `gr.Column(visible=...)` 控制

### 4.8 协作式取消（Path A）

终止按钮要"真停"。流水线本身没有取消机制，本次新增最小协作式取消：

- **状态信号复用现有 `cancelled` 终态**：避免新增 `cancelling` 引发 schema CHECK 迁移；UI 在用户点击后直接 `UPDATE mining_runs SET status='cancelled' ...`，worker 通过定期查 `status` 字段感知到取消
  - 短暂的"DB 已 cancelled / 进程仍在收尾"窗口不构成语义矛盾：UI 已经按 cancelled 渲染，worker 在 ≤ 一篇文档的延迟内看到信号、停止后续动作
- **检查点位置**（`knowledge_mining/mining/jobs/run.py`）：
  - 自定义异常 `MiningCancelled` 与辅助函数 `_check_cancelled(asset_db, runtime_db, run_id)` 在文件顶部
  - Phase 1a per-doc 循环（line 359 附近）：每篇文档进入分类前查一次
  - Phase 1b 之前（`pipeline.process_all` 调用前，line 441 附近）：streaming pipeline 启动前最后一次校验
  - Phase 1c per-doc 写入循环（line 444 附近）：每篇文档结果落库前查一次（最关键 — 每处理一篇可能跑数秒）
  - Phase 2 build / publish 之前（line 625 / 647 附近）：避免取消后还跑出 build / release
  - 这几处足够把"点击终止 → 真停"的最大延迟压到单文档级
- **MiningCancelled 处理**：
  - 在 `_run_pipeline` 顶层 `try/except MiningCancelled` 捕获
  - **不**调用 `tracker.fail_run`（DB 中 status 已经是 cancelled）
  - 仅写一条 `error_summary='Cancelled by user'` 与当前 counters，并 `commit`
  - 函数正常返回 `{"run_id": ..., "status": "cancelled", "committed_count": ..., ...}`，**不**向上抛
  - 顶层 `run()` 的 `except Exception` 不再触发 fail_run（cancelled 不属于失败）
- **DB 查询频率**：每次检查点单条 `SELECT status FROM mining_runs WHERE id=%s`，PG 上单点查询 < 1ms，不影响吞吐
- **不做的事**：不打断已经在执行的 LLM HTTP 调用 / embedding 调用（这些可能需要几秒才返回），等当前调用结束才到下一个检查点。这是可接受的 UX trade-off

### 4.9 UI 终止按钮

- 顶部状态条 `▣ 终止` 按钮（仅在 phase=running 时可见）
- 点击行为：UI 端直接 `UPDATE mining_runs SET status='cancelled', finished_at=now() WHERE id=%s AND status='running'` 一条 SQL（不依赖 mining API server），即时生效；带 `status='running'` 守卫避免覆盖已经 completed/failed 的 run
- 按钮变成 disabled，文案改为"⏳ 正在停止…"，避免重复点
- 1s 轮询时 UI 已经能从 `mining_runs.status` 读到 `'cancelled'`，phase 切到 `cancelled`，Stepper 把"未跑完阶段"标 ⊘ 灰，已跑完阶段保留 ✓

## 5. 验证策略

### 5.1 静态
- `import mining_ui` 不报错
- 模块编译通过（AST parse）

### 5.2 端到端冒烟（必做）
- 重用已有的 `data/uploads/_smoke/` 样本
- 启动 `py -3.10 scripts/mining_ui.py`，浏览器访问 `127.0.0.1:7860`
- 流程：READY → 上传文件确认显示 → 点击开始挖掘 → RUNNING（观察 stepper 实时刷新、KPI 数字变化、焦点跟随）→ DONE（stepper 全绿、各阶段可点击切换焦点）
- 失败路径：可选——故意填一个会让 ingest 失败的输入（如空目录）来验证 FAILED 状态展示

### 5.3 不做
- 不做单元测试（Gradio 组件不便单元测试）
- 不做多用户并发测试

## 6. 已知风险

| 风险 | 评级 | 缓解 |
|------|------|------|
| Gradio Radio 用 CSS 渲染成 stepper 在不同 Gradio 版本下样式漂移 | 中 | 锁定当前 gradio 版本号；CSS 选择器尽量精确 |
| 状态切换时 gr.Group 显隐导致组件 reset / 数据丢失 | 中 | 全部组件保留在 DOM 中，仅切 visible；State 持久化 focus_stage |
| 1s 轮询频率下，多个 callback 并发更新 stepper / panel 引发竞态 | 低 | 单一 callback 一次返回所有需要更新的组件 |
| 协作式取消最大延迟为单文档处理时间（含 LLM 调用） | 中 | 检查点放 stage 边界 + 文档循环；LLM 单次调用结束后即响应。可接受 |
| 取消后写入 PG 的部分数据残留（segment / parse 已写但 relations 未跑） | 中 | 不回滚 — 已落地的 stage 仍有效；用户重跑时通过新 run_id 区分。文档化 |
| BarPlot 改小后 x 轴 label 重叠 | 低 | 数据多时自动旋转 / 截断；测试一遍 |

## 7. 不在本次范围

- 不实现"逐阶段卡断点等用户确认"（这是方案 A，用户已选 B 全自动）
- 不增加新 stage、不重新设计任何 stage 的统计指标
- 不做移动端 / 平板适配
- 不实现历史 run 列表 / 切换查看历史
- 不打断 LLM / embedding 远程调用本身（取消有最多一次远程调用的延迟）
- 不回滚已落地的 PG 数据（取消后已写入 stage 的数据保留）
- 不修复 `pg_schema.py::_split_ddl` PL/pgSQL 切分 bug（残余项）

## 8. 给 Codex 的审查重点

1. State Machine 状态切换是否完备（READY → RUNNING → DONE / FAILED / CANCELLED 各路径）
2. Stepper 渲染在轮询中是否抖动 / 闪烁（应该只在状态实际变化时重渲染）
3. 焦点切换交互的可发现性（用户是否能直觉地知道 stepper 各项可点击）& auto-follow 与用户覆盖的优先级处理是否符合预期
4. CSS 在 Gradio 升级时的稳健性（避免 hardcode 内部 class 名）
5. 协作式取消语义（cancelling → cancelled）是否在所有 happy path / error path 都能收敛，是否会卡在 cancelling 状态
6. 取消检查点位置选择：stage 边界 + 文档循环够不够；是否漏掉某条长执行路径

## 9. 工作量估计

- Layout 重写：30 分钟
- State Machine + Stepper Radio + Group 显隐：30 分钟
- KPI 卡片 + CSS 重写：30 分钟
- 协作式取消（run.py 检查点 + routes/runs.py 改 status）：30 分钟
- UI 取消按钮 + cancelled 状态视图：15 分钟
- 端到端冒烟 + 调试（含取消路径）：45 分钟
- 共计 **约 3 小时**
