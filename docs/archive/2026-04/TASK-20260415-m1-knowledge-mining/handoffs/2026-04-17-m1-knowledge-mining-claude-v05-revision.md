# M1 Knowledge Mining v0.5 修订 — Claude Mining Handoff

## 任务目标

根据 Codex v0.5 schema 审查反馈，对 M1 Mining pipeline 进行全面修正。

## 本次修正范围

### P1-1: Markdown section tree 重复切片（重大 Bug）
- **问题**：`_build_section_tree()` 把同一 heading 同时挂到 root 和 parent section，导致同一段内容产生重复 raw_segments
- **修正**：重写 `structure/__init__.py`，使用 stack-based 层级构建，H1→H2→H3 严格嵌套，无重复
- **文件**：`knowledge_mining/mining/structure/__init__.py`

### P1-2: Markdown table 结构丢失
- **问题**：table 所有 inline token 用 `" | "` 拼接，无 columns/rows 结构
- **修正**：重写 `_parse_table()`，利用 thead_open/tbody_open/tr_open/th_open/td_open token 语义，构建 `{kind, columns, rows, row_count, col_count}`
- **新增**：`ContentBlock` 增加 `structure` 和 `line_start/line_end` 字段
- **文件**：`knowledge_mining/mining/models.py`, `knowledge_mining/mining/structure/__init__.py`, `knowledge_mining/mining/segmentation/__init__.py`

### P1-3: canonicalization 三层归并失效
- **问题**：exact layer 处理所有 group（包括 singleton），导致 normalized/near layer 无输入
- **修正**：exact layer 只处理 `len(group) > 1` 的 group，singleton 进入 normalized/near 候选池
- **文件**：`knowledge_mining/mining/canonicalization.py`

### P1-4: version_code 秒级时间戳碰撞
- **问题**：`pv-YYYYMMDD-HHmmss` 同秒连续发布会撞唯一键
- **修正**：改为 `pv-YYYYMMDD-HHmmss-XXXXXX`（6 位 hex），无需 sleep
- **文件**：`knowledge_mining/mining/publishing/__init__.py`

### P1-5: 发布事务边界 active 丢失风险
- **问题**：activate + metadata 更新若中间出错，旧 active 已被 archive
- **修正**：activate + metadata 更新在同一 commit 前完成
- **文件**：`knowledge_mining/mining/publishing/__init__.py`

### P1-6: primary source 校验漏掉 zero-primary
- **问题**：只查 `WHERE is_primary = 1`，漏掉完全没有 primary 的 canonical
- **修正**：改用 LEFT JOIN 查询，同时检测 zero-primary 和 zero-source
- **文件**：`knowledge_mining/mining/publishing/__init__.py`

### P2-1: source_offsets_json 太弱
- **问题**：只有 `block_index` 和 `section_title`
- **修正**：补充 `parser`、`line_start`、`line_end`
- **文件**：`knowledge_mining/mining/segmentation/__init__.py`, `knowledge_mining/mining/jobs/run.py`

### P2-2: TXT parser 丢失标点
- **问题**：tokenize 只保留 alnum+CJK，重组时丢失标点
- **修正**：改为按段落/空行切片，超长段按原文 offset 窗口切分，raw_text 保持原文
- **文件**：`knowledge_mining/mining/parsers/__init__.py`

### P2-3: processing_profile_json 缺 parse_status
- **修正**：所有文档在 publishing 时写入 `parse_status: parsed/skipped`
- **文件**：`knowledge_mining/mining/publishing/__init__.py`

### P2-4: conflict_candidate 声明
- **状态**：M1 明确不自动生成 `conflict_candidate`，代码注释和测试中已声明

## 改动文件清单

| 文件 | 改动类型 |
|------|---------|
| `knowledge_mining/mining/models.py` | ContentBlock 新增 structure/line_start/line_end |
| `knowledge_mining/mining/structure/__init__.py` | 重写 tree 构建 + table 解析 |
| `knowledge_mining/mining/segmentation/__init__.py` | structure_json 透传 + source_offsets 丰富 |
| `knowledge_mining/mining/parsers/__init__.py` | TXT parser 原文切片 |
| `knowledge_mining/mining/canonicalization.py` | 三层归并逻辑修正 |
| `knowledge_mining/mining/publishing/__init__.py` | version_code + 事务 + validation |
| `knowledge_mining/mining/jobs/run.py` | 传递 parser_name |
| `knowledge_mining/tests/test_v05_fix_regression.py` | 新增 13 个回归测试 |

## 已执行验证

```bash
python -m pytest knowledge_mining/tests/ -q
# 197 passed (184 原有 + 13 新增)
```

新增测试覆盖：
- table segment 不重复
- paragraph 不重复
- H1→H2 层级正确
- table structure_json 有 columns/rows/row_count/col_count
- normalized duplicate 合并（不同 content_hash，相同 normalized_hash）
- singleton 保持独立
- 快速连续发布无 version_code 碰撞
- source_offsets_json 有 parser/block_index
- TXT parser 保留标点
- processing_profile_json 有 parse_status

## 未验证项

- 未使用管理员正式混合测试文件夹验证
- 未验证 Serving 当前 v0.5 是否能读取 Mining 生成 DB
- 嵌套 list、blockquote、code fence 在复杂真实样本中的保真度

## 已知风险

- `_parse_table()` 对合并单元格（colspan/rowspan）不支持，但 markdown-it 不产生这类 token
- `_split_long_text()` 的 token 边界检测对混合 CJK+英文文本可能产生略偏的切分点

## 指定给 Codex 的审查重点

1. `_build_section_tree()` → `_build_nested_section()` → `_split_sub_sections()` 层级是否正确无遗漏
2. `_parse_table()` 的 thead/tbody/tr/th/td 状态机是否覆盖所有 markdown-it token 组合
3. canonicalization exact layer 只处理 `len > 1` 的 group 是否符合三层归并预期
4. validation LEFT JOIN SQL 是否正确检测 zero-primary

## 管理员本轮直接介入记录

管理员确认 Codex 审查意见后指示 Claude Mining 执行修正。
