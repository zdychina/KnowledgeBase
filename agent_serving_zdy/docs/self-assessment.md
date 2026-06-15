# 代码白盒评价 · 自评文本（agent_serving_zdy）

> 姓名：张大勇　工号：z30031510　团队：AI 开发团队　语言：Java, Python
> 项目背景：CoreMasterKB 检索服务 `agent_serving_zdy`（Java 21 / Spring Boot 3.2.5 / MyBatis / Postgres+pgvector，端口 8081）
> 用法：每节对应青鸟一个评分项，单击单元格后将「自评得分 / 自评文本」整段粘贴。

---

## 一、软件设计（满分 30 ｜ 建议自评 24）

自评得分：24
自评文本：
本周期主导将旧 Python agent_serving 检索服务重写为 Java 版 agent_serving_zdy（Java 21 / Spring Boot 3.2.5 / MyBatis / Postgres+pgvector），编码前完成组件级软件实现设计：
【1.2 分层架构】按 DDD 思想划分 api / application / domain / pipeline / retrieval / rerank / domainpack / evidence / observability / infrastructure 十个职责清晰的包，domain 层用充血的值对象/record（RetrievalCandidate、ContextPack、QueryUnderstanding 等）承载语义，识别可复用与需分层解耦的边界，杜绝 Ctrl+C/V。
【1.2 设计模式】检索路由（Retriever → Dense/FTS/Entity/Graph）、融合策略（FusionStrategy → RRF/WeightedRRF/Identity）、重排（Reranker → Llm/Score/Service）三处均用策略模式 + 接口隔离，新增召回路或融合算法对扩展开放、对修改封闭。
【1.2 关键流程设计】设计 SearchService → RetrievalOrchestrator → 多路 Retriever → RRF 融合 → RerankPipeline → ContextAssembler 检索主链路；并设计配置热重载架构——以 main_control 为配置单一事实源，serving 不再直接读文件而走 HTTP 拉取、内存快照 volatile 原子替换、DomainPoolManager 按签名只重建变化的域连接池，实现不重启 JVM 的配置更新。
【1.1 技术选型】通过 DomainRoutingDataSource 做按域动态路由的连接池隔离，支撑多知识域共服务部署。
【1.4 AI 辅助设计】借助 AI 工具完成 Python→Java 架构映射、设计取舍评审与设计文档沉淀。

---

## 二、代码开发（满分 40 ｜ 建议自评 33）

自评得分：33
自评文本：
本周期在 agent_serving_zdy 累计代码量 16852 loc、提交 44 个 MR、问题单 0，质量与测试并重：
【2.1/2.2 代码实现与 CleanCode】主代码约 9000 行、110 个类，函数功能单一、接口对外暴露克制；以 Retriever / Reranker / FusionStrategy 接口承接多实现，模块间低耦合、低重复。
【2.1 高性能与健壮性】利用 Java 21 虚拟线程并行化 embedding 调用降低尾延迟；RetrievalOrchestrator 做路由级异常隔离——单条召回路异常不影响其余路由，保证部分可用而非整体失败。
【2.5 开发者测试】编写 39 个测试类、约 4000 行测试代码，与主代码接近 1:1；按层覆盖 api/application/domain/pipeline/retrieval/rerank/evidence/mapper/repository/observability，并含 system 集成测试，遵循 FIRST 原则，能有效拦截回归。
【2.3/2.4 检视与主动重构】主动对成熟链路做架构腐化点排查，沉淀 docs/optimization-notes.md，自评出延迟串行点、RestTemplate 无连接池、pgvector ANN 强前置过滤打不到 HNSW 索引、SessionStore 无 TTL 的慢性内存泄漏等 10 项问题，并按收益/风险优先级给出可落地改法。
【2.6 AI 辅助编码】在重写、检视、文档环节深度使用 AI 提效，并主动挖掘 AI 在检索服务调优中的适用场景。

---

## 三、软件工程（满分 20 ｜ 建议自评 15）

自评得分：15
自评文本：
聚焦提升服务可运维性与团队工程效率：
【3.2 可观测性建设】为检索 pipeline 引入 Micrometer/Prometheus 指标体系，含每路由候选数、rerank fallback、链路 TraceCollector，并以 AOP（QueryLogAspect）做无侵入查询日志落库，为性能优化提供量化抓手。
【3.2 配置热重载工程化】落地 main_control 聚合配置接口 + serving 扇出热重载，实现配置改动不停机生效，解决多域配置需逐服务重启的团队单点问题。
【3.1 部署工程】服务纳入 docker-compose + supervisord 单容器 All-in-One（6 服务统一编排），简化交付与环境一致性。
【3.3 AI 友好型资产】沉淀模块级实现设计、优化评审笔记等组织资产，固化检索服务专家经验，提升后续 AI Coding 在本模块的确定性。

---

## 四、其他（满分 10 ｜ 建议自评 6）

自评得分：6
自评文本：
【4.1 优秀案例总结与分享】制作检索方案技术分享材料 docs/slides/serving-retrieval-share.pptx，沉淀多路召回 + 融合 + 重排的设计思路用于团队赋能。
【4.2 编码底线】开发过程遵守编码与信息安全底线，不在代码与配置中硬编码敏感信息，问题单数为 0。
