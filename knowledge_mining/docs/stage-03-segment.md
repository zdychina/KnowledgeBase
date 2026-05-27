# Stage 3 — Segment 文档分段

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Segment 阶段负责：
1. 遍历 Parse 阶段产出的 `SectionNode` 树
2. 将树中的 `ContentBlock` 按规则分组为 `RawSegmentData`（L0 原始分段）
3. 对过小的分段进行智能合并（intro paragraph + list/table 模式）
4. 计算每个分段的哈希、token 数、结构元信息

**关键特性**：
- 不涉及 LLM，纯 CPU 操作
- Heading 不作为独立分段，而是作为 `section_title` 传播到后续内容分段
- `semantic_role` 默认为 `"unknown"`，由后续 enrich 阶段赋值
- `entity_refs_json` 默认为空，由后续 enrich 阶段填充

---

## 2. 输入与输出

### 输入
| 参数 | 类型 | 说明 |
|------|------|------|
| `tree` | `SectionNode` | Parse 阶段产出的文档结构树 |
| `profile` | `DocumentProfile` | 文档配置信息（需 `document_key`） |

### 输出
```python
list[RawSegmentData]  # 挂载到 DocumentContext.segments
```

### RawSegmentData 核心字段 (models.py:261)
```
document_key: str              # 所属文档标识
segment_index: int             # 分段序号 (最终重编号)
block_type: str                # paragraph / table / list / code / blockquote / html_table / unknown
semantic_role: str             # 默认 "unknown", enrich 阶段赋值
section_path: list[dict]       # 章节路径 [{"title": "概述", "level": 1}, ...]
section_title: str | None      # 直接所属章节标题
raw_text: str                  # 分段原文
normalized_text: str           # raw_text.lower().strip()
content_hash: str              # SHA256(raw_text)
normalized_hash: str           # SHA256(normalized_text)
token_count: int | None        # CJK-aware token 估计
structure_json: dict           # 结构化元数据 (表格列/行, 列表项等)
source_offsets_json: dict      # 溯源信息 (parser, block_index, line_start, line_end)
entity_refs_json: list[dict]   # 实体引用 (enrich 阶段填充)
metadata_json: dict            # 扩展元数据
```

---

## 3. 分段策略

### 3.1 核心规则 (`_walk_sections`)

递归遍历 SectionNode 树，对每个节点的 blocks 按**类型**分组：

| block_type | 处理方式 |
|------------|----------|
| `heading` | **跳过**，不产生独立分段。标题文本作为 `section_title` 传播到后续分段 |
| `table` / `html_table` | **独立分段** — 先 flush 当前分组，再单独创建一个分段 |
| `list` | **独立分段** — 同上 |
| `code` | **独立分段** — 同上 |
| `blockquote` | **独立分段** — 同上 |
| `paragraph` | **累积到 current_group** — 连续的 paragraph 合并为一个分段 |
| 其他 | 累积到 current_group |

**分组逻辑伪代码**:
```
for block in node.blocks:
    if heading:
        flush current_group → segment
        # heading 不产生 segment
    elif structural block (table/list/code/blockquote):
        flush current_group → segment
        create single-block segment
    else:
        append to current_group

# 循环后 flush 剩余
if current_group: → segment

# 递归子节点
for child in node.children:
    _walk_sections(child, ...)
```

### 3.2 section_path 构建

```
root (title=None, level=0)
  → path = []
  → SectionNode(title="1 概述", level=1)
    → path = [{"title": "1 概述", "level": 1}]
    → SectionNode(title="1.1 功能介绍", level=2)
      → path = [{"title": "1 概述", "level": 1}, {"title": "1.1 功能介绍", "level": 2}]
```

- `section_title` 取**最近**的带标题节点的 title
- `section_path` 记录从根到当前节点的完整路径

### 3.3 段内多 paragraph 合并

连续的 paragraph block 合并到同一个 segment 中：
```python
raw_text = "\n\n".join(b.text for b in blocks)  # 双换行拼接
```

**block_type 决定**：取 blocks 中第一个非 heading 的 block_type。如果全都是 heading，取第一个。

---

## 4. 小分段合并 (`_merge_small_segments`)

**灵感来源**: Unstructured.io 的 CompositeElement 模式

**合并阈值**:

| 常量 | 值 | 含义 |
|------|-----|------|
| `_MERGE_MAX_TOKENS` | 512 | 合并后最大 token 数 |
| `_TABLE_MIN_INDEPENDENT_TOKENS` | 300 | 表格 > 此值保持独立 |
| `min_tokens` (参数) | 100 | 分段 < 此值被视为"小分段" |

### 4.1 两种合并模式

**模式 1: intro_merge (前向合并)**
```
条件:
  prev.block_type == "paragraph"
  AND prev.token_count < 100
  AND current.block_type in ("list", "table", "html_table")
  AND 合并后 <= 512 tokens
  AND (若 current 是 table, 则其 <= 300 tokens)

示例:
  segment[0]: "以下参数需要特别注意：" (paragraph, 30 tokens)
  segment[1]: [列表内容] (list, 80 tokens)
  → 合并为: "以下参数需要特别注意：\n\n[列表内容]" (110 tokens, block_type=list)
```

**模式 2: backward_merge (后向合并)**
```
条件:
  current.token_count < 100
  AND current 不是 table/html_table/code
  AND 合并后 <= 512 tokens
  AND prev 不是 table/html_table/code

示例:
  segment[0]: [较长段落] (paragraph, 200 tokens)
  segment[1]: "注：以上配置仅适用于 V5 版本。" (paragraph, 30 tokens)
  → 合并为一个 segment (230 tokens)
```

