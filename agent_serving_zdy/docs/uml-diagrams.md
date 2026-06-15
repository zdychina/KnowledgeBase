# agent_serving_zdy UML 图集

> 配套 `detailed-design.md`。所有图以 **Mermaid** 编写，可在 GitHub / IntelliJ / VS Code（Markdown Preview Mermaid）直接渲染。
> 含：① 组件/分层依赖图 ② 领域模型类图 ③ 策略模式类图 ④ 检索主链路时序图 ⑤ 配置热重载时序图 ⑥ 多域连接池路由类图 ⑦ 部署图。
> 编写日期：2026-06-15

---

## 1. 组件 / 分层依赖图（Component Diagram）

DDD 单向向内依赖；外部系统以虚线标注。

```mermaid
flowchart TB
    subgraph ext[外部系统]
        UI[kb-ui]
        MC[main_control_service :8910]
        LLM[llm_service :8900]
        PG[(PostgreSQL + pgvector<br/>asset_core)]
    end

    subgraph serving[agent_serving_zdy :8081]
        direction TB
        API["api<br/>SearchController / AdminController<br/>HealthController / GlobalExceptionHandler"]
        APP["application<br/>SearchService / QueryUnderstandingEngine<br/>MultiQueryExpander / RetrievalRouter<br/>ContextAssembler / TreeNavigator<br/>SemanticCacheService / SessionStore"]
        PIPE["pipeline<br/>RetrievalOrchestrator + FusionStrategy"]
        RETR["retrieval<br/>Retriever 实现 + GraphExpander"]
        RERANK["rerank<br/>RerankPipeline + Reranker 实现"]
        EVID["evidence<br/>EvidenceRoleClassifier"]
        DOM["domain<br/>不可变 record 值对象"]
        DPACK["domainpack<br/>DomainRegistry / DomainPoolManager<br/>DomainRoutingDataSource / ConfigReloadService"]
        OBS["observability<br/>SearchMetrics / QueryLogAspect / TraceCollector"]
        INFRA["infrastructure<br/>EmbeddingClient / LlmClient<br/>MainControlClient / PgConfig"]
        PERS["mapper / entity / repository<br/>MyBatis Mapper + AssetRepository"]
    end

    UI -->|改配置/触发重载| MC
    API --> APP
    APP --> PIPE
    APP --> RERANK
    APP --> EVID
    APP --> DPACK
    APP --> OBS
    PIPE --> RETR
    RETR --> PERS
    RERANK --> INFRA
    APP --> INFRA
    APP --> PERS
    APP -.依赖.-> DOM
    PIPE -.-> DOM
    RETR -.-> DOM
    RERANK -.-> DOM

    INFRA -->|embed/rerank/generate| LLM
    DPACK -->|拉取每域配置| MC
    PERS -->|按域路由连接池| PG
    DPACK -->|建 HikariCP 池| PG
    MC -.POST reload-config 扇出.-> API
```

---

## 2. 领域模型类图（Domain Class Diagram）

核心不可变 `record`（`with*` 派生）。

