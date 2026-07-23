# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

CoreMasterKB — 面向 5G 核心网的领域知识库：把 3GPP 文档、内部 wiki 等原始资料挖掘成结构化知识资产，再对外提供检索。6 个服务打包进单容器，由 supervisord 管理。

---

## 架构：两条主线，经数据库耦合

理解这个系统的关键，是看清它有两条主线，**彼此从不调用 HTTP，只通过 PostgreSQL 交接**：

```
挖掘线 (Python)                          检索线 (Java)
knowledge_mining :8901                   agent_serving_java :8081
  parse → segment → enrich                 查询理解 → 路由 → 范围解析
  → 实体抽取 → 篇章关系                     → 多路召回 → 融合 → 重排
  → 检索单元 → 向量化 → 落库                → 上下文组装
  → build → publish release
         │                                          ▲
         └────── 写 asset_* 表 ──► PostgreSQL ──── 只读
```

`agent_serving_java` 对全部 `asset_*` 表只读（8 个 mapper 全是 `<select>`），写方永远是 `knowledge_mining`。serving 自己只写 `serving_query_logs` / `serving_query_cache` / `operator_paradigm*`。

**发布语义**：mining 挖完的内容不会立刻可检索。必须 build 成不可变快照并 `publish` 成 release；`asset_publish_releases` 上有部分唯一索引保证「一域至多一个 active release」。serving 只认 active release。这也是 `no_active_release` / `multiple_active_releases` 报错的来源。

### 其余服务

| 服务 | 端口 | 职责 |
|---|---|---|
| `main_control_service` | 8910 | YAML 配置中心 + 域感知反向代理。**必须最先启动** |
| `llm_service` | 8900 | 统一 LLM 运行时，租约式任务队列（`FOR UPDATE SKIP LOCKED`） |
| `kb-ui` | 80 | Vue 3 前端，经 nginx |
| `mcp_server` | 9000 | 把检索包装成 MCP tool，直连 8081（**绕过控制面**） |

### 前端调用范式（唯一入口）

nginx 只有一条后端路由。前端所有请求都长这样：

```
/api/control-plane/api/v1/proxy/{domain}/{service}/{真实后端路径}
                                            service ∈ {mining, serving, llm, eval}
```

`README.md` 里写的 `/api/mining`、`/api/serving`、`/api/llm` **已不存在**，早期版本的遗留描述。加新接口时从 `kb-ui/src/api/*.ts` 入手，`createProxyClient(service)` 会在**每个请求的拦截器里**重算 baseURL（不是创建时固定），所以切域无需重建客户端。

### 配置来源（改配置前必读）

**总原则：配置都从 `main_control_service` 获取。** 它是配置中心，所以必须最先启动。

| 组件 | 配置从哪来 | 热重载 |
|---|---|---|
| `llm_service` | **HTTP 拉控制面**：`GET {control}/api/v1/system/llm_service/raw` + `/system/database/raw`。**完全不读 `.env`** | `POST /api/v1/admin/reload-config`（只拉 service config，**不碰 db_config**） |
| `agent_serving_java` | **HTTP 拉控制面**：`GET {control}/api/v1/serving-config`；main_control 不可达时回落本地文件（见下） | `POST /api/v1/admin/reload-config`；控制面可扇出：`POST {control}/api/v1/admin/reload-serving` |
| `knowledge_mining` | 直接读文件系统 `main_control_service/config/`（`domain_pack.py` 里硬编码路径，不认环境变量）；DB 配置走 `.env` 的 `PG_*` | 无，改配置必须重启 |
| `kb-ui` | HTTP 走控制面 | — |

`.env.example` 里整块 `LLM_SERVICE_PROVIDER_*` / `LLM_SERVICE_EMBEDDING_*` / `LLM_SERVICE_RERANK_*` 是**死变量**，改了完全无效——真配置在 `main_control_service/config/system/llm_service.yaml`。只有 `LLM_SERVICE_URL` 仍被调用方使用。

---

## 域配置：唯一真相源

**`main_control_service/config/` 是域配置的唯一真相源**，Java 与 Python 共读同一份：

```
main_control_service/config/
  domain_registry.yaml          # 4 个域：cloud_core_network / generic / civil_engineering / odn
  scenario_packs/<pack>/domain.yaml
```

历史上根目录另有一份副本（`./domain_registry.yaml` + `./scenario_packs/`），字段结构不同、内容已分叉，只有 Java 读它——已删除，**勿恢复**。若在旧文档、旧分支或 issue 里看到 `../scenario_packs`、`/app/scenario_packs`、`COREMASTERKB_DB_CLOUD_CORE`，那是统一前的描述。

