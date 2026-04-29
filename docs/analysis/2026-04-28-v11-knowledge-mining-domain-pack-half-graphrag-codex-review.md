# v1.1 Knowledge Mining Domain Pack / Half-GraphRAG 方向审查

- Task: `TASK-20260421-v11-knowledge-mining`
- Date: 2026-04-28
- From: Codex
- To: Claude Mining
- 类型: architecture-review / change-request

## 审查背景

管理员明确了新的产品边界：CoreMasterKB 不是云核心网专用知识库，而是面向各行业的通用知识库底座。云核心网只是当前第一个场景。场景知识应由专家配置和维护，底座能力必须保持一致、可迁移、可工业化。

本轮判断不是继续追问当前 pipeline 某个函数是否能跑，而是评估 Mining 是否正在走向“通用知识资产构建系统”。当前完整本体层工作量过大，暂不要求引入正式 ontology/entity graph 表；但必须先从代码结构上解除云核心网硬编码，形成 Domain Pack 驱动的半 GraphRAG 路线。

## 审查范围

- `knowledge_mining/mining/models.py`
- `knowledge_mining/mining/enrich/__init__.py`
- `knowledge_mining/mining/extractors.py`
- `knowledge_mining/mining/llm_templates.py`
- `knowledge_mining/mining/retrieval_units/__init__.py`
- `databases/asset_core/schemas/001_asset_core.sqlite.sql`
- `agent_serving` 对 `semantic_role / unit_type / entity_refs_json` 的读取依赖
- 工业级参考实现与文档

## 工业级参考

### Microsoft GraphRAG

来源：https://microsoft.github.io/graphrag/index/overview/

GraphRAG 的 indexing package 是面向非结构化文本的 data pipeline / transformation suite，用 LLM 抽取结构化数据。其核心产物包括 entities、relationships、claims、community detection、community summaries/reports 和 embeddings。

对本项目的启发：

- Mining 不应只是 chunking 或 retrieval unit 生成器，而应是知识资产编译器。
- 当前阶段可以不做完整 community/entity graph，但需要保留半 GraphRAG 主线：segment -> entity_refs -> relations -> retrieval_units -> eval。
- GraphRAG 的价值不在“多调用几次 LLM”，而在把语料转换成可检索、可解释、可评估、可增量发布的结构化资产。

### Anthropic Contextual Retrieval

来源：https://www.anthropic.com/research/contextual-retrieval

Anthropic 的 Contextual Retrieval 重点是给 chunk 生成短上下文，并在 embedding 和 BM25 索引前把上下文加入 chunk，而不是为每个上下文额外制造大量独立检索对象。

对本项目的启发：

- `raw_text` 应继续作为主证据单元。
- contextual retrieval 产物优先进入 `search_text` / 后续 `embedding_text`，不应默认膨胀成单独 `contextual_enhanced` unit。
- LLM context 应有成本门控：不处理 heading、不处理短段、优先处理脱上下文风险高的段。

### Haystack Pipelines

来源：https://docs.haystack.deepset.ai/v2.1/docs/pipelines

Haystack pipeline 由 components 和 connections 组成，并支持序列化。它的生产价值在于 pipeline 可配置、可替换、可复用，而不是把每个场景逻辑写死在代码里。

对本项目的启发：

- Mining pipeline 应是 profile-driven，而不是固定 Python 常量驱动。
- parse / segment / enrich / relation / retrieval asset / embedding / publish 可以是默认 profile，但场景差异必须通过配置或插件注入。
- 云核心网 rule extractor、prompt、实体类型和 retrieval policy 都不应留在通用底座代码中。

### LlamaIndex Schema-guided Extraction / Knowledge Graph

来源：https://docs.llamaindex.ai/

LlamaIndex 的知识抽取路线说明了一个关键取舍：schema-guided extraction 能提高一致性，但 schema 过早写死会牺牲跨领域泛化。

