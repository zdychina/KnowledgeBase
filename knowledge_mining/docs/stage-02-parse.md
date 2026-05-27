# Stage 2 — Parse 文档解析

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Parse 阶段负责：
1. 根据 `file_type` 分发到对应的 Parser 实现
2. 将原始文本解析为结构化的 `SectionNode` 树
3. 识别文档的标题层级 (heading)、段落 (paragraph)、表格 (table)、列表 (list)、代码块 (code)、引用 (blockquote) 等结构
4. 保留每个内容块的行号信息 (`line_start` / `line_end`) 用于溯源

**关键特性**：此阶段不涉及 LLM，纯 CPU 操作。解析结果是后续 segment 和 enrich 阶段的基础。

---

## 2. 输入与输出

### 输入
| 参数 | 类型 | 说明 |
|------|------|------|
| `raw_file.content` | `str` | Ingest 阶段产出的文件文本内容 |
| `raw_file.file_type` | `str` | 文件类型: markdown / txt / pdf / html / doc / docx 等 |
| `raw_file.file_name` | `str` | 文件名 |
| `raw_file.file_path` | `str` | 文件绝对路径 (PdfParser 需要) |

### 输出
```python
SectionNode | None  # 挂载到 DocumentContext.tree
```

### 分发逻辑 (`create_parser`)
```
file_type == "markdown"  → MarkdownParser    (结构化解析)
file_type == "txt"       → PlainTextParser   (段落分块)
file_type == "pdf"       → PdfParser         (布局感知解析)
其他                     → PassthroughParser  (返回 None)
```

**注意**：HTML 类型没有专门的 Parser，会走 PassthroughParser 返回 None。HTML 文件在 Ingest 阶段也未做预处理，这意味着 HTML 文件目前完全无法被 pipeline 处理。

---

## 3. 核心数据结构

### 3.1 ContentBlock (models.py:218)

```python
@dataclass(frozen=True)
class ContentBlock:
    block_type: str    # paragraph, heading, table, list, code, blockquote, html_table, raw_html, unknown
    text: str          # 块文本内容
    language: str | None = None        # code 块的语言标识
    level: int | None = None           # heading 的层级 (1-6)
    line_start: int | None = None      # 0-based 起始行号
    line_end: int | None = None        # 0-based 结束行号
    structure: dict[str, Any] | None = None  # 结构化内容 (表格的 columns/rows, 列表的 items 等)
```

**block_type 类型说明**:

| block_type | 来源 Parser | structure 内容 |
|------------|------------|----------------|
| `heading` | Markdown / PDF | `None` (level 在字段中) |
| `paragraph` | 所有 | `None` |
| `table` | Markdown (pipe table) | `{kind: "markdown_table", columns, rows, row_count, col_count}` |
| `html_table` | Markdown (HTML 块中 `<table>`) | `{kind: "html_table", columns, rows, row_count, col_count}` |
| `list` | Markdown (bullet/ordered) | `{kind: "list", ordered, items, items_nested, item_count}` |
| `code` | Markdown (fence / code_block) | `None` (language 在字段中) |
| `blockquote` | Markdown | `None` |
| `raw_html` | Markdown (非 table 的 HTML 块) | `None` |

### 3.2 SectionNode (models.py:231)

```python
@dataclass(frozen=True)
class SectionNode:
    title: str | None                          # 章节标题
    level: int                                 # 层级 (0=root, 1-6=heading)
    children: tuple[SectionNode, ...] = ()     # 子章节
    blocks: tuple[ContentBlock, ...] = ()      # 直接内容块 (不含子章节的内容)
```

**树结构示例**:
```
SectionNode(title="SMF 配置指南", level=0)       ← root
├── blocks: (ContentBlock[paragraph], ...)       ← 标题前的段落
├── children:
│   ├── SectionNode(title="1 概述", level=1)
│   │   ├── blocks: (ContentBlock[paragraph], ContentBlock[table])
│   │   └── children:
│   │       ├── SectionNode(title="1.1 功能介绍", level=2)
│   │       │   └── blocks: (ContentBlock[paragraph])
│   │       └── SectionNode(title="1.2 参数说明", level=2)
│   │           └── blocks: (ContentBlock[table])
│   └── SectionNode(title="2 配置步骤", level=1)
│       └── blocks: (ContentBlock[list], ContentBlock[code])
```

