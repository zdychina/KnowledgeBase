# Stage 8 — Domain Pack 配置体系

> 审查文档 | 2026-05-21

---

## 1. 职责概述

Domain Pack 配置体系负责：
1. 定义 domain 注册表 (domain_registry.yaml): domain_id → scenario_pack + DB 配置
2. 从 domain.yaml 加载领域知识到 `DomainProfile` 不可变对象
3. 将领域特定的实体类型、语义角色、提取规则、检索策略等参数化
4. 使不同领域可通过配置切换，无需修改核心代码

**关键特性**：
- 所有数据类均为 `frozen=True`（不可变）
- 支持新旧两种 YAML 结构（分区式 vs 扁平式）
- 通过注册表实现 domain_id → scenario_pack 的解耦

---

## 2. 核心数据结构

### 2.1 DomainProfile (domain_pack.py:101)

```python
@dataclass(frozen=True)
class DomainProfile:
    domain_id: str                                    # "cloud_core_network"
    display_name: str                                 # "云核心网"

    # Entity configuration
    entity_types: frozenset[str]                      # 所有实体类型
    strong_entity_types: frozenset[str]               # 强实体类型 (用于 entity_card)

    # Semantic role mapping
    role_keyword_rules: tuple[tuple[list[str], str], ...]   # (keywords, role)
    heading_role_keywords: tuple[tuple[list[str], str], ...]

    # Rule-based extractors
    extractor_rules: tuple[ExtractorRule, ...]        # 正则提取规则

    # LLM templates
    llm_templates: tuple[dict[str, Any], ...]         # LLM prompt 模板

    # Semantic roles (v1.2+)
    semantic_roles: frozenset[str]                    # 领域支持的语义角色

    # Retrieval policy
    retrieval_policy: RetrievalPolicy                 # 检索单元生成策略

    # Eval questions
    eval_questions: tuple[EvalQuestion, ...]          # 评估问题
```

### 2.2 RetrievalPolicy (domain_pack.py:66)

```python
@dataclass(frozen=True)
class RetrievalPolicy:
    # Unit generation strategies
    raw_text: str = "primary"
    generated_question: str = "auxiliary"
    entity_card: str = "strong_entities_only"
    table_row: str = "structured_tables"

    # Limits
    max_questions_per_segment: int = 2
    max_entity_cards_per_segment: int = 3
    contextual_retrieval: str = "on"

    # Discourse thresholds
    min_confidence: float = 0.5
    max_distance: int = 5
    discourse_window_size: int = 15

    # Question-worthiness thresholds
    min_questionworthy_tokens: int = 50
    not_questionworthy_roles: frozenset[str] = frozenset({"navigation", "toc", "metadata"})
```

### 2.3 ExtractorRule (domain_pack.py:47)

```python
@dataclass(frozen=True)
class ExtractorRule:
    name: str                   # 规则名称
    pattern: str                # 正则表达式
    entity_type: str            # 提取的实体类型
    groups: tuple[dict, ...]    # 捕获组配置
    _compiled_pattern: Any      # 编译后的正则 (延迟编译)
```

### 2.4 EvalQuestion (domain_pack.py:90)

```python
@dataclass(frozen=True)
class EvalQuestion:
    id: str                              # 问题 ID
    question: str                        # 问题文本
    expected_entities: tuple[str, ...]   # 预期实体
    expected_evidence_contains: tuple[str, ...]
    expected_semantic_role: str | None
    notes: str
```

---

## 3. YAML 结构

### 3.1 新分区式结构 (推荐)

```yaml
display_name: "云核心网"

ontology:
  entity_types:
    - command
    - network_element
    - parameter
    - protocol
    - interface
    - alarm
  strong_entity_types:
    - command
    - network_element
    - parameter

mining:
  semantic_roles:
    - concept
    - parameter
    - example
    - note
    - procedure_step
    - troubleshooting_step
    - constraint
    - alarm
    - checklist

  role_keyword_rules:
    - keywords: ["配置", "设置"]
      role: "procedure_step"
    - keywords: ["告警", "故障"]
      role: "alarm"

  heading_role_keywords:
    - keywords: ["配置指南"]
      role: "procedure"

  extractor_rules:
    - name: "cli_command"
      pattern: "\\b[A-Z][a-z]+(?:-[a-z]+)*\\s+(?:display|show|set|undo)\\b"
      entity_type: "command"

  llm_templates:
    - key: "mining-segment-understanding"
      system: "..."
      user: "..."

  retrieval_policy:
    raw_text: "primary"
    generated_question: "auxiliary"
    entity_card: "strong_entities_only"
    table_row: "structured_tables"
    max_questions_per_segment: 2
    max_entity_cards_per_segment: 3
    contextual_retrieval: "on"
    min_confidence: 0.5
    max_distance: 5
    discourse_window_size: 15
    min_questionworthy_tokens: 50
    not_questionworthy_roles: ["navigation", "toc", "metadata"]

  eval_questions:
    - id: "q001"
      question: "如何配置 SMF 的 PFCP 会话？"
      expected_entities: ["SMF", "PFCP"]
      expected_semantic_role: "procedure_step"

serving:
  # 服务层配置 (mining 不读取)
```

