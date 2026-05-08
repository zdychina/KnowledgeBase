# LLM-first Segmenter Handoff

- 任务：TASK-20260421-v11-knowledge-mining
- 日期：2026-05-07
- 作者：Claude
- 配套 plan：`docs/plans/2026-05-07-llm-first-segmenter-impl-plan.md`

## 1. 任务目标

把 mining 流水线的 segment 阶段升级为 "LLM 优先 + 规则兜底"。LLM 服务可达时由 LLM 决定连续 paragraph block 的边界；不可达或返回非法分组时无缝回落到既有 `DefaultSegmenter`（v1.1）的"全部合并为一段"行为。

## 2. 本次实现范围

- 新增 LLM 模板 `mining-segment-boundary`（template_version=1，`json_object` 输出，schema 含 `groups: [[start,end],...]`）
- 重构 `_walk_sections` 让 paragraph 段的分组策略可注入（`ParagraphGrouper` 函数类型）
- 新增 `LlmSegmenter`（stage_name=`segment`，stage_version=`2`），通过 `mining-segment-boundary` 模板调用 LLM 决定段落边界
- 在 `_init_llm()` 中按现有套路尝试创建 `LlmSegmenter`，挂到 `result["segmenter"]`
- 在 `PipelineConfig` 装配处用 `llm.get("segmenter") or DefaultSegmenter()` 实现"有 LLM 用 LLM、否则用规则"
- 在 `tests/test_pipeline_operators.py` 新增 `TestLlmSegmenter` 测试类（4 用例）

## 3. 不在本次范围

- parse / relations 阶段的 LLM 化
- LlmEnricher 与规则元数据合并陷阱（heading_role / table_column_count 在 LLM 路径丢失）—— 单独跟进
- 多 domain pack 同步增加 `mining-segment-boundary` 模板（仅在 cloud_core_network 加，其他 pack 自然走规则）
- 段落分组 LLM 调用的并发优化 / 缓存（每 section 串行一次，后续可观测后再调）
- DB schema 改动（segment 阶段产出仍是 `asset_raw_segments`，无新字段）

## 4. 改动文件清单

| 文件 | 改动 |
|---|---|
| `knowledge_mining/domain_packs/cloud_core_network/domain.yaml` | 新增 `mining-segment-boundary` 模板 |
| `knowledge_mining/mining/stages/segment.py` | 新增 `LlmSegmenter`、`ParagraphGrouper` 类型、`_safe_group`、`_validate_groups`、`_default_paragraph_grouper`；`segment_document` / `_walk_sections` 增加 `paragraph_grouper` 参数 |
| `knowledge_mining/mining/jobs/run.py` | `_init_llm` 新建 `LlmSegmenter` 注入 `result["segmenter"]`；`PipelineConfig.segmenter` 改为 `llm.get("segmenter") or DefaultSegmenter()` |
| `knowledge_mining/tests/test_pipeline_operators.py` | 新增 `TestLlmSegmenter`（4 用例：LLM 拆分 / 非法 groups 回落 / LLM 异常回落 / 单段不调 LLM） |
| `docs/plans/2026-05-07-llm-first-segmenter-impl-plan.md` | 新增 plan 文档 |
| `docs/handoffs/2026-05-07-llm-first-segmenter-claude-handoff.md` | 本文档 |

## 5. 关键设计决策

### 5.1 LLM 只决定 paragraph 边界

结构性切段（heading / table / html_table / code / list / blockquote 各自独立段）保持规则化，原因：

- 这些是 parse 阶段已确定的原子单元，LLM 拆分会损失 `structure_json` / `line_start` / `line_end`
- LLM 真正能贡献价值的是"主题不同的多个段落是否应拆开"或"短段落是否应合并"
- 缩小 LLM 决策面 → prompt 聚焦、token 少、可回落点明确

### 5.2 严格的输出契约 + 防御性校验

`_validate_groups` 强校验：

- 必须是 list[ list/tuple ]
- 每个分组是 `[start, end]` 整数
- 必须从 `0` 开始严格递增、无重叠、无空隙、`end < n`
- 任一检查失败 → 调用方 `_safe_group` 退回 `[(0, n-1)]`（合并所有 paragraph，等价 v1.1 行为）

### 5.3 单段（n<2）不触发 LLM

`LlmSegmenter._llm_grouper` 在 `n < min_paragraph_count_for_llm`（默认 2）时直接返回 `None`，避免无意义调用。

### 5.4 与既有 LLM 接缝套路一致

仿照 `LlmEnricher`：

