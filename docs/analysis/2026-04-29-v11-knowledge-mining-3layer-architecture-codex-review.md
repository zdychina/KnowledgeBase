# CoreMasterKB v1.1 Knowledge Mining 三层架构重构审查

- 时间：2026-04-29 11:29
- From：Codex
- To：Claude Mining / 管理员
- 任务：`TASK-20260421-v11-knowledge-mining`
- 审查对象：提交 `a87d3df [claude]: restructure mining into 3-layer modular pipeline` 以及当前 `knowledge_mining/mining` 最终生效代码

## 审查背景

本轮不是功能小修，而是 `knowledge_mining/mining` 的架构重写：把原平铺模块拆成 `contracts / infra / stages` 三层，并引入 stage registry 与 `StreamingPipeline`。对于工业级应用，这类重构的验收重点不是“测试是否还绿”，而是：

- 并发执行后的结果是否仍与原文档一一对应
- runtime 是否仍是可信真相源
- 新宣称的可插拔架构是否真的进入主执行链

我结合任务文档、历史审查、当前提交 diff、最终代码和一次最小并发复现实验完成本次审查。

## 审查范围

- 代码：
  - `knowledge_mining/mining/jobs/run.py`
  - `knowledge_mining/mining/pipeline.py`
  - `knowledge_mining/mining/runtime/__init__.py`
  - `knowledge_mining/mining/stages/__init__.py`
  - `knowledge_mining/mining/stages/parse.py`
  - `knowledge_mining/mining/stages/enrich/__init__.py`
  - `knowledge_mining/mining/stages/retrieval_units/__init__.py`
- 关联任务资料：
  - `docs/messages/TASK-20260421-v11-knowledge-mining.md`
  - `docs/handoffs/2026-04-21-v11-knowledge-mining-claude-mining-handoff.md`
  - `docs/handoffs/2026-04-21-v11-knowledge-mining-claude-mining-fix.md`

## 发现的问题

### P0. `StreamingPipeline` 不保序，但 `run.py` 按索引回写结果，存在把 A 文档结果写进 B 文档 snapshot 的真实风险

证据：

- `StreamingPipeline.process_all()` 只是不断从输出队列取结果并 append，未保留输入序号或 document identity，对外承诺却写着“return results in output order”。见 `knowledge_mining/mining/pipeline.py:249-260`。
- `run.py` 随后直接把 `ctxs[i]` 与 `work_items[i]` 按相同下标配对写库。见 `knowledge_mining/mining/jobs/run.py:423-428`。
- 我做了一个最小复现实验，三条输入经过不同 sleep 后，返回顺序实际是 `['1', '2', '0']`，并非输入顺序。

这不是理论洁癖，而是数据污染风险：一旦 `enrich` / `retrieval_units` 等多 worker stage 出现时延差异，错误文档的 segments / relations / retrieval_units 就会落进当前 `snapshot_id`，后果是：

- `document_snapshot_link` 对的还是原文档
- `asset_raw_segments.segment_key` / `retrieval_unit.target_ref_json` 内的 `document_key` 却可能属于另一篇文档
- 后续 build/release 会把混杂数据当成已发布真相

对工业级系统，这是阻断级问题。

### P0. run 最终状态在返回值和 runtime 真相源之间分裂，且“部分失败”语义再次退化

证据：

- `run.py` 先根据 `failed_count` 计算 `run_status`，甚至在注释里承认“all docs failed -> failed”。见 `knowledge_mining/mining/jobs/run.py:641-648`。
- 但真正写库时调用的是 `tracker.complete_run(...)`。见 `knowledge_mining/mining/jobs/run.py:650-659`。
- `RuntimeTracker.complete_run()` 无条件把状态写成 `"completed"`。见 `knowledge_mining/mining/runtime/__init__.py:32-39`。

结果：

- 返回给调用方的 `result["status"]` 可能是 `"failed"`，数据库里的 `mining_runs.status` 却仍是 `"completed"`。
- `publish_on_partial_failure=False` 的文档说明写的是“run marked completed_with_errors”，但当前实现既不写 `completed_with_errors`，也不保留一个强状态，只是在 metadata 里塞 `has_failures`。

这会直接破坏：

- 调度层按 `mining_runs.status` 做恢复/告警
- 运维按 runtime 数据看 run 健康度
- 未来自动 resume / retry / release gating

工业级运行面不能接受“API 返回一种状态，数据库落另一种状态”。

