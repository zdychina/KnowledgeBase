# Stage 7 — DB 写入与构建发布

> 审查文档 | 2026-05-21

---

## 1. 职责概述

DB 写入与构建发布负责：
1. **Phase 1c**: 将 StreamingPipeline 产出的 segments/relations/retrieval_units 写入 PostgreSQL
2. **Phase 2**: 组装 build、校验、发布 release
3. 生成 embedding 向量并存储
4. 管理文档快照的增量更新

**关键特性**：
- Phase 1c 在主线程串行执行（无并发）
- Phase 2 是全局操作（非文档级），在所有文档写入完成后执行
- 支持全量构建和增量构建

---

## 2. Phase 1c: DB 写入 (run.py:566-741)

### 2.1 整体流程

```
for item in work_items:
    ctx = ctxs[i]

    1. 检查 ctx.error → fail_document + continue
    2. 检查 ctx.tree is None → skip_document + continue
    3. try:
       a. select_snapshot          — 选择/创建文档快照
       b. UPDATE 清理旧快照数据     — 删除旧 snapshot 的 segments/relations/units
       c. commit_segments          — 逐条 INSERT segments
       d. build_relations          — 逐条 INSERT relations
       e. build_retrieval_units    — 逐条 INSERT units
       f. embed_batch + INSERT     — 生成并存储 embedding
       g. tracker.commit_document  — 标记文档完成
    4. except → fail_document
```

### 2.2 select_snapshot (stage 6)

```python
document_id, snapshot_id, link_id = select_or_create_snapshot(
    asset_db, doc, doc_profile, batch_id=batch_id,
)
```

- 创建或关联文档快照
- 返回 `document_id`, `snapshot_id`, `link_id`
- 产出写入 `asset_documents` + `asset_document_snapshots` + `asset_document_snapshot_links`

### 2.3 UPDATE 清理

```python
if action == "UPDATE" and existing_doc is not None:
    old_links = asset_db._fetchall(...)
    for old_link in old_links[1:]:  # 保留最新的一条
        asset_db.delete_retrieval_units_by_snapshot(old_snap_id)
        asset_db.delete_relations_by_snapshot(old_snap_id)
        asset_db.delete_segments_by_snapshot(old_snap_id)
```

- 只清理**超出最新一条**的旧 snapshot 数据
- 删除顺序: retrieval_units → relations → segments (避免外键冲突)
- **问题**: 如果只有一个旧 snapshot (len == 1)，不清理任何数据

### 2.4 commit_segments (stage 7)

```python
for seg in segments:
    seg_key = f"{seg.document_key}#{seg.segment_index}"
    seg_id = seg_id_map.get(seg_key, uuid.uuid4().hex)  # fallback UUID
    asset_db.insert_raw_segment(
        segment_id=seg_id,
        document_snapshot_id=snapshot_id,
        segment_key=seg_key,
        segment_index=seg.segment_index,
        block_type=seg.block_type,
        semantic_role=seg.semantic_role,
        section_path=seg.section_path,
        section_title=seg.section_title,
        raw_text=seg.raw_text,
        normalized_text=seg.normalized_text,
        content_hash=seg.content_hash,
        normalized_hash=seg.normalized_hash,
        token_count=seg.token_count,
        structure_json=seg.structure_json,
        source_offsets_json=seg.source_offsets_json,
        entity_refs_json=seg.entity_refs_json,
        metadata_json=seg.metadata_json,
    )
```

- 每条 segment 单独 INSERT (无 batch insert)
- `seg_id` 从 `seg_id_map` 取 (build_seg_ids 生成)，无则 fallback 生成
- `section_path` 是 Python list，DB 层需要转为 JSON

### 2.5 build_relations (stage 8)

```python
for rel in relations:
    src_id = seg_id_map.get(rel.source_segment_key, "")
    tgt_id = seg_id_map.get(rel.target_segment_key, "")
    if src_id and tgt_id:
        asset_db.insert_segment_relation(
            relation_id=uuid.uuid4().hex,
            document_snapshot_id=snapshot_id,
            source_segment_id=src_id,
            target_segment_id=tgt_id,
            relation_type=rel.relation_type,
            weight=rel.weight,
            confidence=rel.confidence,
            distance=rel.distance,
            metadata_json=rel.metadata_json,
        )
```

