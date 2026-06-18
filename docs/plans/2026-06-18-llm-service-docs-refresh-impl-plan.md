# llm_service 文档对齐刷新 · 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 以代码为唯一真相，逐文件全核 `llm_service/` 4271 行源码，刷新 README/QUICKSTART 并新增 ARCHITECTURE.md，使文档与代码完全对齐。

**Architecture:** 文档审计而非代码实现。按目录分批读源码 → 边读边写文档章节 → 跨文档自校 → 汇总审计 handoff。每个 Task 是「读一组文件 → 产出一段文档 → 自校 → 提交」的闭环颗粒度（2-5 分钟）。

**Tech Stack:** Python 3 / FastAPI / PostgreSQL / httpx / pytest。无需运行测试（既不修代码也不补测试），所有"运行命令"步骤均为静态自校脚本。

**关联设计：** `docs/plans/2026-06-18-llm-service-docs-refresh-design.md`

**约束：**
- 只动文档，不动代码（包括 typo / 未用 import 也不修）
- 发现的问题全部进 handoff，按 CRITICAL/HIGH/MEDIUM/LOW 分级
- 文档体量目标：README ≤ 18KB、ARCHITECTURE ≤ 25KB
- git 提交只提交本次新增/修改的文档文件，不带任何代码改动
- `architecture.html` 只加 deprecated banner，不重写

---

## Task 0：准备工作与文档骨架

**Files:**
- Create: `llm_service/ARCHITECTURE.md`（仅 H1 + 章节标题）
- Create: `docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md`（仅模板）

**Step 1: 创建 ARCHITECTURE.md 骨架**

写入 8 个 H2 章节标题（暂留 TODO 占位）：
```
# llm_service 内部架构

> 模块级实现文档。系统级架构请参见 docs/architecture/*。
> 状态：2026-06-18 由 Claude 基于 commit <HEAD> 全核刷新。

## 1. 模块全图
## 2. 启动生命周期
## 3. 数据流
## 4. 任务状态机
## 5. Provider 体系
## 6. 存储层
## 7. 配置与热重载
## 8. 已知边界与限制
```

**Step 2: 创建 handoff 模板**

```
# 2026-06-18 · llm_service 文档审计 · Claude Handoff

## 审计范围
llm_service/ 全部源码 + 现有文档

## 审计方法
逐文件全核 → 对照文档 → 漂移点入此文档

## 发现汇总（按严重度）
### CRITICAL
（占位）

### HIGH
（占位）

### MEDIUM
（占位）

### LOW
（占位）

## 修复建议优先级
（占位）

## 已验证对齐项
（占位）
```

**Step 3: 校验骨架就位**

Run: `ls llm_service/ARCHITECTURE.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md`
Expected: 两个文件都存在

**Step 4: Commit**

```bash
git add -f llm_service/ARCHITECTURE.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: scaffold llm_service docs refresh skeleton"
```

---

## Task 1：审计 runtime 核心（service / worker / task_manager）

**Files to read:**
- `llm_service/runtime/service.py`
- `llm_service/runtime/worker.py`
- `llm_service/runtime/task_manager.py`

**Step 1: 读三个文件**

Run: 用 Read 工具读完整三个文件（不省略行号）

**Step 2: 提炼事实并写入 ARCHITECTURE.md 第 2、3、4 章**

需要从代码中提炼：
- 第 2 章（启动生命周期）：`main.py` lifespan → Worker 启动 → LeaseRecovery → 信号处理（具体调用链）
- 第 3 章（数据流）：sync execute 调用链（service.submit → task_manager → 同步 claim → provider → parser → persist）、async submit 调用链（submit → worker poll → provider → parser → event_bus）
- 第 4 章（任务状态机）：列出所有状态字段值、状态迁移矩阵（claim/complete/fail/cancel/lease_recover 各自动作）

**Step 3: 对照旧 README，把漂移点写入 handoff**

每发现一处文档说的跟代码不一样，立即在 handoff 对应严重度下追加一行：
- 严重度判定：状态机/数据流错误 = HIGH；模块/文件名错误 = MEDIUM；描述不准 = LOW

