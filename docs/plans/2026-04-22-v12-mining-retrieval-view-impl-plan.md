# CoreMasterKB v1.2 Mining Retrieval View 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 正式建立 Retrieval View Layer，实现 source_segment_id 强桥接、jieba 中文分词、LLM 接入 generated_question、以及 5 项加固改进。

**Architecture:** 在 v1.1 的 7 阶段 pipeline 基础上，修改 retrieval_units/reations/enrich/publishing 四个模块，新增 llm_client 和 llm_templates 两个模块。schema 层面在 asset_retrieval_units 表新增 source_segment_id 列和索引。

**Tech Stack:** Python 3.10+, SQLite, FTS5, jieba (optional), httpx (for LLM client), pytest

---

## Task 1: Schema — asset_retrieval_units 新增 source_segment_id

**Files:**
- Modify: `databases/asset_core/schemas/001_asset_core.sqlite.sql:195-249`

**Step 1: Write the failing test**

在 `knowledge_mining/tests/test_v11_pipeline.py` 末尾添加：

```python
def test_source_segment_id_in_schema(tmp_path):
    """asset_retrieval_units 表必须有 source_segment_id 列。"""
    db_path = tmp_path / "schema_test.sqlite"
    schema_path = Path(__file__).resolve().parents[2] / "databases" / "asset_core" / "schemas" / "001_asset_core.sqlite.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    assert "source_segment_id" in schema_sql, "source_segment_id column missing from schema"

    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)
    # Verify column exists
    cols = conn.execute("PRAGMA table_info(asset_retrieval_units)").fetchall()
    col_names = [c[1] for c in cols]
    assert "source_segment_id" in col_names, f"source_segment_id not in {col_names}"

    # Verify index exists
    idxs = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    idx_names = [i[0] for i in idxs]
    assert "idx_asset_retrieval_units_source_segment" in idx_names
    conn.close()
```

**Step 2: Run test to verify it fails**

Run: `cd D:/mywork/KnowledgeBase/CoreMasterKB && python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_source_segment_id_in_schema -v`
Expected: FAIL — source_segment_id not in schema

**Step 3: Modify schema**

在 `001_asset_core.sqlite.sql` 的 `asset_retrieval_units` 表定义中，在 `metadata_json` 之后、`UNIQUE` 约束之前添加：

```sql
    source_segment_id  TEXT REFERENCES asset_raw_segments(id) ON DELETE SET NULL,
```

在现有索引之后添加：

```sql
CREATE INDEX IF NOT EXISTS idx_asset_retrieval_units_source_segment
    ON asset_retrieval_units(source_segment_id);
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_source_segment_id_in_schema -v`
Expected: PASS

**Step 5: Commit**

```bash
git add databases/asset_core/schemas/001_asset_core.sqlite.sql knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): add source_segment_id column to asset_retrieval_units schema"
```

---

## Task 2: DB Layer — insert_retrieval_unit 支持 source_segment_id + count_segments_by_snapshot

**Files:**
- Modify: `knowledge_mining/mining/db.py:351-387` (insert_retrieval_unit)
- Modify: `knowledge_mining/mining/db.py` (add count_segments_by_snapshot)

**Step 1: Write the failing test**

