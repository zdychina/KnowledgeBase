# Stage 1 — Ingest 文件采集

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Ingest 阶段负责：
1. 递归扫描指定目录，发现所有可识别的文件
2. 对特殊格式文件（CHM/HDX/PDF）进行预处理，统一转换为文本
3. 计算文件级哈希（raw_content_hash + normalized_content_hash）用于增量检测
4. 构造 `RawFileData` 对象，作为后续 parse 阶段的输入

**关键特性**：此阶段不涉及 LLM，纯 CPU/IO 操作。

---

## 2. 输入与输出

### 输入
| 参数 | 类型 | 说明 |
|------|------|------|
| `input_path` | `Path` | 要扫描的根目录 |
| `batch_params` | `BatchParams` | 批次参数 (source_type, document_type, scope, tags) |

### 输出
```python
tuple[list[RawFileData], dict[str, Any]]
# list[RawFileData]: 所有发现的文档
# dict: 统计摘要 (discovered_documents, parsed_documents, skipped_files, ...)
```

### RawFileData 核心字段
```
file_path: str           # 绝对路径
relative_path: str       # 相对于 input_path 的路径 (用 / 分隔)
file_name: str           # 文件名
file_type: str           # markdown / txt / html / pdf / doc / docx
content: str             # 文件内容文本 (预处理后)
raw_content_hash: str    # SHA256(原始字节)
normalized_content_hash: str  # SHA256(规范化文本, CRLF→LF, 去空行)
title: str | None        # MD取首个 H1, 其他取文件名
```

---

## 3. 支持的文件类型

| 扩展名 | file_type | 处理方式 |
|--------|-----------|----------|
| `.md`, `.markdown` | `markdown` | 直接 UTF-8 读取 |
| `.txt` | `txt` | 直接 UTF-8 读取 |
| `.html`, `.htm` | `html` | 直接 UTF-8 读取 (后续 parse 阶段处理) |
| `.pdf` | `pdf` | `pdfminer.six` 提取文本, `\x0c` → 双换行 |
| `.doc`, `.docx` | `doc` / `docx` | **不解析**, content="" |
| `.chm` | `markdown` | 解压 → HTML → Markdown (保留 TOC 顺序) |
| `.hdx` | `markdown` | 解压 zip → HTML → Markdown (字典序) |

### 跳过文件
- `manifest.jsonl`, `manifest.json`, `html_to_md_mapping.json`, `.ds_store`, `thumbs.db`, `.gitkeep`
- 扩展名不在 `_EXTENSION_MAP` 中的文件

---

## 4. 具体实现

### 4.1 目录扫描 (`ingest_directory`, 177 行)

```
for file_path in sorted(input_path.rglob("*")):
    1. 跳过非文件、跳过 _SKIP_NAMES
    2. ext → file_type 映射
    3. 读取原始字节 → compute_raw_hash()
    4. 分支处理:
       - .chm/.hdx → archive_to_markdown() → content
       - .pdf → pdf_to_text() → content
       - .md/.txt → UTF-8 decode → content
       - 其他 → content = ""
    5. compute_snapshot_hash(content) → normalized_content_hash
    6. _infer_title() → title
    7. 构造 RawFileData → 加入 documents
```

### 4.2 CHM 预处理 (preprocessing.py, 723 行)

**流程**: `extract_chm()` → `convert_chm_extracted()` → `convert_topic()` × N

1. **解压**: Windows 上优先 `hh.exe -decompile`, 否则 `7z x`
2. **TOC 解析**: 找到 `.hhc` 文件, 用 `_HhcParser` (HTMLParser 子类) 解析, 得到 `[(depth, title, local_path)]` 列表
3. **逐主题转换**: 对每个 TOC 条目:
   - `read_text()` (编码感知: 检测 meta charset, gb2312/gbk→gb18030)
   - `build_tree()` (stdlib HTMLParser 构建简单 DOM)
   - `_find_body()` (定位 `articleBox`/`topicBody` div 或 `<body>`)
   - `_render()` (DOM → Markdown: h1-h6, p, ul/ol, table, code, pre, strong/em, img)
4. **输出**: 按 TOC 顺序拼接, 每主题的 heading 根据深度偏移

**关键渲染能力**:
- HTML 表格 → Markdown pipe table (处理 rowspan/colspan 展开)
- 列表支持 block 级子元素 (table 嵌套在 li 中)
- 图片路径前缀修正 (`_prefix_image_paths`)
- 编码自动检测 (gb18030/utf-8)