**设计要点**：
- 子章节的内容在子 SectionNode 的 blocks 中，不在父节点的 blocks 中
- 父节点的 blocks 只包含"标题后、第一个子标题前"的直接内容块
- `level=0` 是虚拟根节点，可能无 title

---

## 4. 四种 Parser 实现

### 4.1 MarkdownParser (parse.py:49-57)

**职责**：将 Markdown 文本解析为 SectionNode 树。

**调用链**：
```
MarkdownParser.parse(content, file_name, context)
  → structure.parse_structure(content)
    → MarkdownIt().enable("table").parse(content)  # markdown-it-py 生成 token 流
    → _tokens_to_blocks(tokens)                    # token → ContentBlock 列表
    → _build_section_tree(blocks)                  # flat blocks → tree
```

**Markdown 解析细节** (`structure/__init__.py`, 427 行):

#### 4.1.1 Token → ContentBlock 转换 (`_tokens_to_blocks`)

遍历 markdown-it-py 的 token 流，逐类型转换：

| markdown-it token | → ContentBlock type | 处理逻辑 |
|-------------------|---------------------|----------|
| `heading_open` + `inline` + `heading_close` | `heading` | 提取 level (从 tag `h1`-`h6`), text (inline content), line_start/end |
| `table_open` ... `table_close` | `table` | 调用 `_parse_table()` 提取 columns/rows 到 structure |
| `fence` / `code_block` | `code` | text=代码内容, language=fence info |
| `bullet_list_open` / `ordered_list_open` | `list` | 收集嵌套 list item, structure 存 items + items_nested |
| `blockquote_open` ... `blockquote_close` | `blockquote` | 拼接所有 inline text |
| `html_block` (含 `<table`) | `html_table` | 调用 `_parse_html_table()` 用 HTMLParser 提取 columns/rows |
| `html_block` (其他) | `raw_html` | 直接存原始 HTML |
| `paragraph_open` + `inline` | `paragraph` | 从 pending_paragraph_map 获取行号 |

**列表嵌套处理**：
- 维护 `depth` 计数器跟踪嵌套层级
- `items_nested` 存储每个 item 的 `{text, depth}`
- `items` 只存 depth=1 的项
- `_format_nested_items()` 格式化为缩进文本：`  - 子项`, `1. 有序项`

**表格解析** (`_parse_table`):
- 遍历 thead/tr/th 和 tbody/tr/td 的 token 序列
- 第一行 (`thead`) → `columns`
- 后续行 → `rows` (list[dict[str, str]])
- `text` 字段生成可读的 pipe 分隔格式

**HTML 表格解析** (`_HtmlTableParser` + `_parse_html_table`):
- 使用 stdlib `html.parser.HTMLParser`
- 处理 `<thead>/<th>` → columns, `<tr>/<td>` → rows
- 结果格式与 markdown table 相同

#### 4.1.2 Block 列表 → SectionNode 树 (`_build_section_tree`)

```
输入: [block(paragraph), block(heading,H1), block(paragraph), block(heading,H2), block(table), ...]

处理:
1. 找到所有 heading block 的索引
2. 找到最小 heading level (= 顶层 section 划分点)
3. 标题前的 block → root.pre_blocks
4. 按 min_level 切分 top_sections
5. 每个 top_section → _build_nested_section() 递归构建子树
```

**`_build_nested_section` 递归逻辑**:
```
输入: [heading(H1), paragraph, paragraph, heading(H2), table, heading(H2), list]

1. heading = blocks[0]  → 本节标题
2. content_blocks = blocks[1:]  → 本节内容
3. 找 content_blocks 中 level > heading_level 的 sub-heading
4. 有 sub-heading → _split_sub_sections() 切分
   - level <= parent 的 heading 跳过
   - level <= current_group_level → 新建 section
   - level > current_group_level → 归入当前 section
5. 无 sub-heading → blocks 全部是本节直接内容

输出:
SectionNode(title="H1标题", level=1)
├── blocks: (paragraph, paragraph)
└── children:
    ├── SectionNode(title="H2标题", level=2, blocks: (table,))
    └── SectionNode(title="H2标题", level=2, blocks: (list,))
```