```python
def test_insert_retrieval_unit_with_source_segment_id(tmp_path):
    """insert_retrieval_unit 应接受并写入 source_segment_id。"""
    asset_db, runtime_db, _ = _setup_dbs(tmp_path)
    # Create prerequisite: document + snapshot + segment
    doc_id = asset_db.upsert_document("doc:/test.md", "test.md", "md", hash1, hash1)
    snap_id = asset_db.upsert_snapshot(hash1, hash1)
    asset_db.upsert_document_snapshot_link(doc_id, snap_id)
    seg_id = asset_db.insert_raw_segment(
        segment_id="seg-001", document_snapshot_id=snap_id,
        segment_key="doc:/test.md#0", segment_index=0,
        block_type="paragraph", semantic_role="concept",
        section_path=[], section_title="Test",
        raw_text="hello", normalized_text="hello",
        content_hash="ch1", normalized_hash="nh1",
    )
    asset_db.commit()

    # Insert retrieval unit WITH source_segment_id
    unit_id = asset_db.insert_retrieval_unit(
        unit_id="ru-001", document_snapshot_id=snap_id,
        unit_key="ru:test#0:raw_text", unit_type="raw_text",
        target_type="raw_segment", text="hello", search_text="hello",
        source_segment_id="seg-001",
    )
    asset_db.commit()

    row = asset_db._fetchone(
        "SELECT source_segment_id FROM asset_retrieval_units WHERE id = ?", (unit_id,)
    )
    assert row["source_segment_id"] == "seg-001"


def test_count_segments_by_snapshot(tmp_path):
    """count_segments_by_snapshot 返回正确数量。"""
    asset_db, _, _ = _setup_dbs(tmp_path)
    doc_id = asset_db.upsert_document("doc:/test.md", "test.md", "md", hash1, hash1)
    snap_id = asset_db.upsert_snapshot(hash1, hash1)
    asset_db.upsert_document_snapshot_link(doc_id, snap_id)
    asset_db.insert_raw_segment(
        segment_id="seg-001", document_snapshot_id=snap_id,
        segment_key="doc:/test.md#0", segment_index=0,
        block_type="paragraph", semantic_role="concept",
        section_path=[], section_title="T", raw_text="a", normalized_text="a",
        content_hash="c", normalized_hash="n",
    )
    asset_db.commit()
    assert asset_db.count_segments_by_snapshot(snap_id) == 1
    assert asset_db.count_segments_by_snapshot("nonexistent") == 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_insert_retrieval_unit_with_source_segment_id -v`
Expected: FAIL — unexpected keyword argument 'source_segment_id'

**Step 3: Modify db.py**

1. `insert_retrieval_unit()` 新增参数 `source_segment_id: str | None = None`，写入 SQL
2. 新增 `count_segments_by_snapshot()` 方法：
```python
def count_segments_by_snapshot(self, document_snapshot_id: str) -> int:
    row = self._fetchone(
        "SELECT COUNT(*) as cnt FROM asset_raw_segments WHERE document_snapshot_id = ?",
        (document_snapshot_id,),
    )
    return row["cnt"] if row else 0
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_insert_retrieval_unit_with_source_segment_id knowledge_mining/tests/test_v11_pipeline.py::test_count_segments_by_snapshot -v`
Expected: PASS

**Step 5: Run full regression**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add knowledge_mining/mining/db.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): db.py supports source_segment_id + count_segments_by_snapshot"
```

---

## Task 3: Models — RetrievalUnitData 新增 source_segment_id 字段

**Files:**
- Modify: `knowledge_mining/mining/models.py:270-289` (RetrievalUnitData)

**Step 1: Write the failing test**

```python
def test_retrieval_unit_data_has_source_segment_id():
    """RetrievalUnitData 必须有 source_segment_id 字段。"""
    ru = RetrievalUnitData(
        segment_key="sk", unit_key="uk", unit_type="raw_text",
        target_type="raw_segment", text="t", search_text="s",
        source_segment_id="seg-001",
    )
    assert ru.source_segment_id == "seg-001"


