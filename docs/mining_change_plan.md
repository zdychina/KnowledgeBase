# 知识挖掘 schema 修订设计稿

> 本文档记录 `knowledge_mining` 4 个 schema 设计问题的修订方案，按问题逐项推进。
> 范围：`asset_core` 三张表 + 相关 enum 集合。
> 状态：进行中。

## 问题清单

| # | 表 / 字段 | 问题摘要 | 状态 |
|---|---|---|---|
| 1 | `asset_raw_segments.semantic_role` | enum 分类不全；缺 LLM 兜底；source/confidence 字段缺失 | **设计已定** |
| 2 | `asset_raw_segment_relations.relation_type` | 结构/修辞混在一起；RST 标签不全；写入 bug | **本轮——RST 10 类已定，落库方式 TBD** |
| 3 | `asset_retrieval_units.unit_type` | 只有 segment 级单元，缺 document/section 级 | 未启动 |
| 4 | `asset_documents.document_type` | enum 混淆体裁与语义；`document_type` 实际始终 NULL | 未启动 |

---

## 问题 1：`semantic_role` 修订

### 设计 intent

段落级语义意图标签，回答"这段在说什么"。与 `block_type`（结构形态）、`heading_role`（章节层级）、`document_type`（文档体裁）正交。下游用于：检索按问题类型过滤/加权、上下文装配按角色分块、答案合成按角色补足（如 procedure 答案必带 constraint）、retrieval_units 路由（哪些 segment 适合做 entity_card / generated_question）。

### 11 类 enum

| role | 含义 | 来源 |
| :--- | :--- | :--- |
| `overview` | 章节总览、简介、组网简介 | 新增 |
| `concept` | 概念定义、术语解释 | 已有 |
| `scenario` | 适用场景、应用场景 | 新增 |
| `prerequisite` | 前提条件、操作前提 | 新增 |
| `procedure_step` | 编号步骤、操作流程 | 已有 |
| `parameter` | 参数定义 | 已有 |
| `example` | 配置示例、命令示例 | 已有 |
| `constraint` | 限制、约束、不支持项 | 已有 |
| `recommendation` | 推荐做法、最佳实践 | 新增 |
| `alarm` | 警告、注意 | 新增（原 enum 已有） |
| `unknown` | LLM 也判不出 | 已有 |

> 弃用：`note` / `troubleshooting_step` / `checklist`。SMB 部署语料密度低，语义可被上面 11 类覆盖；后续若部署排障类语料引入再单独评审。

### 三段式判定流程

```
Stage 1: rule       _ROLE_RULES 命中           → role_source = 'rule'
Stage 2: LLM        规则未命中 → LlmEnricher    → role_source = 'llm:<model>'
Stage 3: unknown    LLM 非法值 / 低置信        → role = 'unknown', role_source = 'fallback'
```

### Schema 字段补充

| 字段 | 类型 | 用途 |
| :--- | :--- | :--- |
| `semantic_role` | enum (11 类) | 已存在，扩 enum |
| `role_source` | TEXT | `'rule'` / `'llm:<model>'` / `'fallback'` |
| `role_confidence` | REAL | LLM 置信度；rule 来源恒为 1.0 |

---

## 问题 2：`asset_raw_segment_relations` 修订

### 设计 intent

把 segment 间关系拆成两类：

- **结构关系 (structural)**：由 parser/segmenter 直接派生，确定性，零 LLM 成本。
  例：`previous` / `next` / `same_section` / `same_parent_section` / `section_header_of`。
- **修辞关系 (rhetorical / RST)**：由 LLM 基于段落语义推断，需 source / confidence / model 字段。

下游用途：
- 检索阶段沿 RST 边做"上下文扩展"（procedure_step 沿 constraint 边召回约束段、沿 prerequisite 边召回前置段）
- contextual_text 单元生成时确定哪些段落进窗口
- 答案合成时按修辞结构组织（结论 + 证据 + 约束）

### RST 标签集（10 类）

