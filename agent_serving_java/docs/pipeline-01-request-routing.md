# Pipeline Stage 01: 请求入口与域路由

## 概述

本阶段是整个检索 serving 管线的入口。职责是：接收 HTTP 请求 → 参数校验 → 域（domain）验证 → 路由到正确的数据库连接池 → 将请求交给 SearchService 执行后续管线。

## 流程图

```
HTTP POST /api/v1/search
  │
  ▼
SearchController                    ← 接收请求，反序列化为 SearchRequest
  │
  ▼
GlobalExceptionHandler             ← 全局异常兜底
  │
  ▼
SearchService.search()
  ├─ DomainRegistry.resolve()       ← 验证 domain 是否合法/启用
  ├─ DomainPackReader.getProfile()   ← 加载 scenario pack 配置
  ├─ DomainContext.set(domain)       ← ThreadLocal 绑定当前域
  ├─ DomainPoolManager.getDataSource() ← 获取/创建域专属连接池
  └─ DomainRoutingDataSource         ← 每次 JDBC 调用自动路由到正确的库
```

## 输入

**HTTP Request**: `POST /api/v1/search`

请求体 `SearchRequest`（record）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | String | **是** | 用户原始查询文本，不能为空 |
| `scope` | Map\<String, Object\> | 否 | 作用域约束（如产品、版本），默认空 Map |
| `entities` | List\<EntityRef\> | 否 | 预识别实体，默认空 List |
| `debug` | boolean | 否 | 是否返回 debug 信息，默认 false |
| `domain` | String | 否 | 知识域名称，如 `cloud_core_network`，默认取配置 `serving.default-domain` |
| `channel` | String | 否 | 发布通道，如 `prod`、`staging`，默认取 registry 配置 |
| `mode` | String | 否 | 检索模式，默认 `"evidence"` |

**紧凑校验**：`SearchRequest` 的 compact constructor 在构造时就校验 `query` 非空，否则直接抛 `IllegalArgumentException("query_required")`。

## 输出

**正常**：`ContextPack` 被 SearchController 转为 JSON Map 返回：

```json
{
  "query": "...",
  "items": [...],
  "relations": [...],
  "sources": [...],
  "evidence_groups": [...],
  "issues": [...],
  "suggestions": [...],
  "debug": { ... }   // 仅当 request.debug=true 时存在
}
```

**异常**：由 `GlobalExceptionHandler` 统一处理，返回结构化错误：

| HTTP Status | error | 触发条件 |
|-------------|-------|----------|
| 400 | `query_required` | query 为空 |
| 400 | `unknown_domain` | domain 不在 registry 中 |
| 400 | `domain_disabled` | domain 被禁用 |
| 409 | `multiple_active_releases` | 同一 domain+channel 存在多个 active release |
| 503 | `no_active_release` | 没有 active 的发布 |
| 503 | `domain_database_unavailable` | 域数据库连不上 |
| 500 | `scenario_pack_missing` | domain registry 有但找不到 scenario pack |
| 500 | `internal_error` | 未知异常兜底 |

## 涉及的关键文件

| 文件 | 职责 |
|------|------|
| `api/SearchController.java` | HTTP 入口，POST `/api/v1/search`，反序列化 + 响应组装 |
| `api/GlobalExceptionHandler.java` | 全局异常处理，将异常映射为结构化 JSON 错误 |
| `api/HealthController.java` | 健康检查 `GET /actuator/health` |
| `config/CorsConfig.java` | CORS 跨域配置，允许 `localhost:*` 来源 |
| `domain/SearchRequest.java` | 请求 record，含 compact constructor 校验 |
| `domain/ContextPack.java` | 响应 record，items/relations/sources/debug 等 |
| `domainpack/DomainContext.java` | ThreadLocal 载体，绑定当前线程的 domain |
| `domainpack/DomainRoutingDataSource.java` | 继承 `AbstractRoutingDataSource`，每次 JDBC 调用自动路由 |
| `domainpack/DomainPoolManager.java` | 管理 per-domain HikariCP 连接池，懒创建、缓存、生命周期 |
| `domainpack/DomainRegistry.java` | 加载 `domain_registry.yaml`，提供域验证/配置查询 |
| `domainpack/DomainPackReader.java` | 加载 `scenario_packs/<domain>/domain.yaml`，提供 ServingDomainProfile |
| `domainpack/ServingDomainProfile.java` | 域配置 record：实体类型、路由策略、提取规则等 |
| `domainpack/DomainRegistryEntry.java` | 域注册条目：enabled、database_url_env、scenario_pack、default_channel |
| `config/ServingProperties.java` | `serving.*` 配置绑定 record |
| `config/ServingBeans.java` | 显式 Bean 装配（DataSource、RestTemplate、各 retriever） |

## 配置参数

### application.yml

```yaml
server:
  port: 8081

spring:
  datasource:
    url: jdbc:postgresql://${PG_HOST:localhost}:${PG_PORT:15432}/${PG_DBNAME:test_db}
    username: ${PG_USER:zdy}
    password: ${PG_PASSWORD:zdy1234}
    hikari:
      minimum-idle: 2
      maximum-pool-size: 10
      connection-timeout: 5000

serving:
  scenario-packs-dir: ${SCENARIO_PACKS_DIR:../scenario_packs}
  domain-registry-path: ${DOMAIN_REGISTRY_PATH:../domain_registry.yaml}
  default-domain: ${COREMASTERKB_DOMAIN:cloud_core_network}
  llm:
    base-url: ${LLM_SERVICE_URL:http://localhost:8900}
  embedding:
    model: ${EMBEDDING_MODEL:embedding-3}
    dimensions: ${EMBEDDING_DIMENSIONS:1024}
  rerank:
    model: ${RERANK_MODEL:rerank-pro}
```