### 4.2 合并规则限制

- **只合并同 section_path 内的分段**
- **table/code 永远不向后合并** (不会把小段落追加到表格/代码块后面)
- **table > 300 tokens 永远不向前合并** (保持大表格独立)
- 合并后 block_type 取优先级高的: `table > list > code > blockquote/paragraph`

### 4.3 block_type 优先级
```python
_BLOCK_TYPE_PRIORITY = {
    "table": 4, "html_table": 4,
    "list": 3,
    "code": 2,
    "blockquote": 1, "paragraph": 1, "raw_html": 1,
    "unknown": 0,
}
```

### 4.4 合并后字段处理

| 字段 | 处理方式 |
|------|----------|
| `raw_text` | 双换行拼接 |
| `block_type` | 取优先级高的 |
| `semantic_role` | 取 prev 的 |
| `section_path/title` | 取 prev 的 |
| `structure_json` | 合并两个 dict (后者覆盖前者) |
| `source_offsets_json` | 取 prev 的 |
| `content_hash/normalized_hash/token_count` | 重新计算 |
| `segment_index` | 设为 0 (后续重编号) |

### 4.5 重编号

合并完成后，在 `segment_document()` 末尾重编号：
```python
for idx, s in enumerate(segments):
    RawSegmentData(..., segment_index=idx, ...)
```

---

## 5. 结构信息提取 (`_extract_structure_info`)

从 ContentBlock 列表中提取结构化元数据到 `structure_json`:

| block_type | structure_json 内容 |
|------------|---------------------|
| `table` | 有 structure → 直接用 (columns, rows, row_count, col_count); 无 → 按pipe分割估列数 |
| `html_table` | `{kind: "html_table", raw_html_preserved: true, row_count, col_count}` (按 `<tr`/`<td` 标签计数估计) |
| `code` | 有 structure → 用; 有 language → `{kind: "code_block", language}`; 否则 → 空 |
| `list` | 有 structure → 用; 无 → 按 `"; "` 分割估 items |
| `paragraph` | 递增 `paragraph_count` |

---

## 6. 配置参数

| 参数 | 来源 | 默认值 | 说明 |
|------|------|--------|------|
| `min_tokens` | `_merge_small_segments` 参数 | 100 | 低于此值的分段为合并候选 |
| `_MERGE_MAX_TOKENS` | 模块常量 | 512 | 合并后最大 token 数 |
| `_TABLE_MIN_INDEPENDENT_TOKENS` | 模块常量 | 300 | 大于此值的表格保持独立 |
| `parser_name` | kwargs | "unknown" | 记入 source_offsets_json |

**注意**：Segment 阶段**没有** domain.yaml 配置。所有阈值都是 Python 代码中的常量/参数。

---

## 7. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/stages/segment.py` | 339 | DefaultSegmenter + segment_document + 小段合并 |
| `mining/contracts/models.py:261` | — | `RawSegmentData` 数据类定义 |
| `mining/contracts/models.py:39` | — | `VALID_BLOCK_TYPES` 常量 |
| `mining/infra/hash_utils.py` | 42 | content_hash / normalized_hash |
| `mining/infra/text_utils.py` | 102 | token_count |
| `mining/pipeline.py` | — | segment_stage() 调用 DefaultSegmenter.segment() |

---

## 8. 工业化参考

| 参考 | 说明 |
|------|------|
| Unstructured.io `chunk_by_title()` | 我们的合并策略灵感来源，CompositeElement 模式 |
| LangChain `RecursiveCharacterTextSplitter` | 递归分割策略，但我们基于 block type 而非字符数 |
| LlamaIndex `SentenceSplitter` | 按句子边界分割，我们按 block type 边界 |
| Semantic Chunking (Greg Kamradt) | 基于 embedding 相似度的语义分割，我们暂未实现 |
| Azure Document Intelligence | 云端 layout-aware 分段，支持表格/列表/标题/段落 |

---

## 9. 当前不足

1. **合并阈值硬编码**: `_MERGE_MAX_TOKENS=512`, `min_tokens=100`, `_TABLE_MIN_INDEPENDENT_TOKENS=300` 都是模块常量，无法通过 domain.yaml 配置
2. **heading 信息丢失**: heading 不产生独立 segment，仅作为 section_title。如果 heading 后无内容，这个 heading 的信息完全丢失
3. **合并后 structure_json 可能冲突**: 两个不同 block 的 structure 字段合并时，后者覆盖前者 (如 paragraph_count 被丢失)
4. **section_path 存在冗余**: 每个分段都存了完整的 section_path 列表，大文档时内存占用高
5. **无语义感知**: 分段纯粹基于 block type 和 token 数，不考虑内容语义（如同一个表格跨页、相关段落被分开等）
6. **html_table 的 row/col 估计不准确**: 用 `<tr`/`<td` 标签计数，但 HTML 可能有嵌套表格、注释等干扰
6. **无段落级行号追踪**: 多 paragraph 合并后只记录了 min/max line_start/line_end，无法定位到具体段落
7. **_extract_structure_info 对 paragraph 的处理无意义**: 只累计 paragraph_count，但这个信息在后续阶段未被使用
8. **backward_merge 可能语义不当**: 纯按 token 数和 block type 决定合并，不关心内容是否相关
9. **segment_index 重编号效率**: 合并后遍历所有 segment 重建 RawSegmentData（frozen dataclass 不可变），实际上只是改了 segment_index 一个字段
10. **无最大分段数限制**: 一个大文档可能产生数百个分段，无上限保护
