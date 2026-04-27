# LLM / Mining / Serving Integration Codex Review

## 审查背景

- 日期：2026-04-27
- 审查目标：基于当前主干最新提交，重新审视 `llm_service/`、`knowledge_mining/`、`agent_serving/` 的真实集成状态，重点核查：
  - LLM Runtime 是否已能稳定支撑 Mining 批量任务与 Serving 在线调用
  - Mining 是否已按“批量投递 -> worker 拉取 -> 回收结果”方式真实工作
  - Serving / API 是否仍在读取旧数据库、旧 schema 或旧主链
- 用户重点症状：
  - “希望一批次全部丢进来，然后 llm 这边的 worker 去逐个取任务”
  - “数据库里面是 ok 的，但是 app/api 查询都是旧数据库”

## 审查范围

- 提交链：
  - `llm_service/`：`6894364` → `637ad4d`
  - `knowledge_mining/`：`037703f` → `d88b04e`
  - `agent_serving/`：`ecdcd7b` → `968c0be`
- 代码主链：
  - `llm_service/main.py`
  - `llm_service/runtime/service.py`
  - `llm_service/runtime/task_manager.py`
  - `llm_service/runtime/worker.py`
  - `knowledge_mining/mining/jobs/run.py`
  - `knowledge_mining/mining/enrich/__init__.py`
  - `knowledge_mining/mining/retrieval_units/__init__.py`
  - `knowledge_mining/mining/llm_client.py`
  - `agent_serving/serving/main.py`
  - `agent_serving/serving/api/search.py`
  - `agent_serving/serving/repositories/asset_repo.py`
  - `agent_serving/README.md`
  - `agent_serving/QUICKSTART.md`
- 相关测试与数据样本：
  - `agent_serving/tests/test_api_integration.py`
  - `agent_serving/tests/test_mining_contract.py`
  - `knowledge_mining/tests/test_v11_pipeline.py`
  - `data/llm_service.sqlite`
  - `data/asset_contracts/asset_core_v1_1.sqlite`
  - `data/m1_contract_corpus/m1_contract_asset.sqlite`

## 已确认成立的正向结论

- `llm_service` 的内置 worker 当前至少具备基本可运行性。我用 `create_app(..., start_worker=True)` + `MockProvider` 做了最小 smoke test，`POST /api/v1/tasks` 后任务能从 `queued` 转为 `succeeded`，并能通过 `/result` 取回结果。
- `data/llm_service.sqlite` 内已有近期真实任务记录，最近任务显示 `caller_domain='mining'`、`pipeline_stage='enrich'` 且状态为 `succeeded`，说明 Mining 确实已经在某些路径上调用当前 LLM Runtime。
- `agent_serving/tests/test_api_integration.py` 当前通过，说明在“手工注入的 v1.1 内存数据”前提下，Serving 的基础 API 装配、active release 解析和 ContextPack 输出链路是可跑的。

## 发现的问题

### P1. Serving 当前公开启动口径仍然指向旧 M1 数据库和旧 schema，足以直接造成“数据库是新的，但 API 查的还是旧库/旧结构”

- `agent_serving/README.md` 的启动示例仍把 `COREMASTERKB_ASSET_DB_PATH` 指向 `data/m1_contract_corpus/m1_contract_asset.sqlite`。
- `agent_serving/QUICKSTART.md` 不仅继续使用 `m1_realistic_asset.sqlite / m1_contract_asset.sqlite` 作为“典型路径”，还在示例 SQL 中查询旧表名 `asset_releases`，甚至读取 `asset_retrieval_units.canonical_text` 这类旧字段。
- 当前仓库里所谓的 `data/asset_contracts/asset_core_v1_1.sqlite` 也不是 v1.1 三层发布链 schema；我实际检查后发现它仍是旧表：`asset_publish_versions / asset_raw_documents / asset_canonical_segments`，没有 `asset_publish_releases`、`asset_build_document_snapshots`，且 `asset_retrieval_units` 数量为 0。
- `agent_serving/tests/test_mining_contract.py` 仍是 placeholder，且内部常量 `_CONTRACT_DB` 继续指向 `data/m1_contract_corpus/m1_contract_asset.sqlite`，说明 Serving 到今天都没有对“当前 Mining 真正产出的 v1.1 DB”做过正式契约验证。
- 这不是文档小问题，而是实际会把启动、验库、排障、契约测试全部引向旧资产。
- 代码/文件位置：
  - `agent_serving/README.md:111`
  - `agent_serving/QUICKSTART.md:78`
  - `agent_serving/QUICKSTART.md:96`
  - `agent_serving/QUICKSTART.md:105`
  - `agent_serving/QUICKSTART.md:364`
  - `agent_serving/tests/test_mining_contract.py:10`

