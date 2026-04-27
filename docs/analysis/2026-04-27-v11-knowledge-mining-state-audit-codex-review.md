# TASK-20260421-v11-knowledge-mining Current-State Audit

## 审查背景

- 任务：`TASK-20260421-v11-knowledge-mining`
- 本轮目标：在已单独确认 `llm_service` 基本可用的前提下，重新审视 `knowledge_mining` 的当前实现、历史提交链、状态流转、以及与 `llm_service` / `agent_serving` 的协同是否达到最初要求。
- 用户重点关注：
  - Mining 是否真正支持“一批次全部丢进来，由 LLM worker 逐个取任务”
  - 当前每个 state 的真实现状
  - 各阶段与外部组件的协同是否正确

## 审查范围

- 历史提交链：`037703f` 到 `d88b04e`
- 重点模块：
  - `knowledge_mining/mining/jobs/run.py`
  - `knowledge_mining/mining/pipeline.py`
  - `knowledge_mining/mining/db.py`
  - `knowledge_mining/mining/runtime/__init__.py`
  - `knowledge_mining/mining/ingestion/__init__.py`
  - `knowledge_mining/mining/snapshot/__init__.py`
  - `knowledge_mining/mining/enrich/__init__.py`
  - `knowledge_mining/mining/relations/__init__.py`
  - `knowledge_mining/mining/retrieval_units/__init__.py`
  - `knowledge_mining/mining/publishing/__init__.py`
- 相关测试：
  - `knowledge_mining/tests/test_v11_pipeline.py`
  - `knowledge_mining/tests/test_pipeline_operators.py`
  - `knowledge_mining/tests/test_v12_e2e_live.py`
- 相关契约：
  - `databases/asset_core/schemas/001_asset_core.sqlite.sql`
  - `databases/mining_runtime/schemas/001_mining_runtime.sqlite.sql`

## 结论摘要

- 当前 `knowledge_mining` 不是“完全达标可验收”状态。
- 它已经具备可运行的单次全量主链，也已经接入了部分 LLM 能力，但没有达到“稳定增量运行 + 真实状态可追踪 + 对 Serving/LLM 的合同完全收口”的要求。
- 当前最严重的问题不是 stage 内部算法，而是：
  - 第二次增量 run 会直接崩溃
  - runtime state 记录不真实
  - LLM 批处理只做对了一半
  - provenance / 审计字段没有和 Serving / LLM Runtime 真正收口

## 发现的问题

### P1. 第二次增量 run 当前会直接崩溃，`UPDATE / SKIP / REMOVE` 主链没有真正可用

- `run.py` 在 Phase 1a 用 `asset_db.get_document_by_key()` 读取 `asset_documents`，随后直接访问 `existing_doc["normalized_content_hash"]` 来判断 `UPDATE` / `SKIP`。
- 但 `normalized_content_hash` 实际属于 `asset_document_snapshots`，不在 `asset_documents` 表上。
- 我在工作区内做了真实双次运行验证：
  - 第一次 run 正常完成并发布
  - 修改一份文档、删除一份文档、再新增一份文档后，第二次 run 在分类阶段直接抛 `IndexError: No item with that key`
- 这说明文档里声称已经落地的增量 build / `NEW-UPDATE-SKIP-REMOVE` 语义，在真实复跑时并没有成立。
- 代码位置：
  - `knowledge_mining/mining/jobs/run.py:323`
  - `knowledge_mining/mining/jobs/run.py:326`
  - `knowledge_mining/mining/snapshot/__init__.py:31`
  - `databases/asset_core/schemas/001_asset_core.sqlite.sql:33`
  - `databases/asset_core/schemas/001_asset_core.sqlite.sql:62`

### P1. Run state 仍然不是“过程态真相源”，状态机和发布策略都没有按声明实现

- `run.py` 最终固定 `run_status = "completed"`，随后调用 `tracker.complete_run()`，即使 `failed_count > 0` 也一样。
- 我用工作区脚本构造了一个文档级 parse 失败场景，验证结果为：
  - `failed_count = 1`
  - `committed_count = 1`
  - `mining_runs.status = "completed"`
  - 默认不发布 release，但仍会产出 validated build
- 当 `publish_on_partial_failure=True` 时，我再次验证得到：
  - `failed_count = 1`
  - `mining_runs.status` 仍是 `"completed"`
  - active release 仍会被切换到只包含成功文档的部分 build
- fix 文档里宣称的 `completed_with_errors` / `completed_partial` 并不存在：
  - SQL schema 不允许这些状态
  - 代码也没有写入这些状态
