# COLLAB_TASKS

本文档是仓库内协作任务总入口。

使用规则：

- 每个非琐碎任务只保留一条任务记录
- 所有正式文档路径都挂到对应任务下
- 当前状态、当前阶段、最新消息序号优先在这里维护
- 已结束任务可移动到“已完成任务”区，但不要删除历史

---

## 活跃任务模板

## <task-id>
- 标题：
- 级别：
- 状态：
- 当前阶段：
- Claude：
- Codex：
- 管理员：
- 计划文档：
- 交接文档：
- 审查文档：
- 修复文档：
- 管理员文档：
- 最新消息序号：
- 备注：

字段分权：

- Claude 维护：`计划文档`、`交接文档`、`修复文档`
- Codex 维护：`审查文档`
- 管理员维护：`状态`、`当前阶段`、`备注`
- 三方都可维护：自己的责任字段、`最新消息序号`

---

## 活跃任务

## TASK-20260421-v11-knowledge-mining
- 标题：CoreMasterKB v1.1 Knowledge Mining 重构
- 级别：正式
- 状态：Codex review 6 项全部修复，30 测试通过，LLM 接缝已建立，待 Codex 复审
- 当前阶段：review 修复完成，待复审
- Claude：Claude Mining 已完成 Codex review 全部 P1+P2 修复，enrich 正式可替换、generated_question 预留、build merge 语义、run 失败语义、旧测试清理
- Codex：已补发本轮 bug-review，明确当前 LLM 已进入 generated_question，但 enrich 主链、source_refs 合同与测试闭环仍待修
- 管理员：已确认 v1.1 数据库架构、shared snapshot、build/release 与三库边界为统一口径
- 计划文档：`docs/plans/2026-04-21-v11-knowledge-mining-impl-plan.md`
- 交接文档：`docs/handoffs/2026-04-21-v11-knowledge-mining-claude-mining-handoff.md`
- 审查文档：`docs/analysis/2026-04-27-v11-knowledge-mining-state-audit-codex-review.md`
- 修复文档：`docs/handoffs/2026-04-21-v11-knowledge-mining-claude-mining-fix.md`
- 阶段审查文档：`docs/handoffs/2026-04-22-v11-knowledge-mining-claude-mining-stage-review.md`
- 管理员文档：
- 最新消息序号：MSG-20260427-103000-codex
- 备注：主背景见 `README.md`、`docs/architecture/2026-04-21-coremasterkb-v1.1-architecture.md`、`.dev/2026-04-21-v1.1-database-complete-proposal.md` 与 `databases/asset_core|mining_runtime` 契约。

## TASK-20260421-v11-agent-serving
- 标题：CoreMasterKB v1.2 Agent Serving Retrieval View Layer
- 级别：正式
- 状态：v1.2 实现完成，112 测试通过，已提交 handoff，待 Codex 审查
- 当前阶段：v1.2 实现完成 / 等待审查
- Claude：Claude Serving 已完成 v1.2 全量实现（P1×5 + P2×3 + LLM×3 + 自查修复×3），112 passed/1 skipped，提交 handoff
- Codex：已补发本轮 bug-review，明确 `/search` 主链仍未真正进入 LLM normalizer/planner，需先修主链接入再推进后续演进
- 管理员：已确认 Serving 需脱离旧 command/canonical 路径，按 Agent Knowledge Backend 重写
- 计划文档：`docs/plans/2026-04-22-v12-agent-serving-impl-plan.md`
- 交接文档：`docs/handoffs/2026-04-22-v12-agent-serving-claude-serving-handoff.md`
- 审查文档：`docs/analysis/2026-04-22-v11-agent-serving-codex-review.md`
- 修复文档：
- 管理员文档：
- 最新消息序号：MSG-20260423-181000-codex
- 备注：主背景见 `README.md`、`docs/architecture/2026-04-21-coremasterkb-v1.1-architecture.md`、`.dev/2026-04-21-v1.1-database-complete-proposal.md` 与 `databases/asset_core` 契约。

