package com.coremasterkb.serving.infrastructure;

import java.util.*;

/**
 * Serving LLM template definitions, ported from Python SERVING_TEMPLATES.
 *
 * <p>Each template is a {@code Map<String, Object>} with keys:
 * template_key, template_version, purpose, system_prompt (with {output_schema} and {example}
 * placeholders), user_prompt_template, output_schema_json, _example_json.
 */
public final class ServingTemplates {

    private ServingTemplates() {}

    // ---- Query Understanding output schema (JSON string) ----
    private static final String QUERY_UNDERSTANDING_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "intent": {
                  "type": "string",
                  "enum": ["factoid","conceptual","procedural","comparative","troubleshooting","navigational","general"]
                },
                "entities": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "type": {"type":"string"},
                      "name": {"type":"string"},
                      "normalized_name": {"type":"string"}
                    },
                    "required": ["type","name"]
                  }
                },
                "keywords": {"type":"array","items":{"type":"string"}},
                "scope": {
                  "type": "object",
                  "properties": {
                    "products": {"type":"array","items":{"type":"string"}},
                    "network_elements": {"type":"array","items":{"type":"string"}}
                  }
                },
                "evidence_need": {
                  "type": "object",
                  "properties": {
                    "preferred_roles": {"type":"array","items":{"type":"string"}},
                    "preferred_blocks": {"type":"array","items":{"type":"string"}},
                    "needs_comparison": {"type":"boolean"},
                    "needs_citation": {"type":"boolean"}
                  }
                },
                "sub_queries": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "text": {"type":"string"},
                      "intent": {"type":"string"}
                    }
                  }
                },
                "ambiguities": {"type":"array","items":{"type":"string"}}
              },
              "required": ["intent","entities","keywords"]
            }""";

    // ---- Query Understanding example (JSON string) ----
    private static final String QUERY_UNDERSTANDING_EXAMPLE = """
            {
              "intent": "procedural",
              "entities": [
                {"type": "network_element", "name": "SMF", "normalized_name": "SMF"},
                {"type": "command", "name": "ADD UPF", "normalized_name": "ADD UPF"}
              ],
              "keywords": ["SMF", "UPF", "配置"],
              "scope": {
                "products": ["UDG"],
                "network_elements": ["SMF", "UPF"]
              },
              "evidence_need": {
                "preferred_roles": ["procedure_step", "example"],
                "preferred_blocks": ["command_format", "parameter"],
                "needs_comparison": false,
                "needs_citation": false
              },
              "sub_queries": [],
              "ambiguities": []
            }""";

    // ---- Reranker output schema (JSON string) ----
    private static final String RERANKER_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "ranking": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "index": {"type":"integer"},
                      "score": {"type":"number","minimum":0.0,"maximum":1.0}
                    },
                    "required": ["index","score"]
                  }
                }
              },
              "required": ["ranking"]
            }""";

    // ---- Reranker example (JSON string) ----
    private static final String RERANKER_EXAMPLE = """
            {
              "ranking": [
                {"index": 0, "score": 0.95},
                {"index": 2, "score": 0.78},
                {"index": 1, "score": 0.45}
              ]
            }""";

    // ---- Template: serving-query-understanding ----
    private static final Map<String, Object> QUERY_UNDERSTANDING = Map.ofEntries(
            Map.entry("template_key", "serving-query-understanding"),
            Map.entry("template_version", "2"),
            Map.entry("purpose", "理解用户查询，提取意图、实体、关键词和证据需求"),
            Map.entry("system_prompt",
                    "你是一个知识库查询理解系统。你的任务是分析用户的查询，提取以下信息：\n"
                    + "1. 意图分类（factoid/conceptual/procedural/comparative/troubleshooting/navigational/general）\n"
                    + "2. 命名实体（网络元素如SMF/AMF/UPF、命令如ADD/MOD/DEL、产品名如UDG/UNC/CloudCore）\n"
                    + "3. 关键词（去除停用词后的核心词）\n"
                    + "4. 证据需求（需要什么类型的证据来回答）\n\n"
                    + "## JSON Schema 结构定义\n"
                    + "{output_schema}\n\n"
                    + "## 输出要求\n"
                    + "输出严格的 JSON 格式，不要添加任何其他文本。下面是一个输出示例（仅供参考格式，请根据实际内容生成）：\n"
                    + "{example}"),
            Map.entry("user_prompt_template", "分析以下查询：\n\n$query"),
            Map.entry("output_schema_json", QUERY_UNDERSTANDING_SCHEMA),
            Map.entry("_example_json", QUERY_UNDERSTANDING_EXAMPLE)
    );

    // ---- Template: serving-reranker ----
    private static final Map<String, Object> RERANKER = Map.ofEntries(
            Map.entry("template_key", "serving-reranker"),
            Map.entry("template_version", "2"),
            Map.entry("purpose", "对检索结果进行 LLM 相关性重排序"),
            Map.entry("system_prompt",
                    "你是一个文档相关性评估系统。你的任务是根据查询对候选文档进行相关性排序。\n"
                    + "对于每个候选文档，给出一个0-1之间的相关性分数。\n"
                    + "按相关性从高到低排列。\n\n"
                    + "## JSON Schema 结构定义\n"
                    + "{output_schema}\n\n"
                    + "## 输出要求\n"
                    + "输出严格的 JSON 格式，不要添加任何其他文本。下面是一个输出示例（仅供参考格式，请根据实际内容生成）：\n"
                    + "{example}"),
            Map.entry("user_prompt_template",
                    "查询：$query\n\n"
                    + "候选文档：\n$candidates\n\n"
                    + "请对以上 $count 个候选文档按相关性排序。"),
            Map.entry("output_schema_json", RERANKER_SCHEMA),
            Map.entry("_example_json", RERANKER_EXAMPLE)
    );

    public static final List<Map<String, Object>> ALL = List.of(QUERY_UNDERSTANDING, RERANKER);
}
