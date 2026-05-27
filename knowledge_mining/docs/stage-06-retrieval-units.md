# Stage 6 — Retrieval Units 检索单元构建

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Retrieval Units 阶段负责：
1. 为每个 Segment 构建多种类型的检索单元 (RetrievalUnitData)
2. 批量调用 LLM 生成问题 (generated_question)
3. 批量调用 LLM 生成上下文描述 (contextual_retrieval)
4. 为强类型实体生成实体卡片 (entity_card)
5. 为表格生成行级检索单元 (table_row)
6. 为每个 segment 生成增强的全文搜索文本 (search_text)

**关键特性**：
- LLM 调用阶段（I/O 密集），StreamingPipeline 多 worker 并发
- 包含两个子组件：`LlmQuestionGenerator` 和 `LLMContextualizer`
- 使用批量提交 + 轮询模式最大化 LLM 吞吐

---

## 2. 输入与输出

### 输入
| 参数 | 类型 | 说明 |
|------|------|------|
| `segments` | `list[RawSegmentData]` | enrich 阶段产出 |
| `seg_ids` | `dict[str, str]` | segment UUID 映射 |
| `question_generator` | `QuestionGenerator` | LLM 问题生成器 |
| `contextualizer` | `Contextualizer` | LLM 上下文生成器 |
| `profile` | `DomainProfile` | 领域配置 |

### 输出
```python
list[RetrievalUnitData]  # 挂载到 DocumentContext.retrieval_units
```

### RetrievalUnitData 核心字段 (models.py:303)
```
segment_key: str              # 所属 segment 的 key (doc_key#index)
unit_key: str                 # 单元唯一标识 (ru:doc_key#index:type)
unit_type: str                # raw_text / generated_question / entity_card / table_row
target_type: str              # raw_segment / entity
target_ref_json: dict         # 引用定位
title: str | None             # 标题
text: str                     # 文本内容
search_text: str              # 全文搜索文本 (jieba tokenized)
block_type: str               # 继承自 segment
semantic_role: str            # 继承自 segment
facets_json: dict             # 过滤面 {block_type, semantic_role, section_depth}
entity_refs_json: list[dict]  # 继承自 segment
source_refs_json: dict        # 溯源信息 {document_key, segment_index, offsets}
llm_result_refs_json: dict    # LLM 溯源 {source, task_id}
source_segment_id: str        # segment UUID
weight: float                 # 检索权重
metadata_json: dict           # 扩展元数据
```

---

## 3. 四种检索单元类型

### 3.1 raw_text (主要单元, weight=1.0)

**生成规则**: 每个 segment 必然生成一个 raw_text 单元。

**search_text 构成** (Anthropic Contextual Retrieval 模式):
```
Section Path 上下文 (不在原文中的章节标题)
  ↓
LLM 生成的上下文描述 (如果 contextualizer 可用)
  ↓
原始 raw_text
```

示例:
```
"SMF 配置指南 > 参数说明"        ← section path
"本段描述 SMF 设备的关键配置参数" ← LLM context
"SMF 支持以下关键参数..."        ← 原始文本
```

**tokenize_for_search**: 使用 jieba (CJK) 分词后拼接，供 FTS5 全文检索。

**unit_key**: `ru:{doc_key}#{seg_index}:raw_text`

### 3.2 entity_card (实体卡片, weight=0.5)

**生成规则**:
- 只有 `profile.strong_entity_types` 中的实体类型才生成
- 每个 (entity_type, entity_name) 只生成一次 (全局去重 via `seen_entity_cards`)
- 导航性 segment 不生成 (`is_navigation=True` 时跳过)
- 每个 segment 最多 `max_entity_cards_per_segment` 张卡片 (默认 3)

**text 构成**:
```
"{entity_name}（{entity_type}）{上下文摘要}"
或
"{entity_name}（{entity_type}） — 见 {section_title}"
```

**上下文提取** (`_extract_entity_context`): 在 raw_text 中找到实体名，取前后各 40 字符的窗口。

**unit_key**: `ru:entity:{entity_type}:{entity_name}`

### 3.3 generated_question (生成问题, weight=0.7)

**生成规则**:
- 只为"值得提问"的 segment 生成 (`_is_questionworthy`)
- 每个 segment 最多 `max_questions_per_segment` 个问题 (默认 2)
- 问题经过 `_prune_invalid_questions` 验证

**text 构成**:
```
"{question}
---
来源: {section_title}
{raw_text[:200]}"
```

**unit_key**: `ru:{doc_key}#{seg_index}:gen_q_{question_index}`

### 3.4 table_row (表格行, weight=0.8)

**生成规则**:
- 只为 `block_type="table"` 且有 columns/rows 结构的 segment 生成
- 每行一个检索单元

**text 构成**:
```
"{列名}为{值}，{列名}为{值}。"
```

示例: "参数名为timeout，默认值为30，说明为超时时间。"

**unit_key**: `ru:{doc_key}#{seg_index}:table_row_{row_index}`

---

## 4. 批量 LLM 调用流程

### 4.1 Phase 1: Question Generation

