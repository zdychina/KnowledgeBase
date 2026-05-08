---
name: cloud-core-knowledge
description: 当用户问题依赖云核心网知识证据时，调用 serving 获取证据包，指导 Agent 基于证据回答、追问或把证据交给其他更专用的 Skill，避免脱离证据瞎编。
---

# 云核心网知识证据底座 Skill

当用户问题依赖云核心网知识库证据时，使用本 Skill。它的定位不是直接替代其他业务 Skill，也不是一个"会回答一切的云核心网助手"，而是一个面向 Agent 的证据底座：

- 调用 serving 检索证据包
- 帮助 Agent 判断当前能否直接回答，还是应该先追问
- 在需要时把证据交给其他更专用的 Skill
- 在没有其他专用 Skill 时，允许 Agent 基于证据做受约束推理

核心原则：**先取证，再回答；证据不足时先追问；推理必须受证据约束，不能瞎编。**

## 什么时候使用

当用户在问下面这类问题时，应导入本 Skill：

- 云核心网概念、网元、接口、协议、参数、告警、特性
- 命令用法、参数含义、配置前置条件、约束、注意事项、示例
- 配置流程、开通步骤、验证方法、回退方法
- 故障现象、排障思路、可能原因、关联条件
- 对比分析、影响分析、能力边界、适用条件

不适合使用本 Skill 的场景：

- 纯润色、翻译、格式整理
- 与云核心网知识无关的通用任务
- 完全不需要知识库证据、且显然应由其他专用 Skill 独立处理的问题

## Skill 的职责边界

本 Skill 只负责四件事：

1. 判断当前问题是否需要云核心网知识证据
2. 调用 serving 获取证据包
3. 解释证据包，判断证据是否充足
4. 指导 Agent 选择：
   - 直接回答
   - 先追问
   - 谨慎回答
   - 交给其他专用 Skill

本 Skill **不是**：

- 最终业务执行 Skill
- 配置生成 Skill
- 故障处理自动化 Skill
- 命令编排器

如果存在更专用的 Skill，本 Skill 应作为证据底座先行或并行使用，把证据提供给对方。

## 如何调用 serving

### 1. 先确认服务是否可用

```bash
curl -s http://127.0.0.1:8000/health
```

如果服务不可用：

- 明确告知云核心网知识后端当前不可达
- 不要伪造证据
- 如必须继续，只能把后续内容明确标成"非证据化背景判断"

### 2. 调用检索接口

**接口：** `POST http://127.0.0.1:8000/api/v1/search`

**必须使用管道直接解析，禁止存文件再读取。** 返回结果可能超过 2KB 触发自动存文件，所以从一开始就用 Python 管道解析，一步到位：

```bash
curl -s http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" -d '{"query":"什么是SBA","domain":"cloud_core_network"}' | python -c "
import sys, json
data = json.load(sys.stdin)
print('=== Query Understanding ===')
print(json.dumps(data.get('query',{}), ensure_ascii=False, indent=2))
print()
print('=== Items ===')
for i, item in enumerate(data.get('items',[])):
    print(f'--- Item {i} ---')
    print(f'  role: {item.get(\"role\")}')
    print(f'  evidence_role: {item.get(\"evidence_role\")}')
    print(f'  score: {item.get(\"score\")}')
    print(f'  title: {item.get(\"title\",\"\")}')
    print(f'  semantic_role: {item.get(\"semantic_role\")}')
    print(f'  block_type: {item.get(\"block_type\")}')
    print(f'  text (first 300 chars): {item.get(\"text\",\"\")[:300]}')
    print()
print('=== Issues ===')
print(json.dumps(data.get('issues',[]), ensure_ascii=False, indent=2))
print()
print('=== Suggestions ===')
print(json.dumps(data.get('suggestions',[]), ensure_ascii=False, indent=2))
print()
print('=== Sources ===')
for s in data.get('sources',[]):
    print(f'  {s.get(\"document_key\",\"?\")} - {s.get(\"title\",\"\")}')
"
```

**请求体字段：**