**单节提升优化**：如果只有一个顶层 section 且它有标题，直接提升为 root（合并 pre_blocks）。

### 4.2 PlainTextParser (parse.py:60-93)

**职责**：将纯文本按段落分块，长段落按 token 边界切分。

**参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `chunk_size` | 300 | 最大 token 数，超过则切分 |
| `chunk_overlap` | 30 | 切分时重叠 token 数 |

**处理流程**:
```
PlainTextParser.parse(content, file_name, context)
  → _split_paragraphs(content)     # 按空行分割段落
  → 对每个段落:
     if token_count <= chunk_size:
       → ContentBlock(paragraph)
     else:
       → _split_long_text(text, chunk_size, chunk_overlap)  # 按 token 边界切
       → 每个 chunk → ContentBlock(paragraph)
  → SectionNode(title=file_name, level=0, blocks=...)
```

**段落分割** (`_split_paragraphs`):
- 按空行 (`line.strip() == ""`) 分割
- 记录每个段落的 `(text, line_start, line_end)`

**Token 边界检测** (`_find_token_boundaries`):
- CJK 字符 (U+4E00-U+9FFF)：每个字符是一个边界
- 连续的 ASCII 字母数字：起始位置是边界
- 其他字符：断开连续序列
- 作用：确保切分不会在单词中间断裂

**长文本切分** (`_split_long_text`):
```
例: chunk_size=300, chunk_overlap=30
- 总 token 数 > 300 → 需要切分
- chunk 1: token[0:300]
- chunk 2: token[270:570]  (step = 300-30 = 270)
- chunk 3: token[540:840]
- ...
```

**Token 计数** (`text_utils.token_count`):
- CJK 字符按 1.5x 计 (LLM tokenizer 通常 1 CJK = 1-2 tokens)
- ASCII 单词按 1x 计
- 这是一个实用估计值，不是精确的 tokenizer 计算

### 4.3 PdfParser (parse.py:105-119)

**职责**：使用 pdfminer.six 的布局 API 从 PDF 中提取结构化内容。

**调用链**:
```
PdfParser.parse(content, file_name, context)
  → pdf_parser.parse_pdf_to_section_tree(file_path, doc_title)
    → _extract_blocks(pdf_path)               # 每页 → _PdfBlock 列表
    → _drop_repeated_headers_footers(blocks)   # 去除页眉页脚
    → _classify_blocks(blocks)                 # → ContentBlock 列表
    → _build_section_tree(content_blocks, doc_title)  # → SectionNode 树
```

**注意**：PdfParser 不使用传入的 `content` 参数（Ingest 阶段已用 pdfminer 提取的纯文本），而是重新从文件路径解析。传入的 `content` 被忽略。

#### 4.3.1 PDF 块提取 (`_extract_blocks`, pdf_parser.py:57-89)

```python
@dataclass(frozen=True)
class _PdfBlock:
    page_no: int
    text: str
    font_size: float     # 中位数字号
    x0: float            # 左边界
    y0: float            # 下边界
    page_height: float   # 页面高度
```

- 使用 `pdfminer.high_level.extract_pages()` 逐页遍历
- 每个 `LTTextContainer` → 一个 `_PdfBlock`
- 字号取该块所有 `LTChar` 的中位数 (`sizes[len(sizes)//2]`)
- 忽略无字符的容器

#### 4.3.2 页眉页脚去除 (`_drop_repeated_headers_footers`)

**策略**：基于重复文本 + 位置检测

