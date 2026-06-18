# 2026-06-18 · llm_service 文档对齐刷新 · 设计文档

- 任务类型：文档对齐（不修代码）
- 负责人：Claude
- 关联模块：`llm_service/`
- 上游需求：用户指令「全面检查 llm_service 实现细节，更新相关文档，拆分成多个任务」

## 1. 背景与问题

`llm_service/` 自 2026-05 以来累计 **65 次提交**，发生多次重大变更，但 `README.md` / `QUICKSTART.md` 停留在 2026-05-08，`architecture.html` 停留在 2026-04-23。文档与代码出现严重漂移：

| 文档当前描述 | 代码实际状态 |
|---|---|
| SQLite WAL，6 张表 | 已迁 PostgreSQL，schema 由 `pg_schema.py` 定义 |
| `runtime/executor.py` 执行引擎 | 文件不存在（已并入 `service.py` / `worker.py`） |
| 模块图缺 `pg_config.py` / `pg_schema.py` / `runtime/persist_writer.py` / `runtime/event_bus.py` | 均存在并承担关键职责 |
| providers 仅 BigModel / OpenAI / Mock | 多了 `providers/anthropic.py` |
| 未提及配置热重载 | 已支持（commit 2f8cf32, 94764f7） |
| 未提及 DB 死锁恢复 | 已修复（commit 63c0412） |
| 未提及 PersistWriter 解耦 | 已落地（commit 49138e5） |

漂移使 README 成为误导源，新成员按文档无法启动服务，审计/交接成本上升。

## 2. 目标与非目标

### 目标
- 以**代码为唯一真相**，逐文件全核 `llm_service/` 下 4271 行 Python 源码
- 让 `README.md` / `QUICKSTART.md` / `ARCHITECTURE.md` 三份文档与代码完全对齐
- 把审计中发现的问题（代码/文档两类）归档到 handoff，**不在本次修复**

### 非目标
- 不修复发现的代码问题（即使 typo / 未用 import 也只记录）
- 不更新 `docs/` 目录下的其他 llm-service 相关文档（如 `2026-05-20-llm-service-architecture-review.md`、`docs/plans/2026-05-28-llm-service-config-consolidation.md`）——这些是历史归档，保留语义
- 不重写 `architecture.html`，只加 deprecated banner 指向 `ARCHITECTURE.md`
- 不变更任何对外 API/配置/SQL

## 3. 交付物

| 文件 | 动作 | 体量目标 |
|---|---|---|
| `llm_service/README.md` | 重写 | ≤ 18KB |
| `llm_service/ARCHITECTURE.md` | **新建** | ≤ 25KB |
| `llm_service/QUICKSTART.md` | 增量修订 | 保持现有体量 |
| `llm_service/architecture.html` | 仅加 deprecated banner | 单次小改 |
| `docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md` | 新建审计报告 | 不限 |

## 4. 文档目录骨架（已获用户确认）

### 4.1 README.md
1. 系统定位
2. 快速启动（指向 QUICKSTART）
3. API 总览
4. 环境变量
5. 架构指向（→ `ARCHITECTURE.md`）
6. 测试
7. 运维与排错（端口 / 健康 / 死锁恢复 / 日志位置）

### 4.2 ARCHITECTURE.md
1. 模块全图（含表）
2. 启动生命周期（lifespan / worker / recovery）
3. 数据流：聊天 sync / 聊天 async / Embedding / Rerank
4. 任务状态机
5. Provider 体系与扩展
6. 存储层（PostgreSQL schema + PersistWriter 解耦）
7. 配置与热重载
8. 已知边界与限制

## 5. 验证标准

- README 中每一个 API 端点引用，必须能在 `api/*.py` 中找到对应路由
- README 中每一个环境变量，必须能在 `config.py` 中找到定义
- ARCHITECTURE.md 模块图每一行，必须能在仓库中找到对应文件
- ARCHITECTURE.md 每条数据流，必须能在代码中追溯调用链（service.py / model_service.py / worker.py）
- 任务状态机的所有状态/迁移，必须能在 `task_manager.py` + `db.py`/`pg_schema.py` 中找到对应字段/SQL
- 文档与代码冲突点统一列入 handoff，不散落在文档内

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 逐文件全核 4271 行可能放大单次会话上下文 | 按目录分批读（runtime → providers → api → 顶层），每读完一组立即写入对应文档章节 |
| 发现的问题不修可能让用户感觉"白审计" | handoff 中按严重度分级（CRITICAL/HIGH/MEDIUM/LOW），并给出修复建议，便于后续单独立项 |
| ARCHITECTURE.md 新建可能被误认为"重复的架构文档" | 在文件头部注明：本文是 llm_service **模块级**实现文档，区别于 `docs/architecture/*` 的系统级架构 |

## 7. 后续动作

设计获批后，调用 `superpowers:writing-plans` skill 生成实现计划，按"读代码 → 写文档 → 自校 → 提交"的顺序拆分为可独立执行的子任务。

## 8. 修订记录

- 2026-06-18 初版（Claude）
