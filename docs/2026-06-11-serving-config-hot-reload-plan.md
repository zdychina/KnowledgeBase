# Serving 配置热重载：精简配置契约 + 改动清单

> 目标：`agent_serving_zdy`（8081）不再读本地配置文件，改为从 `main_control_service`（8910）HTTP 拉取；前端「配置热重载」按钮触发 serving 重新加载，不重启 JVM。
> 决策：①DB 内联下发（彻底解耦）；②不改前端，仅改 serving 与 main_control；③extractor_rules 按 2A 激活。
> 整理日期：2026-06-11

---

## 一、精简后的 serving 配置契约

### 1. 进程级 / Bootstrap（启动期，不热重载）

| 配置 | env | 默认 | 说明 |
|---|---|---|---|
| `server.port` | `SERVER_PORT` | 需统一为 8081 | 见决策须知① |
| 默认数据源 | `PG_HOST/PORT/DBNAME/USER/PASSWORD` | — | 兜底库（域无独立库时复用） |
| 默认池 | `PG_POOL_MIN/MAX` | 2/10 | |
| `serving.default-domain` | `COREMASTERKB_DOMAIN`/`DEFAULT_DOMAIN` | cloud_core_network | 缺省域 |
| `serving.llm.base-url` | `LLM_SERVICE_URL` | :8900 | embedding/HyDE/rerank/QU 出口 |
| `serving.embedding.model`/`.dimensions` | `EMBEDDING_MODEL`/`EMBEDDING_DIMENSIONS` | embedding-3 / 1024 | |
| `serving.rerank.model` | `RERANK_MODEL` | rerank-pro | |
| `serving.main-control.base-url` 🆕 | `SERVING_MAIN_CONTROL_BASEURL` | http://localhost:8910 | 配置源 |
| ~~`serving.scenario-packs-dir`~~ / ~~`.domain-registry-path`~~ | — | — | 废弃（保留仅作测试回退） |

### 2. 领域级 / Per-domain（main_control 下发，热重载目标）

聚合接口 `GET /api/v1/serving-config` 每域只下发 serving 真正消费的：

```jsonc
{ "domains": {
  "cloud_core_network": {
    "enabled": true,
    "default_channel": "prod",
    "database": {                         // 1A 内联；可为 null → 用默认源
      "host": "...", "port": 5432, "dbname": "kb_db",
      "user": "...", "password": "...", "sslmode": "disable",
      "pool_min": 2, "pool_max": 10
    },
    "serving": {                          // 只取 pack 的 serving: 段，不下发 ontology/mining
      "route_policy": { ... },            // ✅ 必需
      "query_understanding": { ... },     // ✅ 必需
      "extractor_rules": [ ... ],         // 2A 激活
      "intent_strategy": { ... }          // 可选，无则空
    }
  },
  "generic": { "enabled": true, "default_channel": "prod", "database": null, "serving": {...} }
}}
```

serving 的 `parseProfile` 以这个 `serving` 块为根读取 → 四个字段同层，不再嵌套错配（消除风险②）。

### 3. 删除 / 废弃清单

| 项 | 处置 | 理由 |
|---|---|---|
| `ServingDomainProfile.entityTypes` / `strongEntityTypes` / `evalQuestions` | 删字段 | serving 零调用（属 ontology/评测，Mining 才用） |
| 下发 payload 里的 `ontology:` / `mining:` 整块 | 不下发给 serving | 同上 |
| `DomainRegistryEntry.scenarioPack` | 删（或仅留 debug） | serving 按目录/域名映射，从不读它 |
| `database_url_env` | 删 | 1A 内联 database 取代 |
| `scenario-packs-dir` / `domain-registry-path` | 降级为测试回退 | 改走接口 |

---

## 二、文件级改动清单

### main_control_service（Python）

| # | 文件 | 改动 |
|---|---|---|
| M1 | `service.py` | 新增 `get_serving_config()`：遍历 registry，每域拼 `{enabled, default_channel, database, serving: pack["serving"]}` |
| M2 | `main.py` | 新增 `GET /api/v1/serving-config` → M1 |
| M3 | `main.py` | 新增 `POST /api/v1/admin/reload-serving`：取 enabled 且有 `services.serving_url` 的域，去重 url，逐个 `POST {url}/api/v1/admin/reload-config`，聚合返回 |

### agent_serving_zdy（Java）— 按落地顺序

| # | 文件 | 改动 |
|---|---|---|
| S1 | `config/ServingProperties.java` | 加 `MainControl(String baseUrl)`；`scenarioPacksDir`/`domainRegistryPath` 仅测试用 |
| S2 | `resources/application.yml` | 加 `serving.main-control.base-url`；统一 `server.port` |
| S3 | `infrastructure/MainControlClient.java` 🆕 + DTO | RestClient GET 聚合接口 → `ServingConfigSnapshot`；失败抛 `ConfigFetchException` |
| S4 | `config/ServingBeans.java` | 注册 RestClient/MainControlClient bean |
| S5 | `domainpack/DomainRegistryEntry.java` | 去 `databaseUrlEnv`、`scenarioPack`；加 `DatabaseConfig database` |
| S6 | `domainpack/ServingDomainProfile.java` | 删 `entityTypes`/`strongEntityTypes`/`evalQuestions` |
| S7 | `domainpack/DomainRegistry.java` | `entries` 改 volatile Map；`apply(snapshot)` 原子替换；init 不读文件 |
| S8 | `domainpack/DomainPackReader.java` | `parseYaml(Path)` → `parseProfile(domainId, Map serving块)`；`apply(snapshot)` 重建 cache |
| S9 | `domainpack/DomainPoolManager.java` | `resolveDataSource` 改用内联 DatabaseConfig 建 Hikari；`invalidate(snapshot)` 只重建变化/移除域池 |
| S10 | `domainpack/ConfigReloadService.java` 🆕 | `reload()` = fetch → registry.apply → packReader.apply → poolManager.invalidate |
| S11 | `api/AdminController.java` 🆕 | `POST /api/v1/admin/reload-config`；可加 `GET /admin/config-status` |
| S12 | `SearchService.java` | 删 `databaseUrlEnv()`/`scenarioPack()` debug 引用 |
| S13 | 测试 | MainControlClient 抽接口 + stub；核对相关测试 |

### 部署接线

| # | 文件 | 改动 |
|---|---|---|
| D1 | `docker/supervisord.conf` | serving 加 `SERVING_MAIN_CONTROL_BASEURL`；确认 serving→main_control 不被 IP 白名单拦 |
| D2 | `.env` / `.env.example` | 加 `SERVING_MAIN_CONTROL_BASEURL`；移除对 `DOMAIN_REGISTRY_PATH`/`SCENARIO_PACKS_DIR` 依赖 |

---

## 三、决策 / 行为变更须知

1. **端口统一**：`application.yml` 现写死 8082，部署用 8081。改造前确认 8081 来源，对齐默认值，否则 M3 扇出打错端口。
2. **extractor_rules 激活（2A 已采纳）**：改造后 `extractor_rules` 首次生效（cloud_core_network 有 3 条规则），仅影响 QU 规则兜底路径。
3. **启动依赖**：serving 启动依赖 main_control；用 try/catch 降级 + 重载端点兜底，建议加启动短退避重试。
4. **mining 不动**：mining 仍读顶层 `domain_registry.yaml`，serving 与 mining 配置源短期分叉，另立任务统一。