参考另一项目 `src/utils/llm_extract.py:64 RST_RELATION_TYPES`，按语义分组：

| 分组 | RST 类 | 方向 | 含义 | 典型 from → to role | SMB 密度 | 优先级 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **语义展开** | `elaboration` | NS | B 对 A 补充细节/子主题 | overview / concept → 任意 | 极高 | P0 |
|              | `exemplification` | NS | B 给出 A 的具体示例 | concept / parameter → example | 高 | P0 |
| **逻辑结构** | `sequence` | NN | B 在时间/步骤上紧接 A | procedure_step → procedure_step | 高 | P0 |
|              | `causation` | NS | A 导致 B / B 解释 A | constraint / 操作 → 后果 | 中 | P1 |
|              | `contrast` | NN | B 与 A 对立 / 替代方案 | 任意 ↔ 任意 | 中 | P1 |
| **规范约束** | `constraint` | NS | B 对 A 施加 MUST/SHALL 规则 | constraint → procedure_step / feature | 高 | P0 |
|              | `condition` | SN | A 是条件，B 是被条件化内容 | 条件分支 → 配置内容 | 中 | P1 |
|              | `prerequisite` | SN | A 必须先完成/理解才能应用 B | prerequisite → procedure_step | 中高 | P0 |
| **支撑上下文** | `evidence` | NS | B 提供 RFC / 规范 / 数据支撑 A | 任意 → reference | 低 | P2 |
|              | `background` | SN | A 提供 B 所需的背景 / 动机 | overview / scenario → 后续章节 | 中 | P1 |

> **方向语义**：N=Nucleus（核），S=Satellite（卫星）。
> - NS：B 是 A 的卫星（A 是核心）
> - SN：A 是 B 的卫星（B 是核心）
> - NN：平等多核
> 写入约定：`from_segment_id = A`，`to_segment_id = B`。
>
> **命名规范**：schema enum 用蛇形小写（`elaboration`），LLM prompt 用首字母大写（`Elaboration`），中间走映射表。**禁止 `.lower()` 直写库**——这是当前 `DiscourseRelationBuilder._parse_llm_results` 的 P0 写入 bug 根因。

### 与 `semantic_role` 的协同（候选剪枝）

RST 候选生成阶段，用 role 对 segment 对做先验过滤，提升 LLM 精度并降低成本：

| RST 类 | from 端典型 role | to 端典型 role |
| :--- | :--- | :--- |
| `elaboration` | overview / concept | 任意 |
| `exemplification` | concept / parameter | example |
| `constraint` | constraint | procedure_step / feature |
| `prerequisite` | prerequisite | procedure_step |
| `sequence` | procedure_step | procedure_step |
| `causation` | constraint / procedure_step | 任意 |
| `condition` | scenario / overview | procedure_step / parameter |
| `background` | overview / scenario | 后续章节首段 |

### 待定项（本节 TBD）

- **落库方式 A / B / C**：
  - A：原表上扩 enum + 补字段（`relation_kind` / `source` / `confidence` / `nucleus_side`）
  - B：拆两表：`asset_raw_segment_structural_relations` + `asset_raw_segment_rhetorical_relations`
  - C：单表 + `relation_kind ('structural'|'rhetorical')` 分区，修辞行才填 source/confidence/nucleus_side
  - **当前倾向**：C（最小改动、语义清晰）
- **方向字段**：是否引入 `nucleus_side ('NS'|'NN'|'SN')` 列？
- **写入 bug 修复**：`DiscourseRelationBuilder._parse_llm_results` 改为映射表查询 → P0 必修
- **prompt 标签集与 schema enum 严格对齐**：当前 prompt 用 EVIDENCES/CAUSES/... 与 schema 完全错位，要重写

---

## 问题 3：`asset_retrieval_units` 修订

### 设计 intent

retrieval_units 是 segment 之上的"检索就绪单元"，按检索范式分门别类生成。当前共 6 种 unit_type 全部对每个 segment 默认开造，成本高且若干种实际贡献小。本轮**只保留 3 种片段级单元**作为 P0，其余搁置（schema enum 保留，builder 关闭或删除）。