```mermaid
classDiagram
    class SearchRequest {
        +String query
        +Map scope
        +List~EntityRef~ entities
        +boolean debug
        +String domain
        +String channel
        +String mode
        +String sessionId
        +String complexityHint
    }

    class QueryUnderstanding {
        +String originalQuery
        +String intent
        +String queryComplexity
        +List~SubQuery~ subQueries
        +List~EntityRef~ entities
        +Map scope
        +List~String~ keywords
        +EvidenceNeed evidenceNeed
        +String source
    }

    class RetrievalRoutePlan {
        +List~RouteConfig~ routes
        +Map scope
        +FusionConfig fusion
        +RerankConfig rerank
        +AssemblyConfig assembly
        +ExpansionConfig expansion
    }

    class RouteConfig {
        +String name
        +boolean enabled
        +double weight
        +int topK
    }

    class RetrievalQuery {
        +String query
        +List~String~ keywords
        +List~EntityRef~ entities
        +float[] embedding
        +List~String~ subQueries
        +String intent
        +List~String~ sectionPrefixes
    }

    class RetrievalCandidate {
        +String retrievalUnitId
        +double score
        +String source
        +Map metadata
        +ScoreChain scoreChain
        +withScore(double) RetrievalCandidate
        +withSource(String) RetrievalCandidate
        +withScoreChain(ScoreChain) RetrievalCandidate
    }

    class ScoreChain {
        +double rawScore
        +double fusionScore
        +double rerankScore
        +List~String~ routeSources
    }

    class ContextPack {
        +ContextQuery query
        +List~ContextItem~ items
        +List~ContextRelation~ relations
        +List~SourceRef~ sources
        +List~EvidenceGroup~ evidenceGroups
        +List~Issue~ issues
        +List~String~ suggestions
        +Map debug
    }

    class OrchestratorResult {
        +List~RetrievalCandidate~ candidates
        +List~RouteTrace~ routeTraces
    }

    SearchRequest --> QueryUnderstanding : 经 QU 引擎产出
    QueryUnderstanding --> RetrievalRoutePlan : RetrievalRouter.route()
    RetrievalRoutePlan "1" o-- "*" RouteConfig
    QueryUnderstanding --> RetrievalQuery : 构建检索输入
    RetrievalQuery --> RetrievalCandidate : 召回产出
    RetrievalCandidate "1" *-- "1" ScoreChain
    OrchestratorResult "1" o-- "*" RetrievalCandidate
    RetrievalCandidate --> ContextPack : 组装为上下文项
```

---

## 3. 策略模式类图（Strategy Pattern）

三处可插拔点：召回 / 融合 / 重排。

```mermaid
classDiagram
    %% ---- 召回策略 ----
    class Retriever {
        <<interface>>
        +retrieve(RetrievalQuery, List~String~ snapshotIds, int topK) List~RetrievalCandidate~
    }
    class FtsRetriever
    class DenseVectorRetriever
    class EntityExactRetriever
    Retriever <|.. FtsRetriever
    Retriever <|.. DenseVectorRetriever
    Retriever <|.. EntityExactRetriever

    class RetrievalOrchestrator {
        -Map~String,Retriever~ retrievers
        +execute(QueryUnderstanding, RetrievalRoutePlan, float[], List~String~, List~String~) OrchestratorResult
    }
    RetrievalOrchestrator o-- Retriever : 按路由名查找

    %% ---- 融合策略 ----
    class FusionStrategy {
        <<interface>>
        +fuse(List~RetrievalCandidate~, RetrievalRoutePlan) List~RetrievalCandidate~
    }
    class RRFFusion
    class WeightedRRFFusion
    class IdentityFusion
    FusionStrategy <|.. RRFFusion
    FusionStrategy <|.. WeightedRRFFusion
    FusionStrategy <|.. IdentityFusion
    RetrievalOrchestrator ..> FusionStrategy : 调用方按 FusionConfig 选择

    %% ---- 重排策略 + 级联 ----
    class Reranker {
        <<interface>>
        +rerank(List~RetrievalCandidate~, QueryUnderstanding) List~RetrievalCandidate~
    }
    note for Reranker "返回 null = 本级无法产出，触发降级"
    class LlmServiceReranker
    class LlmReranker
    class ServiceReranker
    class ScoreReranker
    Reranker <|.. LlmServiceReranker
    Reranker <|.. LlmReranker
    Reranker <|.. ServiceReranker
    Reranker <|.. ScoreReranker

    class RerankPipeline {
        -Reranker modelReranker
        -Reranker llmReranker
        -Reranker scoreReranker
        +rerank(List~RetrievalCandidate~, RetrievalRoutePlan, QueryUnderstanding) RerankResult
    }
    note for RerankPipeline "级联 model→llm→score + 6 步后处理"
    RerankPipeline o-- Reranker : 持有三级
    GraphExpander ..> Reranker : 无关
```

