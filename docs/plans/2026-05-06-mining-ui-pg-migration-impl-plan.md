# Mining UI PG 迁移实现计划

- 任务归属：`TASK-20260421-v11-knowledge-mining`
- 文件路径：`docs/plans/2026-05-06-mining-ui-pg-migration-impl-plan.md`
- 起草：Claude / 2026-05-06
- 触发背景：v1.1 Mining 流水线已迁移至 PostgreSQL（commits 4bfc177、e001ca9 等），但 `scripts/mining_ui.py` 仍按 SQLite 双库假设编写，运行时会触发 `TypeError: run() got an unexpected keyword argument 'asset_core_db_path'`，且即便修掉 kwarg，9 个 render 函数全部仍读本地 SQLite 文件，UI 实际不可用。

## 1. 任务目标

让 `scripts/mining_ui.py` 在不修改 mining 流水线核心代码的前提下：

1. 通过 `MiningDbConfig` 读取 `.env` 中的 PG 连接，触发 `mining_run()` 不再传废弃 kwarg
2. 所有 polling / render 函数从 PG 同库（`kb_db`）读取 `mining_runs / mining_run_stage_events / mining_run_documents` 与 `asset_*` 表
3. 保持现有 Gradio UI 体验：上传 → 触发 → 进度面板实时刷新 → 各 stage 表/图齐全

## 2. 不在本次范围内

- 不修改 `knowledge_mining/mining/` 内任何流水线代码
- 不重新设计 UI 布局、不增加新页面
- 不修复 `pg_schema.py::_split_ddl` 的 PL/pgSQL 切分 bug（已识别为残余项，单开 task）
- 不删除 `data/ui_asset_core.sqlite` / `data/ui_mining_runtime.sqlite` 旧文件（用户保留参考，至多在文档里提示可删）
- 不改 `requirements.txt` / 依赖（项目已声明 `psycopg[binary]`、`psycopg-pool`）

## 3. 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `scripts/mining_ui.py` | 重写 PG 接入与查询层 | 主体改动，约 1100→1100 行同量级 |

无新增文件、无其他修改。

## 4. 关键设计决策

### 4.1 连接管理

- 引入 `MiningDbConfig` 单例并构造一份 conninfo
- 用 `psycopg_pool.ConnectionPool`（同步、`open=True`）做共享连接池，规模 `min=1, max=4`，避免每次请求新建 PG TCP
- 保留 `_open_asset()` / `_open_runtime()` 函数名（对外接口不变），但内部改为 `pool.connection()` context manager，并按当前调用约定返回一个具备 `.execute(sql, params).fetchall()` 接口的薄包装

> 决策原因：当前调用方写法是 `rt.execute(...)` 直接拿游标，再 `.fetchall()`。psycopg 必须 `with conn.cursor() as cur: cur.execute(...)`。为了不改 9 个 render 函数的调用面，引入一个轻量包装类 `_PGConn`，把 `.execute()` 转成游标层调用，并保留 `.close()` 语义（归还连接）

### 4.2 SQL 占位符

- 所有 `?` → `%s`（共 ~25 处，逐处替换，不用 sed 全文）
- 字符串内偶发的 `?` 字符（如错误消息、URL）保持不动 —— 检视所有改动点确认仅 SQL 中的占位符被换

### 4.3 Row 访问

- psycopg 连接池统一传 `kwargs={"row_factory": dict_row}`
- `r["column"]` 访问保持不变；`for r in rows` 等迭代不变
- `pandas.DataFrame([dict, ...])` 兼容

### 4.4 触发挖掘

- `do_mining()` 的 `mining_run()` 调用：
  - 删除 `asset_core_db_path=ASSET_DB`、`mining_runtime_db_path=RUNTIME_DB`
  - 不传 `db_config=` —— 让 `mining_run()` 自动 `MiningDbConfig()` 从 `.env` 读
- `ASSET_DB` / `RUNTIME_DB` 两个常量删除

### 4.5 polling

- `_query_latest_run()` 改成走连接池一次查询 `mining_runs` + `mining_run_stage_events`，PG 数据延迟 << 1s，与现有 `time.sleep(1.0)` 轮询频率匹配
- 仍按 `input_path` 字段定位最近一次 run

### 4.6 不做的优化

- 不把 9 个 render 合并查询、不引入 ORM、不改 UI 表结构
- 不把 polling 改成 SSE / WebSocket
- 不加 PG 重连/熔断（psycopg pool 自带）

## 5. 验证策略

### 5.1 静态验证
- `py -3.10 -c "import scripts.mining_ui"` 模块可加载
- 全文不再含 `sqlite3.` / `ASSET_DB` / `RUNTIME_DB` / `?` 占位符（除字符串外）

### 5.2 手工冒烟（必做）
1. 启动：`py -3.10 scripts/mining_ui.py` → 浏览器打开 `127.0.0.1:7860`
2. 上传 1-2 个示例 markdown
3. 选 domain pack（默认 `cloud_core_network`）
4. 点击"开始挖掘"
5. 观察：
   - 进度面板 1s 刷新，能看到 stage 名 + status
   - 跑到 "completed" 后所有 9 个 tab（ingest/parse/segment/enrich/relations/retrieval_units/snapshot/build/release/timeline）能渲染出非空表格

### 5.3 不做的验证
- 不跑 `pytest knowledge_mining/`（UI 改动不影响流水线测试）
- 不做 LLM/embedding 路径验证（保持 `use_llm=False` 即可）
- 不做大数据集压力测试

## 6. 已知风险

| 风险 | 评级 | 缓解 |
|------|------|------|
| `_open_asset/_open_runtime` 调用方依赖 sqlite3.Row 特性（如属性访问） | 中 | 已 grep 全文，仅用 `r["col"]` 字典访问；psycopg dict_row 兼容 |
| polling 期间连接池耗尽 | 低 | max=4，每个 render 借完即还；UI 只单用户使用 |
| .env 缺失 PG_* 变量 | 中 | 当前 `.env` 已配；启动失败会立即报 `ValidationError`，用户可见，无破坏 |
| 旧 SQLite 数据文件残留 | 极低 | 不读不写即可；不删除 |
| 表 schema 与 SQL 列名不一致 | 中 | 列名照 `databases/asset_core/schemas/*.sql` 与 `databases/mining_runtime/schemas/*.sql` 对齐 — 已抽样核对 `asset_documents/asset_raw_segments/asset_builds/mining_runs/mining_run_documents/mining_run_stage_events`，列名一致 |

## 7. 验证执行后给 Codex 的审查重点

- `_PGConn` 包装类语义是否能完整替代 sqlite3.Connection 的 `.execute(...).fetchall()` 链
- 连接池关闭时机（`.close()` 是归还连接还是真关池）
- 占位符替换是否漏改 / 误改字符串内的 `?`
- `dict_row` 下 `r["column"]` 对 None 字段的行为是否与 sqlite3.Row 一致

## 8. 不会写的文档

- 不写新 README / QUICKSTART
- 不更新 `mining_ui.py` 的开头 docstring 之外的文档（docstring 内 "mining_runtime.sqlite" 字样改为 "PostgreSQL kb_db"）