## TASK-20260421-v11-agent-llm-runtime
- 标题：CoreMasterKB v1.1 Agent LLM Runtime 从零建设
- 级别：正式
- 状态：已发布，待 Claude LLM 产出 plan
- 当前阶段：任务发布 / 等待计划
- Claude：Claude LLM 已提交 fix，补齐 request_id、template CRUD API、worker/lease recovery 与配置容错；但仍需继续修复 worker 共享连接导致的 SQLite 并发错误，以及 template 默认输出类型合同
- Codex：已按管理员最终口径修正复审结论；确认当前 LLM final contract 已足以作为 Mining / Serving 的统一接入基线，handoff 已更新为“已处置”；当前仅剩 README / QUICKSTART / fix / 示例未完全统一到最终口径的非阻塞残余项
- 管理员：已确认 LLM Runtime 为独立服务，不与 Mining / Serving 私有调用体系混合
- 计划文档：
  - `docs/plans/2026-04-21-v11-llm-service-impl-plan.md`（设计文档 v1.1）
  - `docs/plans/2026-04-21-llm-service-tdd-plan.md`（TDD 执行计划）
- 交接文档：`docs/handoffs/2026-04-21-v11-llm-service-claude-llm-handoff.md`
- 审查文档：`docs/analysis/2026-04-21-v11-agent-llm-runtime-codex-review.md`
- 修复文档：
- 管理员文档：
- 最新消息序号：MSG-20260422-172500-codex
- 备注：主背景见 `README.md`、`docs/architecture/2026-04-21-coremasterkb-v1.1-architecture.md`、`.dev/2026-04-21-v1.1-database-complete-proposal.md` 与 `databases/agent_llm_runtime` 契约。

## 已完成任务

### 说明

- 可将已闭环任务移动到此区
- 如任务较多，可后续按月份拆分归档

## TASK-20260415-cloud-core-architecture
- 标题：云核心网 Agent Knowledge Backend 总体架构与 Phase 1A 落地设计
- 级别：正式
- 状态：M0 已闭环；任务消息已归档
- 当前阶段：M0 已完成；M1 Mining / Serving 已拆分为独立活跃任务
- Claude：已完成 M0 全部 9 个 Task（T1-T9）与 Codex review P1-P3 修复
- Codex：已复核 M0 fix 并确认闭环；已发布 M1 Mining / Serving 并行开发上下文与任务边界
- 管理员：用户已确认 Agent / Skill / Serving / Assets / Mining 分层架构
- 计划文档：
  - `docs/archive/2026-04/TASK-20260415-cloud-core-architecture/plans/2026-04-15-m0-skeleton-design.md`（M0 设计文档）
  - `docs/archive/2026-04/TASK-20260415-cloud-core-architecture/plans/2026-04-15-m0-skeleton.md`（M0 实现计划）
- 交接文档：`docs/archive/2026-04/TASK-20260415-cloud-core-architecture/handoffs/2026-04-15-m0-claude-handoff.md`
- 审查文档：`docs/archive/2026-04/TASK-20260415-cloud-core-architecture/analysis/2026-04-15-m0-skeleton-codex-review.md`
- 修复文档：`docs/archive/2026-04/TASK-20260415-cloud-core-architecture/handoffs/2026-04-15-m0-claude-fix.md`
- 管理员文档：
- 最新消息序号：MSG-20260415-172000-codex（已归档至 `docs/archive/2026-04/TASK-20260415-cloud-core-architecture/messages/TASK-20260415-cloud-core-architecture.md`）
- 备注：架构文档为 `docs/architecture/2026-04-15-cloud-core-agent-knowledge-architecture.md`；并行开发上下文为 `docs/architecture/2026-04-15-mining-serving-parallel-design.md`，作为 M1 历史与 1.1 讨论参考原位保留，不归档。旧代码仅作为 `old/` 参考，不作为新系统 import 依赖。

