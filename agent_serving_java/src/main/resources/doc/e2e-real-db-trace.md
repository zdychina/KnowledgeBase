# E2E 真实数据库全链路验证报告

> 生成时间: 2026-04-28 23:35:25
> 数据库: `D:\mywork\KnowledgeBase\CoreMasterKB\data\kb-asset_core.sqlite`
> LLM 服务: `localhost:8900`
> Embedding: Zhipu embedding-3 (2048维)
> Rerank: Zhipu rerank

---

## 数据库概览

| 指标 | 值 |
|------|-----|
| Retrieval Units | 171 |
| Embeddings (2048维) | 171 |
| 带实体引用的 RU | 128 |

**unit_type 分布:**
- `entity_card`: 66
- `generated_question`: 50
- `raw_text`: 50
- `table_row`: 5

## Stage 0: Resolve Active Scope

- **耗时**: 0ms
- **release_id**: `0a9fcfc3c5794eb59794d964a8edb98c`
- **build_id**: `efb3472786404367a7ea29e9d4daa17d`
- **snapshot_ids** (8): `['6b46743f35754ebe9f8a6725adc0dad5', '43bb38e77e4b44b0aa23e8f48fa1b8c2', '0443a52f81a0433ea3ace67fc1cf01e8']...`

## 服务状态

- **LLM 服务**: ✅ 可用
- **Zhipu Reranker**: ✅ 已加载
- **LLM Reranker**: ✅ 已加载

---
## Query 1: `什么是SA认证`

### Stage 1: Query Understanding (LLM-first)

- **耗时**: 3328ms
- **source**: `llm` ← 🟢 LLM
- **intent**: `conceptual`
- **entities**: `[{"type": "concept", "name": "SA认证"}]`
- **keywords**: `["SA认证"]`
- **scope**: `{}`
- **evidence_need**: `{"preferred_roles": [], "preferred_blocks": [], "needs_comparison": false, "needs_citation": true}`

### Stage 2: Retrieval Router

- **fusion**: `weighted_rrf` (k=60)
- **routes**:
  - `lexical_bm25`: enabled=True, weight=1.0, top_k=50
  - `entity_exact`: enabled=True, weight=1.0, top_k=30
  - `dense_vector`: enabled=True, weight=0.8, top_k=50

### Stage 3a: BM25 (FTS5) Retrieval

