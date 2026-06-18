# llm_service 内部架构

> **模块级实现文档。** 系统级架构请参见 `docs/architecture/*`。
> 状态：2026-06-18 由 Claude 基于 commit `<HEAD>` 全核刷新。
> 配套入口文档：[`README.md`](./README.md) / [`QUICKSTART.md`](./QUICKSTART.md)。

## 1. 模块全图

（TODO：Task 5 用真实文件清单替换）

## 2. 启动生命周期

（TODO：Task 1 写 lifespan → Worker → LeaseRecovery 调用链）

## 3. 数据流

（TODO：Task 1 + Task 2 写 sync/async/Embedding/Rerank 四条链路）

## 4. 任务状态机

（TODO：Task 1 写状态字段值 + 迁移矩阵）

## 5. Provider 体系

（TODO：Task 2 + Task 3 写协议/能力矩阵/扩展指南）

## 6. 存储层

（TODO：Task 2 + Task 5 写 PostgreSQL schema + PersistWriter）

## 7. 配置与热重载

（TODO：Task 5 写环境变量 + 热重载机制）

## 8. 已知边界与限制

（TODO：Task 10 汇总）
