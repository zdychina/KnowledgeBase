# CoreMasterKB v1.1 Knowledge Mining 工业级数据质量基线审查

- 时间：2026-04-28 22:45
- From：Codex
- To：Claude Mining
- 任务：`TASK-20260421-v11-knowledge-mining`
- 审查对象：Claude Mining 最新 `v1.4 domain pack + LLM integration` 实现、`llm_service.sqlite` 调用记录、`data/kb-asset_core.sqlite` 真实产物

## 审查背景

管理员明确要求：Mining 不能继续止步于“LLM 已接入”或“Domain Pack 已外置”的表层实现。CoreMasterKB 的目标是跨行业知识库底座，云核心网只是当前场景；当前阶段暂不引入完整本体层，但必须按工业级可用的半 GraphRAG / RAG ingestion 基线构建真实可用的数据资产。

本轮审查特别关注真实数据，而不是只读代码。管理员指出原始片段 `52bffeb308e54bff9e40b93fcf8c3e50` 的内容只是目录锚点：

```md
- [属性](#zh-cn_topic_0292407882__1.3.1.1)
- [定义](#zh-cn_topic_0292407882__1.3.2.1)
```

但 Mining 生成了问题 `Q1: 在SA识别中，属性的定义是什么？`。这不是孤立显示瑕疵，而是 Mining 当前缺少工业级数据质量门的直接证据。

## 工业级参考

- Anthropic Contextual Retrieval：原始 chunk 仍是主证据层，LLM 主要为 chunk 补充简短上下文以改善 embedding/BM25，不能让生成物压过证据层。https://www.anthropic.com/research/contextual-retrieval
- Microsoft GraphRAG indexing dataflow：索引阶段分层构建 text units、entities、relationships、community reports，强调可追溯图结构，而不是无门槛对每个片段生成问题。https://microsoft.github.io/graphrag//index/default_dataflow/
- Microsoft GraphRAG dynamic community selection：图索引用于在查询时选择相关实体社区，核心仍是结构化证据组织。https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/
- Haystack DocumentPreprocessor：生产 RAG pipeline 将清洗、切分作为独立组件，先处理低质量输入，再进入检索和生成。https://docs.haystack.deepset.ai/docs/documentpreprocessor
- Haystack Evaluation：生产 RAG 应评估 pipeline/component，不只看最终回答。https://docs.haystack.deepset.ai/docs/evaluation
- LlamaIndex Property Graph / schema-guided extraction：结构抽取必须受 schema/policy 约束，避免自由生成污染图资产。https://docs.llamaindex.ai/en/latest/examples/property_graph/property_graph_advanced/
- Ragas Metrics：RAG 质量要拆成 context precision、context recall、faithfulness 等维度，不应只做关键词 recall。https://docs.ragas.io/en/stable/concepts/metrics/

## 审查范围

- 代码范围：
  - `knowledge_mining/mining/retrieval_units/__init__.py`
  - `knowledge_mining/mining/enrich/__init__.py`
  - `knowledge_mining/mining/extractors.py`
  - `knowledge_mining/mining/domain_pack.py`
  - `knowledge_mining/mining/llm_templates.py`
  - `knowledge_mining/mining/jobs/run.py`
  - `knowledge_mining/mining/eval.py`
  - `knowledge_mining/domain_packs/cloud_core_network/domain.yaml`
- 数据范围：
  - `data/kb-asset_core.sqlite`
  - `data/kb-mining_runtime.sqlite`
  - `data/llm_service.sqlite`
- 真实数据统计：
  - `asset_raw_segments = 50`
  - `asset_retrieval_units = 171`
  - `agent_llm_tasks = 119`
  - `agent_llm_requests = 119`
  - `agent_llm_results = 119`
  - `agent_llm_attempts = 119`

## 发现的问题

### P0. 目录/导航片段进入 question-gen，LLM 生成不可回答问题

真实片段 `52bffeb308e54bff9e40b93fcf8c3e50` 是 `block_type=list`、`semantic_role=unknown`、`token_count=20` 的目录锚点列表。Mining 对它生成了两个 `generated_question`：

```text
Q1: 在SA识别中，属性的定义是什么？
Q2: SA识别的定义在哪里查找？
```

`llm_service.sqlite` 中对应 task `9eac3afc-ed34-4549-9323-a7c9b0a38e2e` 的 request input 就是该目录片段，result 确实返回了这两个问题。也就是说，问题不是 UI 拼接导致，而是 pipeline 把不可回答片段送进 LLM，且没有 post-validation。

根因在 `knowledge_mining/mining/retrieval_units/__init__.py` 的 `_is_questionworthy()`：当前只排除 heading、`token_count < 10`、长度 `< 15`。这不足以识别 TOC、纯链接列表、导航片段、稀疏属性表。

工业级要求：LLM 只能作为受控增强器，不得替代内容质量判断。不可回答片段必须在入模前被 deterministic gate 拦截。

### P0. `Q1/Q2` 前缀污染用户可见字段

`Q1/Q2` 前缀来自 `_make_generated_question_unit()`：

```python
title = f"Q{question_index + 1}: {question[:60]}"
```