### Java 侧怎么拿到它

Serving **不直接读这些文件**，而是拉控制面聚合出来的快照：

```
GET {main_control}/api/v1/serving-config
  → {"domains": {<id>: {enabled, default_channel, database, serving}}}
       database: registry 的内联块（或 null → 用默认 DataSource）
       serving : scenario pack 的 serving: 段（ontology:/mining: 不下发——serving 从不读）
  → MainControlClient 解析成 ServingConfigSnapshot
  → ConfigReloadService 原子地喂给 DomainRegistry / DomainPackReader / DomainPoolManager
```

`ConfigReloadService.reload()` 先试 main_control，失败才回落本地文件（`SCENARIO_PACKS_DIR` / `DOMAIN_REGISTRY_PATH`，供 IntelliJ 和测试用）。**两条路径解析同一组键**——改 `MainControlClient.parseDatabase` 时必须同步改 `ConfigReloadService.parseDatabase`，否则两条路径行为分叉。契约由 `MainControlClientTest` 锁住（它按 Python `get_serving_config()` 的输出逐键构造 payload）——**改任何一侧的键名，这个测试是唯一能拦住你的东西，编译器拦不住。**

Java 侧 base-url 由 `SERVING_MAIN_CONTROL_BASEURL` 指定（`docker/supervisord.conf`）；本地 dev 默认值在 `application.yml` 和 `ServingProperties.java` **两处**都有，要改一起改。

### ⚠️ registry 的 `database:` 块是活的

`DatabaseConfig.isUsable()` 只要有 `host` + `dbname` 就返回 true，`DomainPoolManager` 会为该域建**专用 Hikari 池**并**建池时就验连接**——连不上直接抛 `domain_database_unavailable`（503），不会静默回落默认库。

也就是说：**registry 里写了 `database:` 的域，检索就真的连那个库**，不再走 `application.yml` 的 `PG_*`。想让某个域回到共享默认库，把它的 `database:` 块删掉（或留 null）即可。

`resolvedJdbcUrl()` 负责补 `jdbc:` 前缀（registry 存的是裸 host/port/dbname）；`signature()` 用于 reload 时检测配置变化、只重建变了的池。

### 仍然存在的坑

- **Python 侧仍是单库**。mining 的 per-domain 分库没接通：`jobs/run.py:181-197` 用 `.get("database_url_env")` 取不到就静默降级，registry 的 `database:` 块 Python 侧零读取，`conninfo_from_env()`（`mining/infra/pg_config.py`）是不可达死代码。**mining 永远写 `.env` 的那个库**，靠表里的 `domain` 列隔离。所以 Java 若被指向别的库，会读不到 mining 写的数据。
- **两个 LLM 模板代码在用、但没有任何 pack 声明**：`mining-entity-extraction`（`stages/entity_extract/__init__.py:108`）和 `mining-ontology-induction`（`stages/ontology_induction/__init__.py:197`）。`submit_task` 取不到模板只 warning 不报错 → **本体线的实体抽取与归纳全程静默 no-op**。要修需补 prompt + JSON Schema。（模板存在 llm_service 的 `agent_llm_prompt_templates` 表里，pack 只负责启动时注册——若曾被人工 POST 进去则仍可用，查库才能确认。）
- **`generic` pack 完全没有 `llm_templates` 段** → 该域下所有 LLM 阶段降级。
- **`scenario_pack_missing` 已成死代码**：新架构下「缺 pack」表现为空 `serving: {}`，与「合法地没有 override」无法区分，`DomainPackReader` 改为回落 `ServingDomainProfile.defaults()`。`GlobalExceptionHandler` 的映射保留但无人抛。

**改 pack 的 `template_key` 前先 grep 代码**：`submit_task` 的 key 与 pack 声明不一致时静默失效，不报错。三个 pack 的 `mining-question-gen` 就曾因此写成 `mining-question-generation`。

### 其他同构分裂（未收敛）

Python 依赖三份（`pyproject.toml` / `docker/Dockerfile` 手写 pip 列表 / `requirements.txt`，已漂移，`pyproject.toml` 缺 `jieba` 和 `python-multipart`）；`.env` 解析逻辑三份（`reset_db.py` / `export_db.py` / `import_db.py` 各抄一遍）；`db_tables.py` 的 docstring 声称被 `reset_db.py` 使用，但后者自维护了一份顺序相反的 `ALL_TABLES`（父表先 vs 子表先），两份列表并存。