```
1. 过滤 questionworthy segments:
   - block_type != "heading"
   - token_count >= min_questionworthy_tokens (默认 50)
   - raw_text.strip() >= 15 chars
   - is_substantive != False (enrich 的 content_assessment)
   - semantic_role not in not_questionworthy_roles

2. LlmQuestionGenerator.generate_batch(questionworthy):
   Phase 1: Submit all
     template_key = "mining-question-gen"
     input = {title, content}
     → seg_tasks: {seg_key: task_id}

   Phase 2: Poll all
     poll_all(seg_tasks) → raw_results

   Phase 3: Parse
     item["question"] → questions list

3. _prune_invalid_questions():
   - strip 空白
   - 长度 >= 5
   - 去除 "Q1: " 前缀
```

### 4.2 Phase 1b: Context Generation

```
1. document_text = "\n".join(all raw_text)
2. 过滤非空 segment
3. LLMContextualizer.contextualize(segments, document_text):
   - 每个非 heading 且 > 15 chars 的 segment:
     template_key = "mining-contextual-retrieval"
     input = {document: doc_preview[:2000], segment: seg.text[:500]}
   - poll_all → {seg_key: context_description}
```

### 4.3 Phase 2: Build Units

```
for seg in segments:
  1. raw_text unit (必有)
  2. entity_card units (条件: strong_types + 非导航)
  3. table_row units (条件: table block + 有 structure)
  4. generated_question units (条件: question_map 有结果)
```

---

## 5. 配置参数

### 5.1 RetrievalPolicy 参数 (domain.yaml)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_questions_per_segment` | 2 | 每 segment 最多生成问题数 |
| `max_entity_cards_per_segment` | 3 | 每 segment 最多实体卡片数 |
| `contextual_retrieval` | "on" | 是否启用上下文检索 |
| `raw_text` | "primary" | raw_text 单元策略 |
| `generated_question` | "auxiliary" | 问题生成策略 |
| `entity_card` | "strong_entities_only" | 实体卡片策略 |
| `table_row` | "structured_tables" | 表格行策略 |
| `min_questionworthy_tokens` | 50 | 问题生成的最小 token 数 |
| `not_questionworthy_roles` | {navigation, toc, metadata} | 不生成问题的角色 |

### 5.2 LlmClient 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `base_url` | "http://localhost:8900" | LLM Service 地址 |
| `timeout` | 120 | 单任务超时 |

---

## 6. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/stages/retrieval_units/__init__.py` | 603 | LlmQuestionGenerator, LLMContextualizer, build_retrieval_units |
| `mining/infra/llm_client.py` | 292 | LlmClient |
| `mining/infra/text_utils.py` | tokenize_for_search |
| `mining/infra/domain_pack.py` | RetrievalPolicy, DomainProfile |
| `mining/contracts/models.py:303` | — | RetrievalUnitData 数据类 |
| `mining/contracts/protocols.py` | — | QuestionGenerator, Contextualizer 协议 |
| `mining/pipeline.py` | — | retrieval_units_stage() |

---

## 7. 工业化参考

| 参考 | 说明 |
|------|------|
| Anthropic Contextual Retrieval | 在 chunk 前加 LLM 生成的上下文，提升检索精度 |
| LlamaIndex SchemaLLMPathExtractor | 用 schema 约束 LLM 输出，我们用 json_array |
| GraphRAG (Microsoft) | 社区摘要作为检索单元，我们有 entity_card |
| RAPTOR (Recursive Abstractive Processing) | 多粒度摘要，我们有 raw_text + question 两级 |
| LlamaIndex `SentenceWindowNodeParser` | 窗口上下文，我们的 contextualizer 类似 |
| Haystack `QuestionGenerator` | 专门的问题生成组件 |

---

## 8. 当前不足

1. **contextualizer 传入整个文档**: `document_text[:2000]` 截断到前 2000 字符，大文档后面的 segment 只看到文档开头，上下文不准确
2. **entity_card 全局去重**: 同名实体在多个 segment 出现时只在第一次生成卡片，后续出现位置的信息被丢弃
3. **table_row 只支持 markdown table**: `structure_json` 中必须有 columns/rows，html_table block 不生成 table_row units
4. **问题去重缺失**: 不同 segment 可能生成相似或相同的问题，无全局去重
5. **`_is_questionworthy` 检查 `is_substantive` 但 enrich 可能没跑**: 如果 enrich stage 失败/跳过，`content_assessment` 不存在，`assessment.get("is_substantive", True)` 默认 True，不安全
6. **LLM 调用量大**: 每个 segment 两次 LLM 调用 (question + context)，加上 enrich 的一次，每文档 N 个 segment = 3N 次 LLM 调用
7. **poll_all 无超时**: 与 enrich 相同的问题，question/context 轮询可能无限阻塞
8. **_prune_invalid_questions 过于简单**: 只检查长度和 Qn 前缀，不检查是否真的是问题（如 "?" 结尾）
9. **weight 硬编码**: raw_text=1.0, entity_card=0.5, question=0.7, table_row=0.8，不可配置
10. **search_text 拼接逻辑**: section path + LLM context + raw_text 直接拼接到 search_text，但 FTS5 搜索时这些内容的权重相同，可能导致 section title 匹配优先于内容匹配
11. **entity_card text 格式硬编码**: `"{name}（{type}）"` 中文括号硬编码，不适合多语言
12. **_extract_entity_context 简单字符串查找**: 用 `raw_text.find(name)` 做精确匹配，如果实体名是子串（如 "SMF" 在 "SMF-config" 中）会取错上下文