- 这意味着 runtime 既不能准确表达失败，也不能阻止“部分语料 build 被当成正式 active release”。
- 代码位置：
  - `knowledge_mining/mining/jobs/run.py:57`
  - `knowledge_mining/mining/jobs/run.py:589`
  - `knowledge_mining/mining/jobs/run.py:601`
  - `knowledge_mining/mining/runtime/__init__.py:32`
  - `databases/mining_runtime/schemas/001_mining_runtime.sqlite.sql:6`

### P1. Stage event 没有覆盖真实文档级状态，当前无法拿它做可靠追踪或恢复依据

- 当前真正落库的 stage event 只有：
  - `select_snapshot`
  - `assemble_build`
  - `validate_build`
  - `publish_release`
- 文档级的 `parse / segment / enrich / build_relations / build_retrieval_units` 没有任何 stage event 落库。
- 我实际运行后查询 `mining_run_stage_events`，确认：
  - 文档级 pipeline 阶段没有记录
  - `select_snapshot` 的 `started` 事件带 `run_document_id`
  - 但 `completed` 事件又丢了 `run_document_id`
- 这会导致：
  - 无法按文档追踪某个阶段是否完成
  - 无法准确支持断点续跑
  - 阶段事件表无法作为“每个 state 的真相源”
- 另一个合同漂移是：
  - `models.py` 的 `VALID_STAGE_NAMES` 已包含 `discourse_relations`
  - 但 runtime SQL schema 还不允许这个 stage
- 代码位置：
  - `knowledge_mining/mining/jobs/run.py:383`
  - `knowledge_mining/mining/jobs/run.py:425`
  - `knowledge_mining/mining/runtime/__init__.py:82`
  - `knowledge_mining/mining/runtime/__init__.py:100`
  - `knowledge_mining/mining/models.py:114`
  - `databases/mining_runtime/schemas/001_mining_runtime.sqlite.sql:57`

### P1. 你要求的“批量全部投递，由 worker 自己取任务”只在 enrich 上成立，generated_question 仍是串行回收

- 当前 `LlmEnricher.enrich_batch()` 确实是：
  - submit 全部
  - `poll_all`
  - fallback 到 rule-based
- 但 `LlmQuestionGenerator.generate_batch()` 虽然注释写的是 batch async，实际代码仍是：
  - submit 全部
  - 对每个 task 逐个 `poll_result`
- 我用 fake client 做了调用序列验证，结果明确是：
  - `generated_question`: `submit, submit, submit, poll_result, poll_result, poll_result`
  - `enrich`: `submit, submit, submit, poll_all`
- 这与历史提交 `4c3a294` 的描述不一致，也与用户最初要求的批量 worker 模式不一致。
- 结论：当前 Mining 的 LLM 批处理只有 enrich 满足要求，generated_question 不满足。
- 代码位置：
  - `knowledge_mining/mining/retrieval_units/__init__.py:64`
  - `knowledge_mining/mining/retrieval_units/__init__.py:109`
  - `knowledge_mining/mining/enrich/__init__.py:149`

### P1. Retrieval provenance 和 LLM 审计合同仍未收口，Serving/排障仍要背兼容负担

- `source_segment_id` 现在已经有了，这一点是正向进展。
- 但 `source_refs_json` 仍只写：
  - `document_key`
  - `segment_index`
  - `offsets`
- 没有 `raw_segment_ids`。
- 我实际跑出一批 `asset_retrieval_units` 也确认了这点。
- 同时，`generated_question` 的 `llm_result_refs_json` 现在只写占位信息：
  - `{"source":"llm_runtime","question_index":...}`
- 它没有保存真实 `task_id` / `result_id` / `template_version`，后续追查 prompt、结果、失败重放都不够。
- `_init_llm()` 还会在每次 run 时都去注册模板，但不校验注册结果是否生效。
- 这意味着 Mining 和 `llm_service` / `agent_serving` 的集成仍然是“能跑部分路径”，不是“合同真正收口”。
- 代码位置：
  - `knowledge_mining/mining/retrieval_units/__init__.py:433`
  - `knowledge_mining/mining/retrieval_units/__init__.py:622`
  - `knowledge_mining/mining/jobs/run.py:171`

### P2. Runtime 的 `processing` / `REMOVE` 等状态在实现里没有真正使用，恢复语义仍然是名义上的

- `mining_run_documents.status` schema 允许 `processing`，但当前主链从未写入这个状态。
- 文档在注册后是 `pending`，然后直接跳到 `committed` / `failed` / `skipped`。
- `ResumePlan` 把 `failed` 和 `processing` 都当成 redo，但实现上根本没有 `processing` 的真实来源。
- `REMOVE` 只存在于 build classify 结果，不存在真实“被删除文档”的 run_document 记录，因为删除文件根本不会进入本轮扫描。
- 这会让 runtime 表面上有完整状态设计，但真实运转时状态缺失，恢复语义不完整。
- 代码位置：
  - `knowledge_mining/mining/runtime/__init__.py:147`
  - `knowledge_mining/mining/db.py:748`
  - `knowledge_mining/mining/jobs/run.py:331`

