package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 检索执行计划，由 QueryPlanner 根据 NormalizedQuery 生成，贯穿整个检索流水线。
 *
 * <p>流水线各阶段均以此为唯一输入合同：
 * <pre>
 *   QueryPlanner → QueryPlan → RetrieverManager → FusionStrategy → Reranker → ContextAssembler
 * </pre>
 *
 * @param intent           查询意图，取值：command_usage | troubleshooting | concept_lookup | procedure | general
 * @param keywords         用于 FTS 检索的关键词列表，来自 NormalizedQuery.keywords
 * @param entityConstraints 实体约束列表，用于 Reranker 的加分逻辑（匹配则 +0.25）
 * @param scopeConstraints  范围约束（version / product / network_element），
 *                          用于 FtsRetriever 的 facets 过滤和 Reranker 加分（匹配则 +0.20）
 * @param desiredRoles      期望的语义角色列表（如 parameter、example、procedure_step），
 *                          用于 Reranker 加分（匹配则 +0.30）
 * @param desiredBlockTypes 期望的块类型列表（如 paragraph、table），
 *                          用于 Reranker 加分（匹配则 +0.15）
 * @param budget            检索预算：控制最终返回的 item 上限和召回倍数
 * @param expansion         图扩展配置：是否开启 BFS 扩展、最大深度、允许的关系类型
 * @param retrieverConfig   检索器配置：启用的检索器列表、融合方式（identity/rrf）、RRF 的 k 参数
 * @param rerankerConfig    重排配置：重排器类型（当前固定为 score）
 */
public record QueryPlan(
        @JsonProperty("intent") String intent,
        @JsonProperty("keywords") List<String> keywords,
        @JsonProperty("entity_constraints") List<EntityRef> entityConstraints,
        @JsonProperty("scope_constraints") Map<String, Object> scopeConstraints,
        @JsonProperty("desired_roles") List<String> desiredRoles,
        @JsonProperty("desired_block_types") List<String> desiredBlockTypes,
        @JsonProperty("budget") RetrievalBudget budget,
        @JsonProperty("expansion") ExpansionConfig expansion,
        @JsonProperty("retriever_config") RetrieverConfig retrieverConfig,
        @JsonProperty("reranker_config") RerankerConfig rerankerConfig
) {
    /** 对所有 null 字段填充安全默认值，确保下游组件无需判空。 */
    public QueryPlan {
        if (intent == null) intent = "general";
        if (keywords == null) keywords = new ArrayList<>();
        if (entityConstraints == null) entityConstraints = new ArrayList<>();
        if (scopeConstraints == null) scopeConstraints = new HashMap<>();
        if (desiredRoles == null) desiredRoles = new ArrayList<>();
        if (desiredBlockTypes == null) desiredBlockTypes = new ArrayList<>();
        if (budget == null) budget = new RetrievalBudget();
        if (expansion == null) expansion = new ExpansionConfig();
        if (retrieverConfig == null) retrieverConfig = new RetrieverConfig();
        if (rerankerConfig == null) rerankerConfig = new RerankerConfig();
    }
}