```
1. 页数 < 3 → 不处理 (样本不足)
2. 将每个 block 的文本归一化 (数字→N) 后计数
3. 出现次数 >= max(3, 页数/2) 的文本 → 可能是页眉/页脚
4. 位置判断:
   - near_top: 距页面顶部 < 15% 页面高度
   - near_bottom: 距页面底部 < 12% 页面高度
   - near_top 或 near_bottom 且文本重复 → 丢弃
5. 重复但不在页面边缘 → 保留 (可能是正文重复段落)
```

**数字归一化** (`_normalize_for_recurrence`): `\d+` → `N`，使 "第 3 页 / 共 35 页" 和 "第 12 页 / 共 35 页" 匹配。

#### 4.3.3 块分类 (`_classify_blocks`)

**字号分析**:
- 统计所有 block 的字号频率
- 取最常见字号作为 `body_size` (正文字号)

**分类规则** (按优先级):

1. **目录行跳过**: 行尾含 `....数字` (`TOC_DOT_LEADER_RE`) → 跳过

2. **Heading 检测**:
   - 首行匹配 `1.1.1 TITLE` 格式 (`HEADING_RE`: `^\d+(\.\d+){0,4}\s+\S.{0,200}$`)
   - AND 非目录行 (标题不含 `....`)
   - AND 行长度 <= 200 且块总长 <= 400
   - AND 字号 >= body_size - 0.1
   - AND level 1-6
   - → `heading` block, level = 点号数 + 1
   - 首行后剩余文本 → `paragraph` block

3. **表格检测**:
   - 首行匹配 `Tabelle/Table/Abbildung/Figure/Bild N` (`TABLE_CAPTION_RE`)
   - → `table` block (整块文本)

4. **默认**: → `paragraph` block

**HEADING_RE**: `^(\d+(?:\.\d+){0,4})[\u00a0\s]+(\S.{0,200})$`
- 支持 1-5 级编号: `1`, `1.1`, `1.1.1`, `1.1.1.1`, `1.1.1.1.1`
- 编号后用不间断空格或普通空格分隔
- 标题首字符非空白，总长 <= 200

**TABLE_CAPTION_RE**: `^(Tabelle|Table|Abbildung|Figure|Bild)\s+\d+(?:\.\d+)?\b`
- 支持德语 + 英语的表格/图片标题
- 这种 block 只标记为 table type，但 structure 为 None (无 columns/rows 提取)

#### 4.3.4 PDF Section 树构建 (`_build_section_tree`)

与 Markdown 的 `_build_section_tree` 类似但更简单:

```python
# Stack-based builder
root = _mutable_node(title=doc_title, level=0)
stack = [root]

for block in blocks:
    if heading:
        # pop 到合适的祖先层级
        while stack[-1].level >= block.level:
            stack.pop()
        # 新节点挂到当前父节点下
        new_node = _mutable_node(title=block.text, level=block.level)
        stack[-1].children.append(new_node)
        stack.append(new_node)
    else:
        # 非标题 block 挂到当前节点的 blocks
        stack[-1].blocks.append(block)

return _freeze(root)  # dict → frozen SectionNode
```

### 4.4 PassthroughParser (parse.py:96-102)

**职责**：对不支持的文件类型返回 None，使后续 pipeline 阶段跳过该文档。

**当前不支持的类型**: html, doc, docx 及其他所有。

---

## 5. ParserStage 包装器 (parse.py:22-39)

```python
class ParserStage:
    stage_name = "parse"
    stage_version = "1"

    def execute(self, context, **kw):
        raw = context.get("raw_file")
        parser = create_parser(raw.file_type, **self._kwargs)
        tree = parser.parse(raw.content, raw.file_name, {"file_path": raw.file_path})
        context["tree"] = tree
        return context
```

**注意**：此 class 似乎是为了可插拔 stage 设计的，但在实际的 `StreamingPipeline` 中未被使用。实际调用路径在 `pipeline.py` 的 `parse_stage()` 函数中直接调用 `create_parser()` + `parser.parse()`。

---

## 6. 配置参数

| 参数 | 来源 | 默认值 | 适用 Parser |
|------|------|--------|------------|
| `chunk_size` | `create_parser(**kwargs)` | 300 | PlainTextParser |
| `chunk_overlap` | `create_parser(**kwargs)` | 30 | PlainTextParser |