**Step 4: Commit**

```bash
git add -f llm_service/ARCHITECTURE.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: audit runtime core (service/worker/task_manager) → ARCHITECTURE sec 2-4"
```

---

## Task 2：审计 runtime 辅助层（model_service / persist_writer / event_bus / idempotency / parser / template_registry）

**Files to read:**
- `llm_service/runtime/model_service.py`
- `llm_service/runtime/persist_writer.py`
- `llm_service/runtime/event_bus.py`
- `llm_service/runtime/idempotency.py`
- `llm_service/runtime/parser.py`
- `llm_service/runtime/template_registry.py`

**Step 1: 读六个文件**

**Step 2: 补全 ARCHITECTURE.md**

- 第 3 章新增 Embedding / Rerank 数据流子节（model_service 直通链路 + PersistWriter 解耦点）
- 第 6 章（存储层）写入 PersistWriter 的工作机制（队列/批写/异常处理）
- 第 5 章写入 parser 支持的输出模式（text / json_object / json_array + jsonschema）
- 第 4 章补 idempotency 逻辑（idempotency_key 命中复用）
- 第 3 章补 event_bus 落库时机

**Step 3: handoff 追加新发现**

**Step 4: Commit**

```bash
git add -f llm_service/ARCHITECTURE.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: audit runtime helpers → ARCHITECTURE sec 3/5/6 补全"
```

---

## Task 3：审计 providers 体系

**Files to read:**
- `llm_service/providers/base.py`
- `llm_service/providers/model_base.py`
- `llm_service/providers/openai_compatible.py`
- `llm_service/providers/bigmodel_models.py`
- `llm_service/providers/anthropic.py`
- `llm_service/providers/mock.py`
- `llm_service/providers/utils.py`

**Step 1: 读七个文件**

**Step 2: 写 ARCHITECTURE.md 第 5 章（Provider 体系与扩展）**

必须包含：
- 两个协议（ProviderProtocol / ModelProviderProtocol）的方法签名
- 四个具体 Provider 的能力矩阵（聊天 / Embedding / Rerank 各支持哪些）
- 错误模型（ProviderError / ModelProviderError 的字段与重试语义）
- 扩展指南：新增 Provider 的最小步骤（实现协议 / 注册到哪个工厂 / 配置项命名约定）

**Step 3: handoff 追加漂移**

特别注意：旧 README 模块图没有 `anthropic.py`，必记 HIGH。

**Step 4: Commit**

```bash
git add -f llm_service/ARCHITECTURE.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: audit providers → ARCHITECTURE sec 5 完成"
```

---

## Task 4：审计 API 层

**Files to read:**
- `llm_service/api/tasks.py`
- `llm_service/api/results.py`
- `llm_service/api/model_api.py`
- `llm_service/api/templates.py`
- `llm_service/api/admin.py`
- `llm_service/api/stats.py`
- `llm_service/api/health.py`

**Step 1: 读七个文件**

**Step 2: 整理 API 路由清单**

写入临时表格（最后进 README 第 3 章 + ARCHITECTURE 第 1 章的 API 子表）：

| Method | Path | Handler | 用途 |
|---|---|---|---|

**Step 3: handoff 追加文档缺失的端点**

**Step 4: Commit（只更新 handoff，README 留到 Task 7 整合时写）**

```bash
git add -f docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: audit api layer → 收齐路由清单入 handoff"
```

---

## Task 5：审计顶层（main / config / client / models / db / pg_schema / pg_config）

**Files to read:**
- `llm_service/main.py`
- `llm_service/config.py`
- `llm_service/client.py`
- `llm_service/models.py`
- `llm_service/db.py`
- `llm_service/pg_schema.py`
- `llm_service/pg_config.py`
- `llm_service/__init__.py`
- `llm_service/__main__.py`

**Step 1: 读九个文件**

**Step 2: 补全 ARCHITECTURE.md 剩余章节**