- 如果 source/target 的 seg_id 找不到 → **静默跳过**该关系
- `relation_id` 是新生成的 UUID

### 2.6 build_retrieval_units (stage 9)

```python
ru_id_map: dict[str, str] = {}
for ru in retrieval_units:
    unit_id = uuid.uuid4().hex
    ru_id_map[ru.unit_key] = unit_id
    asset_db.insert_retrieval_unit(
        unit_id=unit_id,
        document_snapshot_id=snapshot_id,
        unit_key=ru.unit_key,
        unit_type=ru.unit_type,
        ...  # 所有 RetrievalUnitData 字段
    )
```

- 维护 `ru_id_map` 供后续 embedding 写入使用

### 2.7 Embedding 生成

```python
if embedding_generator is not None and retrieval_units:
    texts_to_embed = [ru.text for ru in retrieval_units if ru.text]
    embeddings = embedding_generator.embed_batch(texts_to_embed)
    for unit_key, text, embedding_vec in zip(unit_keys, texts, embeddings):
        asset_db.insert_retrieval_embedding(
            embedding_id=uuid.uuid4().hex,
            retrieval_unit_id=ru_id_map[unit_key],
            embedding_model=embedding_generator.model_name,
            embedding_provider="zhipu",      # 硬编码!
            text_kind="full",
            embedding_dim=len(embedding_vec),
            embedding_vector=json.dumps(embedding_vec),
            content_hash="",
        )
```

- `embedding_provider` 硬编码为 `"zhipu"`
- `content_hash` 硬编码为空字符串
- `text_kind` 硬编码为 `"full"`
- embedding 失败不阻塞：外层 try-except 捕获后 warning

### 2.8 commit 策略

```python
asset_db.commit()   # 在 segments/relations/units 写完后
                    # 在 embedding 写完后
runtime_db.commit() # 在 tracker.commit_document 后
                    # 在 fail_document 后
```

**问题**: 多处手动 commit，异常路径可能遗漏或重复。

---

## 3. Phase 2: Build & Publish (run.py:743-791)

### 3.1 整体流程

```
Phase 2 (only if not phase1_only and snapshot_decisions):
  1. classify_documents()   — NEW/UPDATE/SKIP/REMOVE
  2. assemble_build()       — 创建 build, 合并 snapshot
  3. validate_build()       — 校验质量
  4. demo_quality_summary() — 质量报告 (非阻塞)
  5. publish_release()      — 发布激活
```

### 3.2 classify_documents (publishing.py:28)

**职责**: 将当前 run 的 snapshot_decisions 与上一个 active build 比较。

| Action | 条件 | 说明 |
|--------|------|------|
| `NEW` | doc_id 不在 prev_build 中 | 新文档 |
| `UPDATE` | doc_id 存在但 snapshot_id 变了 | 文档有变更 |
| `SKIP` | doc_id 存在且 snapshot_id 相同 | 无变更 |
| `REMOVE` | prev_build 有但当前 run 没有 | 文档被删除 |

**注意**: REMOVE 检测默认关闭 (`detect_remove=False`)，因为增量 batch 只处理部分文档。

### 3.3 assemble_build (publishing.py:111)

```python
# 自动判断构建模式
build_mode = "full" if no prev_build else "incremental"

# 创建 build 记录
asset_db.insert_build(
    build_id, build_code="B-XXXXXXXX",
    status="building",
    build_mode, domain, parent_build_id,
    summary_json={snapshot_count, removed_count, action_counts},
)

# 增量合并: 继承父 build 中未被本次覆盖的 snapshot
if parent_build_id:
    for ps in parent_snapshots:
        if ps["document_id"] not in decided_doc_ids:
            asset_db.upsert_build_document_snapshot(..., reason="retain")

# 写入本次决策
for decision in snapshot_decisions:
    asset_db.upsert_build_document_snapshot(...)
```

**增量构建策略**:
1. 从父 build 继承所有 snapshot (reason="retain")
2. 覆盖本次 run 的 NEW/UPDATE snapshot
3. 标记 REMOVE 的 snapshot 为 "removed"

### 3.4 validate_build (publishing.py:190)

**校验规则**:
1. Build 存在
2. 增量 build 的 parent build 存在
3. 至少有一个 active snapshot
4. 每个 active snapshot 至少有一个 segment