### P2. 测试对“单次全量 happy path”覆盖还可以，但对你真正关心的增量 / 状态 / 集成问题覆盖不足

- `test_pipeline_operators.py` 中大量纯逻辑测试可过。
- 但当前缺少能真正守住关键要求的测试：
  - 第二次 run 的增量分类测试
  - `failed_count > 0` 时的 run status / build / publish 合同测试
  - stage event 完整覆盖测试
  - `generated_question` 必须使用 `poll_all` 的批量行为测试
  - `source_refs_json.raw_segment_ids` 与 `llm_result_refs_json` 审计字段测试
- `test_v12_e2e_live.py` 甚至特地 monkey-patch 成“只保留 question_generator”，主动绕过 enrich/discourse/contextualizer 的全链验证，因此它不能证明当前 LLM 主链已经全面就位。

## 每个 State 的现状与分析

### 1. `ingest`

- 现状：基本可用。
- 已做对的部分：
  - 递归扫描目录
  - 区分可解析与不可解析文件
  - 为不可解析文件用 `raw_hash` 兜底 `normalized_content_hash`
- 问题：
  - 它只保证单次输入发现，不负责删除文件的显式 runtime 记录
  - 删除语义完全依赖后续 build classify

### 2. `register_document / action classify`

- 现状：未达标。
- 问题：
  - `NEW` 初次运行没问题
  - 第二次运行的 `UPDATE / SKIP` 判定逻辑读错表，真实复跑即崩
  - `REMOVE` 只在后续 build classify 补算，不是完整文档状态流的一部分

### 3. `parse`

- 现状：内容解析本身基本可用，但状态追踪缺失。
- 问题：
  - parse 出错时文档会失败，这一点是真实生效的
  - 但 runtime 没有 parse stage event，无法按文档追踪 parse 状态

### 4. `segment`

- 现状：结构切分本身可用。
- 已做对的部分：
  - heading 独立成段
  - section path / offsets / hashes 基本都有
- 问题：
  - 没有 stage event
  - 不参与 runtime 恢复判断

### 5. `enrich`

- 现状：是当前 LLM 集成里最接近要求的 state。
- 已做对的部分：
  - `RuleBasedEnricher` 与 `LlmEnricher` 的接口已统一
  - `LlmEnricher` 真实走批量 submit + `poll_all`
  - 失败时会 fallback 到规则实现
- 问题：
  - enrich 的 stage 自己没有 runtime 落库记录
  - enrich 结果没有写出足够的 LLM 审计引用

### 6. `build_relations`

- 现状：结构关系主链可用。
- 已做对的部分：
  - `previous/next`
  - `same_section`
  - `same_parent_section`
  - `section_header_of`
- 问题：
  - discourse relation 在代码里开始出现，但 runtime schema / stage contract 没同步
  - 当前 state 追踪仍缺失

### 7. `build_retrieval_units`

- 现状：基础 retrieval units 可产出，但与 LLM/Serving 的协同还没收口。
- 已做对的部分：
  - `raw_text`
  - `contextual_text`
  - `entity_card`
  - `table_row`
  - `source_segment_id`
- 问题：
  - `generated_question` 没达到真正批量 worker 回收
  - `source_refs_json` 缺 `raw_segment_ids`
  - `llm_result_refs_json` 审计过弱

### 8. `select_snapshot`

- 现状：单次写入快照基本可用。
- 已做对的部分：
  - `document -> snapshot -> link` 三层模型仍成立
  - 共享 snapshot 复用逻辑仍在
- 问题：
  - 只有这个 state 被真正记到文档级 stage event
  - 它的 completed event 又丢了 `run_document_id`

### 9. `assemble_build`

- 现状：第一次全量 build 可用，增量 build 未达标。
- 已做对的部分：
  - build 表 / build_document_snapshots / release 链基本能跑通
  - `validate_build()` 至少做了最小完整性检查
- 问题：
  - 第二次 run 在 build 前已经崩，导致增量 merge 主链没有真实通过
  - 所以当前只能证明“全量 build 能建”，不能证明“增量 build 真可用”

### 10. `validate_build`

- 现状：存在最小校验，但强度有限。
- 已做对的部分：
  - 检查 active snapshot
  - 检查 snapshot 至少有 segment
  - incremental build 检查 parent 是否存在