### 4.3 HDX 预处理 (preprocessing.py)

**流程**: `extract_hdx()` → `convert_hdx_extracted()` → `convert_topic()` × N

- HDX 是华为 HedEx 包 (zip 格式), HTML 在 `resources/` 下
- 无 TOC, 按字典序排列
- 过滤 `hedex-*` 开头的文件
- 复用 `convert_topic()` 转换

### 4.4 PDF 预处理 (pdf_preprocessing.py, 31 行)

```python
from pdfminer.high_level import extract_text
text = extract_text(str(src))
return text.replace("\x0c", "\n\n").strip()
```

- 使用 `pdfminer.six` 的高层 API
- 将 form-feed (分页符 `\x0c`) 替换为双换行, 使后续 `PlainTextParser` 在页边界分段

### 4.5 哈希计算 (hash_utils.py, 42 行)

| 函数 | 输入 | 用途 |
|------|------|------|
| `compute_raw_hash(bytes)` | 原始字节 | `raw_content_hash` — 文件级唯一标识 |
| `compute_snapshot_hash(str)` | 规范化文本 | `normalized_content_hash` — 增量检测 |
| `content_hash(str)` | 文本 | segment 级 `content_hash` |
| `normalized_hash(str)` | `text.lower().strip()` | segment 级 `normalized_hash` |

**规范化规则** (`normalize_for_snapshot`):
1. CRLF → LF
2. 去行尾空白
3. 去空行
4. LF 拼接

---

## 5. 配置参数

| 参数 | 来源 | 默认值 | 说明 |
|------|------|--------|------|
| `default_source_type` | `BatchParams` | `"folder_scan"` | 文档来源类型 |
| `default_document_type` | `BatchParams` | `None` | 文档业务类型 |
| `batch_scope` | `BatchParams` | `{}` | 文档 scope 标签 |
| `tags` | `BatchParams` | `[]` | 文档标签 |

**注意**: Ingest 阶段**没有** domain.yaml 配置。所有文件类型处理逻辑是硬编码的。

---

## 6. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/ingestion/__init__.py` | 177 | `ingest_directory()` 主函数, 文件类型映射, 统计摘要 |
| `mining/ingestion/preprocessing.py` | 723 | CHM/HDX 解压 + HTML→Markdown 转换引擎 |
| `mining/ingestion/pdf_preprocessing.py` | 31 | PDF 文本提取 (pdfminer.six) |
| `mining/infra/hash_utils.py` | 42 | SHA256 哈希计算 (raw/snapshot/content/normalized) |
| `mining/contracts/models.py:194` | — | `RawFileData` 数据类定义 |

---

## 7. 工业化参考

| 参考 | 说明 |
|------|------|
| Unstructured.io `partition()` | 同样做文件类型分发, 但支持更多格式 (PPT/XLS/DOCX) |
| Apache Tika | JVM 级文件解析, 200+ 格式 |
| LangChain `PyPDFLoader` | PDF 加载, 我们用 pdfminer 类似 |
| Markitdown (Microsoft) | 专门做 HTML/PDF→Markdown, 我们自实现 |
| AWS Textract / Google Document AI | 云端 OCR+布局分析, 适合扫描件 |

---

## 8. 当前不足

1. **DOC/DOCX 不解析**: `content=""`, 直接跳过。需要集成 `python-docx` 或 `mammoth`
2. **HTML 不预处理**: 直接传原始 HTML 给 parse 阶段, 但 MarkdownParser 无法处理 HTML; 需要 HTML→MD 预处理或单独的 HTMLParser
3. **PDF 仅文本提取**: `pdfminer.high_level.extract_text` 丢失表格结构、图片、布局信息。工业级应用需要 layout-aware 解析 (如 `pdfplumber`, `PyMuPDF`, `Unstructured.io partition_pdf`)
4. **无 OCR**: 扫描件 PDF (图片型) 无法提取文字
5. **单线程扫描**: `rglob` + 逐文件处理, 无并行; 大目录性能差
6. **全量加载到内存**: `file_path.read_bytes()` 一次性读取, 大文件有 OOM 风险
7. **预处理无缓存**: CHM/HDX 每次都重新解压+转换, 无中间结果缓存
8. **编码检测简单**: 仅检查 meta charset, 无 `chardet`/`cchardet` 兜底
9. **无文件大小限制**: 超大文件直接处理, 无预警
10. **relative_path 用 `/` 替换 `\\`**: Windows 硬编码行为, 虽然不影响功能但不够通用