- 通过 `LlmClient.submit_task` + `poll_result` 异步流程
- 模板从 DomainProfile 加载，`_init_llm` 中走 `client.register_template`
- 服务不可达时 `_init_llm` 返回 `None`，整段流水线降级到规则版

## 6. 已执行验证

### 6.1 LlmSegmenter 单元测试（独立脚本验证）

由于 `tests/conftest.py` 强制连接生产 PG 并对全表 `TRUNCATE`，本次未在该 PG 上跑 pytest。采用独立 Python 脚本验证 `LlmSegmenter` 4 个核心场景，全部通过：

- ✅ DefaultSegmenter 行为不变（`# Doc + 3 paragraphs` 仍合并为 1 段）
- ✅ LlmSegmenter + 有效 groups `[[0,1],[2,2]]` → 3 段切成 2 段，文本顺序与原始一致
- ✅ LlmSegmenter + 非法 groups（缺索引 2） → 回落到合并 1 段
- ✅ LlmSegmenter + LLM 抛异常 → 回落到合并 1 段
- ✅ 单段 paragraph → 完全不调用 LLM（`submitted == []`）

### 6.2 `_validate_groups` 边界测试

```
[[0,1],[2,2]] / n=3 → True
[[0,2]] / n=3 → True
[[0,1]] / n=3 → False  # gap
[[0,2],[1,2]] / n=3 → False  # overlap
[[1,2]] / n=3 → False  # missing 0
[] / n=3 → False
[[0,3]] / n=3 → False  # out of range
```

### 6.3 复杂结构性 doc 回归

输入含 heading/paragraph/heading/paragraph/table/paragraph 的 markdown，DefaultSegmenter 输出仍为 6 段，与重构前一致。

## 7. 未验证项

- **未跑全量 pytest**：conftest.py 的 PG fixture 会对生产 mining 表 TRUNCATE，本机环境下不安全。需要管理员或 Codex 在隔离 PG 实例上跑：
  ```
  pytest knowledge_mining/tests/test_pipeline_operators.py -v
  pytest knowledge_mining/tests -v
  ```
- **未做端到端 mining 跑批**：无法在本工作树触达真实 LLM Service + PG。需要在 dev 环境用真实 LLM 服务跑一次 mining，确认：
  - LLM 路径下 `mining_run_stage_events` 中 `segment` 阶段记录正常
  - LLM 拆分后产出的 `asset_raw_segments` 行数变化合理
  - 段落 `content_hash` 因边界变化而更新，触发 build snapshot diff（预期内）

## 8. 已知风险

| 风险 | 缓解 |
|---|---|
| LLM 输出 groups 不合法导致段落丢失 | `_validate_groups` 严格校验：覆盖 0..N-1、无重叠、有序；任一不满足全部回落 |
| 每 section 一次 LLM 调用导致 mining 整体变慢 | 仅在 paragraph_count ≥ 2 时调用；后续可加并发 / 缓存（不在本次范围） |
| 段边界变化导致 content_hash 不稳，重复 build | 切段策略变化本就期望产生新 segment_id；snapshot 比对会识别为更新，与 v1.1 既定行为一致 |
| 其他 domain pack（如未来加入的）未注册 `mining-segment-boundary` | `_init_llm` 中模板注册按 profile 进行，未注册 pack 的 LlmSegmenter 调用会失败 → 自动回落到规则；无破坏性 |

## 9. 指定给 Codex 的审查重点

1. **`_validate_groups` 的完备性**：是否有让坏分组通过的边界情形（负索引？重复同一索引？非整数？）
2. **`_walk_sections` 重构等价性**：DefaultSegmenter 路径下是否在所有原有用例（嵌套 section、空 section、heading 后紧跟 table 等）保持与 v1.1 完全一致
3. **`LlmSegmenter` 的失败路径**：`submit_task` 返回 None / `poll_result` 返回 None / 返回 list 但首元素不是 dict / 返回 dict 但 groups 字段缺失，是否都正确回落
4. **接入点**：`_init_llm` 的 try/except 范围是否过宽（吞掉真实 bug）；`segmenter=llm.get("segmenter") or DefaultSegmenter()` 是否需要在配置层显式开关
5. **模板 schema**：`output_schema_json` 是否能在 llm_service 端正确约束 LLM 输出（特别是 `[start, end]` 二元数组的 minItems/maxItems）

## 10. 管理员本轮直接介入记录

- 用户提出"先把 segment 阶段变成用 LLM 切段"，本轮直接落实
- 用户先期讨论了"所有阶段 LLM 优先"的范围，已与用户对齐为本轮只做 segment（plan 文档第 6 节"不在本次范围"）