### P1. `/search` API 主链仍未真正进入 LLM normalizer / planner，Serving 对外行为依旧是纯规则路径

- `agent_serving/serving/api/search.py` 里实际执行的是：
  - `normalizer = QueryNormalizer()`
  - `normalized = normalizer.normalize(body.query)`
  - `_get_planner()` 固定返回 `QueryPlanner(RulePlannerProvider())`
  - `plan = planner.plan(...)`
- 当前 API 主链没有调用 `QueryNormalizer.anormalize()`，也没有调用 `LLMPlannerProvider.abuild_plan()`。
- `agent_serving/serving/main.py` 里也没有初始化 `LLMRuntimeClient`，没有把它挂到 app state，再注入给 normalizer / planner。
- 这意味着仓库中虽然存在 LLM normalizer / planner 组件，但它们没有进入 `/api/v1/search` 的真实请求路径。
- 因而“LLM 已接上”不能成立；对用户来说，当前搜索结果仍然是规则系统，不是统一 LLM Runtime 驱动的理解链。
- 代码位置：
  - `agent_serving/serving/api/search.py:39`
  - `agent_serving/serving/api/search.py:45`
  - `agent_serving/serving/api/search.py:62`
  - `agent_serving/serving/api/search.py:70`
  - `agent_serving/serving/main.py:18`

### P1. Mining 的 run 状态机又回退成“无论局部失败与否都标记 completed”，与之前宣称的失败语义修复不一致

- `knowledge_mining/mining/jobs/run.py` 当前在 Phase 2 结束后直接写死：
  - `run_status = "completed"`
  - `tracker.complete_run(...)`
- 即使 `failed_count > 0`，当前实现也不会把 run 标成 `failed`、`interrupted` 或 `completed_with_errors`；只是可能阻断 publish。
- 这和先前 fix 文档里宣称的“`completed / completed_with_errors / completed_partial` 三级状态”不一致，也会让运行态审计继续误导调用方。
- 对批量 LLM/Mining 场景而言，这会直接影响恢复策略、发布判断和故障排查。
- 代码位置：
  - `knowledge_mining/mining/jobs/run.py:532`
  - `knowledge_mining/mining/jobs/run.py:534`
  - `knowledge_mining/mining/runtime/__init__.py:27`

### P1. Mining 声称的“批量 submit -> poll_all”只在 enrich 路径成立，`generated_question` 当前仍是串行 `poll_result`，没有真正吃到 worker 队列模式的收益

- `knowledge_mining/mining/retrieval_units.py` 中 `LlmQuestionGenerator.generate_batch()` 先批量 `submit_task()`，但随后不是 `poll_all()`，而是对每个 task 逐个 `poll_result()`。
- 我用一个替身 client 做了最小复核，实际调用序列是：
  - 3 次 `submit`
  - 3 次 `poll_result`
  - 没有 `poll_all`
- 这意味着当前“批量”只做到了批量入队，没有做到批量结果回收；在结果等待阶段仍然按任务串行阻塞。
- 如果一个批次里有慢任务，当前实现无法像 `poll_all()` 那样先收已完成任务，也不能充分利用 llm worker 并发吞吐。
- 这与架构文档、README 以及提交信息里的“submit_all -> poll_all”说法不一致。
- 代码位置：
  - `knowledge_mining/mining/retrieval_units/__init__.py:87`
  - `knowledge_mining/mining/retrieval_units/__init__.py:111`
  - `knowledge_mining/mining/README.md:184`
  - `knowledge_mining/architecture.html:203`