### 当前 6 种 unit 的盘点

| unit_type | 颗粒 | 来源 | 现 weight | 决策 |
| :--- | :--- | :--- | :--- | :--- |
| `raw_text` | 片段级 1:1 | 规则 | 1.0 | **保留 P0** |
| `contextual_text`（规则版） | 片段级 1:1 | 规则拼接 | 0.6 | **删除**（与 LLM 版冲突） |
| `contextual_text`（LLM 版） | 片段级 1:1 | LLM Anthropic-style | 0.9 | **保留 P0** |
| `generated_question` | 片段级 1:N | LLM | 0.7 | **保留 P0** |
| `entity_card` | 实体级（跨段去重） | 规则 + entity_refs | 0.5 | 搁置（feature flag 关） |
| `table_row` | 子片段级（表行） | 规则 | 0.8 | 搁置（feature flag 关） |
| `summary`（schema 有 enum 无 builder） | — | — | — | dead，保留 enum 占位 |

### 本轮保留的 3 种片段级单元

| 优先级 | unit_type | 检索范式 | 决策依据 |
| :--- | :--- | :--- | :--- |
| **P0** | `raw_text` | 语义/关键词 baseline | 无替代；删了无法 baseline 召回 |
| **P0** | `contextual_text`（LLM） | Anthropic Contextual Retrieval | 公开数据召回错误率降 35~49%，ROI 最高 |
| **P0** | `generated_question` | 问题→文档反向匹配 | SMB 语料用户问句与文档措辞错位严重（"怎么开机" vs "上电流程"），必备 |

### 现状隐患（本轮一并修）

1. **`contextual_text` 一个 enum 装两类对象**：规则版与 LLM 版共用 `unit_type="contextual_text"`（[retrieval_units/__init__.py:328](knowledge_mining/mining/retrieval_units/__init__.py:328) 与 [:626](knowledge_mining/mining/retrieval_units/__init__.py:626)），下游无法区分排序。修法：删规则版代码路径，LLM 版独占 `contextual_text`。
2. **规则版 `_build_paragraph_contextual`** 在 section title 已含于 raw_text 时返回空串（[:530](knowledge_mining/mining/retrieval_units/__init__.py:530)），SMB 语料下出货极少。
3. **每段默认造 6 类 unit**，成本高且向量库膨胀。本轮收敛到 3 类。
4. **`summary` enum 是 dead code**，schema 保留 enum 占位（避免 migration），builder 不实现。

### 搁置项的处理方式

- **`entity_card`** / **`table_row`**：保留代码但加 `enable_entity_cards` / `enable_table_rows` feature flag，**默认 False**。二期 `entity_refs` 抽取稳定 / 表格 schema 解析修复后再开启。
- **`contextual_text` 规则版**：直接删除 [:310-351](knowledge_mining/mining/retrieval_units/__init__.py:310) 与 [:469-542](knowledge_mining/mining/retrieval_units/__init__.py:469) 路径。
- **`summary`**：schema enum 保留，不实现 builder。

### 命名/键统一

- LLM 版 contextual unit 的 `unit_key` 后缀**统一为 `:contextual_text`**（当前是 `:contextual_enhanced`，[:629](knowledge_mining/mining/retrieval_units/__init__.py:629)），消除别名。
- 删除 `_make_contextual_enhanced_unit` 函数名，并入 `_make_contextual_text_unit`（LLM 版）。

### 待定项（本节 TBD）

- **是否暴露 builder 的 feature flag 到 `BatchParams`**？还是写死在 builder 默认参数？
- **`contextual_text` LLM 版失败时是否回退到一个轻量规则版**作为兜底？还是失败就不出 contextual unit？
- 二期 `entity_card` / `table_row` 启用时，是否需要 schema 改动（如加 `parent_unit_id`）？

---



## 问题 4：`asset_documents.document_type` —— 待启动