这不是检索语义，不应进入 `title`、`text` 或 `search_text`。如果 Serving/UI 使用 `title` 展示或排序，会直接暴露噪声。序号只应放入 `metadata_json.question_index`。

工业级要求：检索资产字段应保存语义文本；展示编号属于展示层职责，不能污染知识资产。

### P0. Retrieval Unit 分布已经偏离“证据优先”原则

真实 `asset_retrieval_units` 分布：

```text
raw_text: 50，占 29.2%
generated_question: 50，占 29.2%
entity_card: 66，占 38.6%
table_row: 5，占 2.9%
```

代码注释宣称目标是：

```text
raw_text: 60-70%
generated_question: 15-20%
entity_card: 5-10%
table_row: 5-10%
```

真实产物与设计目标完全不一致。当前不是“raw_text 主证据 + 辅助召回”，而是 `generated_question + entity_card` 合计 `67.8%`，辅助产物反过来压过证据层。

工业级要求：raw evidence 必须是主资产。增强产物应被预算、限流、校验和回滚，不能无限膨胀。

### P0. 生成问题缺少 answerability post-validation

真实库中 `generated_question = 50`，其中：

```text
来自 list: 22
来自 table: 7
来自 paragraph: 19
来自 blockquote: 2
TOC-like 锚点目录问题: 至少 8
title 含 Qn 前缀: 50/50
```

典型错误包括：

```text
Q1: SA解析这个属性的缩略语是什么？
源片段：名称 | 缩略语 | 同义词 / SA解析 | - | -
```

该问题虽然形式上可回答，但答案是 `-`，检索价值极低。另一类问题如“在哪里查找”“包含哪些子主题”属于文档导航问题，不是知识问题，默认不应进入业务知识检索资产。

工业级要求：LLM 输出后必须校验问题是否能由 source segment 直接回答，且答案是否有业务知识价值。

### P1. Domain Pack 只外置了部分场景知识，未承载完整 retrieval policy

当前 `domain.yaml` 已外置 entity types、strong entity types、regex、LLM templates、eval questions，这是正确方向。但 question generation 的核心质量策略仍然在 core 代码中：

```text
_is_questionworthy()
_make_generated_question_unit()
entity_card 生成策略
unit budget
post-validation
```

工业级可插拔场景不只是替换实体枚举。Domain Pack 必须能配置 question policy、content quality policy、entity card policy、retrieval unit budget、skip patterns、eval gates。云核心网只是一个 pack，底座必须一致。

### P1. 目录片段应产生 `references` 关系，而不是 generated_question

目录/锚点列表的知识价值不是“可回答问题”，而是“文档导航关系”。例如：

```md
- [属性](#...)
- [定义](#...)
```

正确处理是解析为：

```text
SA识别目录片段 -> references -> 属性章节
SA识别目录片段 -> references -> 定义章节
```

当前 `asset_raw_segment_relations` 主要是结构关系：

```text
same_parent_section: 83
same_section: 48
previous: 42
next: 42
section_header_of: 31
elaborates: 18
```

但目录锚点未被用于建立有价值的 `references` 关系，反而污染了 generated_question。

### P1. eval 仍不足以拦截真实产物污染

`knowledge_mining/mining/eval.py` 当前主要做 keyword recall，不能发现：

```text
TOC 片段生成问题
Qn 前缀污染 title
entity_card 来自导航片段
辅助 unit 占比超标
生成问题不可由 source segment 直接回答
LLM task_id 追溯失败
```

工业级要求：Mining 必须有数据资产质量 eval，直接检查真实 SQLite，而不是只做 mock 单元测试或 keyword recall。

## 必须一次性交付的修复项

Claude Mining 下一版不得再按“先修一点、后续演进”的口径交付。必须一次性交付以下工业级基线。

### 1. Content Quality Gate

新增正式内容质量门，所有 segment 入 LLM 前必须先判定：

```text
is_navigation_only
is_toc_like
is_sparse_table
is_answerable
answer_signal_score
link_density
text_density
quality_reason
```

短期可以写入 `asset_raw_segments.metadata_json.content_quality`，无需改表。不可回答片段不得进入 `mining-question-gen`，不得生成 `entity_card`。

### 2. Domain Pack 驱动 Question Policy

`domain.yaml` 必须承载 question generation 的质量策略，例如：

```yaml
retrieval_policy:
  max_questions_per_segment: 1
  max_questions_per_document: 20
  generated_question_max_ratio: 0.2
  generated_question_enabled_roles:
    - concept
    - procedure_step
    - parameter
    - constraint
  skip_block_types_for_question:
    - heading
  generated_question_blocklist_patterns:
    - "^\\s*-\\s*\\[[^\\]]+\\]\\(#"
  sparse_table_policy: skip_question
```

Core 代码只能实现通用机制，不得把云核心网策略写死在 `knowledge_mining/mining`。

### 3. Question Post Validation

LLM 返回问题后必须做后验校验：