def test_retrieval_unit_data_source_segment_id_defaults_none():
    """RetrievalUnitData 的 source_segment_id 默认为 None。"""
    ru = RetrievalUnitData(
        segment_key="sk", unit_key="uk", unit_type="raw_text",
        target_type="raw_segment", text="t", search_text="s",
    )
    assert ru.source_segment_id is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_retrieval_unit_data_has_source_segment_id -v`
Expected: FAIL — unexpected keyword argument

**Step 3: Modify models.py**

在 `RetrievalUnitData` dataclass 中，在 `weight: float = 1.0` 之前添加：

```python
    source_segment_id: str | None = None,
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_retrieval_unit_data_has_source_segment_id knowledge_mining/tests/test_v11_pipeline.py::test_retrieval_unit_data_source_segment_id_defaults_none -v`
Expected: PASS

**Step 5: Commit**

```bash
git add knowledge_mining/mining/models.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): add source_segment_id to RetrievalUnitData model"
```

---

## Task 4: P1-1 — retrieval_units 传递 source_segment_id

**Files:**
- Modify: `knowledge_mining/mining/retrieval_units/__init__.py:40-75` (build_retrieval_units)
- Modify: `knowledge_mining/mining/retrieval_units/__init__.py:78-220` (all _make_*_unit helpers)

**Step 1: Write the failing test**

```python
def test_build_retrieval_units_with_seg_ids():
    """build_retrieval_units 应在每个 unit 上设置 source_segment_id。"""
    seg = RawSegmentData(
        document_key="doc:/test.md", segment_index=0,
        block_type="paragraph", semantic_role="concept",
        raw_text="PDU会话建立流程", normalized_text="pdu会话建立流程",
        content_hash="ch", normalized_hash="nh",
        section_path=[{"title": "PDU会话", "level": 2}],
        section_title="PDU会话",
        entity_refs_json=[{"type": "network_function", "name": "SMF"}],
    )
    seg_ids = {"doc:/test.md#0": "uuid-seg-001"}

    units = build_retrieval_units([seg], seg_ids=seg_ids, document_key="doc:/test.md")

    # raw_text unit should have source_segment_id
    raw_units = [u for u in units if u.unit_type == "raw_text"]
    assert len(raw_units) == 1
    assert raw_units[0].source_segment_id == "uuid-seg-001"

    # entity_card should also have source_segment_id
    entity_units = [u for u in units if u.unit_type == "entity_card"]
    assert len(entity_units) == 1
    assert entity_units[0].source_segment_id == "uuid-seg-001"


def test_build_retrieval_units_without_seg_ids_no_crash():
    """不传 seg_ids 不崩溃，source_segment_id 为 None。"""
    seg = RawSegmentData(
        document_key="doc:/test.md", segment_index=0,
        raw_text="test", content_hash="ch", normalized_hash="nh",
    )
    units = build_retrieval_units([seg], document_key="doc:/test.md")
    assert all(u.source_segment_id is None for u in units)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_build_retrieval_units_with_seg_ids -v`
Expected: FAIL — unexpected keyword argument 'seg_ids'

**Step 3: Modify retrieval_units/__init__.py**

1. `build_retrieval_units` 签名加 `seg_ids: dict[str, str] | None = None`
2. 每个 `_make_*_unit` 函数加 `source_seg_id: str | None = None` 参数，传给 `RetrievalUnitData(source_segment_id=...)`
3. 在主循环中从 `seg_ids` 取对应 segment_key 的 ID

**Step 4: Run test to verify it passes**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_build_retrieval_units_with_seg_ids knowledge_mining/tests/test_v11_pipeline.py::test_build_retrieval_units_without_seg_ids_no_crash -v`
Expected: PASS

**Step 5: Run full regression**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add knowledge_mining/mining/retrieval_units/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): build_retrieval_units passes source_segment_id to units"
```

---

## Task 5: P1-2 — jieba 预分词写入 search_text

**Files:**
- Modify: `knowledge_mining/mining/retrieval_units/__init__.py` (所有 _make_*_unit 中的 search_text)
- Modify: `knowledge_mining/mining/text_utils.py` (新增 tokenize_for_search 函数)

**Step 1: Write the failing test**

```python
def test_tokenize_for_search_chinese():
    """tokenize_for_search 应对中文做 jieba 分词。"""
    from knowledge_mining.mining.text_utils import tokenize_for_search
    result = tokenize_for_search("PDU会话建立流程")
    # jieba 分词后空格连接
    assert "PDU" in result
    assert "会话" in result
    # 不是原文整串
    assert result != "PDU会话建立流程"


def test_tokenize_for_search_fallback():
    """无 jieba 时应回退到原文。"""
    from knowledge_mining.mining.text_utils import tokenize_for_search
    # 即使没有 jieba 也不崩溃
    result = tokenize_for_search("hello world")
    assert "hello" in result


def test_retrieval_units_search_text_is_tokenized():
    """retrieval units 的 search_text 应为分词结果。"""
    seg = RawSegmentData(
        document_key="doc:/test.md", segment_index=0,
        raw_text="SMF会话管理功能是5G核心网中的关键控制面网络功能",
        content_hash="ch", normalized_hash="nh",
    )
    units = build_retrieval_units([seg], document_key="doc:/test.md")
    raw_unit = [u for u in units if u.unit_type == "raw_text"][0]
    # search_text should be tokenized, not raw text
    assert raw_unit.search_text != seg.raw_text or " " in raw_unit.search_text
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_tokenize_for_search_chinese -v`
Expected: FAIL — cannot import name 'tokenize_for_search'

**Step 3: Add tokenize_for_search to text_utils.py**

```python
def tokenize_for_search(text: str) -> str:
    """Tokenize text for FTS5 search. Uses jieba for CJK if available."""
    try:
        import jieba
        return " ".join(jieba.cut(text))
    except ImportError:
        return text
