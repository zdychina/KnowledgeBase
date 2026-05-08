# M1 Knowledge Mining Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **版本:** v1.1 — 基于 Codex 审查 P1-P2 修订；对齐 schema v0.4；纳入 manifest.jsonl；拆分 block_type/section_role；SQLite 读取共享 DDL

**Goal:** 实现离线知识挖掘最小闭环：上游转换后 Markdown / source artifacts → L0 raw_segments → L1 canonical_segments → L2 canonical_segment_sources，写入 SQLite staging publish version。

**Architecture:** 6 模块 pipeline（ingestion → document_profile → structure → segmentation → canonicalization → publishing），内部用 dataclass 传递数据，SQLite dev 模式读取共享 DDL，三层 hash 去重，block_type 与 section_role 分离。

**Tech Stack:** Python 3.11+, markdown-it-py, SQLite, pytest

---

### Task 1: 添加依赖

**Files:**
- Modify: `pyproject.toml`

**Step 1: 添加 markdown-it-py 依赖**

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "markdown-it-py>=3.0",
]
```

**Step 2: 安装依赖**

Run: `pip install -e ".[dev]"`

**Step 3: 验证安装**

Run: `python -c "import markdown_it; print(markdown_it.__version__)"`
Expected: 版本号输出，无报错

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "[claude-mining]: add markdown-it-py dependency for M1 mining"
```

---

### Task 2: 数据对象定义（v1.1 修订：对齐 schema v0.4）

**Files:**
- Create: `knowledge_mining/mining/models.py`
- Test: `knowledge_mining/tests/test_models.py`

**关键变更（v1.1）：**
- `RawDocumentData` 增加 `manifest_meta` 字段，存储 manifest.jsonl 元数据
- `DocumentProfile` 以 `source_type/document_type/scope_json/tags_json` 为核心，product 为可选 facet
- `RawSegmentData` 拆分 `block_type`（结构形态）和 `section_role`（语义角色），增加 `structure_json`、`source_offsets_json`
- `CanonicalSegmentData` 增加 `section_role`
- `ContentBlock.block_type` 增加 `html_table`、`raw_html`、`unknown`

**Step 1: 写测试** — 测试 dataclass 能实例化、字段正确。

测试需覆盖：
1. `RawDocumentData` 含 manifest 元数据
2. `DocumentProfile` 含 source_type、scope_json、tags_json
3. `ContentBlock` 含 html_table block_type
4. `RawSegmentData` 含 block_type 和 section_role
5. `CanonicalSegmentData` 含 section_role

**Step 2-5: 同标准 TDD 流程**

实现要点（models.py）：

```python
@dataclass(frozen=True)
class RawDocumentData:
    file_path: str
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    manifest_meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class DocumentProfile:
    file_path: str
    source_type: str = "other"           # productdoc_export, official_vendor, expert_authored, etc.
    document_type: str | None = None     # command, feature, procedure, troubleshooting, etc.
    scope_json: dict[str, Any] = field(default_factory=dict)  # product/version/NE as optional facets
    tags_json: list[str] = field(default_factory=list)
    product: str | None = None           # 兼容字段
    product_version: str | None = None   # 兼容字段
    network_element: str | None = None   # 兼容字段
    structure_quality: str = "unknown"

@dataclass(frozen=True)
class ContentBlock:
    block_type: str  # heading, paragraph, list, table, html_table, code, blockquote, raw_html, unknown
    text: str
    language: str | None = None

@dataclass(frozen=True)
class RawSegmentData:
    document_file_path: str
    segment_index: int
    section_path: list[str]
    section_title: str | None
    heading_level: int | None
    segment_type: str       # command, parameter, example, note, table, paragraph, concept, other
    block_type: str = "unknown"  # heading, paragraph, list, table, html_table, code, blockquote, raw_html, unknown
    section_role: str | None = None  # parameter, example, note, precondition, procedure_step, etc.
    raw_text: str = ""
    normalized_text: str = ""
    content_hash: str = ""
    normalized_hash: str = ""
    token_count: int | None = None
    command_name: str | None = None
    structure_json: dict[str, Any] = field(default_factory=dict)
    source_offsets_json: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class CanonicalSegmentData:
    canonical_key: str
    segment_type: str
    section_role: str | None = None  # v0.4 新增
    title: str | None
    canonical_text: str
    search_text: str
    has_variants: bool
    variant_policy: str
    command_name: str | None
    raw_segment_refs: list[str]
```