---

## 常用命令

### 本地开发

```bash
# 前端（需先起 main_control_service:8910，它是配置中心）
cd kb-ui && npm install && npm run dev        # → localhost:5173

# 各服务单独起（注意模块路径，Windows 下必须用 -m）
python -m main_control_service.main            # 8910，必须最先
python -m llm_service                          # 8900
python -m knowledge_mining.mining.api          # 8901
python -m mcp_server --transport streamable-http --port 9000
```

Windows 上 `llm_service` 和 `knowledge_mining` 必须走 `python -m`：入口模块会 monkey-patch uvicorn 用 `SelectorEventLoop`，psycopg async 在默认的 ProactorEventLoop 上不工作。直接 `uvicorn llm_service.main:create_app` 会崩。

`pip install -e .` 要在**仓库根**跑（`pyproject.toml` 在根）。但它装不全依赖——缺 `jieba` / `python-multipart`，跑 uploads 路由会 ImportError。

### 测试

```bash
# llm_service —— 纯单测，不需要 DB，最快（38 passed, 5 skipped）
pytest llm_service/tests/ -q

# knowledge_mining —— ⚠️ 强绑真实 PostgreSQL
python -m pytest knowledge_mining/tests/ -v
python -m pytest knowledge_mining/tests/test_pipeline_operators.py::test_xxx -v   # 单个

# Java —— 三级分层
cd agent_serving_java
mvn test                          # L1 单测（排除 pg-integration,e2e）
mvn verify                        # L2 + 集成测试（需 PG）
mvn verify -Pe2e                  # L3 端到端
mvn test -Dtest=QueryUnderstandingEngineTest       # 单个测试类
mvn test -Dtest=QueryUnderstandingEngineTest#方法名  # 单个方法
```

**`knowledge_mining` 测试的两个硬约束**（`tests/conftest.py`）：
1. `_ensure_schema` 是 **autouse + session 级**，连不上 `.env` 里的 PG 就在 setup 阶段直接 error——即使是纯函数测试。
2. 默认**不清表**：`_truncate_all` 除非 `KB_ALLOW_TEST_TRUNCATE=1` 否则直接 return。这是防误删 `.env` 指向的生产库的护栏。副作用是跨测试残留会污染断言。

**⚠️ 改了 Java 的 record / 构造器签名后，`mvn test-compile` 的 BUILD SUCCESS 是假的。** Maven 增量编译只看**源文件时间戳**：没动测试源码，它就报 `Nothing to compile - all classes are up to date` 并跳过重编译，哪怕主类签名已经变了。必须强制全量重编：

```bash
rm -rf target/classes target/test-classes && mvn -o test
```

（`mvn clean` 在离线环境用不了——clean 插件不在 `~/.m2` 缓存里，会报 `Cannot access central in offline mode`。手工删目录即可。本地 m2 缓存齐全，`mvn -o` 可离线跑通编译和全部单测。）

### 数据库

```bash
python reset_db.py      # 破坏性重建（DROP CASCADE 后重跑 DDL）
python export_db.py     # 只导数据不导 DDL → backups/export_<ts>.sql
python import_db.py     # TRUNCATE 后逐条 INSERT
```

`reset_db.py` 的 `SCHEMA_FILES` 顺序是强制的：ontology DDL **必须最后**（FK 指向 `asset_*`，且要给 `mining_runs` 补 `subloop_stage` / `ontology_version_id` 两列）；`ALL_TABLES` 的 DROP 顺序则**相反**，子表先——ontology 表组须排在 `asset_core` 之前，因为 `DROP ... CASCADE` 只删外键约束、不删引用方的表本身。

`db_tables.py` 的 `EXPORT_TABLES` 顺序与 DROP **正好相反**（父表先，TRUNCATE 时 `reversed()`）。其中 `OPTIONAL_TABLES`（`operator_paradigm*`）由 Java 的 `ParadigmSchemaInitializer` 在启动时建、Python 侧不建，所以 Java 没跑过的库里不存在——export/import 会跳过它们，改这两个脚本时别把这个保护去掉（`import_db.py` 把所有表拼进**一条** TRUNCATE，少一张表整条都会失败）。

权威 schema 是 Python 侧 `databases/*/schemas/*.sql`（由 `pg_schema.py` 按序执行，ontology 必须最后——它的 FK 指向 `asset_*`）。曾经并存的 `agent_serving_java/src/main/resources/db/init.sql` 是一份腐坏的同构副本（基于 SQLite 时代的 `001_asset_core.sql`，声明 `embedding_vector TEXT` 而没有 mapper 实际使用的 `embedding_vector_vec vector(1024)`），无任何代码执行它，**已删除**——在旧文档或旧分支里看到它时不要照着建库。

