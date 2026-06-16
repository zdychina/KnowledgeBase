# 开发者测试文档 · agent_serving_zdy

> 评价人：张大勇（z30031510）　团队：AI 开发团队
> 范围：CoreMasterKB 检索服务 `agent_serving_zdy`（Java 21 / Spring Boot 3.2.5 / MyBatis / Postgres+pgvector，端口 8081）
> 用途：青鸟「代码白盒评价 · 开发者测试」评分项手工举证（规则 2.5）
> 整理日期：2026-06-16

本文描述检索服务的测试策略、分层、覆盖矩阵、关键测试设计与执行方式，所有数据可由命令核验。

---

## 一、测试规模（可核验）

| 指标 | 数值 | 统计口径 |
|------|------|---------|
| 测试类 | **39** | `find src/test/java -name "*.java"` |
| 测试方法 | **214** 个 `@Test` | `grep -rh "@Test" src/test/java \| wc -l` |
| 测试代码行数 | **4052** loc | 主代码 9077 loc，**主:测试 ≈ 2.24:1**，接近 1:1 |
| `@DisplayName` | **318** | 中文/英文可读用例名，自文档化 |
| `@Nested` 分组 | **66** | 按场景嵌套组织 |
| `@SpringBootTest` | 3 | 集成/E2E 启动上下文 |
| 使用 Mockito 的类 | 10 | 纯单测隔离依赖 |

> 演进记录 `docs/2026-06-03-...-evolution.md` 中一轮全量回归为 `Tests run: 176, Failures: 0, Errors: 0`（BUILD SUCCESS）。

---

## 二、测试金字塔（三级分层）

测试按运行成本与依赖分三级，由 `pom.xml` 的 surefire / failsafe / `e2e` profile 分别驱动：

```
            ╱ L3 E2E ╲          system/*E2ETest（3 类）：MockMvc 打 /api/v1/search 全链路
          ╱  集成 L2  ╲        *IT（Mapper/Retriever/Repository/DomainRouting）：真实 PG
        ╱   单元 L1     ╲      纯逻辑：策略/路由/融合/重排/QU/工具（无外部依赖，Mockito 隔离）
```

| 层 | 触发方式 | 标记 | 依赖 | 数量级 |
|----|---------|------|------|--------|
| **L1 单元** | `mvn test`（surefire，排除 `pg-integration,e2e`） | 无 | 无（Mockito mock） | 主体，毫秒级 |
| **L2 集成** | `mvn verify`（failsafe，含 `pg-integration` 排除 `e2e`） | `@Tag("pg-integration")` | 真实 PostgreSQL+pgvector | `*IT` 类 |
| **L3 E2E** | `mvn verify -Pe2e` | `@Tag("e2e")` | 真实 PG + MockMvc | `system/*E2ETest`（3 类） |

`pom.xml` 配置要点：
- surefire `<excludedGroups>pg-integration,e2e</excludedGroups>` —— 默认只跑 L1，CI 快速反馈。
- failsafe `<groups>pg-integration</groups><excludedGroups>e2e</excludedGroups>` —— L2 集成。
- `e2e` profile：failsafe 仅 `**/system/*E2ETest.java`，并 `skip` surefire。

---

## 三、按层覆盖矩阵（无盲区）

| 主代码层 | 测试类（@Test 数） | 类型 |
|---------|-------------------|------|
| `api` | GlobalExceptionHandlerTest(10) · SearchControllerTest(1) · HealthControllerTest(1) | L1 |
| `application` | QueryUnderstandingEngineTest(15) · RetrievalRouterTest(12) · ContextAssemblerTest(7) · TreeNavigatorTest(7) · SearchServiceTest(3) | L1 |
| `pipeline` | RRFFusionTest(7) · WeightedRRFFusionTest(6) · RetrievalOrchestratorTest(6) · IdentityFusionTest(5) | L1 |
| `rerank` | RerankPipelineTest(10) · ScoreRerankerTest(4) | L1 |
| `retrieval` | GraphExpanderTest(3) · FtsRetrieverIT(2) · GraphExpanderIT(1) · EntityExactRetrieverIT(1) | L1+L2 |
| `domain` | DomainRecordDefaultsTest(20) · DomainRecordWithMethodsTest(7) | L1 |
| `domainpack` | DomainPackReaderTest(5) · DomainRoutingIT(5) · DomainContextTest(4) · DomainPoolManagerTest(4) | L1+L2 |
| `evidence` | EvidenceRoleClassifierTest(13) | L1 |
| `observability` | QueryLogServiceTest(7) · TraceCollectorTest(7) · SearchMetricsTest(2) | L1 |
| `mapper` | AssetRetrievalUnitMapperIT(4) · AssetPublishReleaseMapperIT(2) · AssetRawSegmentRelationMapperIT(2) · ServingQueryLogMapperIT(2) · AssetRawSegmentMapperIT(1) | L2 |
| `repository` | AssetRepositoryIT(2) | L2 |
| `util` | JsonUtilsTest(18) | L1 |
| `system`(E2E) | SearchE2ETest(4) · ErrorHandlingE2ETest(3) · HealthE2ETest(1) | L3 |

