package com.coremasterkb.serving.application;

import com.coremasterkb.serving.client.LlmRuntimeClient;
import com.coremasterkb.serving.constants.ServingConstants;
import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.NormalizedQuery;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Rule-based query normalizer with optional LLM enhancement.
 * Translated from application/normalizer.py.
 *
 * Two-layer strategy:
 *   1. Try LLM if available (LlmRuntimeClient.isAvailable())
 *   2. Fall back to deterministic rules
 */
public class QueryNormalizer {

    private static final Logger log = LoggerFactory.getLogger(QueryNormalizer.class);

    // ---- Command pattern ----
    private static final Pattern COMMAND_PATTERN =
            Pattern.compile("(ADD|MOD|DEL|SET|SHOW|LST|DSP)\\s+([A-Z][A-Z0-9_]*)");

    // ---- Version pattern ----
    private static final Pattern VERSION_PATTERN =
            Pattern.compile("V\\d{3}R\\d{3}(C\\d{2})?");

    // ---- Tokenization split (mirrors Python regex) ----
    private static final Pattern TOKEN_SPLIT =
            Pattern.compile("[\\s,，、？?。.！!；;：:]+");

    // ---- CJK single-char detection ----
    private static final Pattern CJK_CHAR = Pattern.compile("[\\u4e00-\\u9fff]");

    // ---- CN operator → EN command map ----
    private static final Map<String, String> CN_OP_MAP = Map.of(
            "新增", "ADD",
            "修改", "MOD",
            "删除", "DEL",
            "查询", "SHOW",
            "查看", "DSP",
            "显示", "LST",
            "设置", "SET",
            "配置", "SET"
    );

    // ---- Known products ----
    private static final Set<String> PRODUCTS = Set.of("UDG", "UNC", "CloudCore");

    // ---- Known network elements ----
    private static final Set<String> NETWORK_ELEMENTS = Set.of(
            "AMF","SMF","UPF","UDM","PCF","NRF","AUSF","BSF","NSSF","SCP","UDSF","UDR"
    );

    // ---- Intent keywords ----
    private static final Map<String, List<String>> INTENT_KEYWORDS = Map.of(
            ServingConstants.INTENT_COMMAND_USAGE,
                List.of("命令","用法","参数","格式","语法","怎么写","如何配置"),
            ServingConstants.INTENT_TROUBLESHOOT,
                List.of("故障","排查","告警","错误","异常","处理"),
            ServingConstants.INTENT_CONCEPT_LOOKUP,
                List.of("是什么","什么是","概念","介绍","概述","原理"),
            ServingConstants.INTENT_PROCEDURE,
                List.of("步骤","流程","操作","怎么做","如何操作")
    );

    // ---- Intent → desired roles map ----
    private static final Map<String, List<String>> INTENT_ROLES = Map.of(
            ServingConstants.INTENT_COMMAND_USAGE,
                List.of("parameter","example","procedure_step"),
            ServingConstants.INTENT_TROUBLESHOOT,
                List.of("troubleshooting_step","alarm","constraint"),
            ServingConstants.INTENT_CONCEPT_LOOKUP,
                List.of("concept","note"),
            ServingConstants.INTENT_PROCEDURE,
                List.of("procedure_step","parameter","example"),
            ServingConstants.INTENT_GENERAL,
                Collections.emptyList()
    );

    // ---- Stopwords ----
    private static final Set<String> STOPWORDS_ZH = Set.of(
            "的","了","在","是","和","与","及","或","也","都","这","那","有","没","不","会","能","要",
            "可以","什么","怎么","如何","哪些","为什么","吗","呢","啊","个","一","到","把","被","让",
            "给","从","对","等","请问","帮我","告诉","知道","想","应该","需要"
    );
    private static final Set<String> STOPWORDS_EN = Set.of(
            "a","an","the","is","are","was","were","be","been","do","does","did",
            "has","have","had","and","or","but","not","no","in","on","at","to","of",
            "for","with","from","by","as","what","which","how","why","when","where","who"
    );

    private final LlmRuntimeClient llmClient; // nullable

    public QueryNormalizer(LlmRuntimeClient llmClient) {
        this.llmClient = llmClient;
    }

    // -------------------------------------------------------------------------
    // Main entry point
    // -------------------------------------------------------------------------

    /**
     * Normalize the raw query string. Tries LLM enhancement first if available,
     * then falls back to rule-based logic.
     */
    public NormalizedQuery normalize(String rawQuery) {
        if (rawQuery == null) rawQuery = "";
        String query = rawQuery.trim();

        // Layer 1: LLM enhancement (optional)
        if (llmClient != null && llmClient.isAvailable()) {
            try {
                NormalizedQuery llmResult = normalizeWithLlm(query);
                if (llmResult != null) {
                    return llmResult;
                }
            } catch (Exception e) {
                log.debug("LLM normalization failed, using rules: {}", e.getMessage());
            }
        }

        // Layer 2: rule-based
        return normalizeWithRules(query);
    }

    // -------------------------------------------------------------------------
    // LLM normalization
    // -------------------------------------------------------------------------

    private NormalizedQuery normalizeWithLlm(String query) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("task_type", "query_normalization");
        payload.put("query", query);

        Map<String, Object> resp = llmClient.execute(payload);
        if (resp.isEmpty()) return null;

        // Parse LLM response fields
        String intent  = getStr(resp, "intent", ServingConstants.INTENT_GENERAL);
        String normalized = getStr(resp, "normalized_query", query);
        List<String> keywords = getStringList(resp, "keywords");
        List<String> roles    = getStringList(resp, "desired_roles");

        // Entities from LLM
        List<EntityRef> entities = extractEntitiesFromLlmResp(resp);