对本项目的启发：

- 当前阶段应采用“轻 schema”：由 Domain Pack 提供实体类型、关系类型、语义角色、prompt schema、抽取示例。
- 不应在底座中固定云核心网实体枚举。
- LLM 输出可被 domain pack 校验和过滤，但底座只负责通用承载和 provenance。

### Weaviate Hybrid Search

来源：https://docs.weaviate.io/weaviate/concepts/search/hybrid-search

Weaviate 的 hybrid search 将 vector search 与 keyword/BM25 搜索融合，说明工业检索通常不是单一路径。

对本项目的启发：

- Mining 产物必须服务多路召回：lexical/BM25、vector、entity、structure、relation、generated question。
- retrieval unit 不是越多越好，而是要分清主证据、召回辅助、rerank 特征。
- Serving 不应强依赖某个 JSON 子字段；Mining 也不能只为单一 SQL/BM25 路径生产资产。

## 当前主要问题

### P1: 云核心网实体类型仍写死在底座代码，阻断跨行业复用

当前硬编码位置包括：

- `models.py` 的 `STRONG_ENTITY_TYPES`
- `enrich/__init__.py` 的 `_ALLOWED_ENTITY_TYPES`
- `llm_templates.py` 的 JSON Schema enum 和通信网络 prompt
- `extractors.py` 的 SMF/UPF/AMF、N1/N4、ALM 等正则
- `retrieval_units/__init__.py` 的 entity_card 强实体筛选

这意味着即使 LLM 理解了另一个行业的新实体，也会在 schema enum、allowed types 或 retrieval policy 层被丢弃。当前问题不是数据库无法承载，而是代码把场景知识写进了通用底座。

### P1: 当前 LLM prompt 是场景 prompt，不是底座能力

`mining-segment-understanding` 当前 system prompt 写成通信网络知识库助手，实体类型和质量指引也面向通信网络。这可以作为云核心网 Domain Pack 的默认 prompt，但不能作为 Mining core prompt。

Mining core 不应内置行业 prompt。它应按 domain pack 注册模板，例如：

- `cloud_core_network.segment_understanding.v1`
- `generic.segment_understanding.v1`
- `finance_policy.segment_understanding.v1`

### P1: 缺少 Domain Pack Contract，专家知识没有正式入口

管理员的产品口径是：场景知识依赖专家，通用底座负责工业级能力。当前没有一个正式位置让专家提供行业实体类型、术语、别名、规则、prompt、样例和评测集，只能靠开发者改代码。

这会导致两个问题：

- 换行业需要重写 Mining 代码。
- 专家无法独立演进场景知识。

### P2: 半 GraphRAG 路线还没有被明确为当前阶段目标

当前不要求完整本体层，也不要求现在新增 `asset_entities / asset_entity_relations / communities`。但 Mining 必须立住半 GraphRAG 的资产主线：

- segment 是事实证据层。
- entity_refs 是轻量实体提及层。
- raw_segment_relations 是轻量关系层。
- retrieval_units 是检索入口层。
- eval_questions 是质量验证层。

这条线不清楚，后续很容易继续变成“多产几个 unit / 多调几个 LLM”的局部优化。

### P2: 数据库短期可不改，但 CHECK 枚举要谨慎使用

短期不建议改数据库。`entity_refs_json` 是 JSON 字段，本身可承载任意行业实体类型。

但需要注意：以下字段有 CHECK 枚举，长期会限制泛化：

- `asset_raw_segments.semantic_role`
- `asset_retrieval_units.semantic_role`
- `asset_raw_segment_relations.relation_type`
- `asset_documents.document_type`
- `asset_source_batches.source_type`
- `asset_retrieval_units.unit_type`

短期策略：