## TASK-20260415-m1-knowledge-mining
- 标题：M1 Knowledge Mining / 原始语料与归并语料生产
- 级别：正式
- 状态：已收口归档；后续 1.1 演进另建任务承接
- 当前阶段：M1 实现与多轮修复讨论已结束，任务文档已归档
- Claude：已完成 M1 与 v0.5 修订实现，并完成 Codex 复审后 6 项修复
- Codex：已完成计划审查、v0.5 实现审查、fix 复审与归档收口
- 管理员：2026-04-20 要求原 M1 任务收口，转入 1.1 数据库 / Mining / Serving 重写讨论
- 计划文档：
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/plans/2026-04-16-m1-knowledge-mining-design.md`
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/plans/2026-04-16-m1-knowledge-mining-impl-plan.md`
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/plans/2026-04-17-m1-knowledge-mining-v05-revision-plan.md`
- 交接文档：
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/handoffs/2026-04-17-m1-knowledge-mining-claude-handoff.md`
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/handoffs/2026-04-17-m1-knowledge-mining-claude-v05-revision.md`
- 审查文档：
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/analysis/2026-04-16-m1-knowledge-mining-plan-codex-review.md`
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/analysis/2026-04-17-m1-knowledge-mining-v05-codex-review.md`
  - `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/analysis/2026-04-20-m1-knowledge-mining-fix-codex-review.md`
- 修复文档：
- 管理员文档：
  - `docs/architecture/2026-04-15-mining-serving-parallel-design.md`（共享架构上下文，原位保留）
- 最新消息序号：MSG-20260420-173600-codex（已归档至 `docs/archive/2026-04/TASK-20260415-m1-knowledge-mining/messages/TASK-20260415-m1-knowledge-mining.md`）
- 备注：本任务作为 M1 历史基线保留。1.1 不在该任务内继续追加补丁。

## TASK-20260415-m1-agent-serving
- 标题：M1 Agent Serving / 归并语料检索与差异下钻
- 级别：正式
- 状态：已收口归档；后续 1.1 Serving 重写另建任务承接
- 当前阶段：M1 实现与多轮修复讨论已结束，任务文档已归档
- Claude：已完成 M1 与 v0.5 泛化修订实现，并完成 Codex 复审后修复
- Codex：已完成设计审查、v0.5 实现审查、fix 复审与归档收口
- 管理员：2026-04-20 要求原 M1 任务收口，转入 1.1 数据库 / Mining / Serving 重写讨论
- 计划文档：
  - `docs/archive/2026-04/TASK-20260415-m1-agent-serving/plans/2026-04-15-m1-agent-serving-design.md`
  - `docs/archive/2026-04/TASK-20260415-m1-agent-serving/plans/2026-04-15-m1-agent-serving-impl-plan.md`
- 交接文档：`docs/archive/2026-04/TASK-20260415-m1-agent-serving/handoffs/2026-04-17-m1-agent-serving-claude-handoff.md`
- 审查文档：
  - `docs/archive/2026-04/TASK-20260415-m1-agent-serving/analysis/2026-04-16-m1-agent-serving-codex-review.md`
  - `docs/archive/2026-04/TASK-20260415-m1-agent-serving/analysis/2026-04-17-m1-agent-serving-v05-codex-review.md`
  - `docs/archive/2026-04/TASK-20260415-m1-agent-serving/analysis/2026-04-20-m1-agent-serving-fix-codex-review.md`
- 修复文档：
- 管理员文档：
  - `docs/architecture/2026-04-15-mining-serving-parallel-design.md`（共享架构上下文，原位保留）
- 最新消息序号：MSG-20260420-173700-codex（已归档至 `docs/archive/2026-04/TASK-20260415-m1-agent-serving/messages/TASK-20260415-m1-agent-serving.md`）
- 备注：本任务作为 M1 历史基线保留。Serving 1.1 应按通用 Agent Knowledge Backend 重写，不在该任务内继续追加补丁。