---

### Task 3: SQLite Schema Adapter（v1.1 修订：读取共享 DDL）

**Files:**
- Create: `knowledge_mining/mining/db.py`
- Test: `knowledge_mining/tests/test_db.py`
- 引用: `knowledge_assets/schemas/001_asset_core.sqlite.sql`

**关键变更（v1.1）：**
- 不在 db.py 中内嵌 DDL，改为读取共享 `knowledge_assets/schemas/001_asset_core.sqlite.sql`
- SQLite 表名使用 `asset_` 前缀（与共享 DDL 一致）
- raw_documents 包含 scope_json, tags_json, source_type, relative_path, structure_quality 等字段
- raw_segments 包含 block_type, section_role, structure_json, source_offsets_json

**Step 1: 写测试**

```python
# knowledge_mining/tests/test_db.py
"""Verify SQLite schema creation from shared DDL and basic CRUD."""
import tempfile
from pathlib import Path

from knowledge_mining.mining.db import MiningDB


def test_create_tables_from_shared_ddl():
    """Schema must be loaded from the shared SQLite DDL file."""
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor]
        assert "asset_source_batches" in tables
        assert "asset_publish_versions" in tables
        assert "asset_raw_documents" in tables
        assert "asset_raw_segments" in tables
        assert "asset_canonical_segments" in tables
        assert "asset_canonical_segment_sources" in tables
        conn.close()


def test_insert_and_query_publish_version():
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        pv_id = db.create_publish_version(conn, version_code="v1", status="staging")
        cursor = conn.execute(
            "SELECT version_code, status FROM asset_publish_versions WHERE id = ?",
            (pv_id,),
        )
        row = cursor.fetchone()
        assert row == ("v1", "staging")
        conn.close()


def test_raw_documents_has_v04_fields():
    """Verify v0.4 fields exist: scope_json, tags_json, source_type, structure_quality."""
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        pv_id = db.create_publish_version(conn, version_code="v1", status="staging")
        conn.execute(
            """INSERT INTO asset_raw_documents
               (id, publish_version_id, document_key, source_uri, file_name,
                file_type, content_hash, scope_json, tags_json, source_type,
                structure_quality, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("d1", pv_id, "test_doc", "/test.md", "test.md",
             "markdown", "abc", '{"product":"UDG"}', '["5G"]',
             "synthetic_coldstart", "markdown_native", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        cursor = conn.execute(
            "SELECT scope_json, tags_json, source_type, structure_quality FROM asset_raw_documents WHERE id = ?",
            ("d1",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert "product" in row[0]
        conn.close()
```

**Step 2-3: 同标准 TDD 流程**

实现要点（db.py）：

```python
class MiningDB:
    _SHARED_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "knowledge_assets" / "schemas" / "001_asset_core.sqlite.sql"

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create_tables(self) -> None:
        schema_sql = self._SHARED_SCHEMA_PATH.read_text(encoding="utf-8")
        conn = self.connect()
        conn.executescript(schema_sql)
        conn.close()
```

**Step 4-5: 运行测试通过后提交**

---

### Task 4: Text Utilities (hash, normalize, simhash, token_count)

**Files:**
- Create: `knowledge_mining/mining/text_utils.py`
- Test: `knowledge_mining/tests/test_text_utils.py`

**Step 1: 写测试**

```python
# knowledge_mining/tests/test_text_utils.py
"""Verify text utility functions."""
from knowledge_mining.mining.text_utils import (
    content_hash,
    normalize_text,
    normalized_hash,
    simhash_fingerprint,
    hamming_distance,
    jaccard_similarity,
    token_count,
)


def test_content_hash_deterministic():
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_content_hash_different():
    h1 = content_hash("hello")
    h2 = content_hash("world")
    assert h1 != h2


def test_normalize_text():
    result = normalize_text("  Hello   World  ")
    assert result == "hello world"


def test_normalize_text_cjk():
    result = normalize_text("５Ｇ　网络")
    assert "5g" in result
    assert "网络" in result


def test_normalized_hash():
    h = normalized_hash("  Hello   World  ")
    assert len(h) == 64


def test_simhash_similar():
    fp1 = simhash_fingerprint("ADD APN命令用于配置APN")
    fp2 = simhash_fingerprint("ADD APN命令用于配置APN。")
    dist = hamming_distance(fp1, fp2)
    assert dist <= 3


def test_simhash_different():
    fp1 = simhash_fingerprint("ADD APN命令用于配置APN")
    fp2 = simhash_fingerprint("网络切片是一种5G核心技术")
    dist = hamming_distance(fp1, fp2)
    assert dist > 10


def test_jaccard():
    s = jaccard_similarity("hello world foo", "hello world bar")
    assert 0.3 < s < 0.7


def test_jaccard_identical():
    assert jaccard_similarity("a b c", "a b c") == 1.0


def test_token_count_ascii():
    assert token_count("hello world") == 2


def test_token_count_cjk():
    assert token_count("５Ｇ网络配置") == 5  # 5G=2, 网络=2, 配置=2 → 6 tokens CJK chars
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_text_utils.py -v`
Expected: FAIL

