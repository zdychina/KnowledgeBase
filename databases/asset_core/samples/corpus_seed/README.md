# Corpus Seed

本目录是用户导入产品文档的入口目录。

## 使用方式

将已解析为 Markdown 格式的云核心网产品文档放入此目录，然后运行挖掘态 pipeline：

> **注意：** 以下命令为 M2+ 计划入口，当前 M0 尚未实现 `knowledge_mining.mining.jobs.run` 模块。

```bash
python -m knowledge_mining.mining.jobs.run --input databases/asset_core/samples/corpus_seed/
```

## 要求

- 文档格式：Markdown（阶段 1A 优先支持）
- 文档应已解析完成（系统不做 PDF/Word 解析）
- 文档中应包含标题层级、代码块（命令示例）、表格（参数说明）等结构化标记