**注意**：
- Parse 阶段**没有** domain.yaml 配置
- chunk_size/chunk_overlap 目前在代码中从未被外部传入，始终使用默认值
- MarkdownParser 无任何可配置参数
- PdfParser 无任何可配置参数

---

## 7. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/stages/parse.py` | 203 | Parser 分发 + 4 种 Parser 实现 + 纯文本切分工具 |
| `mining/infra/structure/__init__.py` | 427 | Markdown 结构解析: token→block, tree 构建, HTML table 解析 |
| `mining/infra/pdf_parser.py` | 210 | PDF 布局解析: 块提取, 页眉页脚去除, heading/table 分类 |
| `mining/infra/text_utils.py` | 102 | Token 计数, 文本归一化, SimHash, Jaccard 相似度 |
| `mining/contracts/models.py:218` | — | `ContentBlock` 数据类定义 |
| `mining/contracts/models.py:231` | — | `SectionNode` 数据类定义 |
| `mining/contracts/models.py:39` | — | `VALID_BLOCK_TYPES` 常量 |

---

## 8. 工业化参考

| 参考 | 说明 |
|------|------|
| Unstructured.io `partition()` | 同样做文件类型分发 + 结构化解析，支持更多格式 |
| LangChain `RecursiveCharacterTextSplitter` | 类似 PlainTextParser 的分块逻辑，但有更多分隔符选项 |
| LlamaIndex `SentenceSplitter` | 按句子边界切分，我们的实现按 token 边界 |
| Docling (IBM) | PDF 结构化解析，支持 layout 检测 + table 提取，比我们的 pdfminer 方案强 |
| PyMuPDF (`fitz`) | 比 pdfminer 更快的 PDF 解析库，支持图片、表格提取 |
| markitdown (Microsoft) | 专门做 Markdown 结构化处理 |
| Apache Tika | JVM 级文档解析，200+ 格式 |

---

## 9. 当前不足

1. **HTML 无 Parser**: HTML file_type 直接走 PassthroughParser，Ingest 阶段也未预处理 HTML → Markdown，导致 HTML 文件完全无法进入 pipeline
2. **PDF 解析质量有限**:
   - 只用 pdfminer 的 layout API，无真正的 OCR
   - 表格只检测 caption (`Tabelle/Table/Figure` 开头)，不提取实际的行列结构
   - Heading 检测依赖编号格式 (`1.1.1`)，无编号的标题无法识别
   - 图片完全忽略
   - 多栏布局可能混乱 (pdfminer 按位置提取，不一定按阅读顺序)
3. **PlainTextParser 参数硬编码**: chunk_size=300 / chunk_overlap=30 从未被外部配置覆盖
4. **PdfParser 绕过 Ingest**: Ingest 阶段用 pdfminer 提取了纯文本放在 content 中，但 PdfParser 又从文件路径重新解析，等于做了两遍 PDF 处理。如果文件被删除或移动，PdfParser 会失败
5. **MarkdownParser 无错误恢复**: markdown-it-py 解析失败时无 fallback
6. **无文档级元数据提取**: 没有从文档内容中提取创建日期、作者、版本等元信息
7. **列表嵌套只有 1 层深度展示**: `_format_nested_items` 的有序计数器只在 depth=1 时递增，嵌套有序列表不支持
8. **HTML table 解析脆弱**: `_HtmlTableParser` 不处理 colspan/rowspan，不处理 `<caption>`，异常被静默吞掉
9. **行号信息丢失**: PlainTextParser 切分长段落后，子 chunk 共享原段落的 line_start/end，无法精确定位
10. **ParserStage 包装器未被使用**: 存在死代码，实际的 parse_stage 在 pipeline.py 中直接调用
11. **_find_token_boundaries 与 text_utils._tokenize 重复**: 两者做了类似的 token 边界检测，但实现略有不同，应该复用
12. **PDF heading 正则只支持数字编号**: 不支持中文标题 (如 "概述"、"配置步骤") 或无编号英文标题 (如 "Introduction")