- 问题：
  - 不检查 retrieval units / relations / release readiness
  - 不能阻止“部分失败但剩余 build 仍被认为 validated”

### 11. `publish_release`

- 现状：技术上可发布，业务上不够安全。
- 已做对的部分：
  - build -> release -> active 切换链路能跑
- 问题：
  - `publish_on_partial_failure=True` 时可把部分 build 直接切成 active
  - runtime 状态仍写成 completed，外部看不出这是残缺发布

## 与其他组件的协同分析

### 与 `llm_service` 的协同

- 已达成：
  - enrich 主链已能真实使用 LLM runtime
  - generated_question 也能真实提交到 runtime
- 未达成：
  - generated_question 没有真正 `poll_all`
  - 模板注册缺少生效校验
  - LLM 结果审计字段没有闭环到 task/result 级

### 与 `agent_serving` 的协同

- 已达成：
  - `source_segment_id` 已经能给 Serving 一条强桥接线
- 未达成：
  - `source_refs_json` 仍缺 `raw_segment_ids`
  - provenance 仍需要 Serving 做兼容兜底
  - 如果 Mining 发布的是部分失败 build，Serving 读取到的 active release 仍可能是不完整版本

## 测试与验证

### 已执行验证

- `pytest knowledge_mining/tests/test_pipeline_operators.py -q`
  - 58 passed
  - 1 failed
  - 失败点是当前环境临时目录 / SQLite 打开权限问题，不是该逻辑测试本身暴露的新功能缺陷
- `pytest knowledge_mining/tests/test_v11_pipeline.py -q`
  - 15 passed
  - 大量触及真实 SQLite / 临时目录的测试被当前机器权限环境阻断
- 工作区内定向脚本验证：
  - 单次 run 可完成并发布
  - 第二次增量 run 真实崩溃
  - 部分失败时 run 状态仍为 completed
  - `publish_on_partial_failure=True` 时会发布部分 build
  - `generated_question` 使用逐个 `poll_result`
  - `enrich` 使用 `poll_all`
  - `source_refs_json` 不含 `raw_segment_ids`

### 测试缺口

- 缺真实第二次 run 的回归测试
- 缺 run status 与 partial publish 合同测试
- 缺 stage event 完整性测试
- 缺 `generated_question` 批处理行为测试
- 缺 provenance / LLM audit 合同测试

## 回归风险

- 如果现在让另外两方建立在这套 runtime state 上，会误判 run 已完全成功。
- 如果现在继续按“增量 build 已可用”推进，第二次真实运行会在分类阶段直接中断。
- 如果现在让 Serving 只信 active release，不附加人工核查，可能读到部分失败 build。
- 如果现在扩大 LLM 批量规模，generated_question 这条链会先成为吞吐瓶颈。

## 建议修复项

1. 先修增量复跑主链：
   - `UPDATE / SKIP` 必须基于 document 当前 active link/snapshot 判断，而不是从 `asset_documents` 读不存在字段。
2. 修 run 状态机：
   - `failed_count > 0` 时不要再固定写 `completed`
   - 明确是否允许 partial build 发布；默认建议禁止 active 切换
3. 把文档级 stage event 补全：
   - `parse / segment / enrich / build_relations / build_retrieval_units`
   - `end_stage()` 必须保留 `run_document_id`
4. 把 `generated_question` 改成真实 `poll_all`
5. 收口 provenance / audit 合同：
   - `source_refs_json.raw_segment_ids`
   - `llm_result_refs_json.task_id/result_id/template_version`
6. 增加最小回归测试：
   - 第二次 run
   - partial failure
   - stage event completeness
   - qgen batch mode

## 无法确认的残余风险

- 当前机器对系统临时目录和 `.pytest_cache` 有明显权限噪音，导致无法把所有 SQLite/临时目录相关 pytest 结果直接当成唯一验收依据。
- 未对真实大规模语料、长文档和高并发 LLM 任务做压力验证。

## 管理员介入影响

- 用户已经明确要求 Mining 既要支撑另外两方，又要满足“批量投递、worker 逐个取任务”的运行模型。
- 因此本轮把“增量 run 真可用”“runtime state 真实”“LLM batch 主链真实”视为正式验收项，而不是后续优化建议。

## 最终评估

- 当前 `knowledge_mining` 可以跑通第一次全量主链，也已经具备部分 LLM 接入能力。
- 但它没有达到“可稳定支撑另外两方”的要求。
- 当前最关键的阻断点是：
  - 第二次增量 run 真实崩溃
  - runtime state 不真实
  - generated_question 没达到目标批处理模式
  - provenance / 审计合同未收口
- 结论：**当前不建议把 `knowledge_mining` 视为已经完成验收的生产底座。**