---

## 4. 检索主链路时序图（`POST /api/v1/search`）

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant SC as SearchController
    participant SS as SearchService
    participant EC as EmbeddingClient
    participant QU as QueryUnderstandingEngine
    participant RR as RetrievalRouter
    participant PM as DomainPoolManager
    participant TN as TreeNavigator
    participant MQ as MultiQueryExpander
    participant CACHE as SemanticCacheService
    participant RO as RetrievalOrchestrator
    participant RET as Retriever(s)
    participant FU as FusionStrategy
    participant RP as RerankPipeline
    participant CA as ContextAssembler

    Client->>SC: POST /search (SearchRequest)
    SC->>SS: search(request)
    SS-->>EC: ★ 乐观启动原始 query HyDE embedding (异步, 虚拟线程)
    SS->>QU: understand(query, profile, hint)
    QU-->>SS: QueryUnderstanding (intent/complexity/entities/subQueries)
    SS->>RR: route(understanding, profile)
    RR-->>SS: RetrievalRoutePlan
    SS->>PM: getDataSource(domain) (校验 DB 可达)
    PM-->>SS: DataSource / 抛 domain_database_unavailable
    Note over SS: DomainContext.set(domain) — 本线程 DB 绑定该域池
    SS->>TN: inferSections(entities, snapshotIds)
    TN-->>SS: soft 加权 / hard 过滤章节
    SS->>MQ: expand(query)
    MQ-->>SS: [原始 + ≤2 变体]
    SS->>EC: 并行 embed 所有 variant + sub-query (join futures)
    EC-->>SS: variantEmbeddings
    SS->>CACHE: lookup(domain, queryEmbedding)
    alt 命中
        CACHE-->>SS: ContextPack (缓存)
        SS-->>SC: 直接返回，跳过后续
    else 未命中
        loop 每个 variant / sub-query (≤4)
            SS->>RO: execute(understanding, plan, emb, snapshotIds, hardFilter)
            loop 每条启用路由 (异常隔离)
                RO->>RET: retrieve(RetrievalQuery, snapshotIds, topK)
                RET-->>RO: List<RetrievalCandidate>
            end
            RO-->>SS: OrchestratorResult (candidates + routeTraces)
        end
        SS->>FU: fuse(rawCandidates, plan)
        FU-->>SS: fused
        SS->>RP: rerank(fused, plan, understanding)
        Note over RP: model→llm→score 级联 + 6 步后处理
        RP-->>SS: RerankResult (ranked + traces)
        SS->>CA: assemble(query, understanding, scope, ranked, plan, sections)
        Note over CA: GraphExpander 邻域扩展 + EvidenceRoleClassifier
        CA-->>SS: ContextPack
        SS->>CACHE: store(...) (best-effort)
    end
    Note over SS: finally DomainContext.clear()
    SS-->>SC: ContextPack
    SC-->>Client: JSON {items, relations, sources, evidence_groups, issues, suggestions[, debug]}
```

---

## 5. 配置热重载时序图

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 运维/前端
    participant UI as kb-ui
    participant MC as main_control_service :8910
    participant AC as AdminController :8081
    participant CRS as ConfigReloadService
    participant MCC as MainControlClient
    participant REG as DomainRegistry
    participant DPR as DomainPackReader
    participant PM as DomainPoolManager

    Admin->>UI: 编辑配置并保存
    UI->>MC: 保存 YAML (配置单一事实源)
    Admin->>UI: 点「配置热重载」
    UI->>MC: POST /api/v1/admin/reload-serving
    MC->>AC: 向各 enabled 域 serving_url 扇出 POST /api/v1/admin/reload-config
    AC->>CRS: reload()
    CRS->>MCC: fetchServingConfig()
    alt main_control 可达
        MCC-->>CRS: ServingConfigSnapshot
    else 不可达
        CRS->>CRS: loadFromFiles() (本地 domain_registry.yaml + scenario_packs)
    end
    CRS->>REG: apply(snapshot) (volatile 原子替换)
    CRS->>DPR: apply(snapshot)
    CRS->>PM: invalidate() (按签名只重建变化/移除的域池)
    CRS-->>AC: domain count
    AC-->>MC: {ok:true, domains, count}
    Note over AC: 全程不重启 JVM
```