**Step 3: 写实现**

```python
# knowledge_mining/mining/text_utils.py
"""Text hashing, normalization, and similarity utilities."""
from __future__ import annotations

import hashlib
import re
import unicodedata


def content_hash(text: str) -> str:
    """SHA-256 hex digest of raw text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    """Normalize text for dedup: CJK fullwidth→halfwidth, lowercase, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    # Fullwidth ASCII → halfwidth
    text = unicodedata.normalize("NFKC", text)
    # Remove punctuation variations
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalized_hash(text: str) -> str:
    """SHA-256 hex digest of normalized text."""
    return content_hash(normalize_text(text))


def _tokenize(text: str) -> list[str]:
    """Split text into tokens for similarity computation. CJK-aware."""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf.lower())
                buf = ""
            tokens.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            if buf:
                tokens.append(buf.lower())
                buf = ""
    if buf:
        tokens.append(buf.lower())
    return tokens


def token_count(text: str) -> int:
    """Count tokens (CJK-aware). CJK chars count individually."""
    return len(_tokenize(text))


def simhash_fingerprint(text: str, bits: int = 64) -> int:
    """Compute SimHash fingerprint for near-duplicate detection."""
    tokens = _tokenize(text)
    if not tokens:
        return 0
    v = [0] * bits
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(bits):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(fp1: int, fp2: int, bits: int = 64) -> int:
    """Count differing bits between two fingerprints."""
    x = fp1 ^ fp2
    count = 0
    while x and count < bits:
        count += x & 1
        x >>= 1
    return count


def jaccard_similarity(text1: str, text2: str) -> float:
    """Jaccard similarity of token sets."""
    s1 = set(_tokenize(text1))
    s2 = set(_tokenize(text2))
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)
```