### P1. Mining 与 Serving 的 `source_refs_json` 合同仍未真正对齐，当前只靠 `source_segment_id` 勉强兜底

- Serving 的解析逻辑明确把 `source_refs_json` 视为 `{"raw_segment_ids": [...]}`：
  - `agent_serving/serving/schemas/json_utils.py:8`
  - `agent_serving/serving/application/assembler.py:209`
- 但 Mining 当前 `_build_source_refs()` 写出的却是：
  - `document_key`
  - `segment_index`
  - `offsets`
  - 没有 `raw_segment_ids`
- 对 `raw_text/contextual_text/generated_question/table_row` 这类 unit，当前还能依赖单独的 `source_segment_id` 字段继续下钻。
- 但对一切想通过 `source_refs_json` 做多源 provenance、JSON fallback 或后续跨 segment 聚合的路径，这个合同仍然是裂开的。
- 这也解释了为什么 Serving 的测试夹具全都手工写 `raw_segment_ids`，但真实 Mining 代码并不生产这套字段。
- 代码位置：
  - `knowledge_mining/mining/retrieval_units/__init__.py:599`
  - `agent_serving/serving/schemas/json_utils.py:8`
  - `agent_serving/tests/conftest.py:186`

## 测试缺口

- `agent_serving/tests/test_api_integration.py` 使用的是手工注入 `app.state.db` 的内存种子库，不覆盖真实 lifespan、真实 `COREMASTERKB_ASSET_DB_PATH`、真实 Mining 产出 DB。
- `agent_serving/tests/test_mining_contract.py` 仍是 skip placeholder，没有任何基于当前 v1.1 Mining 输出的契约测试。
- `knowledge_mining/tests/test_v11_pipeline.py` 没有覆盖“批量 LLM 问题生成是否真正 `poll_all`”。
- `knowledge_mining/tests/test_v11_pipeline.py` 也没有覆盖“部分失败时 run status 应如何落库”。
- `Serving` 的 LLM 集成测试主要验证组件级 client/provider，未验证 `/api/v1/search` 真正走到 LLM 路径。

## 回归风险

- 只要接入方继续按 `agent_serving/README.md` 或 `QUICKSTART.md` 启动，极大概率会继续连到旧 M1 DB 或按旧 schema 排障。
- 即使 LLM Runtime 本身能跑，Serving 由于主 API 没接 LLM normalizer/planner，用户仍会感知为“LLM 没生效”。
- Mining 如果继续把批量问题生成做成串行等待，批次吞吐和时延会随着任务数线性恶化。
- run 状态机继续把带失败的批次记成 `completed`，会污染后续恢复和发布判断。

## 无法确认的残余风险

- 当前环境对 pytest 临时目录与仓库缓存目录存在 `WinError 5 / Permission denied`，导致部分 pytest 无法完整复跑；本次结论以代码静态审查、定向脚本复核和现有 SQLite 实物检查为主。
- 仓库内没有一份由当前 `knowledge_mining` 最新主链正式产出的、可供 Serving 契约验证的 v1.1 示例 DB，因此无法在本轮对“真实 Mining 新库 -> Serving 真服务”做全链路验收。

## 最终评估

- `llm_service` 本身现在更接近“基本可用的统一 runtime”，不再是当前最主要的阻断点。
- 当前真正阻断另外两方稳定使用的，是 **Mining / Serving 集成层没有收口**：
  - Serving 公开口径仍指向旧库旧 schema；
  - `/search` 主链仍是 rule path；
  - Mining 的批量 LLM 回收和 run 状态机仍有实质缺口；
  - Mining / Serving 的 provenance 合同仍未完全统一。
- 结论：**不能认定“已经没有 bug、可放心支持另外两方使用”。当前最优先要修的是 Serving 的真实数据入口与主 API LLM 接入，其次是 Mining 的批量回收和 run 状态语义。**