**问题**: 校验很基础，不检查 retrieval_units、relations、embedding 的完整性。

### 3.5 publish_release (publishing.py:222)

```python
# 校验 build 状态
if build.status not in ("validated", "published"):
    raise ValueError(...)

# 创建 release
asset_db.insert_release(
    release_id, release_code="R-XXXXXXXX",
    build_id, domain, channel="prod",
    status="staging",
    previous_release_id,
)

# 激活: 退役旧 release, 激活新 release
asset_db.activate_release(release_id)
```

**channel 默认 "prod"**: 发布到生产频道。

**发布前提**:
- Build 状态 = validated
- Build 的 domain 匹配
- 无文档失败 或 `publish_on_partial_failure=True`

### 3.6 demo_quality_summary (publishing.py:271)

非阻塞的质量报告：
- 统计 unit_type 分布
- 检查 generated_question 数量 (0 时警告)
- 检查问题是否还带 Qn 前缀
- 统计 RST 关系类型分布

---

## 4. 运行状态判定 (run.py:793-810)

```python
if failed_count > 0 and committed_count == 0:
    run_status = "failed"            # 全部失败
elif failed_count > 0:
    run_metadata = {"has_failures": True}  # 部分失败
    run_status = "completed"
else:
    run_status = "completed"         # 全部成功
```

---

## 5. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/jobs/run.py:566-810` | ~245 | Phase 1c DB 写入 + Phase 2 build/publish |
| `mining/stages/publishing.py` | ~300 | classify_documents, assemble_build, validate_build, publish_release |
| `mining/infra/db.py` | — | AssetCoreDB (所有 INSERT/DELETE/SELECT 操作) |
| `mining/snapshot.py` | — | select_or_create_snapshot |
| `mining/runtime.py` | — | RuntimeTracker (stage events, run/document 状态) |

---

## 6. 工业化参考

| 参考 | 说明 |
|------|------|
| Apache Airflow DAG | DAG 编排 + 重试，我们用串行 pipeline |
| dbt (data build tool) | 增量构建 + 物化视图，我们的 assemble_build 类似 |
| Flyway / Liquibase | 数据库版本管理，我们的 build/release 类似 |
| Feature Store (Feast/Tecton) | 特征版本管理 + 发布，我们的 snapshot/build/release 类似 |
| Kubernetes Rolling Update | 增量更新 + 回滚，我们的 release 链支持回滚 |
| CI/CD (GitHub Actions) | build → validate → deploy 流程 |

---

## 7. 当前不足

1. **逐条 INSERT 无 batch**: segments/relations/units 每条一个 INSERT，大文档时性能差（应使用 batch insert 或 COPY）
2. **手动 commit 管理**: 多处 `asset_db.commit()` + `runtime_db.commit()`，异常路径可能遗漏或重复
3. **embedding_provider 硬编码**: `"zhipu"` 写死，不支持其他 embedding 提供者
4. **content_hash 为空**: embedding 记录的 content_hash 总是空字符串，无法做增量检测
5. **UPDATE 清理逻辑有问题**: 只清理 `old_links[1:]` (超出最新的)，但最新那个旧 snapshot 的数据不清理，可能导致新旧数据混合
6. **segment_id fallback**: 如果 seg_id_map 中找不到 key，fallback 生成新 UUID，但这会导致后续 relation 的 seg_id_map 查找也失败
7. **relation 静默丢弃**: source/target 的 seg_id 找不到时静默跳过，不记录丢弃了多少条
8. **无事务隔离**: 每个文档独立 commit，如果中途失败，前面的文档已经入库，后面的丢失，数据不完整
9. **validate_build 过于简单**: 只检查 snapshot 和 segment 存在性，不检查 retrieval_units、embedding 的完整性
10. **Phase 1c 串行瓶颈**: 所有文档在主线程串行写入 DB，大 batch 时是性能瓶颈
11. **demo_quality_summary 使用 _fetchall**: 使用内部 `_fetchall` 方法而非公共 API，违反封装
12. **publish_on_partial_failure 无用户控制**: 该参数从 run() 传入但调用链上看不出用户如何配置
13. **无回滚机制**: 发布后发现问题无法回滚到上一个 release (虽然有 previous_release_id 但无回滚 API)