**Step 4: 运行测试确认通过**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_text_utils.py -v`
Expected: 全部 passed

**Step 5: Commit**

```bash
git add knowledge_mining/mining/text_utils.py knowledge_mining/tests/test_text_utils.py
git commit -m "[claude-mining]: add text hashing, normalization, and simhash utilities"
```

---

### Task 5: Ingestion Module（v1.1 修订：支持 manifest.jsonl）

**Files:**
- Modify: `knowledge_mining/mining/ingestion/__init__.py`
- Test: `knowledge_mining/tests/test_ingestion.py`

**关键变更（v1.1）：**
- 支持两种模式：manifest.jsonl 驱动（模式 A）和纯 Markdown 目录（模式 B）
- manifest.jsonl 每行含 doc_id, title, doc_type, nf, scenario_tags, source_type, path
- 无 manifest 时仍可递归扫描 .md 文件

**Step 1: 写测试**

需覆盖：
1. 纯 Markdown 目录扫描（原有）
2. frontmatter 解析（原有）
3. **manifest.jsonl 驱动导入** — 读取 manifest，按 path 读取 md，元数据进 manifest_meta
4. **无 manifest 无 frontmatter** — 仍可导入，document_key 由相对路径生成
5. 空目录、非 Markdown 跳过、递归（原有）

**Step 2-5: 同标准 TDD 流程**

实现要点：
- `ingest_directory(path: Path) -> list[RawDocumentData]`
- 先检查 `manifest.jsonl` 是否存在，存在则按 manifest 驱动
- 每行 JSON 解析，按 `path` 字段读取对应 Markdown 文件
- manifest 元数据存入 `RawDocumentData.manifest_meta`
- 无 manifest 时，递归扫描 .md 文件

---

### Task 6: Document Profile Module（v1.1 修订：通用语料画像）

**Files:**
- Modify: `knowledge_mining/mining/document_profile/__init__.py`
- Test: `knowledge_mining/tests/test_document_profile.py`

**关键变更（v1.1）：**
- 以 `source_type/document_type/scope_json/tags_json` 为核心
- product/version/NE 为可选 facet，放入 scope_json
- 支持专家文档（无产品/版本/NE）

**Step 1: 写测试**

覆盖：
1. manifest 元数据驱动（source_type, doc_type, nf → scope_json, tags_json）
2. frontmatter 显式声明
3. 内容模式匹配（MML 命令 → document_type=command）
4. 专家文档（无 product/version/NE，scope_json 含 author/team/scenario）
5. 无任何元数据 → source_type=other, document_type=None

**Step 2-5: 同标准 TDD 流程**

---

### Task 7: Structure Parser（v1.1 修订：支持 HTML table）

**Files:**
- Modify: `knowledge_mining/mining/structure/__init__.py`
- Test: `knowledge_mining/tests/test_structure.py`

**关键变更（v1.1）：**
- 识别标准 Markdown table → block_type="table"
- 识别保留的 HTML table（`<table>`）→ block_type="html_table"
- 识别 raw HTML 块 → block_type="raw_html"
- 未知结构 → block_type="unknown"

**Step 1: 写测试**

覆盖：
1. 简单标题 + 段落 → SectionNode
2. 嵌套标题 → 树结构
3. 标准 Markdown 表格 → ContentBlock(block_type="table")
4. **HTML `<table>` 块 → ContentBlock(block_type="html_table")**
5. 代码块 → ContentBlock(block_type="code", language="mml")
6. 列表 → ContentBlock(block_type="list")
7. 无标题段落 → root level section
8. **未知 HTML 块 → ContentBlock(block_type="raw_html")**

**Step 2-5: 同标准 TDD 流程**

---

### Task 8: Segmentation Module（v1.1 修订：block_type/section_role 分离）

**Files:**
- Modify: `knowledge_mining/mining/segmentation/__init__.py`
- Test: `knowledge_mining/tests/test_segmentation.py`

**关键变更（v1.1）：**
- `block_type` 表示结构形态（table, html_table, code, list, paragraph, unknown）
- `section_role` 表示语义角色（parameter, example, note, precondition, procedure_step, troubleshooting_step, concept_intro）
- segment_type 保持兼容（按 block_type 映射）
- 增加 structure_json（表格列数/行数等）和 source_offsets_json

**Step 1: 写测试**

覆盖：
1. 单个 section → segment with block_type="paragraph"
2. Markdown 表格 → segment with block_type="table"
3. **HTML 表格 → segment with block_type="html_table"**
4. 代码块 → segment with block_type="code"
5. **section_role 推断** — "参数说明"标题下 → section_role="parameter"
6. command_name 检测（ADD APN → command_name="ADD APN"）
7. content_hash / normalized_hash / token_count 正确
8. section_path 正确传递

**Step 2-5: 同标准 TDD 流程**

实现要点：
- segment_type 由 block_type 映射：table→table, html_table→table, code→example, list→paragraph, paragraph→paragraph
- section_role 由标题关键词推断："参数"→parameter, "示例"→example, "注意"→note, "前置"→precondition, "排障"→troubleshooting_step, "步骤"→procedure_step
- HTML table 的 raw_text 保留原始 HTML
- structure_json 记录表格行数/列数等

---

### Task 9: Canonicalization Module

**Files:**
- Create: `knowledge_mining/mining/canonicalization.py`
- Test: `knowledge_mining/tests/test_canonicalization.py`

**Step 1: 写测试**

覆盖：
1. 单个 segment → 创建 canonical（relation=primary）
2. 完全重复（content_hash 相同）→ exact_duplicate，合并
3. 归一重复（normalized_hash 相同）→ near_duplicate，合并
4. 近似重复（simhash ≤ 3 且 Jaccard ≥ 0.85）→ near_duplicate
5. 不同 product 同内容 → product_variant，has_variants=true
6. 不同 version 同内容 → version_variant，has_variants=true
7. 无重复的 segment 各自独立成 canonical

**Step 2-5: 同上 TDD 流程**

实现要点：
- `canonicalize(segments: list[RawSegmentData], profiles: dict[str, DocumentProfile]) -> tuple[list[CanonicalSegmentData], list[SourceMappingData]]`
- 建立 `content_hash → [segment]` 索引
- 建立 `normalized_hash → [segment]` 索引
- 建立近重复候选（simhash bucket 或全量比较，M1 数据量小可用全量）
- 归并逻辑：
  1. 先按 content_hash 分组 → exact_duplicate
  2. 未匹配的按 normalized_hash 分组 → near_duplicate
  3. 未匹配的按 simhash + Jaccard 判断 → near_duplicate
  4. 每组生成一个 CanonicalSegment
  5. 组内按 profile 判断 variant 类型

---

### Task 10: Publishing Module

**Files:**
- Modify: `knowledge_mining/mining/publishing/__init__.py`
- Test: `knowledge_mining/tests/test_publishing.py`

**Step 1: 写测试**

覆盖：
1. 创建 source_batch 和 staging publish_version
2. 写入 raw_documents（带 profile 信息）
3. 写入 raw_segments
4. 写入 canonical_segments（has_variants 用 0/1 表示）
5. 写入 canonical_segment_sources
6. 查询验证数据完整

**Step 2-5: 同上 TDD 流程**

实现要点：
- `publish(profiles, segments, canonicals, sources, db_path)` 函数
- 使用 MiningDB 连接
- 将 pipeline 内存对象映射为 SQL INSERT
- section_path 序列化为 JSON 字符串
- has_variants 用 INTEGER 0/1

---

### Task 11: Pipeline 入口

**Files:**
- Create: `knowledge_mining/mining/jobs/run.py`
- Test: `knowledge_mining/tests/test_pipeline.py`

**Step 1: 写集成测试**

用合成 Markdown 样例（包含标题层级、表格、代码块、重复段落），验证端到端 pipeline：
1. 输入 → L0 raw_segments 非空
2. L0 中有正确的 segment_type（table, example, paragraph）
3. L1 canonical_segments 去重后数量 < L0
4. L2 source_mappings 正确关联 L1 → L0
5. SQLite 中可查询到完整数据

**Step 2-5: 同上 TDD 流程**

实现 `knowledge_mining/mining/jobs/run.py`：
- `run_pipeline(input_path, db_path)` 编排所有模块
- 支持 `python -m knowledge_mining.mining.jobs.run --input <path>` CLI 入口

---

### Task 12: 真实语料 + 最终验证（v1.1 修订：使用 cloud_core_coldstart_md）

**Files:**
- Test corpus: `cloud_core_coldstart_md/`（已有 manifest.jsonl + 分类 Markdown）
- 额外创建少量合成测试样例覆盖边界场景

**Step 1: 用 cloud_core_coldstart_md 运行端到端 pipeline**

Run: `python -m knowledge_mining.mining.jobs.run --input cloud_core_coldstart_md/ --db .dev/test.sqlite`

验证：
- manifest.jsonl 被正确读取
- 每个 doc 的 source_type, document_type, scope_json 正确
- L0 segments 包含正确的 block_type 和 section_role
- L1 去重归并正确
- L2 mapping 正确

**Step 2: 补充边界测试**

创建合成测试覆盖：
1. 无 manifest 的纯 Markdown 目录
2. 无 frontmatter、无产品/网元的专家文档
3. 带 HTML table 的 Markdown
4. manifest 中无 nf 字段的文档

**Step 3: 运行全量测试**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/ -v`
Expected: 全部 passed

**Step 4: Commit**

```bash
git add knowledge_mining/
git commit -m "[claude-mining]: complete M1 mining pipeline v1.1 with real corpus"
```

---

## 验证清单

- [ ] `python -m pytest knowledge_mining/tests/ -v` 全部通过
- [ ] cloud_core_coldstart_md 样例能跑通完整 pipeline（manifest 驱动）
- [ ] 无 manifest 的纯 Markdown 目录也能导入
- [ ] L0 每个 segment 有 section_path, raw_text, content_hash, block_type, section_role
- [ ] HTML table 保留为 block_type="html_table"，不丢失
- [ ] L1 去重正确，重复概念只生成一个 canonical segment
- [ ] L2 能表达 exact_duplicate / version_variant / product_variant
- [ ] 专家文档不需要 product/version/NE 也能正确入库
- [ ] SQLite schema 来源于共享 `001_asset_core.sqlite.sql`
- [ ] 不依赖 `agent_serving` 代码