- 第 1 章（模块全图）：用真实文件清单替换骨架里的 TODO，含每个文件一句话职责
- 第 6 章（存储层）：写入 pg_schema 定义的表/字段、pg_config 的连接策略、db.py 的连接池/autocommit
- 第 7 章（配置与热重载）：列出所有环境变量（从 config.py 提取）+ 热重载机制（信号/文件 watcher/inotify）

**Step 3: handoff 追加漂移**

特别注意：
- README 说 SQLite WAL → 实际 PostgreSQL（CRITICAL，影响启动排错）
- README 说 6 张表 → 核对 pg_schema 实际表数（HIGH）
- 环境变量前缀 LLM_SERVICE_* 是否仍然有效（HIGH）

**Step 4: Commit**

```bash
git add -f llm_service/ARCHITECTURE.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: audit top-level (main/config/client/db/pg_*) → ARCHITECTURE sec 1/6/7 完成"
```

---

## Task 6：审计 tests 与补充

**Files to read:**
- `llm_service/tests/conftest.py`
- `llm_service/tests/test_client.py`
- `llm_service/tests/test_models.py`
- `llm_service/tests/test_parser.py`
- `llm_service/tests/test_providers.py`
- `llm_service/tests/curl_test.md`
- `llm_service/tests/profile_execute.py`
- `llm_service/tests/test_live_demo.py`

**Step 1: 读全部 tests 文件**

**Step 2: 整理测试清单**

每文件分类：unit / integration / live / profiling，每个 test 函数一句话说明。

**Step 3: 旧 README 说"96 passed" → 实际数对照**

Run: `grep -c "def test_" llm_service/tests/*.py`
对比：若实际数 ≠ 96，记入 handoff MEDIUM。

**Step 4: Commit（只更新 handoff）**

```bash
git add -f docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: audit tests → handoff 收齐测试清单"
```

---

## Task 7：重写 README.md

**Files:**
- Modify: `llm_service/README.md`（完全重写）

**Step 1: 用前面 Task 1-6 收集的事实重写 README**

按已确认的目录骨架：
1. 系统定位
2. 快速启动（指向 QUICKSTART）
3. API 总览（用 Task 4 表格）
4. 环境变量（用 Task 5 config.py 提取的）
5. 架构指向（→ ARCHITECTURE.md，一句摘要 + 链接）
6. 测试（用 Task 6 清单）
7. 运维与排错（端口 / 健康 / 死锁恢复 / 日志位置）

体量目标 ≤ 18KB。超过则压缩表格与示例。

**Step 2: 自校**

Run:
```bash
# README 提到的每个 /api 路径必须在 api/ 中存在
grep -oE '/api/v[0-9]+/[a-z_/{}-]+' llm_service/README.md | sort -u
```
逐一对照 `api/*.py` 中的 `@router.{method}("...")`。

Run:
```bash
# README 提到的每个环境变量必须在 config.py 中存在
grep -oE 'LLM_SERVICE_[A-Z_]+' llm_service/README.md | sort -u
```
逐一对照 `config.py` 中的字段定义。

不一致的全部在 handoff 中追加（如有）。

**Step 3: Commit**

```bash
git add -f llm_service/README.md docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: rewrite llm_service README aligned with current code"
```

---

## Task 8：增量更新 QUICKSTART.md

**Files:**
- Modify: `llm_service/QUICKSTART.md`

**Step 1: 读现状**

Run: 用 Read 工具读完整 QUICKSTART.md

**Step 2: 修订**

只改与代码冲突的部分（最小动作）：
- 数据库连接串示例：SQLite → PostgreSQL
- 端口/启动命令：核对 `__main__.py` + `main.py`
- 客户端示例：核对 `client.py` 当前 API
- curl 示例：核对 `tests/curl_test.md` 中最新可用端点

其余保留。若 QUICKSTART 已正确则只更新顶部"最后核对日期"。

**Step 3: Commit**

```bash
git add -f llm_service/QUICKSTART.md
git commit -m "[claude]: incrementally update llm_service QUICKSTART for current code"
```

---

## Task 9：architecture.html 加 deprecated banner

