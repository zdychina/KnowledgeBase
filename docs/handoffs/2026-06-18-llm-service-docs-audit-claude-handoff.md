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

（占位 · Task 2-7 继续追加）

## 修复建议优先级

（占位 · Task 10 整合）

## 已验证对齐项

（占位 · Task 10 整合）

## 未验证项

（占位 · Task 10 整合）

## 修订记录

- 2026-06-18 初版（Claude）
