# Mining UI PG 迁移 — Claude Handoff

- 任务归属：`TASK-20260421-v11-knowledge-mining`
- 关联计划：`docs/plans/2026-05-06-mining-ui-pg-migration-impl-plan.md`
- 文件路径：`docs/handoffs/2026-05-06-mining-ui-pg-migration-claude-handoff.md`
- 提交：Claude / 2026-05-06

## 1. 任务目标

让 `scripts/mining_ui.py`（Gradio 可视化面板）从 SQLite 双库假设迁移到 PostgreSQL，使其能与已经迁移到 PG 的 Mining v1.1 流水线协同工作，恢复"上传 → 触发挖掘 → 进度回显 → 多 stage 结果展示"的端到端体验。

## 2. 本次实现范围

| 项 | 状态 |
|----|------|
| 改 `_open_asset` / `_open_runtime` 为 PG 池版本 | ✅ |
| 引入 `_PGConn` / `_PGCursor` 兼容层（保留 `.execute(...).fetchall()` 链式调用） | ✅ |
| 全文 25+ 处 `?` SQL 占位符 → `%s` | ✅ |
| 4 处 IN-clause 动态 placeholder builder（`?` 改为 `%s`） | ✅ |
| `_query_latest_run` 改成 PG 查询 | ✅ |
| `do_mining()` 删除废弃的 `asset_core_db_path` / `mining_runtime_db_path` kwarg | ✅ |
| 删除 `ASSET_DB` / `RUNTIME_DB` 常量与 `import sqlite3` | ✅ |
| 顶部 docstring 与函数 docstring 中 "mining_runtime.sqlite" 字样改为 "PostgreSQL kb_db" | ✅ |
| 端到端冒烟（mining_run + 全部 10 个 render 函数） | ✅ |

## 3. 不在本次范围内

- 不修改 `knowledge_mining/mining/` 下的流水线代码
- 不重新设计 Gradio UI 布局，未新增 tab / control / 图表
- 不修复 `pg_schema.py::_split_ddl` 的 PL/pgSQL 切分 bug —— 已识别为残余项（详见第 8 节）
- 不删除旧 `data/ui_asset_core.sqlite` / `data/ui_mining_runtime.sqlite` 文件（保留供用户参考）
- 不改 `requirements.txt` / 依赖清单（已声明 `psycopg[binary]`、`psycopg-pool`）
- 不实现 PG 重连 / 熔断（依赖 psycopg_pool 默认行为）

## 4. 改动文件清单

| 文件 | 类型 | 行数变化 | 说明 |
|------|------|---------|------|
| `scripts/mining_ui.py` | 修改 | 1251 → 1244 | 主体迁移，全文 PG 化 |
| `docs/plans/2026-05-06-mining-ui-pg-migration-impl-plan.md` | 新增 | +106 | 计划文档 |
| `docs/handoffs/2026-05-06-mining-ui-pg-migration-claude-handoff.md` | 新增 | 本文件 | 交接文档 |

注：`scripts/mining_ui.py` 在本次会话开始前未在 git 索引中（worktree 状态显示为 untracked），本次提交即首次入库。

## 5. 关键设计决策

### 5.1 兼容层 `_PGConn` / `_PGCursor`

为避免改动 9 个 render 函数的调用面（`rt.execute(sql, params).fetchall()` / `.fetchone()` 链式调用），引入两个轻量包装类：

- `_PGConn` 借用 `psycopg_pool.ConnectionPool.connection()` context manager，并暴露 `.execute()` 与 `.close()`；`.close()` 语义为"归还连接到池"
- `_PGCursor` 包住一次查询的游标，`.fetchone()` / `.fetchall()` 调用后自动关闭游标

> **为什么不直接重写 render 函数**：9 个 render 函数都遵循同样的调用模式，通过包装层一次性兼容比逐个改写风险小、改动面小

### 5.2 共享连接池

- 模块级全局 `_pg_pool: ConnectionPool | None` 单例
- 第一次 `_get_pool()` 调用时延迟初始化（`open=True`、`min=1, max=4`、`row_factory=dict_row`）
- `_open_asset()` 与 `_open_runtime()` 共用同一池（指向同一 `kb_db`），保留双工厂函数仅为不打破 render 函数命名习惯

### 5.3 SQL 占位符

- `?` → `%s` 共 21 处（文件级别变更）
- 4 处 IN-clause 动态构造：`",".join("?" * len(ids))` → `",".join(["%s"] * len(ids))`
  - 注意：`"%s" * 3 = "%s%s%s"`（无逗号），所以必须用 `[]` 列表展开后 join
- `mime = (snap["mime_type"] if snap else "?") or "?"`（`mining_ui.py` 第 706 行附近）保留——这是显示回退字符串，非 SQL placeholder

### 5.4 触发挖掘

`mining_run()` 调用方仅删除两个废弃 kwarg，不传 `db_config`，让 `mining_run` 内部自行 `MiningDbConfig()` 从 `.env` 读取 PG 配置。维持 mining 流水线"db 配置全局来自 .env"的统一口径。