```text
问题不能是“在哪里查找/有哪些子主题/包含哪些章节”这类导航问题
问题必须能由 source segment 直接回答
问题的核心名词必须能在 source segment 或 section context 找到证据
问题之间近义重复时只保留一个
稀疏表格、目录列表、纯链接列表默认丢弃
```

被丢弃的问题必须记录 `generation_decision`，便于审计。

### 4. Qn Prefix Removal

`generated_question.title` 必须直接等于问题文本。`Q1/Q2` 只允许存在于：

```json
{"question_index": 0}
```

不得进入 `title`、`text`、`search_text`。

### 5. Retrieval Unit Budget

构建结束后必须检查 unit 分布。建议默认阈值：

```text
raw_text >= 55%
generated_question <= 20%
entity_card <= 20%
```

如果超阈值，必须裁剪低质量辅助 unit，或让 build validation 失败。不能让真实库继续出现 `raw_text 29.2%`、`entity_card 38.6%` 这种分布。

### 6. Entity Card Quality Gate

`entity_card` 必须满足：

```text
实体类型属于 strong_entity_types
来源 segment 不是 navigation-only / toc-like
实体在 source segment 中有足够上下文
每个 segment 有 entity_card cap
弱实体、泛概念、目录链接实体不得默认立卡
```

`entity_card` 是召回入口，不是所有识别实体的镜像。

### 7. Reference Relation Extraction

目录/锚点/Markdown 链接应转化为 `references` 关系。对无法解析目标 segment 的链接，应记录 unresolved reference metadata，而不是生成伪问题。

### 8. LLM Provenance 完整追溯

所有 LLM 增强产物必须满足：

```text
asset_retrieval_units.llm_result_refs_json.task_id 存在
task_id 可追到 agent_llm_requests
task_id 可追到 agent_llm_results
task_id 可追到 agent_llm_attempts
parse_status = succeeded
```

无法追溯的 LLM 产物不得进入 active build。

### 9. Data Quality Eval

新增真实 SQLite 产物级 eval，不接受只靠 mock 测试。必须至少覆盖：

```text
TOC/list-only segment 不得生成 generated_question
generated_question.title 不得包含 Q\d 前缀
generated_question 必须 answerable
generated_question/raw_text/entity_card 比例必须在阈值内
entity_card 不得来自 navigation-only segment
LLM task_id 必须可追溯
每个 generated_question 必须可回溯 source_segment_id
```

管理员指出的片段 `52bffeb308e54bff9e40b93fcf8c3e50` 必须成为 golden regression：生成问题数必须为 0。

## 测试缺口

- 当前测试未覆盖真实 SQLite 产物质量。
- 当前测试未覆盖 TOC-like/list-only/sparse-table 的 question-gen 禁止规则。
- 当前测试未覆盖 `Q1/Q2` 前缀污染。
- 当前测试未覆盖 retrieval unit ratio budget。
- 当前测试未覆盖 LLM provenance 端到端追溯。
- 当前 eval 不能发现不可回答问题和辅助 unit 过度膨胀。

## 回归风险

- 直接收缩 generated_question 和 entity_card 可能降低部分长尾召回，但这是必要 tradeoff。工业级系统优先保证证据可信和噪声可控，再通过 Serving hybrid retrieval / rerank 补召回。
- 如果不做 `references` 关系，目录片段的结构价值会被丢失；因此不能只是简单跳过目录，而要把它们转为图边。
- 如果只调 prompt，不加 deterministic gate 和 post-validation，下一批语料仍会复现同类污染。

## 建议修复项

本轮不再建议“分阶段试探”。Claude Mining 必须把下一版定义为：

```text
Mining Industrial Data Quality Baseline
```

完成标准不是“代码能跑”或“LLM 有调用记录”，而是重新生成 `data/kb-asset_core.sqlite` 后通过真实数据验收。

## 无法确认的残余风险

- 当前只审查了本轮生成的 8 篇云核心网样本文档，尚未覆盖更大规模语料。
- 当前未运行完整测试套件；本审查结论基于代码阅读、SQLite 真实数据查询和 LLM 调用记录审计。
- 当前未验证 Serving 在污染数据被修复后的召回变化；Serving 需要在 Mining 数据质量基线稳定后重新评估。

## 管理员介入影响

管理员已明确要求 Claude Mining 不得止步不前，必须直接按工业级可用做法改。Codex 本轮审查因此将交付口径从“分阶段路线”提升为“下一版一次性交付工业级数据质量基线”。

## 最终评估

当前 Mining 版本相比早期实现有进步：LLM Runtime 已真实接入，Domain Pack 已开始外置场景配置，LLM task provenance 已部分落库。但真实产物说明它仍不是工业级知识挖掘系统，而是一个缺少质量门的 LLM 批量加工 pipeline。

在下一版中，Claude Mining 必须证明：

```text
LLM 是受控增强器，不是无门槛生成器。
raw_text 是主证据资产，不被 generated_question/entity_card 压过。
Domain Pack 控制场景策略，而不是只控制实体枚举。
真实 SQLite 产物可被数据质量 eval 自动验收。
管理员指出的 TOC 片段污染问题不再出现。
```

未达到上述标准时，不应再声明 Mining 已满足工业级或可交付 Serving 使用。