- `query`：用户原问题，或追问后收敛出的明确问题
- `domain`：云核心网问题默认传 `"cloud_core_network"`
- `scope`：只有在用户明确给出产品、网元、场景、版本等约束时再传
- `entities`：只有在实体已经明确且高置信时才传
- `debug`：只有在你需要看检索过程、路由、trace、诊断信息时才设为 `true`

**更多示例：**

```bash
# 带 scope 约束
curl -s http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" -d '{"query":"ADD APN 怎么写","domain":"cloud_core_network","scope":{"products":["UDG"],"network_elements":["SMF"]}}' | python -c "
import sys, json
data = json.load(sys.stdin)
for i, item in enumerate(data.get('items',[])):
    print(f'--- Item {i} ---')
    print(f'  role: {item.get(\"role\")}')
    print(f'  evidence_role: {item.get(\"evidence_role\")}')
    print(f'  score: {item.get(\"score\")}')
    print(f'  title: {item.get(\"title\",\"\")}')
    print(f'  semantic_role: {item.get(\"semantic_role\")}')
    print(f'  block_type: {item.get(\"block_type\")}')
    print(f'  text (first 300 chars): {item.get(\"text\",\"\")[:300]}')
    print()
"
```

```bash
# 带 debug 模式
curl -s http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" -d '{"query":"PDU Session 建立失败怎么排查","domain":"cloud_core_network","debug":true}' | python -c "
import sys, json
data = json.load(sys.stdin)
for i, item in enumerate(data.get('items',[])):
    print(f'--- Item {i} ---')
    print(f'  role: {item.get(\"role\")}')
    print(f'  evidence_role: {item.get(\"evidence_role\")}')
    print(f'  score: {item.get(\"score\")}')
    print(f'  title: {item.get(\"title\",\"\")}')
    print(f'  semantic_role: {item.get(\"semantic_role\")}')
    print(f'  block_type: {item.get(\"block_type\")}')
    print(f'  text (first 300 chars): {item.get(\"text\",\"\")[:300]}')
    print()
print('=== Debug ===')
print(json.dumps(data.get('debug',{}), ensure_ascii=False, indent=2))
"
```

## 如何理解返回结果

把返回结果当成**证据包**，不要当成"已经生成好的答案"。

### 重点看这些字段

- `query`：后端对本次问题的理解，包括 `intent`、`entities`、`scope`、`keywords`
- `items`：主要证据条目
- `relations`：证据之间的结构或图关系
- `sources`：来源文档，用于溯源和引用
- `evidence_groups`：按文档快照聚合的证据组
- `issues`：检索质量或证据质量提示
- `suggestions`：后端建议的后续问题
- `debug`：只在 `debug=true` 时返回，用于看 route trace、query understanding 等诊断信息

### 重点看 item 的这些字段

- `role`：`seed` / `context` / `support`
- `evidence_role`：`direct_answer` / `support` / `contrast` / `background` / `missing`
- `score`：分数可参考，但不能单独当结论依据
- `semantic_role`：概念、参数、步骤、排障、约束、示例等语义线索
- `block_type`：内容块类型
- `citation`：引用和来源信息
- `relation_to_seed`：它和主召回证据的关系

## 证据语义规则

本 Skill 要求 Agent 这样理解证据：

- `direct_answer`
  这是最接近用户问题主答案的证据

- `support`
  这是支撑性证据，用来补充前置条件、参数、限制、步骤、注意事项

- `contrast`
  这是对比性证据，用来解释差异、区分对象、比较方案

- `background`
  这是背景性证据，只能帮助理解上下文，不能单独支撑高风险操作结论

- `missing`
  这是"相关但不足以支撑答案"的信号，不应强行当有效答案证据使用

优先信任：

- 有 `direct_answer` 的条目
- 与当前 `intent` 匹配的 `semantic_role`
- 多条证据互相印证、且来源一致或互补的内容

不要做这些事：

- 只因为分数高就下结论
- 把背景证据当成操作依据
- 用一条模糊片段支撑高风险回答

## Agent 必须产出的两个内部判断

在读完证据包后，Agent 应先形成两个内部判断。

### 1. evidence_sufficiency

只能取其一：

- `sufficient`
  当前证据已经覆盖用户核心问题，关键条件也基本明确

