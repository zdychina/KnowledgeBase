# LLM-first Segmenter 实现计划

- 任务：TASK-20260421-v11-knowledge-mining
- 日期：2026-05-07
- 作者：Claude

## 1. 任务目标

把 mining 流水线的 segment 阶段从"纯规则切段"升级为"LLM 优先 + 规则兜底"，在 LLM 服务可用时由 LLM 决定段落边界，不可用或失败时无缝回落到现有 `DefaultSegmenter` 的行为。

## 2. 当前实现回顾

- `knowledge_mining/mining/stages/segment.py:18-33` `DefaultSegmenter` 是当前唯一实现
- `_walk_sections` 走 `SectionNode` 树时按确定规则切段：
  - 章节标题（`block.level > 0`）→ 独立 heading 段
  - `heading` block → 独立段
  - `table / html_table / code / list / blockquote` → 各自独立段
  - 连续 `paragraph` block → 合并为一段
- 该阶段无 LLM 调用；后续 enrich 阶段才接 LLM

## 3. 设计决策

### 3.1 LLM 只决定 paragraph 段的边界

**决定**：保留所有结构性切段规则不变，只把"连续 paragraph 合并"这一步交给 LLM。

**理由**：
- heading / table / code / list 是文档解析层确定的原子单元，让 LLM 决定是否拆分会损失结构信息（line_start/line_end、structure_json）
- LLM 真正能贡献价值的是"主题不同的多个段落是否应拆开"或"短段落是否应该合并"
- 缩小 LLM 决策面 → prompt 更聚焦、token 更少、可回落点明确

### 3.2 prompt 与输出契约

- 新模板 `mining-segment-boundary`，模板版本 `"1"`
- 输入：
  - `section_title`：所在 section 标题（可空）
  - `paragraphs`：JSON 数组，每个元素 `{"index": 整数, "preview": 段落前 240 字}`
- 输出 JSON：
  ```json
  {"groups": [[0,1], [2,2], [3,5]]}
  ```
  - 每个内层数组是 `[start_idx, end_idx]`（**闭区间**），按起始升序排列
  - 必须正好覆盖 0..N-1 全部 paragraph 索引
  - 不允许重叠或留空

### 3.3 LlmSegmenter 行为

- 新类 `LlmSegmenter(stage_name="segment", stage_version="2")` 与 `DefaultSegmenter` 同地共存于 `stages/segment.py`
- 内部仍走与默认实现相同的 `_walk_sections` 骨架：headings/tables/code/list 的处理完全不变
- 唯一区别：每次需要 flush 一组 paragraph（≥2 个 block）时调用 LLM
  - **段数 < 2**：直接走默认合并（无意义调用 LLM）
  - LLM 失败、返回非法分组（覆盖不全 / 索引越界 / 顺序错） → 退回"全部合并为一段"的默认行为
- 单段（≥1 token 数 / 段太短）的 LLM 调用阈值通过参数 `min_paragraph_count_for_llm`（默认 2）控制

### 3.4 不接管的场景

- heading 段、table 段、code 段、list 段、blockquote 段：**不调用 LLM**
- 输出 `RawSegmentData` 的字段构造规则（hash/token_count/section_path/structure_json/source_offsets_json）完全沿用现有 `_make_segment` / `_make_heading_segment`

## 4. 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `knowledge_mining/domain_packs/cloud_core_network/domain.yaml` | 新增 | 追加 `mining-segment-boundary` 模板 |
| `knowledge_mining/mining/stages/segment.py` | 修改 | 新增 `LlmSegmenter` 类 + 内部辅助函数 `_llm_split_paragraph_run` |
| `knowledge_mining/mining/jobs/run.py` | 修改 | `_init_llm` 中创建 `LlmSegmenter`；`PipelineConfig.segmenter` 使用 `llm.get("segmenter") or DefaultSegmenter()` |
| `knowledge_mining/tests/test_pipeline_operators.py` | 新增测试 | `TestLlmSegmenter`：mock LLM 返回有效分组 / 非法分组 / 健康检查失败 |

## 5. 验证

- `pytest knowledge_mining/tests/test_pipeline_operators.py -v` 全部通过
- `pytest knowledge_mining/tests` 全量回归通过
- 新增 3 个测试用例：
  1. 有效 groups 返回 → 段落按 LLM 拆分
  2. 非法 groups（覆盖不全） → 回落到全合并
  3. LLM 调用抛异常 → 回落

## 6. 不在本次范围

- parse / relations 阶段的 LLM 化
- LlmEnricher 与规则元数据合并陷阱（heading_role/table_column_count）—— 后续单独修
- 模板的多 domain pack 适配（仅在 cloud_core_network 加，其他 pack 沿用规则版即可）
- DB schema 改动（segment 阶段产出仍是 `asset_raw_segments`，无新字段）

## 7. 风险

| 风险 | 缓解 |
|---|---|
| LLM 输出的 groups 不合法导致段落丢失 | 严格校验：覆盖 0..N-1、无重叠、有序；任一不满足全部回落 |
| 每段调用一次 LLM 导致 mining 整体变慢 | 仅在 paragraph_count ≥ 2 时调用；后续可加并发 / 缓存优化（不在本次范围） |
| 段边界变化导致 content_hash 不稳，触发重复 build | 与 v1.1 既定行为一致：切段策略变化本就期望产生新 segment_id；snapshot 比对会识别为更新 |

## 8. 依赖

- llm_service 已有 `submit_task` / `poll_all` 接口，无需改动
- DomainProfile 模板自动注册路径已在 `_init_llm` 中处理（`build_templates_from_profile` + `client.register_template`）