### 3.2 旧扁平结构 (向后兼容)

```yaml
entity_types: [...]
strong_entity_types: [...]
role_keyword_rules: [...]
retrieval_policy: {...}
# 无 ontology/mining/serving 分区
```

---

## 4. 加载流程

### 4.1 domain_registry.yaml

```yaml
domains:
  cloud_core_network:
    enabled: true
    scenario_pack: cloud_core_network
    database_url_env: CLOUD_CORE_DB_URL
    default_channel: prod
  generic:
    enabled: true
    scenario_pack: generic
    database_url_env: GENERIC_DB_URL
```

### 4.2 加载链

```
load_domain_pack(domain_id)
  ↓
_resolve_scenario_pack(domain_id)
  ↓ resolve_domain(domain_id) → registry entry
  ↓ entry["scenario_pack"] → pack name
  ↓
scenario_packs/<pack>/domain.yaml
  ↓ (如果不存在)
domain_packs/<domain_id>/domain.yaml  ← legacy fallback + deprecation warning
  ↓
_parse_domain_yaml(data, domain_id)
  ↓ 检测分区 vs 扁平结构
  ↓ _parse_extractor_rules()
  ↓ _parse_role_keyword_rules()
  ↓ _parse_retrieval_policy()
  ↓ _parse_eval_questions()
  ↓
DomainProfile (frozen)
```

### 4.3 错误处理

- domain_id 不在 registry → `KeyError`
- domain 被禁用 → `ValueError`
- YAML 文件不存在 → `FileNotFoundError` (搜索两个路径)
- 使用 legacy 路径 → `DeprecationWarning`

---

## 5. 在 Pipeline 中的使用

| Stage | 使用的 profile 字段 |
|-------|-------------------|
| Enrich | `semantic_roles`, `entity_types` |
| Discourse | `retrieval_policy.min_confidence`, `.max_distance`, `.discourse_window_size` |
| Retrieval Units | `strong_entity_types`, `retrieval_policy.*` (全部) |
| LLM 模板注册 | `llm_templates` |
| Build/Publish | `domain_id` |

---

## 6. 配置参数完整清单

### entity_types vs strong_entity_types

- `entity_types`: 所有领域实体类型（用于 enrich 阶段过滤 LLM 返回的实体）
- `strong_entity_types`: 子集，用于 entity_card 生成

**当前值 (cloud_core_network)**:
- entity_types: command, network_element, parameter, protocol, interface, alarm
- strong_entity_types: command, network_element, parameter

### semantic_roles

每个领域定义自己支持的语义角色集合。enrich 阶段只接受在此集合中的角色。

### retrieval_policy 参数

见 Stage 6 文档中的详细说明。

---

## 7. 关联文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `mining/infra/domain_pack.py` | 381 | DomainProfile + RetrievalPolicy + 加载/解析逻辑 |
| `domain_registry.yaml` | — | domain_id → scenario_pack + DB 配置 |
| `scenario_packs/cloud_core_network/domain.yaml` | — | 云核心网领域配置 |
| `scenario_packs/generic/domain.yaml` | — | 通用领域配置 |
| `mining/jobs/run.py:460-469` | — | PipelineConfig 组装 (传入 profile) |

---

## 8. 工业化参考

| 参考 | 说明 |
|------|------|
| dbt `profiles.yml` | 类似的多环境配置 + 注册表 |
| Kubernetes Custom Resource | 类似的领域特定配置对象 |
| Ansible `group_vars/` | 类似的分层配置加载 |
| Hibernate `persistence.xml` | 类似的 domain 配置 |
| Django `settings.py` 分层 | 类似的默认值 + 覆盖模式 |

---

## 9. 当前不足

1. **get_default_profile() 硬编码 cloud_core_network**: 退路方案直接加载 "cloud_core_network"，如果这个 domain 不存在会抛异常
2. **无 schema 校验**: domain.yaml 的解析完全靠 `.get(key, default)` 的兜底模式，字段拼写错误或类型错误不会报错
3. **ExtractorRule.compiled 每次调用都检查 None**: 延迟编译但不缓存（frozen=True 限制了缓存机制）
4. **llm_templates 是原始 dict tuple**: 没有 PromptTemplate 数据类校验，template 格式错误在运行时才发现
5. **heading_role_keywords 未被任何 stage 使用**: 已定义但未发现引用
6. **role_keyword_rules 未被任何 stage 使用**: 同上
7. **eval_questions 未被 pipeline 使用**: 定义了评估问题但没有自动化评估流程
8. **两个路径 (scenario_packs vs domain_packs)**: 维护成本高，legacy fallback 应设置过期时间
9. **_REPO_ROOT 通过 parents[3] 计算**: 依赖文件层级结构，如果文件移动会静默出错
10. **DomainProfile 字段过多**: 13 个字段，部分字段未使用，增加了理解成本
11. **无 profile 合并/继承**: 不支持 profile 之间的继承关系（如 generic → cloud_core_network）
12. **RetrievalPolicy 的 "策略字符串" 无校验**: `"primary"` / `"auxiliary"` / `"off"` 是自由字符串，无枚举约束
