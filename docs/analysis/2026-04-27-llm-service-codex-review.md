# LLM Service Codex Review

## 审查背景

- 日期：2026-04-27
- 审查对象：`llm_service/` 当前主干实现
- 目标：单独审视 LLM Runtime 本体，不混入 Mining / Serving 集成问题，确认：
  - 同步 `/execute` 是否真实可用
  - 异步 `/tasks + worker` 是否真实可用
  - template / request / attempt / result / event 主链是否一致
  - 当前是否还存在会直接影响调用方接入的实质缺陷

## 审查范围

- 代码主链：
  - `llm_service/main.py`
  - `llm_service/runtime/service.py`
  - `llm_service/runtime/task_manager.py`
  - `llm_service/runtime/executor.py`
  - `llm_service/runtime/worker.py`
  - `llm_service/runtime/template_registry.py`
  - `llm_service/api/tasks.py`
  - `llm_service/api/results.py`
- 测试：
  - `llm_service/tests/test_integration.py`
  - `llm_service/tests/test_template_resolution.py`
  - `llm_service/tests/test_task_manager.py`
  - `llm_service/tests/test_executor.py`
- 运行验证：
  - 本地 mock provider smoke
  - 本地多任务 worker 并发 smoke
  - 使用当前 `.env` 的真实 provider `/execute` smoke

## 已确认成立的能力

- `create_app(start_worker=False)` 下，同步 `/api/v1/execute` 能走通真实 provider。我在当前 `.env` 配置下实际发起了最小文本请求，服务返回：
  - `status = "succeeded"`
  - `attempts = 1`
  - `text_output = "OK"`
- `create_app(start_worker=True)` 下，异步 `/api/v1/tasks` + 内置 worker 能走通 mock provider。
- `worker_concurrency=4` 下，我用 20 个并发任务做了最小压测，20/20 都成功，未复现之前那类 API/worker 共享连接导致的提交冲突。
- 当前 `data/llm_service.sqlite` 里已有真实成功任务记录，且最近任务来自 `caller_domain='mining'`、`pipeline_stage='enrich'`，说明这不是空壳服务。

## 发现的问题

### P1. 异步 `submit()` 在“只有 input、没有 messages，且模板未命中/未展开”时，会把空 `messages` 落库，worker 随后会拿空 prompt 调 provider

- 这是 `llm_service` 本体里我这轮找到的唯一实质性功能缺陷。
- 原因是：
  - `LLMService.execute()` 会在模板未生成消息时回退为 `[{role:'user', content: json.dumps(input)}]`
  - 但 `LLMService.submit()` 之前没有同样的 fallback，导致异步任务 request row 里 `messages_json=[]`
- 我用最小复现脚本确认过修复前行为：
  - `POST /api/v1/tasks`
  - body 只给 `input + template_key='missing-template'`
  - worker 实际收到的 provider 调用为 `messages=[]`
- 这会直接影响 Mining 的异步批量路径。只要模板注册失败、模板不存在，或调用方本来就打算只传 `input`，后台 worker 就会用空 prompt 执行。
- 我已在本轮修复该问题，并补了两条覆盖测试：
  - `test_submit_without_messages_falls_back_to_input_payload`
  - `test_submit_with_missing_template_still_persists_fallback_message`
- 修复位置：
  - `llm_service/runtime/service.py`
  - `llm_service/tests/test_template_resolution.py`

## 本轮修改

- 代码修复：
  - `llm_service/runtime/service.py`
  - 让 `submit()` 与 `execute()` 的消息回退语义保持一致：
    - 当模板未展开出消息，且调用方只提供了 `input` 时，自动合成一条 user message
- 测试补充：
  - `llm_service/tests/test_template_resolution.py`
  - 新增 2 个最小回归测试，覆盖 async submit 的 fallback 语义

## 测试与验证

- 已完成的定向验证：
  - mock provider 下 `start_worker=True` 异步任务 smoke：通过
  - mock provider 下 `worker_concurrency=4`、20 并发任务 smoke：20/20 成功
  - 真实 provider 下 `/execute` 文本请求 smoke：通过
  - 修复后脚本复核：
    - `submit(input=...)` 会把 fallback user message 写入 `agent_llm_requests.messages_json`
    - 缺失模板时异步 worker 实际收到的 provider `messages` 不再为空
- 未完整完成的验证：
  - 当前环境的 `pytest tmp_path / cache` 权限仍不稳定，导致我没有在本轮完成 `llm_service/tests/` 全量 pytest 复跑；因此本轮以定向脚本和代码/数据复核为主

## 回归风险

- 同步 `/execute` 当前已可用，但异步批量调用方若依赖 template，仍然要保证模板注册/发布流程本身可靠；本轮只修了“模板没命中时不至于空 prompt”。
- 当前 worker 共享单个 `worker_db` 连接，虽然本轮最小并发压测未复现问题，但它依然不是高并发写场景下最稳妥的最终形态；若后续批量规模显著放大，仍建议继续保留并发专项验证。

## 无法确认的残余风险

- 未对真实 provider 做长时间、多批次、失败注入下的 worker 压测。
- 未在本机完成完整 pytest 回归，原因是当前环境的临时目录/缓存目录权限噪音。

## 最终评估

- 当前 `llm_service` 单体结论比我之前对整条链路的判断要积极得多：
  - 它已经是一个基本可用的统一 runtime，不再是主要阻断项。
- 本轮确实发现了 1 个会直接影响异步调用方的实质 bug：
  - `submit()` 空 messages 落库
- 该问题已经修复并做了定向验证。
- 因此，就 `LLM Service` 本体而言，我当前结论是：

```text
可用，但仍建议继续以“已验证主链 + 保留残余风险”的口径对待；
不再适合作为当前系统的首要阻断问题。
```