- `partial`
  证据相关，但仍缺版本、场景、网元、范围、前提或关键步骤

- `insufficient`
  当前证据不足以可靠支撑用户真正想问的结论

判断时重点看四件事：

- 相关性：证据是否真在回答用户问题，而不只是"沾边"
- 覆盖度：是否覆盖了用户真正关心的核心点
- 条件完整性：产品、网元、场景、版本、前提、风险背景是否清楚
- 风险等级：现网操作类问题比解释性问题要求更严格

### 2. recommended_action

只能取其一：

- `answer_now`
- `ask_followup`
- `delegate_to_other_skill`
- `answer_with_caution`

推荐关系：

- `sufficient`：通常对应 `answer_now` 或 `delegate_to_other_skill`
- `partial`：通常对应 `ask_followup` 或 `answer_with_caution`
- `insufficient`：通常优先 `ask_followup`

## 追问策略

如果证据是 `partial` 或 `insufficient`，先判断缺的是哪一类：

- 证据缺口：后端没有召回到足够支撑内容
- 问题约束缺口：用户没有把问题说清楚

优先追问这些维度：

- `product_or_nf`：这是哪个产品、哪个网元、哪个功能面
- `version`：是否有版本、厂商、发布差异
- `scenario`：概念解释、配置、排障、验证、回退、影响分析中的哪一种
- `operation_goal`：用户到底想得到概念说明、原因判断，还是可执行步骤
- `risk_context`：学习性问题还是现网操作决策
- `expected_output_granularity`：高层解释还是工程落地细节

追问要求：

- 只问最少必要问题
- 追问要能明显缩小答案空间
- 避免泛泛地说"请提供更多信息"

推荐追问示例：

- "你这里更关心概念解释，还是现网配置步骤？"
- "这个问题是针对 SMF、UPF，还是某个具体产品版本？"
- "你要的是原因分析，还是一套可执行的排查步骤？"
- "这是学习性咨询，还是现网变更前的判断？"

## 回答约束

回答时，必须明确区分三层内容：

1. 证据直接支持的内容
2. 基于证据做出的推断
3. 当前还不确定或缺失的部分

### 当 `recommended_action = answer_now`

回答应包含：

- 直接结论
- 关键证据依据
- 会影响结论成立的前提或限制
- 必要时给出来源说明

### 当 `recommended_action = answer_with_caution`

回答应包含：

- 明确标注的保守结论或方向性判断
- 当前最强证据
- 缺失的假设、范围或证据
- 如果要提高置信度，用户下一步需要补什么信息

### 当 `recommended_action = delegate_to_other_skill`

应把本 Skill 的结果作为"证据输入"传给下游 Skill，并明确告诉对方：

- 哪些是直接证据
- 哪些是支撑证据
- 哪些地方还有缺口

不要让本 Skill 去硬做本来属于其他专用 Skill 的执行工作。

## 推理护栏

本 Skill 允许 Agent 基于证据进行推理，但必须遵守：

- 不要编造命令、参数、约束、依赖、步骤
- 不要默认脑补产品、版本、网元、场景
- 不要把背景材料说成确定结论
- 不要在证据不支撑时宣称因果关系、影响范围或操作安全性
- 如果不同证据指向不同范围或前提，要把冲突显式说出来

当只能做概率性判断时，用这种表达：

- "从当前证据看，更可能是......"
- "现有证据支持到这里，但还不能确定......"

## 推荐回答骨架

不要求死板套模板，但复杂问题建议按这个顺序组织：

1. 结论或当前判断
2. 依据
3. 前提/限制
4. 不确定点
5. 建议下一步

对于高风险操作类问题，优先显式输出：

- `结论`
- `依据`
- `前提/限制`
- `不确定点`
- `建议下一步`

## 实际工作流

1. 判断当前问题是否真的需要云核心网知识证据
2. 如果需要，调用 `POST /api/v1/search`，传 `domain: "cloud_core_network"`
3. 读取 `query.intent`、`items`、`evidence_role`、`sources`、`issues`、`suggestions`
4. 形成 `evidence_sufficiency`
5. 形成 `recommended_action`
6. 选择直接回答、先追问、谨慎回答，或交给其他专用 Skill
