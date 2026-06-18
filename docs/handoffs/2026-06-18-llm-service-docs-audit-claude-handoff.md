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

### 新增 MEDIUM/HIGH（Task 4 追加）

- **H-006 [README §3 API 总览大量端点缺失]** 旧 README 仅提到 `/tasks`、`/execute`、`/tasks/{id}`、`/cancel`、`/models/embeddings`、`/models/rerank`。实际共 **21 个端点**（见下表）。重写 README 时必须全列。
- **M-003 [同步 model 端点已加 Deprecation]** `api/model_api.py:16-18` 在 `/api/v1/models/embeddings` 与 `/api/v1/models/rerank` 的响应里加了 `X-Deprecation-Notice` header，引导改用 `/api/v1/tasks/embed` 与 `/api/v1/tasks/rerank`（异步队列版）。README 未提，且 QUICKSTART 若仍示例同步端点需补充异步版示例。
- **M-004 [admin/reload-config 是热重载入口]** `api/admin.py:53-176` 实现完整热重载（含跨 provider 切换、worker concurrency 动态 scale、cache_ttl 热更新），是配置热重载章节的关键证据。README 完全未提此端点。
- **M-005 [templates DELETE 实为 archive]** `api/templates.py:113-120` 的 DELETE 不删行，只把 `status='archived'`，与 RESTful DELETE 语义略有偏差，应在文档明示。
- **M-006 [tasks/retry 路径存在]** `api/tasks.py:145-170` 提供 retry 端点：把 failed/dead_letter/cancelled 的任务重置为 queued，attempt_count=0。README 未提。

#### Task 4 完整路由清单（用于 README §3）

| Method | 路径 | 文件 | 用途 |
|---|---|---|---|
| POST | `/api/v1/tasks` | tasks.py | 异步提交 chat 任务 |
| POST | `/api/v1/tasks/embed` | tasks.py | 异步提交 embedding 任务 |
| POST | `/api/v1/tasks/rerank` | tasks.py | 异步提交 rerank 任务 |
| POST | `/api/v1/execute` | tasks.py | **同步**执行 chat，立即返回 |
| GET | `/api/v1/tasks/{task_id}` | tasks.py | 任务详情（含 request/result/attempts/events） |
| POST | `/api/v1/tasks/{task_id}/cancel` | tasks.py | 取消 queued 任务 |
| POST | `/api/v1/tasks/{task_id}/retry` | tasks.py | 重置失败任务为 queued |
| POST | `/api/v1/tasks/batch-cancel` | tasks.py | 批量取消 |
| GET | `/api/v1/tasks/{task_id}/result` | results.py | 解析结果 |
| GET | `/api/v1/tasks/{task_id}/request` | results.py | 原始请求快照 |
| GET | `/api/v1/tasks/{task_id}/attempts` | results.py | 所有尝试列表 |
| GET | `/api/v1/tasks/{task_id}/events` | results.py | 状态变迁事件流 |
| POST | `/api/v1/models/embeddings` | model_api.py | **同步** embedding（已加 Deprecation header） |
| POST | `/api/v1/models/rerank` | model_api.py | **同步** rerank（已加 Deprecation header） |
| GET | `/health` | health.py | 健康检查（含 DB 连通性 + tables_ok） |
| POST | `/api/v1/templates` | templates.py | 创建/UPSERT 模板 |
| GET | `/api/v1/templates` | templates.py | 列出模板（可选 domain 过滤） |
| GET | `/api/v1/templates/{template_key}` | templates.py | 按 key+domain 解析模板 |
| PUT | `/api/v1/templates/{tpl_id}` | templates.py | 更新模板字段 |
| DELETE | `/api/v1/templates/{tpl_id}` | templates.py | 归档（status='archived'） |
| POST | `/api/v1/admin/reload-config` | admin.py | **热重载**配置（跨 provider 切换） |
| GET | `/api/v1/admin/worker-status` | admin.py | Worker 诊断（concurrency/active_tasks） |
| GET | `/api/v1/stats` | stats.py | 全局聚合统计 |
| GET | `/api/v1/stats/tokens` | stats.py | token 用量细分 |
| GET | `/api/v1/tasks` | stats.py | 任务列表（分页+多维过滤） |

实际为 25 个端点（含 list_tasks）。README 重写时按功能分组：提交/同步/查询/管理/模型/统计/系统。

### 新增 MEDIUM（Task 6 追加）

- **M-007 [README §6 测试数 96 已过时]** 旧 README 写"pytest 96 passed"，实际为 **33 个 test 函数**（5 个被 skip 的集成 stub + 28 个真实可执行）。分布：
  - `test_parser.py`：12（json_object / json_array / text / markdown 剥围栏 / schema 验证通过/失败 / 非法 schema 不崩溃 / 空输入 / text 跳过 schema）
  - `test_providers.py`：8（Mock 循环 + OpenAICompatible URL 构造 + Anthropic 3 个：system 转换、JSON fallback 提取、tool_use input 序列化）
  - `test_models.py`：7（TaskSubmitRequest 默认值 / legacy caller_domain 兼容 / 校验拒绝空服务名 / ExecuteResponse 两态 / EmbeddingRequest 标量归一化 / RerankRequest 空文档拒绝）
  - `test_client.py`：1 真实（_build_submit_payload）+ 5 `@pytest.mark.skip` 集成 stub（execute/submit+get/cancel/embed/rerank）
  - `conftest.py`：0（仅 `config` fixture + `TEST_CFG` 常量 + asyncio_mode=auto 设置）
  - 非测试脚本：`curl_test.md`（curl 食谱，非 pytest）、`profile_execute.py`（手动跑的 ASGI 计时脚本）、`test_live_demo.py`（带 `__main__` 的 live 演示，**非 pytest**，且 line 147-152 仍写 `data/llm_service.sqlite` 与 `sqlite3` 指令 — SQLite 残留）

- **M-008 [test_live_demo.py 仍引用 SQLite]** `tests/test_live_demo.py:147-152` 的总结输出打印 `DB file: data/llm_service.sqlite` + `sqlite3 data/llm_service.sqlite` 命令。这是 SQLite→PG 迁移时漏改的残留，会误导新成员。属代码层（非本次修复范围），但应在 README §6 测试章节标注「demo 脚本输出有 SQLite 残留」。

- **L-005 [test_live_demo.py 用 legacy caller_domain]** `tests/test_live_demo.py:93, 117` 仍用 `caller_domain` 字段（legacy），而 `test_models.py::test_task_submit_request_accepts_legacy_caller_domain` 证实新字段是 `caller_service`。models.py 同时接受两者做兼容，但 demo 脚本应升级到新字段。

## 修复建议优先级

（占位 · Task 10 整合）

## 已验证对齐项

（占位 · Task 10 整合）

## 未验证项

（占位 · Task 10 整合）

## 修订记录

- 2026-06-18 初版（Claude）