```

**Step 4: Modify retrieval_units to use tokenize_for_search**

在每个 `_make_*_unit` 函数中，把 `search_text=seg.raw_text` 改为调用 `tokenize_for_search(seg.raw_text)`。

**Step 5: Run tests**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_tokenize_for_search_chinese knowledge_mining/tests/test_v11_pipeline.py::test_tokenize_for_search_fallback knowledge_mining/tests/test_v11_pipeline.py::test_retrieval_units_search_text_is_tokenized -v`
Expected: PASS

**Step 6: Full regression + commit**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v`

```bash
git add knowledge_mining/mining/text_utils.py knowledge_mining/mining/retrieval_units/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): jieba pre-tokenization for search_text in FTS5"
```

---

## Task 6: P1-3 + P1-4 — LLM Client + LlmQuestionGenerator + 模板

**Files:**
- Create: `knowledge_mining/mining/llm_client.py`
- Create: `knowledge_mining/mining/llm_templates.py`
- Modify: `knowledge_mining/mining/retrieval_units/__init__.py` (LlmQuestionGenerator)

**Step 1: Write the failing test**

```python
def test_llm_question_generator_protocol():
    """LlmQuestionGenerator 实现 QuestionGenerator Protocol。"""
    from knowledge_mining.mining.retrieval_units import QuestionGenerator, LlmQuestionGenerator
    gen = LlmQuestionGenerator(base_url="http://localhost:8000")
    assert isinstance(gen, QuestionGenerator)


def test_llm_question_generator_failure_returns_empty():
    """LLM 失败时返回空列表。"""
    from knowledge_mining.mining.retrieval_units import LlmQuestionGenerator
    gen = LlmQuestionGenerator(base_url="http://localhost:99999")
    seg = RawSegmentData(
        document_key="doc:/test.md", segment_index=0,
        raw_text="test content", content_hash="ch", normalized_hash="nh",
        section_title="Test Section",
    )
    result = gen.generate(seg)
    assert result == []


def test_llm_templates_has_question_gen():
    """llm_templates 必须包含 mining-question-gen 模板。"""
    from knowledge_mining.mining.llm_templates import TEMPLATES
    keys = [t["template_key"] for t in TEMPLATES]
    assert "mining-question-gen" in keys


def test_llm_client_submit_task():
    """LlmClient.submit_task 发送正确请求。"""
    from knowledge_mining.mining.llm_client import LlmClient
    client = LlmClient(base_url="http://localhost:99999")
    # Should not crash, just fail gracefully
    result = client.submit_task(
        template_key="mining-question-gen",
        variables={"title": "Test", "content": "Test content"},
        caller_domain="mining",
        pipeline_stage="retrieval_units",
    )
    # Returns None on failure
    assert result is None or isinstance(result, str)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_llm_question_generator_protocol -v`
Expected: FAIL — cannot import name 'LlmQuestionGenerator'

**Step 3: Create llm_templates.py**

```python
"""LLM template definitions for Mining v1.2."""