        // Scope from LLM (pass-through map)
        @SuppressWarnings("unchecked")
        Map<String, Object> scope = resp.get("scope") instanceof Map<?,?> m
                ? (Map<String, Object>) m : new HashMap<>();

        return new NormalizedQuery(query, intent, entities, scope, keywords, roles);
    }

    @SuppressWarnings("unchecked")
    private List<EntityRef> extractEntitiesFromLlmResp(Map<String, Object> resp) {
        Object raw = resp.get("entities");
        if (!(raw instanceof List<?> list)) return Collections.emptyList();
        List<EntityRef> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof Map<?,?> m) {
                Map<String, Object> em = (Map<String, Object>) m;
                String type = getStr(em, "type", "");
                String name = getStr(em, "name", "");
                String norm = getStr(em, "normalized_name", "");
                if (!name.isBlank()) result.add(new EntityRef(type, name, norm));
            }
        }
        return result;
    }

    // -------------------------------------------------------------------------
    // Rule-based normalization
    // -------------------------------------------------------------------------

    public NormalizedQuery normalizeWithRules(String query) {
        // 1. Detect entities
        List<EntityRef> entities = detectEntities(query);

        // 2. Detect intent
        String intent = detectIntent(query);

        // 3. Extract scope (version, product, NE)
        Map<String, Object> scope = extractScope(query);

        // 4. Tokenize + filter keywords
        List<String> keywords = extractKeywords(query);

        // 5. Map intent → desired roles
        List<String> desiredRoles = INTENT_ROLES.getOrDefault(intent, Collections.emptyList());

        return new NormalizedQuery(query, intent, entities, scope, keywords, desiredRoles);
    }

    // -------------------------------------------------------------------------
    // Entity detection
    // -------------------------------------------------------------------------

    private List<EntityRef> detectEntities(String query) {
        List<EntityRef> entities = new ArrayList<>();

        // Command entities (e.g. ADD USER_GROUP)
        Matcher cmdMatcher = COMMAND_PATTERN.matcher(query);
        while (cmdMatcher.find()) {
            String op  = cmdMatcher.group(1);
            String obj = cmdMatcher.group(2);
            entities.add(new EntityRef("command", op + " " + obj, op + "_" + obj));
        }

        // CN operator translations
        for (Map.Entry<String, String> entry : CN_OP_MAP.entrySet()) {
            if (query.contains(entry.getKey())) {
                entities.add(new EntityRef("command_op", entry.getKey(), entry.getValue()));
            }
        }

        // Products
        for (String product : PRODUCTS) {
            if (query.contains(product)) {
                entities.add(new EntityRef("product", product, product));
            }
        }

        // Network elements
        for (String ne : NETWORK_ELEMENTS) {
            // Whole-word match using word boundaries or surrounded by non-alpha
            if (query.matches(".*(?<![A-Z])" + ne + "(?![A-Z]).*")) {
                entities.add(new EntityRef("network_element", ne, ne));
            }
        }

        // Versions
        Matcher verMatcher = VERSION_PATTERN.matcher(query);
        while (verMatcher.find()) {
            String ver = verMatcher.group();
            entities.add(new EntityRef("version", ver, ver));
        }

        return entities;
    }

    // -------------------------------------------------------------------------
    // Intent detection
    // -------------------------------------------------------------------------

    private String detectIntent(String query) {
        for (Map.Entry<String, List<String>> entry : INTENT_KEYWORDS.entrySet()) {
            for (String kw : entry.getValue()) {
                if (query.contains(kw)) {
                    return entry.getKey();
                }
            }
        }
        // Check if query looks like a command (EN pattern)
        if (COMMAND_PATTERN.matcher(query).find()) {
            return ServingConstants.INTENT_COMMAND_USAGE;
        }
        return ServingConstants.INTENT_GENERAL;
    }

    // -------------------------------------------------------------------------
    // Scope extraction
    // -------------------------------------------------------------------------

    private Map<String, Object> extractScope(String query) {
        Map<String, Object> scope = new HashMap<>();

        // Version
        Matcher verMatcher = VERSION_PATTERN.matcher(query);
        if (verMatcher.find()) {
            scope.put("version", verMatcher.group());
        }

        // Product
        for (String product : PRODUCTS) {
            if (query.contains(product)) {
                scope.put("product", product);
                break;
            }
        }

        // Network element
        for (String ne : NETWORK_ELEMENTS) {
            if (query.matches(".*(?<![A-Z])" + ne + "(?![A-Z]).*")) {
                scope.put("network_element", ne);
                break;
            }
        }

        return scope;
    }

    // -------------------------------------------------------------------------
    // Keyword extraction
    // -------------------------------------------------------------------------

    private List<String> extractKeywords(String query) {
        String[] parts = TOKEN_SPLIT.split(query.trim());
        List<String> keywords = new ArrayList<>();
        for (String part : parts) {
            if (part.isEmpty()) continue;
            // Keep len >= 2 or single CJK character
            if (part.length() >= 2 || CJK_CHAR.matcher(part).matches()) {
                if (!STOPWORDS_ZH.contains(part) && !STOPWORDS_EN.contains(part.toLowerCase())) {
                    keywords.add(part);
                }
            }
        }
        return keywords;
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private String getStr(Map<String, Object> map, String key, String defaultVal) {
        Object val = map.get(key);
        return val instanceof String s ? s : defaultVal;
    }

    @SuppressWarnings("unchecked")
    private List<String> getStringList(Map<String, Object> map, String key) {
        Object val = map.get(key);
        if (!(val instanceof List<?> list)) return Collections.emptyList();
        List<String> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof String s) result.add(s);
        }
        return result;
    }
}