### domain_registry.yaml（外部文件）

控制哪些域可用、各自连接哪个数据库、使用哪个 scenario pack：

```yaml
domains:
  cloud_core_network:
    enabled: true
    database_url_env: PG_JDBC_URL        # 可选，不设则用默认库
    scenario_pack: cloud_core_network
    default_channel: prod
```

### scenario_packs/<domain>/domain.yaml（外部文件）

定义域的检索策略、实体类型、路由策略等，由 DomainPackReader 加载。

## 具体实现细节

### 1. 域路由数据源（核心机制）

**问题**：多个知识域可能共用一个 PostgreSQL 实例但使用不同数据库，或者完全不同的数据库实例。需要每次 JDBC 调用自动路由到正确的库。

**方案**：`DomainRoutingDataSource` + `ThreadLocal`：

1. `SearchService.search()` 在执行任何 DB 操作前调用 `DomainContext.set(effectiveDomain)`，将 domain 名称绑定到当前线程
2. 每次 MyBatis/JDBC 调用获取连接时，`DomainRoutingDataSource.determineTargetDataSource()` 被触发
3. 读取 `DomainContext.get()` 获取当前 domain
4. 委托 `DomainPoolManager.getDataSource(domain)` 获取该域的连接池
5. 在 `finally` 块中调用 `DomainContext.clear()` 清理

**连接池管理**：
- `DomainPoolManager` 为每个 domain 维护独立的 HikariCP 连接池
- 懒创建：首次访问时创建，后续复用
- 如果 domain 的 `database_url_env` 未配置，复用默认 DataSource
- 创建时立即验证连接可用性（`conn.isValid(3)`），失败抛 `domain_database_unavailable`
- `@PreDestroy` 关闭所有自建连接池

### 2. Scenario Pack 加载

`DomainPackReader` 在 `@PostConstruct` 阶段扫描 `scenario_packs/` 目录下所有子目录，读取 `domain.yaml`，解析为 `ServingDomainProfile` 并缓存。

如果找不到 scenario pack 但 registry 有注册，抛 `scenario_pack_missing`（部署配置错误）。如果 registry 未加载（dev/test），返回默认 profile。

### 3. CORS 配置

`CorsConfig` 允许 `http://localhost:*` 和 `http://127.0.0.1:*` 来源跨域访问，支持前端开发服务器（Vite 默认 5173 端口）调用后端 API。

### 4. 异常处理层次

```
请求进入
  │
  ├─ SearchRequest 构造校验 → query_required
  │
  ├─ DomainRegistry.resolve()
  │   ├─ unknown_domain
  │   └─ domain_disabled
  │
  ├─ DomainPackReader.getProfile()
  │   └─ scenario_pack_missing
  │
  ├─ DomainPoolManager.getDataSource()
  │   └─ domain_database_unavailable
  │
  ├─ AssetRepository.resolveActiveScope()
  │   ├─ no_active_release
  │   └─ multiple_active_releases
  │
  └─ 其他异常 → internal_error (500)
```

## 工业化参考

| 参考实践 | 说明 |
|----------|------|
| **Spring AbstractRoutingDataSource** | Spring 官方提供的多数据源路由方案，基于 `determineCurrentLookupKey()` 查找目标数据源 |
| **ThreadLocal 上下文传播** | 类似 Spring Security 的 `SecurityContextHolder`，在当前线程传播上下文信息 |
| **HikariCP 懒加载** | 按需创建连接池，避免启动时连接所有域数据库 |
| **domain_registry.yaml** | 类似 SaaS 多租户配置，每个租户（域）有独立的数据库和策略 |
| **Scenario Pack** | 类似插件系统，每个域通过 YAML 文件定义自己的检索策略和实体模型 |

## 当前实现的不足

### 1. 域路由缺乏租户隔离保障

`DomainContext` 基于 ThreadLocal，但如果某个代码路径忘记清理（`DomainContext.clear()`），后续请求可能路由到错误的数据库。当前只在 `SearchService` 的 `finally` 块中清理，其他入口（如健康检查、管理接口）未覆盖。

**改进方向**：使用 Servlet Filter 或 Spring Interceptor 在请求级别统一设置和清理 DomainContext。

### 2. 连接池无健康检查和自动恢复

`DomainPoolManager` 在创建连接池时验证一次连接，之后如果数据库暂时不可用，连接池不会自动恢复。没有定期健康检查或重连机制。

**改进方向**：添加 HikariCP 的 `connectionTestQuery` + 定期验证活跃域的连接池状态。

### 3. CORS 配置过于宽松

当前允许所有 `localhost:*` 来源跨域，生产环境应该限制为特定来源。

**改进方向**：通过 profile 区分 dev/prod 的 CORS 策略，生产环境从配置文件读取允许的 origins。

### 4. 缺少请求级超时控制

SearchController 没有 per-request 超时。如果某个下游 LLM 服务挂起，请求会一直等待直到 RestTemplate 的全局超时（60s）。

**改进方向**：使用 `DeferredResult` 或 `CompletableFuture` + per-request deadline 传播。

### 5. 缺少限流和认证

当前无任何限流（rate limiting）和认证（authentication）机制。任何能访问 8081 端口的客户端都可以无限制调用。

**改进方向**：添加 Spring Security + Bucket4j 或 Resilience4j RateLimiter。

### 6. 响应格式不够统一

`SearchController` 手动将 `ContextPack` 拆解为 `Map<String, Object>`，字段名用 snake_case（如 `evidence_groups`），但 `ContextPack` record 的字段名是 camelCase（如 `evidenceGroups`）。如果后续加新字段容易遗漏。

**改进方向**：直接返回 `ContextPack` 对象让 Jackson 序列化，或统一使用 `@JsonProperty` 注解控制字段名。