覆盖了从控制器、应用编排、策略、领域模型到持久化、可观测、端到端的全部 11 个层。

---

## 四、遵循 FIRST 原则

| 原则 | 落地 |
|------|------|
| **F**ast | L1 单测无外部依赖、Mockito mock LLM/DB，毫秒级；与 L2/L3 用 tag 隔离，本地默认只跑 L1 |
| **I**solated | 单测彼此独立，`@BeforeEach`（22 处）重建夹具；不可变 record 无共享态 |
| **R**epeatable | L2/L3 依赖真实 PG，但通过基类**优雅跳过**（见 §五）保证任意环境可重复执行不误报 |
| **S**elf-validating | 全部断言式，通过/失败明确；318 个 `@DisplayName` 表达预期行为 |
| **T**imely | 重写/演进与测试同步提交（演进记录每个特性均含新增/更新测试清单） |

---

## 五、关键测试设计

### 1. 集成测试基类：真实 PG + 优雅跳过
`AbstractPgIntegrationTest`（所有 `*IT` 与 E2E 的基类）：
- `@SpringBootTest + @ActiveProfiles("test-pg") + @Tag("pg-integration")`。
- `@BeforeEach` 用 `Assumptions.assumeTrue()` 检测 PG 连接与 active scope：**PG 不可达/无快照数据时跳过而非失败**——CI/无 DB 环境不会误报红。
- 从**真实数据**动态解析 `activeScope`（`cloud_core_network`），避免硬编码 snapshot id。
- 测试配置隔离于 `src/test/resources/application-test-pg.yml`。

### 2. E2E：MockMvc 打真实端点
`system/SearchE2ETest` 继承上述基类 + `@AutoConfigureMockMvc + @Tag("e2e")`，对 `POST /api/v1/search` 断言 JSON 结构（`$.query.original` 等）与意图识别（如 `ADD SMFPARTNER 命令怎么写` → command_usage）。

### 3. 单元：Mockito 隔离外部依赖
`SearchServiceTest`、`RetrievalOrchestratorTest`、`RerankPipelineTest`、`GraphExpanderTest`、`ContextAssemblerTest` 等 10 类用 Mockito mock LLM/DB/下游组件，纯验证编排与算法逻辑。

### 4. 行为等价守门测试（重写对齐）
- `RetrievalRouterTest`(12)：意图×复杂度路由权重（command_usage→entity_exact 主导、concept_lookup→dense 主导），锁定与 Python `_BUILTIN_ROUTES` 对齐。
- `RerankPipelineTest`(10)：级联 model→llm→score 降级、6 步后处理（去重/降权/相似度去重/阈值/截断）。
- `RRFFusionTest`/`WeightedRRFFusionTest`：融合算法正确性。
- `ContextAssemblerTest`：组装顺序（nucleus 排序、章节加权、缺失降级）。

### 5. 可读性结构
66 个 `@Nested` 按场景分组、318 个 `@DisplayName` 自文档化，测试报告即行为规格。

---

## 六、如何运行

```bash
cd agent_serving_zdy

# L1 单元测试（默认，无需 DB，秒级）
mvn -o test

# L2 集成测试（需可达的 PostgreSQL+pgvector；不可达自动跳过）
mvn -o verify

# L3 端到端测试
mvn -o verify -Pe2e
```

环境变量（L2/L3）：`PG_HOST / PG_PORT / PG_DBNAME / PG_USER / PG_PASSWORD`（见 `.env.example`）。PG 不可达时 L2/L3 用例 `assumeTrue` 跳过，不计失败。

---

## 七、举证文件清单

| 文件 | 说明 |
|------|------|
| `agent_serving_zdy/docs/developer-testing.md`（本文） | 2.5 测试策略与覆盖 |
| `agent_serving_zdy/src/test/java/**`（39 类 / 214 @Test） | 测试源码 |
| `agent_serving_zdy/src/test/java/.../AbstractPgIntegrationTest.java` | 集成测试基类（优雅跳过设计） |
| `agent_serving_zdy/src/test/resources/application-test-pg.yml` | 测试配置隔离 |
| `agent_serving_zdy/pom.xml`（surefire/failsafe/e2e profile） | 三级测试执行配置 |
| `agent_serving_zdy/docs/code-development-evidence.md` §2.5 | 代码开发举证中的测试小节 |