- 通用字段继续使用底座枚举。
- 行业细分角色写入 `facets_json.domain_role` 或 `metadata_json.domain_role`。
- 行业关系类型若不在 CHECK 中，先写 `relation_type='other'`，真实类型写入 `metadata_json.domain_relation_type`。
- 行业实体类型写入 `entity_refs_json[].type`，不要被 core allowed list 丢弃。

## 建议修复方向

### 方向 1: 新增 Domain Pack 目录，不改数据库

建议结构：

```text
knowledge_mining/domain_packs/
  generic/
    domain.yaml
    ontology_light.yaml
    prompts.yaml
    extractors.yaml
    retrieval_policy.yaml
    eval_questions.yaml
  cloud_core_network/
    domain.yaml
    ontology_light.yaml
    prompts.yaml
    extractors.yaml
    retrieval_policy.yaml
    eval_questions.yaml
```

最低字段建议：

```yaml
domain_id: cloud_core_network
display_name: Cloud Core Network
entity_types:
  - command
  - network_element
  - parameter
  - protocol
  - interface
  - alarm
  - feature
  - concept
strong_entity_types:
  - command
  - network_element
  - parameter
  - protocol
  - interface
  - alarm
  - feature
semantic_roles:
  core_mapping:
    parameter: parameter
    example: example
    procedure: procedure_step
    troubleshooting: troubleshooting_step
retrieval_policy:
  raw_text: primary
  generated_question: auxiliary
  entity_card: strong_entities_only
```

### 方向 2: Mining core 加载 DomainProfile，而不是 import 行业常量

建议新增 `DomainProfile` / `DomainPackLoader`：

```python
profile = load_domain_pack("cloud_core_network")
run(input_path, domain_profile=profile, llm_base_url=...)
```

底座代码只依赖：

- `profile.entity_types`
- `profile.strong_entity_types`
- `profile.prompts`
- `profile.extractor_rules`
- `profile.retrieval_policy`
- `profile.eval_questions`

不要再从 `models.py` import `STRONG_ENTITY_TYPES` 作为全局真理。

### 方向 3: LLM templates 从 domain pack 注册

`llm_templates.py` 应拆成：

- core template registry loader
- domain pack prompt templates
- schema builder

LLM JSON Schema 的 enum 应来自 domain pack，而不是写死。

验收标准：

- 云核心网 pack 注册的 `segment_understanding` 包含通信网络实体。
- generic pack 注册的 `segment_understanding` 不包含 SMF/UPF/N4 等场景词。
- 新建一个 toy domain pack，不改 core 代码也能跑出该 domain 的实体类型。

### 方向 4: Rule extractor 改成插件或配置规则

当前 `extractors.py` 中的 regex 可以先迁移到 `cloud_core_network/extractors.yaml`。短期不必实现复杂 DSL，先支持几种基础规则即可：

- regex entity extractor
- table column parameter extractor
- section title command extractor
- alias hints

底座提供通用 runner，domain pack 提供规则。

### 方向 5: Retrieval policy 由 Domain Pack 控制

`entity_card` 是否生成、哪些实体生成、每段最多几个 generated questions、contextual retrieval 处理哪些 segment，都应由 retrieval policy 控制。

默认工业策略建议：

- `raw_text`: always primary
- `contextual_retrieval`: enrich `raw_text.search_text`，不单独建 unit
- `generated_question`: only substantial non-heading segment，默认最多 1-2 个
- `entity_card`: only strong entity types，且按 domain policy 限制
- `table_row`: only structured table with stable columns

### 方向 6: 每个 Domain Pack 必须带 eval_questions

没有评测集，不允许宣称“工业级改进”。最低评测字段：

```yaml
questions:
  - id: q001
    question: registerIPv4 和 bindingIPv4 有什么区别？
    expected_entities:
      - registerIPv4
      - bindingIPv4
    expected_evidence_contains:
      - registerIPv4
      - bindingIPv4
    must_not_rank_top:
      - unrelated alarm
```

Mining 不一定直接回答问题，但必须能验证它生产的 retrieval assets 是否让 Serving 更容易召回正确 evidence。

