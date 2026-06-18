# 2026-06-18 · llm_service 文档审计 · Claude Handoff

- 负责人：Claude
- 关联设计：`docs/plans/2026-06-18-llm-service-docs-refresh-design.md`
- 关联实现计划：`docs/plans/2026-06-18-llm-service-docs-refresh-impl-plan.md`
- 审计基准 commit：`<HEAD at audit start>`

## 审计范围

`llm_service/` 全部源码（4271 行）+ 现有文档（README.md / QUICKSTART.md / architecture.html）

## 审计方法

逐文件全核 → 对照现有文档 → 漂移点按严重度入下表 → 不在本次修复。

## 发现汇总（按严重度）

### CRITICAL

- **C-001 [README §3.1 数据流完全失真]** `llm_service/README.md` 把同步 `execute()` 描述为「原子 claim（UPDATE WHERE status='queued'）→ Executor.run()」，但实际 `LLMService.execute()` **不走 claim / Worker 路径**，而是直调 provider → 解析 → 内存构造 SyncChatRecord → `PersistWriter.enqueue()` 异步落库。这是 v1.2 → 现版本最核心的架构变化（commit 49138e5 "decouple sync-call DB writes from request hot path via PersistWriter"）。位置：`README.md` §3.1 与 `runtime/service.py:457-601`。

### HIGH

- **H-001 [README §2 模块图含不存在的文件]** 列出 `runtime/executor.py` 作为「执行引擎（同步路径）」，但该文件在仓库中不存在。实际同步执行逻辑在 `runtime/service.py::LLMService.execute()` 内部完成。
- **H-002 [README §2 模块图缺真实文件]** 缺失：`pg_config.py`、`pg_schema.py`、`runtime/persist_writer.py`、`runtime/event_bus.py`、`providers/anthropic.py`。
- **H-003 [README §1 系统定位错标存储]** 写「SQLite 数据库（WAL 模式）」，实际已迁 PostgreSQL，schema 由 `pg_schema.py` 定义。需在 Task 5 进一步核对表数。
- **H-004 [任务状态机缺失 dead_letter 语义]** README 未说明 `dead_letter` 是任务级终态、`failed` 只是 attempt 级状态；新用户易误以为 task 可以处于 `failed`。

### MEDIUM

- **M-001 [README §2 未提 LeaseRecovery]** `runtime/worker.py` 包含 `LeaseRecovery` 类（30s 扫描 lease_expires_at），README 完全未提。
- **M-002 [README §2 模块图提 "dashboard/" "templates/"]** 这两个目录在当前 `llm_service/` 下不存在（见 Task 0 ls 输出），需在重写 README 时删除。

### LOW

- **L-001 [幂等查询存在两条不一致的路径]** `runtime/idempotency.py::find_existing_task` 按 `succeeded → running → queued` 优先级返回；`LLMService._submit_with_idempotency` 内部用「NOT IN (failed, dead_letter, cancelled) ORDER BY created_at DESC LIMIT 1」。前者只在 `TaskManager.submit` 路径使用，后者在 `LLMService.submit*` 路径使用。语义差异：若同时存在一条 succeeded 和一条 queued，前者返回 succeeded，后者返回最新创建的（可能是 queued）。建议统一到 `find_existing_task` 的优先级语义。位置：`runtime/service.py:286-297` vs `runtime/idempotency.py:6-23`。
- **L-002 [parser 未在文档列出的边界]** `parse_output` 在 `expected_type` 既非 text 也非 json_object/json_array 时，会走 json 解析但不做类型校验（行为同 json_object 但允许 array）。建议文档化或显式拒绝。位置：`runtime/parser.py:34-48`。

### 新增 CRITICAL/HIGH（本节追加）

无新增 CRITICAL。新增 HIGH：

- **H-005 [README §1 表数错]** 标"数据库：agent_llm_runtime（6 张表）"，实际至少 7 张（多出 `agent_llm_model_calls` 用于 embedding/rerank 审计）。位置：`runtime/persist_writer.py:182-188` 的 `_model_call_sql`。

### 新增 LOW（Task 3 追加）

- **L-003 [BigModelProvider 兼容 legacy 参数命名]** 构造函数同时接受 `timeout` / `bypass_proxy` / `extra_headers`（legacy）与 `embedding_*` / `rerank_*` 前缀（新），并保留 `if timeout is None` 等回退逻辑。属于迁移期产物，长期应移除。位置：`providers/bigmodel_models.py:30-50`。
- **L-004 [AnthropicProvider tool_use input_schema 空定义]** 强制 JSON 输出时塞入的 tool `input_schema` 是 `{"type":"object","properties":{}}`（无字段约束），仅起触发 tool_use 之效；若上层 `output_schema_json` 已注入到 system prompt，两者并不联动。可考虑把真实 schema 透传进 tool_use。位置：`providers/anthropic.py:137-146`。

## 修复建议优先级

（占位 · Task 10 整合）

## 已验证对齐项

（占位 · Task 10 整合）

## 未验证项

（占位 · Task 10 整合）

## 修订记录

- 2026-06-18 初版（Claude）