Java 侧现在只保留自己拥有的表的 DDL，全部会自动执行：

| 目录 | 表 | 执行者 |
|---|---|---|
| `db/operator/` | `operator_paradigm*` | `ParadigmSchemaInitializer`（非路由的 `defaultDataSource`） |
| `db/serving/` | `serving_query_logs` / `serving_query_cache` | `ServingRuntimeSchemaInitializer` + `DomainPoolManager` 建池时（**按域路由，每个域建进自己的库**） |

`db/migrate_v1_to_zdy.sql` / `db/migrate_v2_semantic_cache.sql` 是人工执行的历史迁移，内容已分别被 `databases/asset_core/schemas/002_*.sql` 末尾的幂等升级段和 `db/serving/002_*.sql` 覆盖，不会自动执行。

### 部署

```bash
bash deploy-build.sh                # → cmkb.tar（约 203MB）
bash deploy-server.sh               # 仅补缺，保护服务器本地改动
bash deploy-server.sh --force       # 覆盖代码
bash deploy-server.sh --force-config # 只覆盖 .env（域配置归 --force 管，见下）

docker compose exec app supervisorctl status
docker compose exec app supervisorctl restart mining   # Python 改完重启即生效（volume 挂载）
```

⚠️ **`--force` 会 `rm -rf main_control_service/`**，连带删掉 `main_control_service/config/` —— 也就是**真正生效的 registry、4 个 scenario pack、system/*.yaml 全部被镜像版本覆盖**。脚本把这归类为「代码」，但用户会以为配置只受 `--force-config` 管辖。这是最危险的语义陷阱。

Java / 前端改动必须重新 build 镜像（无 volume 挂载）；Python 改宿主机文件后 `supervisorctl restart` 即可。

---

## 修改代码时的注意事项

**`llm_service` 有两条完全独立的落库路径。** 异步路径（`/tasks` → Worker → `TaskManager`）失败走 `dead_letter`，永远不会是 `failed`；同步路径（`/execute`）由 `PersistWriter` 事后异步写入，status 直接是终态且**可能是 `failed`**。查 `agent_llm_tasks` 时把两类混在一起统计必错。

**不要给 `LLMService.execute_chat_attempt` 加 `raise`。** 它的 docstring 说会 raise，但**实现刻意在所有失败路径都不 re-raise**（见 `service.py` 相应注释）——因为 `Worker._execute_task` 的 safety net 会再调一次 `_mgr.fail()`，加了 raise 就复活「每次 attempt 扣 2 次重试额度」的 bug。且这条路径**无测试拦截**（TaskManager / Worker 零覆盖）。看注释，别看 docstring。

**算子系统的 `scope` 必须显式连线。** `ParadigmCompiler` 的 `ENTRY_SLOTS` **只有 `query`**，`scope` 被故意排除——否则图会「编译通过但运行时 scope 为 null，静默检索不到东西」。所有检索算子的 `scope` 入槽必须连到 `scope_resolve`。这是 `missing_required_input` 报错的来源。

**虚拟线程不继承 ThreadLocal。** `DomainContext` 是普通 `ThreadLocal`，任何 `CompletableFuture.runAsync` 提交的任务都必须显式 `DomainContext.set()` 或用 `DomainContext.wrapRunnable`。`ParadigmExecutor` 每个节点都做了；`SearchService` 的变体/子查询检索**漏了**（已知 bug，导致 `entity_graph` 路由在 `/api/v1/search` 中恒返回空）。

**新增算子只需打 `@Component`**，`OperatorRegistry` 靠构造注入自动收集，type 重复会启动失败。前端按算子的 `paramSchemaJson`（JSON Schema draft-07）自动渲染参数表单，加参数只改后端 schema、前端零改动。

**`AssetRawSegmentMapper.selectWithMeta` 会按 snapshot 链接数放大行。** 它 `LEFT JOIN asset_document_snapshot_links`（1:N，同一文档被索引成多个 `relative_path` 时有多行），SQL 无 `DISTINCT`，所以同一个 `raw_segment` id 会返回多行。`ContextAssembler` 已在两处按 id 去重（`buildSourceItems` + `assemble` 组装 `allItems` 后的统一兜底，保留首次出现：seed > context > support），契约由 `ContextAssemblerTest.ItemDeduplication` 锁住。**任何新消费 `selectWithMeta` 结果的代码（如 `GraphExpander`）都要自己去重**，别假设行已唯一。

---

## 一段能解释很多疑惑的历史

`agent_serving_java` **不是**这个检索服务的第一版。v4 分支上它叫 `agent_serving_zdy`；`268f9f1`「纳入同事 agent_java2/main_control_service2 的工作到主目录」用同事那份实现替换了它——带来了算子/范式系统，但**静默丢掉了整个控制面集成**（`MainControlClient` / `ConfigReloadService` / `AdminController` / `DatabaseConfig`，以及控制面侧的 `/api/v1/serving-config` 和 `/api/v1/admin/reload-serving`）。这批能力后来从 v4 移植了回来，就是上文描述的架构。

这解释了几件否则说不通的事：

- `docs/code_guide.md` 提到的 `serving.embedding.model` / `serving.rerank.model` **不是虚构的**——它们在 v4 的 `application.yml` 里真实存在，只是同事那版没有（模型改由 llm_service 决定）。
- `kb-ui` 的 `ReloadConfigTab.vue` 提示文案是复数的「对应服务的重载按钮」，却只有 LLM 一个按钮——serving 那个按钮是 v4 有、替换时丢的。控制面的扇出端点已经补回来了，UI 按钮还没补。

**读 v4 分支时**：Java 模块在 `agent_serving_zdy/`（不是 `agent_serving_java/`），且那个分支的根目录还有已废弃的 `domain_registry.yaml` + `scenario_packs/` 副本。v4 的实现可以当参考，但它的文件兜底路径读的是 `database_url_env`（旧 schema），当前实现读内联 `database:` 块——别照抄。

---

## 文档可信度（重要）

文档质量差异极大，照着读会被带偏：

| 文档 | 状态 |
|---|---|
| `agent_serving_java/docs/ontology-retrieval-explained.md` | ✅ **准确**，与源码逐行对得上，可直接信 |
| `agent_serving_java/docs/检索范式使用说明.md` | ✅ 质量高。小偏差：算子实际 19 个（漏列 `entity_graph`） |
| `agent_serving_java/docs/TODO-known-issues.md` | ✅ serving 侧「已确认未修复」问题台账，逐条给了根因/触发边界/修法。当前记录：语义缓存污染（降级/空结果被写入 `serving_query_cache`，恢复后仍命中返回空）——修前先看这份 |
| `llm_service/README.md` / `ARCHITECTURE.md` / `QUICKSTART.md` | ⚠️ 主体质量高（PostgreSQL 迁移、双路径语义都写对了），但**配置章节大面积照理想设计而非实际代码书写**。最致命：配置键实际是 `provider_type` 不是 `provider.type`，写错会静默 fallback 到 openai_compatible。另有一类系统性漂移——文档定稿早于 `4dee50a`，仍在「记录已被修复的 bug」 |
| `agent_serving_java/docs/code_guide.md`、`pipeline-0X-*.md` | ❌ 过时，**且有一部分写的是 v4 的 `agent_serving_zdy`**（见上文「一段能解释很多疑惑的历史」）——所以它描述的东西可能既非虚构、也不在当前代码里。pipeline 实际 14+ 阶段不是 10；`pipeline-03` 描述的 intent 驱动路由是**死代码**（`BUILTIN_ROUTES` 赋值后从未被读取），实际按 query complexity 分层 |
| `knowledge_mining/README.md`、`docs/stage-*.md` | ❌ 描述的是**已被删除的 SQLite 时代架构**，整条本体线零文档 |
| `kb-ui/FRONTEND-PLAN.md` | ❌ 描述的架构从未落地，且与现实**相反**（它设计了 `/:domain/mining` 前缀路由和三端口直连 + CORS，实际是控制面单入口、路由不含 domain 段） |
| `kb-ui/README.md` | ❌ Vite 模板默认文本，零信息量 |
| `databases/README.md` | ⚠️ 声称「逻辑分库必须坚持」，但 ontology DDL 已跨库建 FK，物理合库不可逆。且漏列实际在用的 `ontology/` 和 `serving_runtime/` |
| 根 `README.md` | ⚠️ 部署部分准确；nginx 路由描述已过时（见上文「前端调用范式」） |

新人最短上手路径：先起 `main_control_service`，再读 `ontology-retrieval-explained.md` + `检索范式使用说明.md`，其余文档一律对着源码读。`docker/nginx.conf` 里的三行注释比 `FRONTEND-PLAN.md` 和 `kb-ui/README.md` 加起来都准确。