## 6. 已执行验证

### 6.1 静态验证

- AST parse OK（78 顶层节点）
- `import mining_ui` 无错误
- 全文搜索：无残留 `sqlite3.connect` / `sqlite3.Row` / `ASSET_DB` / `RUNTIME_DB` 引用（除 `_PGConn` docstring 中"sqlite3.Connection"作为 API 语义说明保留）

### 6.2 PG 接入层冒烟

```
mining_runs count: 0
mining_run_documents count: 0
asset_documents count: 0
IN clause query OK, rows: 0
latest run for nonexistent path: None
OK
```

确认 `_get_pool` / `_PGConn` / `_PGCursor` / `dict_row` / IN-clause 占位符 / `_query_latest_run` 全部正常。

### 6.3 端到端冒烟

样本：`cloud_core_coldstart_md/01_features/{gwfd_010224_n4.md, gwfd_010310_dnn.md}` 复制到 `data/uploads/_smoke/`

调用：`mining_run(input_path='data/uploads/_smoke', batch_params=BatchParams(...), domain_pack='cloud_core_network', llm_base_url=None, embedding_api_key=None)`

结果：

```
RUN RESULT: {'run_id': 'eb6ac5026cac491faf552ef9859f5b94',
             'status': 'completed',
             'total_documents': 2, 'new_count': 2,
             'failed_count': 0, 'committed_count': 2}
```

随即对该 run_id 调用 10 个 render 函数：

| renderer | 状态 | final df 行数 |
|----------|------|--------------|
| ingest | OK | 2 |
| parse | OK | 28 |
| segment | OK | 54 |
| enrich | OK | 0 |
| relations | OK | 806 |
| retrieval_units | OK | 60 |
| snapshot | OK | 2 |
| build | OK | 2 |
| release | OK | 1 |
| timeline | OK | 22 |

> `enrich` 返回 0 行符合预期：本次冒烟未启用 LLM（`llm_base_url=None`），enrich 阶段的 LLM 角色/实体附注本就不会产生数据。其他 9 个 stage 全部产出非空表。

## 7. 未验证项

- **未实际启动 Gradio UI 服务在浏览器跑一遍**：无法在终端环境驱动浏览器；render 函数已经端到端验证，但 Gradio 组件绑定（按钮 → callback → DataFrame 输出）这层未做交互验证。建议用户启动 `py -3.10 scripts/mining_ui.py` 自检一次
- 未在 `use_llm=True` 路径下做冒烟（plan 已声明不验证）
- 未在大数据集（>50 文档）上做压测

## 8. 已知风险与残余问题

| 项 | 风险评级 | 说明 |
|---|---------|------|
| `pg_schema.py::_split_ddl` 切坏 PL/pgSQL 函数体 | 中 | 已发现：第二次 `ensure_schema` 重跑会因 CREATE TRIGGER 无 IF NOT EXISTS 而失败；本次绕开未修。建议另开 task |
| Gradio UI 实际交互未跑 | 中 | 见第 7 节 |
| 旧 SQLite 文件残留 | 极低 | 不读不写，保留供用户参考 |
| psycopg pool 在长期空闲后是否需要 keepalive | 低 | 默认 idle timeout 由 psycopg_pool 管理，UI 单用户场景下不构成问题 |

## 9. 给 Codex 的审查重点

请重点审查以下几项：

1. **`_PGConn` 包装类语义完备性**：`.execute(sql, params).fetchone()/fetchall()` 是否完全等价于原 sqlite3.Connection 用法？特别是空结果集、None 字段、JSON 字段的返回行为
2. **连接池关闭时机**：每个 render 函数 `finally: rt.close(); asset.close()` 现在归还的是池连接而非真关连接，是否会因游标未及时关闭导致连接泄漏？`_PGCursor` 已在 `fetchone/fetchall` 后立即 close 游标
3. **占位符替换完整性**：是否漏改 / 误改？特别是 IN-clause 动态构造和字符串内的 `?`
4. **`dict_row` 行为兼容**：原 `sqlite3.Row` 支持索引访问 `r[0]` 与列名访问 `r["col"]`，psycopg `dict_row` 仅支持后者；本文件全部用列名访问，已确认安全
5. **多线程下连接池**：`do_mining` 启动后台 worker 线程跑 `mining_run()`，主线程同时跑 `_query_latest_run` 轮询。pool 默认线程安全，但需确认 `mining_run` 内部连的是 `MiningDbConfig` 自建的池而非 UI 的池——确认无冲突
6. **CRTL-C 退出时连接池清理**：当前没有显式 `pool.close()`，进程退出时连接由 OS 回收，是否需要加 `atexit` hook

## 10. 管理员本轮直接介入记录

- 用户在本会话中先报告 `TypeError: run() got an unexpected keyword argument 'asset_core_db_path'`
- 用户选择"完整迁移 UI"方案（plan 中的方案 1）
- 用户口头确认 plan，未对具体设计点作定向指示
- 冒烟样本由 Claude 自行从 `cloud_core_coldstart_md/01_features/` 选取，未事先征询用户