### P1. stage completion event 丢失 `run_document_id`，runtime 无法形成完整的文档级阶段闭环

证据：

- `start_stage()` 会写入 `run_document_id`。见 `knowledge_mining/mining/runtime/__init__.py:84-100`。
- `end_stage()` 在重写完成事件时没有把 `run_document_id` 带回去。见 `knowledge_mining/mining/runtime/__init__.py:125-134`。

后果：

- 你只能看到某个文档阶段“开始过”，却无法把 completed/failed 事件稳定归属到同一 `run_document_id`
- 文档级 stage duration、失败定位、按文档回放都不可靠
- 这与任务里“`mining_runtime` 作为过程态真相源”的要求冲突

该问题在这次架构重写后仍然保留，说明 runtime 契约没有被回归测试真正兜住。

### P1. 新增的 stage registry 没有进入主执行链，“hot-pluggable” 仍停留在展示层

证据：

- `knowledge_mining/mining/stages/__init__.py` 新增 registry、自发现和版本选择。见 `knowledge_mining/mining/stages/__init__.py:14-65`。
- 但当前仓库内 `get_stage()` / `list_stages()` 没有任何主链调用；实际执行仍是 `run.py` 直接 import `DefaultSegmenter`、`RuleBasedEnricher`、`DefaultRelationBuilder`、`assemble_build` 等具体实现。见 `knowledge_mining/mining/jobs/run.py:35-45`。
- `pipeline.py` 里 retrieval units 仍直接 import `build_retrieval_units`。见 `knowledge_mining/mining/pipeline.py` 对应 retrieval stage 实现。

这意味着：

- 架构上宣称的版本选择、自动发现、热插拔，目前不会影响真实 run
- 新层次增加了概念复杂度，但没有换来可运行的扩展收益
- 后续如果团队误以为 registry 已经接管执行链，极容易出现“注册成功但主链根本没切过去”的隐性缺陷

这项更偏架构真实性问题，不像前两项那样立刻污染数据，但对工业级可维护性是实质负债。

### P1. 数据质量审计已经实现，但没有进入 build/release 发布门，当前“质量基线”仍是旁路工具

证据：

- `run_data_quality_eval()` 与 `DataQualityReport` 已在 `knowledge_mining/mining/stages/eval.py:58-82` 实现。
- 但主发布链里，`run.py` 在 `assemble_build()` 后只补记一个 `validate_build` stage，然后直接进入 `publish_release`。见 `knowledge_mining/mining/jobs/run.py:612-638`。
- 当前 `validate_build()` 只验证“有 active snapshot / snapshot 非空 / incremental parent 存在”，并不验证 retrieval unit 质量、LLM provenance、导航片段污染、golden regression 等工业级数据质量条件。

这说明当前系统虽然已经引入“工业级数据质量基线”的概念，但它还没有成为正式 release gate。换句话说，系统现在可以在 data quality audit 失败的情况下继续发布 active release。

对于工业级 ingestion 系统，这个缺口不是可选优化项，而是发布面设计未收口。

### P1. Domain Pack 还不是单一真相源，核心模块仍在回读原始 YAML，合同没有真正闭合

证据：

- `DomainProfile` 目前承载 entity types、role rules、heading role、extractor rules、templates、retrieval policy、eval questions。见 `knowledge_mining/mining/infra/domain_pack.py:74-90`。
- 但 `RuleBasedEntityExtractor` 初始化后仍会再次打开 `domain.yaml` 读取 `parameter_column_names` 和 `section_title_command_pattern`。见 `knowledge_mining/mining/infra/extractors.py:27-45`。
- `RuleBasedEnricher` 也会再次打开 `domain.yaml` 读取 `parameter_column_names`。见 `knowledge_mining/mining/stages/enrich/__init__.py:53-68`。

这意味着：

- “换一个 Domain Pack 就能替换全部领域知识”的设计目标并未完全兑现；
- 领域合同被拆成了两层：一层在 `DomainProfile`，另一层仍散落在 YAML 二次读取逻辑里；
- 后续如果 pack schema 演进，最容易出现 `DomainProfile` 与模块私读字段不一致的问题。

从工业级演进角度看，这属于架构合同没有真正封装完成，而不是单纯代码风格问题。

### P2. README 对成熟度表述过头，当前实现与“生产就绪”口径不一致

证据：

