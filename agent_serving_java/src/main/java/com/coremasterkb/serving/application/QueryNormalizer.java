package com.coremasterkb.serving.application;

import com.coremasterkb.serving.client.LlmRuntimeClient;
import com.coremasterkb.serving.constants.ServingConstants;
import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.EvidenceNeed;
import com.coremasterkb.serving.domain.NormalizedQuery;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Rule-based query normalizer with optional LLM enhancement.
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

    // ---- Tokenization split ----
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

    private final Set<String> products;
    private final Set<String> networkElements;

    // ---- Intent keywords ----
    private static final Map<String, List<String>> INTENT_KEYWORDS = Map.of(
            ServingConstants.INTENT_COMMAND_USAGE,
                List.of("命令","用法","参数","格式","语法","怎么写","如何配置"),
            ServingConstants.INTENT_TROUBLESHOOT,
                List.of("故障","排查","告警","错误","异常","处理"),
            ServingConstants.INTENT_CONCEPT_LOOKUP,
                List.of("是什么","什么是","概念","介绍","概述","原理"),
            ServingConstants.INTENT_PROCEDURE,
                List.of("步骤","流程","操作","怎么做","如何操作"),
            ServingConstants.INTENT_COMPARATIVE,
                List.of("区别","对比","比较","差异","有什么不同","和...的区别")
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
            ServingConstants.INTENT_COMPARATIVE,
                List.of("concept","note"),
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

    // ---- LLM intent alias normalizer ----
    private static final Map<String, String> INTENT_ALIAS = Map.of(
            "conceptual",     ServingConstants.INTENT_CONCEPT_LOOKUP,
            "procedural",     ServingConstants.INTENT_PROCEDURE,
            "troubleshoot",   ServingConstants.INTENT_TROUBLESHOOT,
            "troubleshooting",ServingConstants.INTENT_TROUBLESHOOT,
            "comparative",    ServingConstants.INTENT_COMPARATIVE
    );

    private final LlmRuntimeClient llmClient; // nullable

    public QueryNormalizer(LlmRuntimeClient llmClient, Set<String> products, Set<String> networkElements) {
        this.llmClient = llmClient;
        this.products = products;
        this.networkElements = networkElements;
    }

    // -------------------------------------------------------------------------
    // Main entry point
    // -------------------------------------------------------------------------

    public NormalizedQuery normalize(String rawQuery) {
        if (rawQuery == null) rawQuery = "";
        String query = rawQuery.trim();

        if (llmClient != null && llmClient.isAvailable()) {
            try {
                NormalizedQuery llmResult = normalizeWithLlm(query);
                if (llmResult != null) return llmResult;
            } catch (Exception e) {
                log.debug("LLM normalization failed, using rules: {}", e.getMessage());
            }
        }

        return normalizeWithRules(query);
    }

    // -------------------------------------------------------------------------
    // LLM normalization
    // -------------------------------------------------------------------------

    private static final String LLM_SYSTEM_PROMPT =
            "You are a query normalization assistant for a telecom knowledge base.\n" +
            "Analyze the user query and return a JSON object with exactly these fields:\n" +
            "- intent: one of [command_usage, troubleshooting, concept_lookup, procedure, comparative, general]\n" +
            "- normalized_query: a cleaner restatement of the query\n" +
            "- keywords: array of key terms (strings)\n" +
            "- desired_roles: array of relevant roles from " +
            "[parameter, example, procedure_step, troubleshooting_step, alarm, constraint, concept, note]\n" +
            "- entities: array of {type, name, normalized_name} where type is one of " +
            "[command, product, version, network_element, command_op]\n" +
            "- scope: object with optional fields {version, product, network_element}\n" +
            "- evidence_need: object with fields " +
            "{preferred_roles: [], preferred_blocks: [], needs_comparison: bool, needs_citation: bool}\n" +
            "Return only the JSON object, no explanation.";

    private NormalizedQuery normalizeWithLlm(String query) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("caller_domain", "serving");
        payload.put("pipeline_stage", "normalizer");
        payload.put("messages", List.of(
                Map.of("role", "system", "content", LLM_SYSTEM_PROMPT),
                Map.of("role", "user",   "content", query)
        ));
        payload.put("expected_output_type", "json_object");

        Map<String, Object> resp = llmClient.execute(payload);
        if (resp.isEmpty()) return null;

        if (!"succeeded".equals(getStr(resp, "status", ""))) return null;

        if (!(resp.get("result") instanceof Map<?,?> resultMap)) return null;
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) resultMap;
        if (!"succeeded".equals(getStr(result, "parse_status", ""))) return null;

        if (!(result.get("parsed_output") instanceof Map<?,?> parsedMap)) return null;
        @SuppressWarnings("unchecked")
        Map<String, Object> parsed = (Map<String, Object>) parsedMap;

        String rawIntent = getStr(parsed, "intent", ServingConstants.INTENT_GENERAL);
        String intent    = INTENT_ALIAS.getOrDefault(rawIntent, rawIntent);
        List<String> keywords = getStringList(parsed, "keywords");
        List<String> roles    = getStringList(parsed, "desired_roles");
        List<EntityRef> entities = extractEntitiesFromLlmResp(parsed);

        @SuppressWarnings("unchecked")
        Map<String, Object> scope = parsed.get("scope") instanceof Map<?,?> m
                ? (Map<String, Object>) m : new HashMap<>();

        EvidenceNeed evidenceNeed = extractEvidenceNeed(parsed);

        return new NormalizedQuery(query, intent, entities, scope, keywords, roles, evidenceNeed);
    }

    @SuppressWarnings("unchecked")
    private List<EntityRef> extractEntitiesFromLlmResp(Map<String, Object> parsed) {
        Object raw = parsed.get("entities");
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

    @SuppressWarnings("unchecked")
    private EvidenceNeed extractEvidenceNeed(Map<String, Object> parsed) {
        Object raw = parsed.get("evidence_need");
        if (!(raw instanceof Map<?,?> m)) return new EvidenceNeed();
        Map<String, Object> en = (Map<String, Object>) m;
        List<String> preferredRoles  = getStringList(en, "preferred_roles");
        List<String> preferredBlocks = getStringList(en, "preferred_blocks");
        boolean needsComparison = Boolean.TRUE.equals(en.get("needs_comparison"));
        boolean needsCitation   = Boolean.TRUE.equals(en.get("needs_citation"));
        return new EvidenceNeed(preferredRoles, preferredBlocks, needsComparison, needsCitation);
    }

    // -------------------------------------------------------------------------
    // Rule-based normalization
    // -------------------------------------------------------------------------

    public NormalizedQuery normalizeWithRules(String query) {
        List<EntityRef> entities   = detectEntities(query);
        String intent              = detectIntent(query);
        Map<String, Object> scope  = extractScope(query);
        List<String> keywords      = extractKeywords(query);
        List<String> desiredRoles  = INTENT_ROLES.getOrDefault(intent, Collections.emptyList());
        EvidenceNeed evidenceNeed  = computeEvidenceNeed(intent);

        return new NormalizedQuery(query, intent, entities, scope, keywords, desiredRoles, evidenceNeed);
    }

    // -------------------------------------------------------------------------
    // Entity detection
    // -------------------------------------------------------------------------

    private List<EntityRef> detectEntities(String query) {
        List<EntityRef> entities = new ArrayList<>();

        Matcher cmdMatcher = COMMAND_PATTERN.matcher(query);
        while (cmdMatcher.find()) {
            String op  = cmdMatcher.group(1);
            String obj = cmdMatcher.group(2);
            entities.add(new EntityRef("command", op + " " + obj, op + "_" + obj));
        }

        for (Map.Entry<String, String> entry : CN_OP_MAP.entrySet()) {
            if (query.contains(entry.getKey())) {
                entities.add(new EntityRef("command_op", entry.getKey(), entry.getValue()));
            }
        }

        for (String product : products) {
            if (query.contains(product)) {
                entities.add(new EntityRef("product", product, product));
            }
        }

        for (String ne : networkElements) {
            if (query.matches(".*(?<![A-Z])" + ne + "(?![A-Z]).*")) {
                entities.add(new EntityRef("network_element", ne, ne));
            }
        }

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
                if (query.contains(kw)) return entry.getKey();
            }
        }
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

        Matcher verMatcher = VERSION_PATTERN.matcher(query);
        if (verMatcher.find()) scope.put("version", verMatcher.group());

        for (String product : products) {
            if (query.contains(product)) { scope.put("product", product); break; }
        }

        for (String ne : networkElements) {
            if (query.matches(".*(?<![A-Z])" + ne + "(?![A-Z]).*")) {
                scope.put("network_element", ne); break;
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
            if (part.length() >= 2 || CJK_CHAR.matcher(part).matches()) {
                if (!STOPWORDS_ZH.contains(part) && !STOPWORDS_EN.contains(part.toLowerCase())) {
                    keywords.add(part);
                }
            }
        }
        return keywords;
    }

    // -------------------------------------------------------------------------
    // EvidenceNeed (rule-based)
    // -------------------------------------------------------------------------

    private EvidenceNeed computeEvidenceNeed(String intent) {
        return switch (intent) {
            case ServingConstants.INTENT_COMPARATIVE    ->
                    new EvidenceNeed(Collections.emptyList(), Collections.emptyList(), true, false);
            case ServingConstants.INTENT_CONCEPT_LOOKUP ->
                    new EvidenceNeed(Collections.emptyList(), Collections.emptyList(), false, true);
            default -> new EvidenceNeed();
        };
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