**Files:**
- Modify: `llm_service/architecture.html`（仅头部插入 banner）

**Step 1: 读 HTML 头部 30 行**

**Step 2: 在 `<body>` 之后插入 deprecated banner**

样式简洁，内容：
- 标题：⚠️ 本架构图已过时（2026-04-23 版本）
- 指向：`./ARCHITECTURE.md`
- 不删除原图（用户指示"对齐实现"+"只加 banner"）

**Step 3: Commit**

```bash
git add -f llm_service/architecture.html
git commit -m "[claude]: add deprecated banner to llm_service architecture.html"
```

---

## Task 10：完善 handoff 终稿

**Files:**
- Modify: `docs/handoffs/2026-06-18-llm_service-docs-audit-claude-handoff.md`

**Step 1: 整合所有发现**

将 Task 1-7 中追加的每条漂移点重新审视：
- 去重
- 按 CRITICAL/HIGH/MEDIUM/LOW 排序
- 每条给出：位置（文件:行号）+ 现状 + 建议 + 工作量估计

**Step 2: 写"已验证对齐项"**

列出本次已经通过文档更新对齐的项目（让接手人知道哪些点不用再看）。

**Step 3: 写"修复建议优先级"**

按"先 CRITICAL 再 HIGH"给出修复顺序，并标注哪些可以批量改、哪些需要单独评审。

**Step 4: 写"未验证项"**

诚实列出本次没核到的（如未跑测试、未在容器内验证启动、未做实际 LLM 调用）。

**Step 5: Commit**

```bash
git add -f docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
git commit -m "[claude]: finalize llm_service docs audit handoff"
```

---

## Task 11：总体自校与统一提交

**Files:** 全部本次产出的文档

**Step 1: 全文交叉校验**

Run:
```bash
# 1) ARCHITECTURE.md 提到的文件都存在
grep -oE 'llm_service/[a-z_/]+\.py' llm_service/ARCHITECTURE.md | sort -u | while read f; do
  [ -f "$f" ] || echo "MISSING: $f"
done

# 2) README 与 ARCHITECTURE 引用一致
diff <(grep -oE 'LLM_SERVICE_[A-Z_]+' llm_service/README.md | sort -u) \
     <(grep -oE 'LLM_SERVICE_[A-Z_]+' llm_service/ARCHITECTURE.md | sort -u) || true

# 3) handoff 中每条 CRITICAL/HIGH 都有对应文件路径
grep -E '^(CRITICAL|HIGH)' docs/handoffs/2026-06-18-llm-service-docs-audit-claude-handoff.md
```

不一致的全部补齐。

**Step 2: CLAUDE.md §6 自检**

- 是否只提交了文档，没带任何代码改动？✓
- 是否所有 commit message 以 `[claude]:` 开头？✓
- 是否逐文件 `git add -f <path>`，没用 `git add .`？✓

**Step 3: 总结报告**

输出本次会话总结：审计了多少行代码、刷新了几份文档、记录了几条 handoff 项（按严重度）。

---

## 执行总览

| Task | 主产出 | 估时 |
|---|---|---|
| 0 | ARCHITECTURE.md 骨架 + handoff 模板 | 2 分钟 |
| 1 | ARCH sec 2-4（runtime 核心） | 8 分钟 |
| 2 | ARCH sec 3/5/6（runtime 辅助） | 8 分钟 |
| 3 | ARCH sec 5（providers） | 6 分钟 |
| 4 | API 路由清单入 handoff | 5 分钟 |
| 5 | ARCH sec 1/6/7（顶层 + 存储 + 配置） | 8 分钟 |
| 6 | 测试清单入 handoff | 4 分钟 |
| 7 | README 重写 + 自校 | 10 分钟 |
| 8 | QUICKSTART 增量更新 | 5 分钟 |
| 9 | architecture.html banner | 2 分钟 |
| 10 | handoff 终稿 | 6 分钟 |
| 11 | 总体自校 | 4 分钟 |

合计 11 个 Task，可串行执行；每个 Task 后均提交一次，可随时暂停。