- `knowledge_mining/README.md:4` 仍写着 `v1.1（生产就绪）`。
- 但当前最终代码至少仍存在：并发结果错配风险、run status 真相源分裂、stage 审计链不完整、resume 仅有 plan 无自动恢复、data quality eval 未接入发布门。

文档口径不是次要问题。对于协作型仓库，这会直接影响：

- 管理员对可上线性的判断
- Claude Mining 对后续演进优先级的排序
- Serving / eval / 运维方是否把当前 release 当成稳定基线

因此这项虽然不如 P0/P1 直接破坏数据，但会持续放大错误决策。

## 测试缺口

- 现有测试没有覆盖“多文档并发后结果顺序必须与输入稳定绑定”的断言，因此 `StreamingPipeline` 的核心缺陷能在 `152 tests passed` 下直接漏过。
- `test_run_status.py` 只覆盖了 metadata 型 partial failure，没有覆盖“all docs failed but `run()` 仍调用 `complete_run`”这一真实主链分支。
- 没有测试验证 stage completed event 必须回填 `run_document_id`。
- 没有测试证明 stage registry 真的驱动了主执行路径；当前更像是结构存在性测试，而不是行为测试。
- 没有集成测试保证 `run_data_quality_eval()` 会阻断 release，因此当前质量基线不具备执行约束力。
- 没有合同测试保证 Domain Pack 的全部运行时字段都来自 `DomainProfile`，因此 pack schema 演进风险没有被测试兜住。

## 回归风险

- 多文档并发越高，错配写库概率越高，且问题一旦发生会污染已发布 release，不是单次请求级错误。
- runtime 状态失真会让调度、补偿、告警和人工排障全部建立在错误事实之上。
- registry 与主链脱节会让后续版本演进继续叠概念，而不是收敛复杂度。

## 工业级短板清单

从工业级知识 ingestion 系统视角看，当前 Mining 的短板不是单点缺陷，而是集中在 5 个能力面：

### 1. 运行正确性还不是生产级

- 并发 pipeline 结果与输入文档未稳定绑定。
- run / run_document / stage_event 三层 runtime 真相源没有严格一致。
- resume 目前只有 `ResumePlan`，没有真正进入可恢复执行链。

这意味着系统现在更像“可跑通”，还不是“可稳定重跑、可可靠追责、可自动恢复”。

### 2. 发布门只有结构校验，没有内容质量校验

- `validate_build()` 只检查 snapshot/segment 是否存在。
- retrieval unit 质量、导航污染、LLM provenance、golden regression 仍不影响 release。

对于工业级知识库，发布门至少应同时覆盖：

- 结构完整性
- 溯源完整性
- 内容质量底线
- 关键回归样例

当前系统只覆盖了第一项。

### 3. Domain Pack 已经出现方向价值，但还没成为真正的平台合同

- 当前 pack 已承载 prompt、entity types、role rules、retrieval policy、eval questions，这是对的。
- 但核心代码仍存在 pack 外私有逻辑和 YAML 二次读取。
- 默认 pack 仍写死为 `cloud_core_network`，说明“通用底座，行业只是可插拔知识层”这个目标还没有完全压实。

这会导致系统名义上是“跨行业 ingestion 平台”，实际上仍偏“云核心网特化实现 + 通用化外壳”。

### 4. 评估体系存在，但还没有成为开发闭环的一部分

- `run_eval()` 和 `run_data_quality_eval()` 已经具备雏形。
- 但它们目前不是 run/build/release 的默认链路，也不是变更验收标准的一部分。

工业级系统不能把 eval 当“事后辅助工具”，而应把它变成“变更必须通过的约束面”。

### 5. 架构抽象增长快于主链收敛

- `contracts / infra / stages / registry / streaming / llm / eval / domain_pack` 这些概念都在增加。
- 但真正决定系统是否可靠的主链约束还没完全稳住。

这类项目最危险的演进方式，不是“代码脏”，而是“抽象越来越多，但运行面没有同步变硬”。当前 Mining 已经有这个倾向。

## 建议修复项