TEMPLATES = [
    {
        "template_key": "mining-question-gen",
        "template_version": "1",
        "purpose": "从段落内容生成假设性检索问题",
        "system_prompt": "你是通信网络知识库的检索优化助手。",
        "user_prompt_template": (
            "根据以下技术文档段落，生成 2-3 个用户可能提出的问题。\n\n"
            "段落标题：$title\n段落内容：$content\n\n"
            "输出 JSON 数组，每个元素包含 question 字段。"
        ),
        "expected_output_type": "json_array",
    },
]
```

**Step 4: Create llm_client.py**

独立 HTTP 客户端，使用 `httpx`（或标准库 `urllib`）：
- `submit_task(template_key, variables, caller_domain, pipeline_stage)` → task_id | None
- `poll_result(task_id, timeout=30)` → str | None
- 失败返回 None，不抛异常

**Step 5: Add LlmQuestionGenerator to retrieval_units**

```python
class LlmQuestionGenerator:
    """v1.2: LLM-backed question generation via llm_service."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30) -> None:
        from knowledge_mining.mining.llm_client import LlmClient
        self._client = LlmClient(base_url=base_url)
        self._timeout = timeout

    def generate(self, segment: RawSegmentData) -> list[str]:
        try:
            task_id = self._client.submit_task(
                template_key="mining-question-gen",
                variables={"title": segment.section_title or "", "content": segment.raw_text},
                caller_domain="mining",
                pipeline_stage="retrieval_units",
            )
            if task_id is None:
                return []
            result_text = self._client.poll_result(task_id, timeout=self._timeout)
            if result_text is None:
                return []
            import json
            items = json.loads(result_text)
            return [item["question"] for item in items if "question" in item]
        except Exception:
            return []
```

**Step 6: Run tests**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -k "llm_" -v`
Expected: All PASS

**Step 7: Full regression + commit**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v`

```bash
git add knowledge_mining/mining/llm_client.py knowledge_mining/mining/llm_templates.py knowledge_mining/mining/retrieval_units/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): LLM client + LlmQuestionGenerator + template for generated_question"
```

---

## Task 7: Pipeline — run.py 传递 seg_ids 和 source_segment_id

**Files:**
- Modify: `knowledge_mining/mining/jobs/run.py:272-353` (Stage 4-6 + writes)

**Step 1: Write the failing test**

```python
def test_pipeline_source_segment_id_end_to_end(tmp_path):
    """端到端 pipeline 产出的 retrieval_unit 都有 source_segment_id。"""
    # Create test corpus
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "test.md").write_text("# Test\n\nPDU会话管理功能是5G核心网中的关键控制面网络功能\n", encoding="utf-8")

    result = run(
        corpus,
        asset_core_db_path=tmp_path / "asset.sqlite",
        mining_runtime_db_path=tmp_path / "runtime.sqlite",
        phase1_only=True,
    )
    assert result["committed_count"] >= 1

    # Check retrieval units
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "asset.sqlite"))
    conn.row_factory = sqlite3.Row
    units = conn.execute("SELECT * FROM asset_retrieval_units WHERE source_segment_id IS NOT NULL").fetchall()
    assert len(units) > 0, "No retrieval units with source_segment_id"
    conn.close()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_pipeline_source_segment_id_end_to_end -v`
Expected: FAIL — no retrieval units with source_segment_id

**Step 3: Modify run.py**

在 Stage 5 (build_retrieval_units) 调用处：

```python
# 旧:
retrieval_units = build_retrieval_units(segments, document_key=doc_key)

# 新:
retrieval_units = build_retrieval_units(
    segments, seg_ids=seg_id_map, document_key=doc_key,
)
```

在写入 retrieval_units 循环中：

```python
# 旧:
asset_db.insert_retrieval_unit(
    unit_id=uuid.uuid4().hex,
    ...,
    # no source_segment_id
)

# 新:
asset_db.insert_retrieval_unit(
    unit_id=uuid.uuid4().hex,
    ...,
    source_segment_id=ru.source_segment_id,
)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_pipeline_source_segment_id_end_to_end -v`
Expected: PASS

**Step 5: Full regression + commit**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v`

```bash
git add knowledge_mining/mining/jobs/run.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): pipeline passes seg_ids and source_segment_id to retrieval units"
```

---

## Task 8: P2-1 — same_section 距离上限

**Files:**
- Modify: `knowledge_mining/mining/relations/__init__.py:81-89` (same_section loop)

**Step 1: Write the failing test**

```python
def test_same_section_distance_limit():
    """same_section 关系不应超过 max_distance。"""
    from knowledge_mining.mining.relations import build_relations

    # 20 segments in same section
    segments = []
    for i in range(20):
        segments.append(RawSegmentData(
            document_key="doc:/test.md", segment_index=i,
            block_type="paragraph", semantic_role="concept",
            section_path=[{"title": "S1", "level": 2}],
            section_title="S1",
            raw_text=f"segment {i}", content_hash=f"ch{i}", normalized_hash=f"nh{i}",
        ))

    relations, _ = build_relations(segments, max_distance=5)
    same_section = [r for r in relations if r.relation_type == "same_section"]
    # Without limit: C(20,2) = 190
    # With max_distance=5: 20*5 - (5*6/2) = ~85
    assert len(same_section) < 190, f"Too many same_section relations: {len(same_section)}"
    # All distances <= 5
    for r in same_section:
        assert r.distance is None or r.distance <= 5, f"distance {r.distance} > 5"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_same_section_distance_limit -v`
Expected: FAIL — Too many same_section relations

**Step 3: Modify relations/__init__.py**

1. `build_relations` 签名加 `max_distance: int = 5`
2. 修改 same_section 循环：

```python
# 旧:
for i in range(len(seg_keys)):
    for j in range(i + 1, len(seg_keys)):
        ...

# 新:
for i in range(len(seg_keys)):
    for j in range(i + 1, min(i + max_distance + 1, len(seg_keys))):
        ...
```

**Step 4: Run test + full regression + commit**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v`

```bash
git add knowledge_mining/mining/relations/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): same_section distance limit (max_distance=5)"
```

---

## Task 9: P2-2 — validate_build 真实校验

**Files:**
- Modify: `knowledge_mining/mining/publishing/__init__.py:71-144` (assemble_build)

**Step 1: Write the failing test**

```python
def test_validate_build_rejects_empty_build(tmp_path):
    """空 build 应无法通过 validate_build。"""
    from knowledge_mining.mining.publishing import validate_build
    asset_db, _, _ = _setup_dbs(tmp_path)
    # Create a build with no snapshots
    asset_db.insert_build(
        build_id="build-empty", build_code="B-EMPTY",
        status="building", build_mode="full",
    )
    asset_db.commit()

    with pytest.raises(ValueError, match="no active snapshots"):
        validate_build(asset_db, "build-empty")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_validate_build_rejects_empty_build -v`
Expected: FAIL — cannot import name 'validate_build'

**Step 3: Add validate_build to publishing**

```python
def validate_build(asset_db: AssetCoreDB, build_id: str) -> None:
    """Validate that a build has at least one active snapshot with segments."""
    snapshots = asset_db.get_build_snapshots(build_id)
    active = [s for s in snapshots if s["selection_status"] == "active"]
    if not active:
        raise ValueError(f"Build {build_id} has no active snapshots")
    for snap in active:
        count = asset_db.count_segments_by_snapshot(snap["document_snapshot_id"])
        if count == 0:
            raise ValueError(f"Snapshot {snap['document_snapshot_id']} has no segments")
```

在 `assemble_build` 中，`update_build_status(build_id, "validated")` 前调用 `validate_build`。

**Step 4: Run tests + commit**

```bash
git add knowledge_mining/mining/publishing/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): validate_build checks for active snapshots with segments"
```

---

## Task 10: P2-3 — entity_card 内容丰富化

**Files:**
- Modify: `knowledge_mining/mining/retrieval_units/__init__.py:139-167` (_make_entity_card_unit)

**Step 1: Write the failing test**

```python
def test_entity_card_includes_context():
    """entity_card 应包含实体周边上下文描述。"""
    seg = RawSegmentData(
        document_key="doc:/test.md", segment_index=0,
        raw_text="SMF是5G核心网中的会话管理功能，负责PDU会话的建立和释放",
        content_hash="ch", normalized_hash="nh",
        entity_refs_json=[{"type": "network_function", "name": "SMF"}],
        section_title="SMF功能",
    )
    units = build_retrieval_units([seg], document_key="doc:/test.md")
    cards = [u for u in units if u.unit_type == "entity_card"]
    assert len(cards) == 1
    # Should contain context beyond just name and type
    assert "5G" in cards[0].text or "会话管理" in cards[0].text or "SMF功能" in cards[0].text
    assert cards[0].text != "SMF (network_function) — 见 SMF功能"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_entity_card_includes_context -v`
Expected: FAIL — entity_card text doesn't include context

**Step 3: Modify _make_entity_card_unit**

```python
def _extract_entity_context(name: str, raw_text: str, window: int = 80) -> str:
    """Extract text around entity mention for context."""
    idx = raw_text.find(name)
    if idx < 0:
        return ""
    start = max(0, idx - window // 2)
    end = min(len(raw_text), idx + len(name) + window // 2)
    ctx = raw_text[start:end].strip()
    if start > 0:
        ctx = "..." + ctx
    if end < len(raw_text):
        ctx = ctx + "..."
    return ctx
```

修改 `_make_entity_card_unit` 中的 text 构建：

```python
# 旧:
text = f"{entity_name} ({entity_type})"
if seg.section_title:
    text += f" — 见 {seg.section_title}"

# 新:
description = _extract_entity_context(entity_name, seg.raw_text)
text = f"{entity_name}（{entity_type}）"
if description:
    text += f" {description}"
elif seg.section_title:
    text += f" — 见 {seg.section_title}"
```

**Step 4: Run tests + commit**

```bash
git add knowledge_mining/mining/retrieval_units/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): entity_card includes entity context from raw text"
```

---

## Task 11: P2-4 — UPDATE 场景清理旧数据

**Files:**
- Modify: `knowledge_mining/mining/jobs/run.py:229-332` (UPDATE branch)

**Step 1: Write the failing test**

```python
def test_update_cleanup_old_data(tmp_path):
    """UPDATE 场景应清理旧 snapshot 下的数据。"""
    import sqlite3

    # First run: create document
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "test.md").write_text("# V1\n\nFirst version content\n", encoding="utf-8")

    result1 = run(
        corpus,
        asset_core_db_path=tmp_path / "asset.sqlite",
        mining_runtime_db_path=tmp_path / "runtime.sqlite",
        phase1_only=True,
    )
    assert result1["committed_count"] == 1

    conn = sqlite3.connect(str(tmp_path / "asset.sqlite"))
    segments_v1 = conn.execute("SELECT COUNT(*) FROM asset_raw_segments").fetchone()[0]

    # Second run: update document (changed content)
    (corpus / "test.md").write_text("# V2\n\nUpdated content with more text\n", encoding="utf-8")

    result2 = run(
        corpus,
        asset_core_db_path=tmp_path / "asset.sqlite",
        mining_runtime_db_path=tmp_path / "runtime.sqlite",
        phase1_only=True,
    )
    assert result2["committed_count"] == 1

    # Old snapshot's data should be cleaned
    segments_v2 = conn.execute("SELECT COUNT(*) FROM asset_raw_segments").fetchone()[0]
    # Should not be 2x (no data doubling)
    assert segments_v2 <= segments_v1 + 5, f"Data doubled: {segments_v2} vs {segments_v1}"
    conn.close()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_update_cleanup_old_data -v`
Expected: FAIL — data doubled

**Step 3: Modify run.py UPDATE branch**

在 `select_or_create_snapshot` 返回后、写入 segments 之前，加入清理逻辑：

```python
# After select_or_create_snapshot, before writing segments:
if action == "UPDATE":
    # Clean old data under the new snapshot (if it reuses an existing one)
    existing_snap = asset_db._fetchone(
        "SELECT document_snapshot_id FROM asset_document_snapshot_links "
        "WHERE document_id = ? ORDER BY created_at DESC LIMIT 1 OFFSET 1",
        (document_id,),
    )
    if existing_snap:
        old_snap_id = existing_snap["document_snapshot_id"]
        asset_db.delete_retrieval_units_by_snapshot(old_snap_id)
        asset_db.delete_relations_by_snapshot(old_snap_id)
        asset_db.delete_segments_by_snapshot(old_snap_id)
        asset_db.commit()
```

**Step 4: Run tests + commit**

```bash
git add knowledge_mining/mining/jobs/run.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): UPDATE scenario cleans old snapshot data"
```

---

## Task 12: P2-5 — enrich batch-capable 接口

**Files:**
- Modify: `knowledge_mining/mining/enrich/__init__.py:36-39` (Enricher Protocol)

**Step 1: Write the failing test**

```python
def test_enricher_protocol_has_enrich_batch():
    """Enricher Protocol 必须有 enrich_batch 方法。"""
    from knowledge_mining.mining.enrich import Enricher

    class TestEnricher:
        def enrich(self, segments, **kwargs):
            return segments
        def enrich_batch(self, segments, **kwargs):
            return segments

    assert isinstance(TestEnricher(), Enricher)


def test_rule_based_enricher_has_enrich_batch():
    """RuleBasedEnricher 必须有 enrich_batch 方法。"""
    from knowledge_mining.mining.enrich import RuleBasedEnricher
    enricher = RuleBasedEnricher()
    assert hasattr(enricher, "enrich_batch")
    segs = [RawSegmentData(
        document_key="doc:/t.md", segment_index=0,
        raw_text="test", content_hash="ch", normalized_hash="nh",
    )]
    result = enricher.enrich_batch(segs)
    assert len(result) == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py::test_enricher_protocol_has_enrich_batch -v`
Expected: FAIL — enrich_batch not in Protocol

**Step 3: Modify Enricher Protocol + RuleBasedEnricher**

```python
@runtime_checkable
class Enricher(Protocol):
    """Protocol for the enrich stage. v1.2 LLM implementation replaces this."""
    def enrich(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...
    def enrich_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]: ...
```

在 `RuleBasedEnricher` 中添加：

```python
def enrich_batch(self, segments: list[RawSegmentData], **kwargs: Any) -> list[RawSegmentData]:
    """Default batch: call enrich on full list."""
    return self.enrich(segments, **kwargs)
```

**Step 4: Run tests + commit**

```bash
git add knowledge_mining/mining/enrich/__init__.py knowledge_mining/tests/test_v11_pipeline.py
git commit -m "[claude-mining]: feat(v1.2): enrich Protocol adds enrich_batch for LLM batch support"
```

---

## Task 13: Full Regression + Acceptance

**Step 1: Run all tests**

Run: `python -m pytest knowledge_mining/tests/test_v11_pipeline.py -v --tb=short`
Expected: All tests PASS (30+ original + ~15 new)

**Step 2: Run end-to-end with real corpus**

```python
from knowledge_mining.mining.jobs.run import run

result = run(
    "data/knowledge_base",
    asset_core_db_path="test_v12.sqlite",
    mining_runtime_db_path="test_v12_runtime.sqlite",
)
print(result)
```

**Step 3: Verify acceptance criteria**

```python
import sqlite3
conn = sqlite3.connect("test_v12.sqlite")
conn.row_factory = sqlite3.Row

# 1. source_segment_id: every unit has non-null
units = conn.execute("SELECT COUNT(*) FROM asset_retrieval_units WHERE source_segment_id IS NOT NULL").fetchone()[0]
total = conn.execute("SELECT COUNT(*) FROM asset_retrieval_units").fetchone()[0]
print(f"source_segment_id: {units}/{total} units")

# 2. search_text is tokenized (has spaces)
samples = conn.execute("SELECT search_text FROM asset_retrieval_units LIMIT 10").fetchall()
for s in samples:
    assert " " in s["search_text"], f"Not tokenized: {s['search_text'][:50]}"

# 3. same_section count reasonable
rels = conn.execute("SELECT COUNT(*) FROM asset_raw_segment_relations WHERE relation_type='same_section'").fetchone()[0]
print(f"same_section relations: {rels}")

conn.close()
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "[claude-mining]: feat(v1.2): v1.2 Mining Retrieval View Layer complete — all 9 items delivered"
```

---

## Implementation Order Summary

| Task | Item | Files | New Tests |
|------|------|-------|-----------|
| 1 | Schema source_segment_id | schema SQL | 1 |
| 2 | DB layer support | db.py | 2 |
| 3 | Model field | models.py | 2 |
| 4 | P1-1 retrieval_units bridge | retrieval_units/ | 2 |
| 5 | P1-2 jieba tokenization | text_utils.py, retrieval_units/ | 3 |
| 6 | P1-3+4 LLM client | llm_client.py, llm_templates.py, retrieval_units/ | 4 |
| 7 | Pipeline integration | jobs/run.py | 1 |
| 8 | P2-1 same_section limit | relations/ | 1 |
| 9 | P2-2 validate_build | publishing/ | 1 |
| 10 | P2-3 entity_card enrich | retrieval_units/ | 1 |
| 11 | P2-4 UPDATE cleanup | jobs/run.py | 1 |
| 12 | P2-5 enrich batch | enrich/ | 2 |
| 13 | Regression + acceptance | — | — |

**Total: 13 tasks, ~21 new tests, 9 implementation items**