## 不建议现在做的事

- 不要现在引入完整本体层。
- 不要马上新增大批 `asset_entities / asset_communities / ontology_versions` 表。
- 不要继续在 core pipeline 中加入更多云核心网 if/regex/prompt。
- 不要用“LLM 已接入”替代“质量可验证”。
- 不要把 `entity_card` 扩成所有实体默认建卡。

## 建议实施顺序

1. 提交一份 Domain Pack Contract 设计说明，明确文件结构、字段、默认 generic pack 和 cloud_core_network pack。
2. 把实体类型、strong entity policy、LLM prompt schema 从 core 迁移到 cloud_core_network pack。
3. 改 `run()` 支持 `domain_pack` 参数，默认 `generic` 或 `cloud_core_network` 由配置决定。
4. 把 rule extractor 改为读取 domain pack regex/rules。
5. 把 retrieval unit 生成策略改为读取 retrieval_policy。
6. 增加最小 toy domain 测试：不用改 core 代码，换一个 domain pack 能生成不同实体类型。
7. 增加 cloud_core_network eval_questions，验证当前核心问题能命中正确 evidence。

## 测试缺口

请补以下测试：

- `test_domain_pack_loader.py`: 能加载 generic 和 cloud_core_network pack。
- `test_domain_entity_schema.py`: LLM segment schema enum 来自 domain pack。
- `test_domain_rule_extractor.py`: 云核心网 regex 只在 cloud_core_network pack 生效。
- `test_domain_retrieval_policy.py`: entity_card 只为 policy 允许的 strong types 生成。
- `test_toy_domain_no_core_change.py`: 新增 toy domain pack，不改 `knowledge_mining/mining` 核心代码即可跑出 toy entity。
- `test_eval_questions_contract.py`: domain pack 必须包含 eval questions，且字段完整。

## 回归风险

- Serving 当前可能默认偏好 `raw_text/contextual_text`、`semantic_role`、`entity_refs_json`，迁移时必须保持字段向后兼容。
- LLM template key/version 注册要避免覆盖已有活跃模板，建议 template key 带 domain id。
- 如果直接移除 `STRONG_ENTITY_TYPES`，旧测试会失败；应先保留兼容 alias，但 deprecated，内部改为 profile 注入。
- 数据库 CHECK 暂不改，因此 domain-specific semantic role 不应直接写进 `semantic_role`，否则会插库失败。

## 残余风险

- 不引入完整 ontology 层时，跨文档实体归并、别名归一、实体关系强一致性仍然有限。
- 轻量 `entity_refs_json` 可以支撑半 GraphRAG，但不能替代长期实体表。
- Domain Pack 的质量依赖专家输入；如果专家只给实体枚举不给评测集，系统仍无法证明效果。

## 管理员介入影响

管理员明确要求：本项目面向各行业知识库，云核心网只是当前场景；场景应即插即用，专家知识由场景包承载，通用底座能力向工业级靠近。同时管理员明确当前阶段不引入完整本体层，优先跑通半 GraphRAG。

本审查按该口径约束 Claude Mining：短期不要求数据库大改，不要求完整 ontology，但要求立刻停止把云核心网知识继续写入 core。

## 最终评估

当前 Mining 已比早期版本更接近工业路线：LLM 进入 enrich / generated_question / contextual retrieval / discourse relation，retrieval unit 密度也开始收缩。但它仍不是通用知识库底座，因为场景知识仍写在 core 代码和 core prompt 中。

下一轮可验收目标不是“再多几个 LLM 能力”，而是：

> 不改 `knowledge_mining/mining` 核心代码，只替换 Domain Pack，就能切换实体类型、prompt、抽取规则、retrieval policy 和 eval questions。

做到这一点，Mining 才从“云核心网抽取 pipeline”转向“可插拔半 GraphRAG 知识资产编译器”。
