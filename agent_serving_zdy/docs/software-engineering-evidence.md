# 软件工程举证 · agent_serving_zdy

> 评价人：张大勇（z30031510）　团队：AI 开发团队
> 范围：CoreMasterKB 检索服务 `agent_serving_zdy`（Java 21 / Spring Boot 3.2.5 / MyBatis / Postgres+pgvector，端口 8081）
> 用途：青鸟「代码白盒评价 · 软件工程」评分项手工举证
> 整理日期：2026-06-15

本文按软件工程评分规则 3.1 / 3.2 / 3.3 逐条列出可核验的工程产出，每项均给出代码或文档落点，可溯源。

---

## 3.2 提升团队基础软件工程能力（可观测性 + 配置热重载）

### 一、检索 Pipeline 可观测性（Micrometer + Prometheus + Grafana）

为检索服务从零接入指标可观测体系，应用侧零侵入暴露、外部进程抓取与出图。

**应用侧落点**
- `observability/SearchMetrics.java`：每次检索把运行事实写为内存 meter。
- `observability/QueryLogAspect.java`：AOP 无侵入查询日志落库。
- `observability/TraceCollector.java`：检索链路 trace 采集。
- `src/main/resources/application.yml` 的 `management` 段：仅暴露 `/actuator/prometheus` 端点，所有指标自动带 `application=agent-serving` 标签。

**已暴露指标（6 个，pull 模式）**

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| `serving_search_duration_ms` | histogram | — | 端到端延迟（含异常） |
| `serving_retrieval_candidates` | histogram | `route` | 每路检索候选数 |
| `serving_rerank_duration_ms` | histogram | — | rerank 阶段耗时 |
| `serving_rerank_fallback_total` | counter | `method` | 最终生效的 rerank 层（model/llm/score） |
| `serving_query_intent_total` | counter | `intent` | 意图分布 |
| `serving_scope_empty_total` | counter | — | scope 为空且无结果次数 |

**工程化价值**：`serving_rerank_fallback_total{method!="model"}` 的占比可作为 LLM Service 健康度信号，已配套告警规则（rerank 降级率 > 50% 持续 5 分钟告警、搜索 P99 > 2s 告警）。

**部署佐证文档**：`docs/2026-06-07-prometheus-grafana-deployment.md`（含 docker-compose / Kubernetes ServiceMonitor / 托管服务三种部署路径、PromQL 速查、告警规则、部署坑位清单）。

> 说明：该文档示例端口写 8082，为独立运行镜像的遗留值；集成部署中 serving 实际跑在 8081，以 8081 为准。

### 二、配置热重载（不停机更新配置）

将 serving 从「直接读本地配置文件」改造为「以 main_control_service 为配置单一事实源、HTTP 拉取 + 前端按钮触发热重载、不重启 JVM」，解决多域配置需逐服务重启的团队单点问题。

**架构**
```
kb-ui 改配置 → 存入 main_control(8910) → 点「配置热重载」
  → main_control 向各 enabled 域 serving_url 扇出
  → serving(8081) 回拉聚合配置 → 内存快照原子替换（volatile），不重启 JVM
```

**serving 侧落点**
- `infrastructure/MainControlClient.java`：RestClient 拉取 `GET /api/v1/serving-config` 聚合配置。
- `domainpack/ServingConfigSnapshot.java` / `DatabaseConfig.java`：下发配置 DTO（database 内联下发，彻底解耦）。
- `domainpack/ConfigReloadService.java`：`reload()` = fetch → registry.apply → packReader.apply → poolManager.invalidate。
- `domainpack/DomainRegistry.java` / `DomainPackReader.java`：`apply(snapshot)` 内存原子替换，不再读文件。
- `domainpack/DomainPoolManager.java`：`invalidate(snapshot)` 按签名**只重建发生变化/移除的域连接池**，未变域不动。
- `api/AdminController.java`：`POST /api/v1/admin/reload-config` 重载端点。

**设计文档**：`docs/2026-06-11-serving-config-hot-reload-plan.md`（精简配置契约、main_control 侧 M1–M3 与 serving 侧 S1–S13 文件级改动清单、决策与行为变更须知）。

---

## 3.1 团队基础软件工程能力（部署工程）

服务纳入单容器 All-in-One 交付，6 个服务由 supervisord 统一编排，nginx 反代后端 API，前端不依赖 localhost。

**落点**
- `README.md`（仓库根）：Docker 单容器部署架构表、构建/部署/运维命令、配置文件说明。
- `docker/supervisord.conf`：serving 进程编排，注入 `SERVER_PORT=8081`、`SERVING_MAIN_CONTROL_BASEURL`。
- `agent_serving_zdy/Dockerfile`、`docker-compose.yml`：服务镜像与编排。
- `deploy-build.sh` / `deploy-server.sh`：一键构建镜像（生成 cmkb.tar）与服务器部署（支持 `--force` 覆盖、增量更新两种模式）。

**价值**：交付物与环境一致性收敛为一个镜像 + 三个文件，降低部署门槛与环境漂移。

---

## 3.3 建设 AI 友好型资产

固化检索服务专家经验为组织资产，提升后续 AI Coding 在本模块的确定性。

**落点**
- `agent_serving_zdy/docs/optimization-notes.md`：成熟链路的架构腐化点评审笔记，自评出延迟串行、HTTP 无连接池、pgvector ANN 强前置过滤打不到 HNSW 索引、SessionStore 无 TTL 内存泄漏等 10 项，按收益/风险优先级给出可落地改法——可直接作为后续 AI 辅助优化的输入上下文。
- `docs/2026-06-03-agent-serving-zdy-evolution.md`：模块演进说明。
- `docs/2026-06-10-search-endpoint-retrieval-flow.md`：检索链路与接口流程说明。
- `docs/serving-search-api-output-spec.md`：检索输出契约 SPEC。
- `agent_serving_zdy/docs/slides/serving-retrieval-share.pptx`：检索方案技术分享材料（多路召回 + 融合 + 重排）。

---

## 举证文件清单（可随本评分项上传）

| 文件 | 对应规则 |
|------|----------|
| `agent_serving_zdy/docs/software-engineering-evidence.md`（本文） | 3.1 / 3.2 / 3.3 索引 |
| `docs/2026-06-07-prometheus-grafana-deployment.md` | 3.2 可观测性 |
| `docs/2026-06-11-serving-config-hot-reload-plan.md` | 3.2 配置热重载 |
| `agent_serving_zdy/docs/optimization-notes.md` | 3.3 AI 友好型资产 |
| `agent_serving_zdy/docs/slides/serving-retrieval-share.pptx` | 3.3 案例分享 |