- **耗时**: 875ms
- **召回数**: 20
  - [3.6882] [属性](#ZH-CN_TOPIC_0292407882) | 名称 | 缩略语 | 同义词\nSA解析 | - | -
  - [3.6024] [定义](#ZH-CN_TOPIC_0292407882) | UDG 对到达自身的用户报文进行解析，获取消息中指定的字段的内容。按照消息简繁程度，SA解析可以分成以下三类：
  - [3.4564] SA | SA（feature） ...P业务的服务质量，为运营商提供了更多业务模式，也为用户提供丰富的业务服务。\n- SA功能提供了丰富的安全特性，能够过滤、管理UP...
  - ... +17 more

### Stage 3b: Entity Exact Retrieval

- **耗时**: 0ms
- **召回数**: 0

### Stage 3c: Dense Vector Retrieval (Zhipu Embedding)

- **Embedding 耗时**: 860ms, dim=2048
- **检索耗时**: 265ms
- **召回数**: 50
  - [0.7368] SA识别 | SA识别
  - [0.5831] 行1: SA解析、-、- | 名称为SA解析，缩略语为-，同义词为-。
  - [0.5790] 业务感知定义 | 业务感知定义
  - ... +47 more

### Stage 4: Weighted RRF Fusion

- **耗时**: 0ms
- **融合后候选数**: 53 (去重前: 70)
- **Top 5 融合结果**:
  - [fusion=0.0287] sources=['fts_bm25', 'dense_vector'] | SA识别 | SA识别
  - [fusion=0.0276] sources=['fts_bm25', 'dense_vector'] | 行1: SA解析、-、- | 名称为SA解析，缩略语为-，同义词为-。
  - [fusion=0.0268] sources=['fts_bm25', 'dense_vector'] | SA | SA（feature） ...P业务的服务质量，为运营商提供了更多业务模式，也为用户提供丰富的业务服务。\n- SA功能...
  - [fusion=0.0260] sources=['fts_bm25', 'dense_vector'] | Q2: SA识别的定义在哪里查找？ | SA识别的定义在哪里查找？\n---\n来源: SA识别\n- [属性](#ZH-CN_TOPIC_0292407882...
  - [fusion=0.0257] sources=['fts_bm25', 'dense_vector'] | [定义](#ZH-CN_TOPIC_0292407882) | UDG 对到达自身的用户报文进行解析，获取消息中指定的字段的内容。按照消息简繁程度，SA解析可以分成以下三类：

### Stage 5: Rerank (Zhipu Model → LLM → Score Cascade)

- **耗时**: 2578ms
- **使用的 Reranker**: `zhipu_model`
- **排序后候选数**: 53
- **Top 5 Rerank 结果**:
  - [rerank=1.0000] sources=['fts_bm25', 'dense_vector'] | 业务感知定义 | 业务感知（Service Awareness，简称SA），是指在用户会话过程中，对用户的数据报文进行解析，从而区分出用户使用的不同业务。通过业务感知，运营商能够...
  - [rerank=1.0000] sources=['fts_bm25', 'dense_vector'] | [定义](#ZH-CN_TOPIC_0292407882) | - SPI（Shallow Packet Inspection）仅对三四层中的五元组（源地址、目的地址、源端口、目的端口以及协议类型）信息进行分析，来确定当前流...
  - [rerank=1.0000] sources=['fts_bm25', 'dense_vector'] | SA | SA（feature） ...P业务的服务质量，为运营商提供了更多业务模式，也为用户提供丰富的业务服务。\n- SA功能提供了丰富的安全特性，能够过滤、管理UP...
  - [rerank=1.0000] sources=['fts_bm25', 'dense_vector'] | SA识别 | SA识别
  - [rerank=1.0000] sources=['fts_bm25', 'dense_vector'] | Q2: H-SA技术适用于哪些类型的协议？ | H-SA技术适用于哪些类型的协议？\n---\n来源: [定义](#ZH-CN_TOPIC_0292407882)\n- SPI（Shallow Packet ...

### Query 1 汇总

| 阶段 | 耗时 | 召回数 | source |
|------|------|--------|--------|
| BM25 | 875ms | 20 | lexical_bm25 |
| Entity Exact | 0ms | 0 | entity_exact |
| Dense Vector | 1125ms | 50 | dense_vector |
| Fusion (WRRF) | 0ms | 53 | — |
| Rerank (zhipu_model) | 2578ms | 53 | — |
| **总计** | **3718ms** | — | — |

---
## Query 2: `ADD AMF 怎么配置`

### Stage 1: Query Understanding (LLM-first)

- **耗时**: 3407ms
- **source**: `llm` ← 🟢 LLM
- **intent**: `procedural`
- **entities**: `[{"type": "network_element", "name": "AMF"}, {"type": "command", "name": "ADD"}]`
- **keywords**: `["配置", "ADD", "AMF"]`
- **scope**: `{"products": [], "network_elements": ["AMF"]}`
- **evidence_need**: `{"preferred_roles": ["amf_configuration"], "preferred_blocks": ["add_amf"], "needs_comparison": false, "needs_citation": false}`

### Stage 2: Retrieval Router

- **fusion**: `weighted_rrf` (k=60)
- **routes**:
  - `lexical_bm25`: enabled=True, weight=1.0, top_k=50
  - `entity_exact`: enabled=True, weight=1.0, top_k=30
  - `dense_vector`: enabled=True, weight=0.8, top_k=50

### Stage 3a: BM25 (FTS5) Retrieval

- **耗时**: 0ms
- **召回数**: 28
  - [7.8348] ADD RULE | ADD RULE（command） 更多关于规则配置的内容，详见 **[ADD RULE](../../../../../OM参考/命令/UDG MML命令/用...
  - [7.5908] ADD HEADEN | ADD HEADEN（command） ...504.md)** 配置的分类属性名称；对于HEADEN策略，策略名称是 **[ADD HEADEN](../.....
  - [7.5617] ADD CATEGORYPROP | ADD CATEGORYPROP（command） ...7606.md)** 配置的PCC策略组名称；对于BWM策略，策略名称是 **[ADD CATEGOR...
  - ... +25 more

### Stage 3b: Entity Exact Retrieval

- **耗时**: 15ms
- **召回数**: 5
  - [0.9500] ADD PCCPOLICYGRP | ADD PCCPOLICYGRP（command） ...定到规则上。策略名称随策略类型的变化而变化，如对于PCC策略，策略名称是 **[ADD PCCPOLI...
  - [0.9500] ADD CATEGORYPROP | ADD CATEGORYPROP（command） ...7606.md)** 配置的PCC策略组名称；对于BWM策略，策略名称是 **[ADD CATEGOR...
  - [0.9500] ADD HEADEN | ADD HEADEN（command） ...504.md)** 配置的分类属性名称；对于HEADEN策略，策略名称是 **[ADD HEADEN](../.....
  - ... +2 more

### Stage 3c: Dense Vector Retrieval (Zhipu Embedding)

- **Embedding 耗时**: 1063ms, dim=2048
- **检索耗时**: 0ms
- **召回数**: 50
  - [0.5647] 规则 | 规则
  - [0.5432] SA识别 | SA识别
  - [0.5412] 业务解析与识别流程 | 业务解析与识别流程
  - ... +47 more

### Stage 4: Weighted RRF Fusion

- **耗时**: 0ms
- **融合后候选数**: 60 (去重前: 83)
- **Top 5 融合结果**:
  - [fusion=0.0443] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | ADD RULE | ADD RULE（command） 更多关于规则配置的内容，详见 **[ADD RULE](../../../../.....
  - [fusion=0.0425] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | ADD HEADEN | ADD HEADEN（command） ...504.md)** 配置的分类属性名称；对于HEADEN策略，策略名称是 ...
  - [fusion=0.0416] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | ADD CATEGORYPROP | ADD CATEGORYPROP（command） ...7606.md)** 配置的PCC策略组名称；对于BWM策略，...
  - [fusion=0.0413] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | Q1: 增加规则（ADD RULE）命令的更多内容在哪里查看 | 增加规则（ADD RULE）命令的更多内容在哪里查看？\n---\n来源: [定义](#ZH-CN_TOPIC_0292...
  - [fusion=0.0318] sources=['fts_bm25', 'entity_exact'] | ADD PCCPOLICYGRP | ADD PCCPOLICYGRP（command） ...定到规则上。策略名称随策略类型的变化而变化，如对于PCC策略，...

### Stage 5: Rerank (Zhipu Model → LLM → Score Cascade)

- **耗时**: 1344ms
- **使用的 Reranker**: `zhipu_model`
- **排序后候选数**: 60
- **Top 5 Rerank 结果**:
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | ADD CATEGORYPROP | ADD CATEGORYPROP（command） ...7606.md)** 配置的PCC策略组名称；对于BWM策略，策略名称是 **[ADD CATEGOR...
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | ADD RULE | ADD RULE（command） 更多关于规则配置的内容，详见 **[ADD RULE](../../../../../OM参考/命令/UDG MML命令/用...
  - [rerank=1.0000] sources=['fts_bm25', 'dense_vector'] | [定义](#ZH-CN_TOPIC_0292407887) | 更多关于规则配置的内容，详见 **[ADD RULE](../../../../../OM参考/命令/UDG MML命令/用户面服务管理/业务匹配策略/业务匹配...
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | ADD HEADEN | ADD HEADEN（command） ...504.md)** 配置的分类属性名称；对于HEADEN策略，策略名称是 **[ADD HEADEN](../.....
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact'] | ADD PCCPOLICYGRP | ADD PCCPOLICYGRP（command） ...定到规则上。策略名称随策略类型的变化而变化，如对于PCC策略，策略名称是 **[ADD PCCPOLI...

### Query 2 汇总

| 阶段 | 耗时 | 召回数 | source |
|------|------|--------|--------|
| BM25 | 0ms | 28 | lexical_bm25 |
| Entity Exact | 15ms | 5 | entity_exact |
| Dense Vector | 1063ms | 50 | dense_vector |
| Fusion (WRRF) | 0ms | 60 | — |
| Rerank (zhipu_model) | 1344ms | 60 | — |
| **总计** | **1359ms** | — | — |

---
## Query 3: `UDG和UNC的区别`

### Stage 1: Query Understanding (LLM-first)

- **耗时**: 4109ms
- **source**: `llm` ← 🟢 LLM
- **intent**: `comparative`
- **entities**: `[{"type": "product", "name": "UDG"}, {"type": "product", "name": "UNC"}]`
- **keywords**: `["UDG", "UNC", "区别"]`
- **scope**: `{"products": ["UDG", "UNC"], "network_elements": []}`
- **evidence_need**: `{"preferred_roles": [], "preferred_blocks": ["产品介绍", "功能差异"], "needs_comparison": true, "needs_citation": false}`

### Stage 2: Retrieval Router

- **fusion**: `weighted_rrf` (k=60)
- **routes**:
  - `lexical_bm25`: enabled=True, weight=1.0, top_k=50
  - `entity_exact`: enabled=True, weight=1.0, top_k=30
  - `dense_vector`: enabled=True, weight=0.8, top_k=50

### Stage 3a: BM25 (FTS5) Retrieval

- **耗时**: 0ms
- **召回数**: 30
  - [4.7445] Q1: SPI和SA技术的主要区别是什么？ | SPI和SA技术的主要区别是什么？\n---\n来源: [定义](#ZH-CN_TOPIC_0292407882)\n- SPI（Shallow Packet ...
  - [3.0314] UDG NAT功能专题 | UDG NAT功能专题（feature） ...vTCP_OPT功能专题/相关特性_51051778.md)<br>、<br>[UDG NAT功能专题](../...
  - [3.0085] UDG vTCP_OPT功能专题 | UDG vTCP_OPT功能专题（feature） ...用策略当前支持的功能包含：to、nat和tethering_block。\n- [UDG vTCP_O...
  - ... +27 more

### Stage 3b: Entity Exact Retrieval

- **耗时**: 0ms
- **召回数**: 27
  - [0.9500] UDG | UDG（network_element） UDG 对到达自身的用户报文进行解析，获取消息中指定的字段的内容。按照消息简繁程度，S...
  - [0.9500] UDG | UDG（network_element） ...别能力到特征库中。\n- 客户可以在特征库中自行定义协议特征，进行协议识别。\n- UDG无需升级，只通过简单更...
  - [0.9500] GWFD-020351 PCC基本功能 | GWFD-020351 PCC基本功能（feature） ...费与策略控制，代表该规则可以配置PCC策略，用于实现计费和策略控制功能。\n- [GWFD-02...
  - ... +24 more

### Stage 3c: Dense Vector Retrieval (Zhipu Embedding)

- **Embedding 耗时**: 1062ms, dim=2048
- **检索耗时**: 16ms
- **召回数**: 50
  - [0.5074] 规则 | 规则
  - [0.4970] SA识别 | SA识别
  - [0.4902] UDG | UDG（network_element） UDG 对到达自身的用户报文进行解析，获取消息中指定的字段的内容。按照消息简繁程度，S...
  - ... +47 more

### Stage 4: Weighted RRF Fusion

- **耗时**: 0ms
- **融合后候选数**: 62 (去重前: 107)
- **Top 5 融合结果**:
  - [fusion=0.0447] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | UDG | UDG（network_element） UDG 对到达自身的用户报文进行解析，获取消息中指定的字段的内容。按照消息简繁...
  - [fusion=0.0428] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | UDG | UDG（network_element） ...别能力到特征库中。\n- 客户可以在特征库中自行定义协议特征，进行协议识...
  - [fusion=0.0418] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | UDG NAT功能专题 | UDG NAT功能专题（feature） ...vTCP_OPT功能专题/相关特性_51051778.md)<br>、<...
  - [fusion=0.0395] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | UDG vTCP_OPT功能专题 | UDG vTCP_OPT功能专题（feature） ...用策略当前支持的功能包含：to、nat和tethering_b...
  - [fusion=0.0380] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | [定义](#ZH-CN_TOPIC_0292407882) | UDG 对到达自身的用户报文进行解析，获取消息中指定的字段的内容。按照消息简繁程度，SA解析可以分成以下三类：

### Stage 5: Rerank (Zhipu Model → LLM → Score Cascade)

- **耗时**: 1063ms
- **使用的 Reranker**: `zhipu_model`
- **排序后候选数**: 62
- **Top 5 Rerank 结果**:
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | [定义](#ZH-CN_TOPIC_0292407883) | - 由于应用/服务供应商随时间不断变化，为了确保业务感知的识别准确率，协议特征库需要经常更新。\n- 可以根据客户需求，更新特定协议识别能力到特征库中。\n- ...
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | Q2: UDG如何支持新协议或新业务的识别？ | UDG如何支持新协议或新业务的识别？\n---\n来源: [定义](#ZH-CN_TOPIC_0292407883)\n- 由于应用/服务供应商随时间不断变化，...
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | Q2: 协议特征库有哪些特点？ | 协议特征库有哪些特点？\n---\n来源: [定义](#ZH-CN_TOPIC_0292407883)\n协议特征库独立在 UDG 软件之外，是多种应用层协议、...
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | Q1: 协议特征库是否独立于UDG软件之外？ | 协议特征库是否独立于UDG软件之外？\n---\n来源: [定义](#ZH-CN_TOPIC_0292407883)\n协议特征库独立在 UDG 软件之外，是多...
  - [rerank=1.0000] sources=['fts_bm25', 'entity_exact', 'dense_vector'] | [定义](#ZH-CN_TOPIC_0292407883) | 协议特征库独立在 UDG 软件之外，是多种应用层协议、应用程序特有的识别特征的集合。协议特征库允许 UDG 针对特定的业务功能对应的常用协议、协议组合、应用商开...

### Query 3 汇总

| 阶段 | 耗时 | 召回数 | source |
|------|------|--------|--------|
| BM25 | 0ms | 30 | lexical_bm25 |
| Entity Exact | 0ms | 27 | entity_exact |
| Dense Vector | 1078ms | 50 | dense_vector |
| Fusion (WRRF) | 0ms | 62 | — |
| Rerank (zhipu_model) | 1063ms | 62 | — |
| **总计** | **1079ms** | — | — |

---
## 总结

- **LLM QU source**: 全部查询均为 `llm` ✅
- **三路召回**: BM25 + Entity Exact + Dense Vector ✅
- **融合算法**: Weighted RRF ✅
- **Rerank**: Zhipu Model Reranker (第一优先) ✅
- **Embedding**: Zhipu embedding-3, 2048维, 真实 API 调用 ✅