启动期 `@PostConstruct` 同样调 `reload()`；失败则降级为空配置（lenient），靠 reload 端点恢复。

---

## 6. 多域路由与连接池类图

```mermaid
classDiagram
    class DomainContext {
        <<ThreadLocal>>
        +set(String domain)$
        +get()$ String
        +clear()$
    }
    class DomainRoutingDataSource {
        +determineCurrentLookupKey() Object
    }
    class DomainPoolManager {
        -Map~String,DataSource~ pools
        -Map~String,String~ poolSignatures
        -Map~String,HikariDataSource~ ownedPools
        +getDataSource(String) DataSource
        +invalidate()
    }
    class DomainRegistry {
        -volatile snapshot
        +apply(ServingConfigSnapshot)
        +findEntry(String) Optional~DomainRegistryEntry~
        +getDefaultChannel(String) String
        +knownDomains() List
    }
    class DomainRegistryEntry {
        +String domain
        +boolean enabled
        +String defaultChannel
        +DatabaseConfig database
    }
    class DatabaseConfig {
        +String resolvedJdbcUrl
        +String user
        +String password
        +Integer poolMin
        +Integer poolMax
        +isUsable() boolean
        +signature() String
    }
    class HikariDataSource

    DomainRoutingDataSource ..> DomainContext : 读当前域
    DomainPoolManager --> DomainRegistry : 查域配置
    DomainRegistry "1" o-- "*" DomainRegistryEntry
    DomainRegistryEntry "1" *-- "0..1" DatabaseConfig
    DomainPoolManager "1" o-- "*" HikariDataSource : 自有专属池
    DomainPoolManager ..> DatabaseConfig : 按 signature 检测变化
```

---

## 7. 部署图（Deployment）

```mermaid
flowchart LR
    subgraph host[单容器 All-in-One · supervisord 编排]
        direction TB
        MCsvc[main_control_service<br/>:8910]
        SERV[agent_serving_zdy<br/>:8081<br/>SERVER_PORT / SERVING_MAIN_CONTROL_BASEURL]
        LLMsvc[llm_service<br/>:8900]
        MINING[knowledge_mining]
        MCP[mcp_server]
        KBUI[kb-ui]
    end

    subgraph extdb[外部独立部署]
        PG[(PostgreSQL + pgvector<br/>asset_core)]
        PROM[Prometheus]
    end

    KBUI --> MCsvc
    MCsvc -. reload 扇出 .-> SERV
    SERV -->|拉配置| MCsvc
    SERV -->|embed/rerank/generate| LLMsvc
    SERV -->|按域 HikariCP 路由| PG
    MINING -->|publish_release 写入| PG
    SERV -->|只读 active release| PG
    PROM -->|抓取 /actuator/prometheus| SERV
```

> 注：`Dockerfile` 的 `EXPOSE 8082` 为独立运行镜像遗留值；集成部署以 supervisord 注入的 **8081** 为准。

---

## 渲染与导出

- **GitHub / IDE**：直接预览本 `.md` 即渲染。
- **导出 PNG/SVG**：`mmdc -i uml-diagrams.md -o uml.png`（@mermaid-js/mermaid-cli），或贴到 mermaid.live。
- 如需 **PlantUML（.puml）** 版本或嵌入 `docs/html/` 的 HTML 页面，可另行生成。
