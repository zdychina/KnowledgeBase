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

    // ---- HyDE output schema ----
    private static final String HYDE_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "hypothetical_doc": {"type": "string"}
              },
              "required": ["hypothetical_doc"]
            }""";

    private static final String HYDE_EXAMPLE = """
            {"hypothetical_doc": "AMF注册流程包括以下步骤：1. UE通过RAN发送Registration Request；2. AMF选择鉴权方法并触发鉴权流程；3. 鉴权成功后AMF向UDM获取签约数据；4. AMF注册到UDM并建立UE上下文；5. 返回Registration Accept给UE。"}""";

    // ---- Template: serving-hyde-expansion ----
    private static final Map<String, Object> HYDE_EXPANSION = Map.ofEntries(
            Map.entry("template_key", "serving-hyde-expansion"),
            Map.entry("template_version", "2"),
            Map.entry("purpose", "生成假设性文档段落，用于 HyDE 向量检索"),
            Map.entry("system_prompt",
                    "你是一个技术文档生成助手。根据用户的查询，生成一段可能出现在相关技术手册中的回答段落。"
                    + "要求：\n"
                    + "1. 使用专业的技术文档风格\n"
                    + "2. 段落长度 100-200 字\n"
                    + "3. 输出 JSON 格式，字段 hypothetical_doc 包含生成的段落\n"
                    + "4. 内容不需要完全准确，只需在语义空间接近真实文档即可\n\n"
                    + "## JSON Schema\n{output_schema}\n\n## 示例\n{example}"),
            Map.entry("user_prompt_template", "查询：$query\n\n请生成假设性文档："),
            Map.entry("output_schema_json", HYDE_SCHEMA),
            Map.entry("_example_json", HYDE_EXAMPLE)
    );

    // ---- Multi-Query Expansion output schema ----
    private static final String MULTI_QUERY_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "variants": {
                  "type": "array",
                  "items": {"type": "string"},
                  "minItems": 1,
                  "maxItems": 4
                }
              },
              "required": ["variants"]
            }""";

    private static final String MULTI_QUERY_EXAMPLE = """
            {
              "variants": [
                "SMF 注册失败排查方法",
                "SMF registration failure troubleshooting steps",
                "SMF 无法注册到 NRF 的原因"
              ]
            }""";

    // ---- Template: serving-multi-query-expansion ----
    private static final Map<String, Object> MULTI_QUERY_EXPANSION = Map.ofEntries(
            Map.entry("template_key", "serving-multi-query-expansion"),
            Map.entry("template_version", "1"),
            Map.entry("purpose", "将用户查询改写为 2-3 个语义相近但表达不同的变体，提升检索召回率"),
            Map.entry("system_prompt",
                    "你是查询扩展助手。给定一个用户查询，生成 2-3 个语义相近但表达不同的查询变体。\n"
                    + "要求：\n"
                    + "1. 保持与原查询相同的意图和领域\n"
                    + "2. 变体之间表达方式有差异（中英文混用、同义词替换、缩写展开等）\n"
                    + "3. 不要重复原始查询\n\n"
                    + "## JSON Schema\n"
                    + "{output_schema}\n\n"
                    + "## 示例\n"
                    + "{example}"),
            Map.entry("user_prompt_template", "原始查询：$query\n\n请生成查询变体："),
            Map.entry("output_schema_json", MULTI_QUERY_SCHEMA),
            Map.entry("_example_json", MULTI_QUERY_EXAMPLE)
    );

    public static final List<Map<String, Object>> ALL = List.of(
            QUERY_UNDERSTANDING, RERANKER, HYDE_EXPANSION, MULTI_QUERY_EXPANSION);
}