1. 给 `DocumentContext` 或 `StreamingPipeline` 增加稳定 identity / sequence id，`process_all()` 必须按输入顺序返回，或改成显式返回 `{seq: ctx}` 后由 `run.py` 按 identity 回绑。
2. 把最终 run status 真正传给 runtime 层，禁止 `complete_run()` 硬编码 `"completed"`；若 SQL 契约暂不接受更多枚举，也至少在 all-failed 场景调用 `fail_run()`，并把 partial failure 语义统一到单一真相源。
3. `end_stage()` 必须写回对应的 `run_document_id`，必要时从 started event 读回并沿用。
4. 把 `run_data_quality_eval()` 接入 build/release gate，至少让 golden regression、navigation question pollution、LLM provenance、generated_question title 规则成为正式发布门。
5. 扩充 `DomainProfile`，把 `parameter_column_names`、`section_title_command_pattern` 等仍在模块私读的字段纳入正式合同，停止 `extractors/enrich` 二次回读 YAML。
6. 若要保留 stage registry，就让 `run.py` / `PipelineConfig` 真正从 registry 解析 stage 实现；若短期不用，建议先去掉这层未接线抽象，避免误导。
7. README 与 handoff 口径应降级为“可运行/待工业化收口”，不要继续标注“生产就绪”。
8. 新增六类回归测试：
   - 多文档乱序并发写回测试
   - all-failed / partial-failed run status 集成测试
   - stage event `run_document_id` 完整性测试
   - registry 驱动真实主链切换测试
   - quality eval 阻断 release 的集成测试
   - Domain Pack 完整合同测试（不得绕过 `DomainProfile` 私读 YAML）

## 推荐演进路线图

建议不要继续按“想到什么补什么”的方式演进，而是按下面 3 个阶段收口。

### Phase A: 先把主链变成可信生产线

目标：保证同一份输入永远产出可追溯、可重跑、可判定状态的结果。

必须完成：

- 修复并发结果错位
- 统一 run status 真相源
- 补全 stage completed event 的 `run_document_id`
- 明确 partial failure / all failed / skipped / phase1_only 的最终合同
- 把 resume 从“有计划”推进到“有可执行入口”

验收标准：

- runtime DB 足以单独回答“这次 run 到底成功没有、哪些文档失败、卡在哪个 stage、是否允许发布”

### Phase B: 再把质量门变成 release gate

目标：保证系统不会把明显劣质知识资产发布成 active release。

必须完成：

- 把 `run_data_quality_eval()` 接进 build/release 主链
- 明确哪些 check 是 hard gate，哪些是 warning
- 增加 golden regression 集
- 把 LLM provenance、navigation pollution、question/title 规则纳入默认 gate

验收标准：

- release 不再只表示“有数据”，而表示“过了最小工业质量门”

### Phase C: 最后再把平台化合同真正封闭

目标：让 Mining 真正成为跨行业知识 ingestion 平台，而不是场景特化系统的抽象外衣。

必须完成：

- 扩充 `DomainProfile`，把所有运行时 pack 字段纳入正式 schema
- 停止核心模块绕过 `DomainProfile` 私读 YAML
- 让 registry 真正接入主执行链，或删掉未接线部分
- 把默认行为从“cloud_core_network 特化”改成“generic baseline + 显式场景 pack”

验收标准：

- 不改 core 代码，只替换/新增 Domain Pack，就能切换场景知识、prompt、retrieval policy、eval questions

### 不建议的路线

当前阶段不建议优先做这些事：

- 继续增加更多 retrieval unit 类型
- 继续扩更多 LLM stage
- 继续堆更复杂的 rerank / graph / embedding 策略
- 继续强化 stage registry 的概念层包装

原因很简单：底盘还没收口，继续加能力只会放大错误产物和排障成本。

## 无法确认的残余风险

- 本次未对真实 SQLite 进行端到端高并发压测，因此尚未量化错配概率；但从实现语义看，缺陷已经成立。
- 由于当前 registry 尚未接入主链，未来 Claude Mining 若继续围绕这层扩展，可能还会引入第二批“注册成功但未生效”的问题。

## 管理员介入影响

- 管理员此前已明确要求 Mining 朝工业级可用底座收口，而不是继续做表面式结构升级。本次结论与该口径一致：当前重构在“结构分层”上前进了，但把几条运行面底线重新暴露出来了。

## 最终评估

本次三层架构重构**不能按工业级可用通过**。

原因不是代码风格或模块命名，而是“主链正确性 + 发布质量门 + 架构合同闭环”三条线同时没有收口：

- 并发结果与文档绑定不可靠
- run 状态真相源失真
- stage 审计链不完整
- data quality audit 未进入 release gate
- Domain Pack 仍不是唯一合同源

在修复这些问题前，不建议把这版 Mining 作为后续 Serving / eval / 生产数据生成的稳定基线。
