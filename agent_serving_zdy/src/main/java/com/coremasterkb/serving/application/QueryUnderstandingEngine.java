package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import com.coremasterkb.serving.infrastructure.LlmClient;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.huaban.analysis.jieba.JiebaSegmenter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.regex.Pattern;

/**
 * LLM-first query understanding with rule-based fallback.
 *
 * <p>Matches Python's QueryUnderstandingEngine behavior:
 * <ul>
 *   <li>7 intent types: command_usage, troubleshooting, concept_lookup, procedure, comparison, navigational, general</li>
 *   <li>Entity extraction via Domain Pack extractor_rules + default command regex + Chinese op map</li>
 *   <li>jieba tokenization for keyword extraction</li>
 *   <li>Scope extraction (products + network_elements)</li>
 *   <li>SubQuery decomposition (LLM path only)</li>
 *   <li>EvidenceNeed classification</li>
 *   <li>Ambiguity detection (LLM path only)</li>
 * </ul>
 */
@Component
public class QueryUnderstandingEngine {

    private static final Logger log = LoggerFactory.getLogger(QueryUnderstandingEngine.class);

    private static final ObjectMapper MAPPER = new ObjectMapper();

    // ---- Intent keyword sets (same as Python) ----
    private static final Set<String> INTENT_COMMAND_KW = Set.of(
            "命令", "用法", "参数", "格式", "语法", "怎么写", "如何配置");
    private static final Set<String> INTENT_TROUBLESHOOT_KW = Set.of(
            "故障", "排查", "告警", "错误", "异常", "处理");
    private static final Set<String> INTENT_CONCEPT_KW = Set.of(
            "是什么", "什么是", "概念", "介绍", "概述", "原理");
    private static final Set<String> INTENT_PROCEDURE_KW = Set.of(
            "步骤", "流程", "操作", "怎么做", "如何操作");
    private static final Set<String> INTENT_COMPARISON_KW = Set.of(
            "区别", "差异", "对比", "比较", "不同");
    private static final Set<String> INTENT_NAVIGATION_KW = Set.of(
            "在哪里", "如何找到", "路径");

    // ---- Default command regex ----
    private static final Pattern DEFAULT_COMMAND_RE = Pattern.compile(
            "(ADD|MOD|DEL|SET|SHOW|LST|DSP|REG|DEREG)\\s+([A-Z][A-Z0-9_]*)",
            Pattern.CASE_INSENSITIVE);

    // ---- Chinese op map ----
    private static final Map<String, String> DEFAULT_OP_MAP = Map.ofEntries(
            Map.entry("新增", "ADD"), Map.entry("添加", "ADD"), Map.entry("创建", "ADD"),
            Map.entry("修改", "MOD"), Map.entry("更改", "MOD"), Map.entry("编辑", "MOD"),
            Map.entry("删除", "DEL"), Map.entry("移除", "DEL"),
            Map.entry("查询", "SHOW"), Map.entry("查看", "DSP"), Map.entry("显示", "LST"),
            Map.entry("设置", "SET"), Map.entry("配置", "SET"));

    // ---- Default network elements and products ----
    private static final List<String> DEFAULT_NE = List.of(
            "AMF", "SMF", "UPF", "UDM", "PCF", "NRF",
            "AUSF", "BSF", "NSSF", "SCP", "UDSF", "UDR");
    private static final List<String> DEFAULT_PRODUCTS = List.of("UDG", "UNC", "CloudCore");

    // Pre-compiled word-boundary patterns for the default lists (avoid per-request Pattern.compile)
    private static final Map<String, Pattern> DEFAULT_NE_PATTERNS       = buildPatternMap(DEFAULT_NE);
    private static final Map<String, Pattern> DEFAULT_PRODUCT_PATTERNS  = buildPatternMap(DEFAULT_PRODUCTS);

    // ---- Stopwords (Chinese + English, same as Python) ----
    private static final Set<String> STOPWORDS_ZH = Set.of(
            "的", "了", "在", "是", "和", "与", "及", "或", "也", "都",
            "这", "那", "有", "没", "不", "会", "能", "要", "可以",
            "什么", "怎么", "如何", "哪些", "为什么", "吗", "呢", "啊",
            "个", "一", "到", "把", "被", "让", "给", "从", "对", "等",
            "请问", "帮我", "告诉", "知道", "想", "应该", "需要");
    private static final Set<String> STOPWORDS_EN = Set.of(
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "do", "does", "did", "has", "have", "had",
            "and", "or", "but", "not", "no", "in", "on", "at", "to",
            "of", "for", "with", "from", "by", "as",
            "what", "which", "how", "why", "when", "where", "who");
    private static final Set<String> ALL_STOPWORDS;
    static {
        Set<String> combined = new HashSet<>(STOPWORDS_ZH);
        combined.addAll(STOPWORDS_EN);
        ALL_STOPWORDS = Collections.unmodifiableSet(combined);
    }

    // ---- Intent -> evidence role map ----
    private static final Map<String, List<String>> INTENT_ROLE_MAP = Map.of(
            "command_usage", List.of("parameter", "example", "procedure_step"),
            "troubleshooting", List.of("troubleshooting_step", "alarm", "constraint"),
            "concept_lookup", List.of("concept", "note"),
            "procedure", List.of("procedure_step", "parameter", "example"),
            "comparison", List.of("concept", "parameter"),
            "navigational", List.of(),
            "general", List.of()
    );

    private static final ThreadLocal<JiebaSegmenter> SEGMENTER_TL =
            ThreadLocal.withInitial(JiebaSegmenter::new);

    private final LlmClient llmClient;

    public QueryUnderstandingEngine(LlmClient llmClient) {
        this.llmClient = llmClient;
    }

    /**
     * Understand a user query: LLM path first, rule fallback on failure.
     */
    public QueryUnderstanding understand(String query, ServingDomainProfile profile) {
        // LLM path
        if (llmClient != null && llmClient.isAvailable()) {
            QueryUnderstanding result = tryLlmUnderstand(query);
            if (result != null) {
                return result;
            }
        }
        // Rule fallback
        return ruleUnderstand(query, profile);
    }

    // =========================================================================
    // LLM path
    // =========================================================================

    private QueryUnderstanding tryLlmUnderstand(String query) {
        try {
            Map<String, Object> result = llmClient.execute(
                    "query_understanding",
                    "serving-query-understanding",
                    Map.of("query", query));

            // Execute endpoint returns {task_id, status, result: {parsed_output, ...}}
            Object innerObj = result.getOrDefault("result", result);
            @SuppressWarnings("unchecked")
            Map<String, Object> inner = (innerObj instanceof Map) ? (Map<String, Object>) innerObj : Map.of();
            @SuppressWarnings("unchecked")
            Map<String, Object> parsed = (Map<String, Object>) inner.getOrDefault("parsed_output", Map.of());

            if (parsed.isEmpty()) {
                return null;
            }
            return parseLlmOutput(query, parsed);
        } catch (Exception e) {
            log.warn("LLM query understanding failed, falling back to rules: {}", e.getMessage());
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private QueryUnderstanding parseLlmOutput(String query, Map<String, Object> parsed) {
        // Entities
        List<EntityRef> entities = new ArrayList<>();
        List<Map<String, Object>> rawEntities = (List<Map<String, Object>>) parsed.getOrDefault("entities", List.of());
        for (var e : rawEntities) {
            String name = String.valueOf(e.getOrDefault("name", ""));
            entities.add(new EntityRef(
                    String.valueOf(e.getOrDefault("type", "unknown")),
                    name,
                    String.valueOf(e.getOrDefault("normalized_name", name))
            ));
        }

        // Sub-queries
        List<SubQuery> subQueries = new ArrayList<>();
        List<Map<String, Object>> rawSubQueries = (List<Map<String, Object>>) parsed.getOrDefault("sub_queries", List.of());
        for (var sq : rawSubQueries) {
            subQueries.add(new SubQuery(
                    String.valueOf(sq.getOrDefault("text", "")),
                    String.valueOf(sq.getOrDefault("intent", "general")),
                    null
            ));
        }

        // Evidence need
        Map<String, Object> evidenceMap = (Map<String, Object>) parsed.getOrDefault("evidence_need", Map.of());
        List<String> preferredRoles = (List<String>) evidenceMap.getOrDefault("preferred_roles", List.of());
        List<String> preferredBlocks = (List<String>) evidenceMap.getOrDefault("preferred_blocks", List.of());
        boolean needsComparison = Boolean.TRUE.equals(evidenceMap.get("needs_comparison"));
        boolean needsCitation = Boolean.TRUE.equals(evidenceMap.get("needs_citation"));

        // Keywords
        List<String> keywords = (List<String>) parsed.getOrDefault("keywords", List.of());

        // Scope
        Map<String, Object> scope = (Map<String, Object>) parsed.getOrDefault("scope", Map.of());

        // Ambiguities
        List<String> ambiguities = (List<String>) parsed.getOrDefault("ambiguities", List.of());

        // Intent
        String rawIntent = String.valueOf(parsed.getOrDefault("intent", "general"));
        String normalizedIntent = normalizeIntent(rawIntent);

        return new QueryUnderstanding(
                query,
                normalizedIntent,
                subQueries,
                entities,
                scope,
                keywords,
                new EvidenceNeed(preferredRoles, preferredBlocks, needsComparison, needsCitation),
                ambiguities,
                "llm"
        );
    }

    // =========================================================================
    // Rule-based fallback
    // =========================================================================

    private QueryUnderstanding ruleUnderstand(String query, ServingDomainProfile profile) {
        // Load config from profile
        Pattern cmdRe = DEFAULT_COMMAND_RE;
        Map<String, String> opMap = DEFAULT_OP_MAP;
        List<String> neList = DEFAULT_NE;
        List<String> products = DEFAULT_PRODUCTS;

        if (profile != null && profile.queryUnderstanding() != null && !profile.queryUnderstanding().isEmpty()) {
            Map<String, Object> qu = profile.queryUnderstanding();
            String regexStr = (String) qu.get("command_regex");
            if (regexStr != null && !regexStr.isBlank()) {
                cmdRe = Pattern.compile(regexStr, Pattern.CASE_INSENSITIVE);
            }
            @SuppressWarnings("unchecked")
            Map<String, String> customOpMap = (Map<String, String>) (Map<?, ?>) qu.get("op_map");
            if (customOpMap != null && !customOpMap.isEmpty()) {
                opMap = customOpMap;
            }
            @SuppressWarnings("unchecked")
            List<String> customNe = (List<String>) qu.get("network_elements");
            if (customNe != null && !customNe.isEmpty()) {
                neList = customNe;
            }
            @SuppressWarnings("unchecked")
            List<String> customProducts = (List<String>) qu.get("products");
            if (customProducts != null && !customProducts.isEmpty()) {
                products = customProducts;
            }
        }

        Map<String, Pattern> nePatterns      = (neList == DEFAULT_NE)      ? DEFAULT_NE_PATTERNS      : buildPatternMap(neList);
        Map<String, Pattern> productPatterns = (products == DEFAULT_PRODUCTS) ? DEFAULT_PRODUCT_PATTERNS : buildPatternMap(products);

        List<EntityRef> entities = extractEntities(query, profile, cmdRe, opMap);
        Map<String, Object> scope = extractScope(query, nePatterns, productPatterns);
        String intent = detectIntent(query, entities);
        List<String> keywords = extractKeywords(query, cmdRe);

        return new QueryUnderstanding(
                query,
                normalizeIntent(intent),
                List.of(),
                entities,
                scope,
                keywords,
                new EvidenceNeed(INTENT_ROLE_MAP.getOrDefault(intent, List.of()), List.of(), false, false),
                List.of(),
                "rule"
        );
    }

    // =========================================================================
    // Entity extraction
    // =========================================================================

    private List<EntityRef> extractEntities(String query, ServingDomainProfile profile,
                                            Pattern cmdRe, Map<String, String> opMap) {
        List<EntityRef> entities = new ArrayList<>();

        // Domain Pack driven extractors
        if (profile != null && profile.extractorRules() != null) {
            for (Map<String, Object> rule : profile.extractorRules()) {
                String pattern = rule != null ? (String) rule.get("pattern") : null;
                String entityType = rule != null ? (String) rule.getOrDefault("entity_type", "unknown") : "unknown";
                if (pattern != null && !pattern.isBlank()) {
                    try {
                        var matcher = Pattern.compile(pattern).matcher(query);
                        while (matcher.find()) {
                            entities.add(new EntityRef(entityType, matcher.group(0), matcher.group(0).toUpperCase()));
                        }
                    } catch (Exception e) {
                        // skip bad pattern
                    }
                }
            }
        }

        // Default command extraction
        String cmd = extractCommand(query, cmdRe, opMap);
        if (cmd != null) {
            boolean alreadyPresent = entities.stream().anyMatch(e -> cmd.equals(e.name()));
            if (!alreadyPresent) {
                entities.add(new EntityRef("command", cmd, cmd));
            }
        }

        return entities;
    }

    private String extractCommand(String query, Pattern cmdRe, Map<String, String> opMap) {
        // Try regex match first
        var matcher = cmdRe.matcher(query);
        if (matcher.find()) {
            return matcher.group(1).toUpperCase() + " " + matcher.group(2).toUpperCase();
        }

        // Try Chinese op map
        for (var entry : opMap.entrySet()) {
            String cnWord = entry.getKey();
            String cmdPrefix = entry.getValue();
            int idx = query.indexOf(cnWord);
            if (idx >= 0) {
                String after = query.substring(idx + cnWord.length());
                var targetMatcher = Pattern.compile("\\s*([A-Za-z][A-Za-z0-9_]*)").matcher(after);
                if (targetMatcher.find()) {
                    return cmdPrefix + " " + targetMatcher.group(1).toUpperCase();
                }
                return cmdPrefix;
            }
        }
        return null;
    }

    // =========================================================================
    // Scope extraction
    // =========================================================================

    private Map<String, Object> extractScope(
            String query,
            Map<String, Pattern> nePatterns,
            Map<String, Pattern> productPatterns) {
        Map<String, Object> scope = new LinkedHashMap<>();

        Set<String> prods = new TreeSet<>();
        for (Map.Entry<String, Pattern> e : productPatterns.entrySet()) {
            if (e.getValue().matcher(query).find()) {
                prods.add(e.getKey().toUpperCase());
            }
        }
        if (!prods.isEmpty()) scope.put("products", List.copyOf(prods));

        Set<String> nes = new TreeSet<>();
        for (Map.Entry<String, Pattern> e : nePatterns.entrySet()) {
            if (e.getValue().matcher(query).find()) {
                nes.add(e.getKey().toUpperCase());
            }
        }
        if (!nes.isEmpty()) scope.put("network_elements", List.copyOf(nes));

        return scope;
    }

    private static Map<String, Pattern> buildPatternMap(List<String> terms) {
        Map<String, Pattern> map = new LinkedHashMap<>();
        for (String t : terms) {
            map.put(t, Pattern.compile(
                    "(?<![A-Za-z0-9_])" + Pattern.quote(t) + "(?![A-Za-z0-9_])",
                    Pattern.CASE_INSENSITIVE));
        }
        return Collections.unmodifiableMap(map);
    }

    // =========================================================================
    // Intent detection
    // =========================================================================

    private String detectIntent(String query, List<EntityRef> entities) {
        // Command entity detected
        if (entities.stream().anyMatch(e -> "command".equals(e.type()))) {
            return ServingConstants.INTENT_COMMAND_USAGE;
        }

        // Keyword matching in priority order (same as Python)
        if (containsAny(query, INTENT_COMPARISON_KW)) return "comparison";
        if (containsAny(query, INTENT_TROUBLESHOOT_KW)) return ServingConstants.INTENT_TROUBLESHOOT;
        if (containsAny(query, INTENT_PROCEDURE_KW)) return ServingConstants.INTENT_PROCEDURE;
        if (containsAny(query, INTENT_CONCEPT_KW)) return ServingConstants.INTENT_CONCEPT_LOOKUP;
        if (containsAny(query, INTENT_NAVIGATION_KW)) return ServingConstants.INTENT_NAVIGATIONAL;

        return ServingConstants.INTENT_GENERAL;
    }

    private boolean containsAny(String query, Set<String> keywords) {
        for (String kw : keywords) {
            if (query.contains(kw)) {
                return true;
            }
        }
        return false;
    }

    // =========================================================================
    // Keyword extraction
    // =========================================================================

    private List<String> extractKeywords(String query, Pattern cmdRe) {
        // Remove command patterns from query
        String cleaned = cmdRe.matcher(query).replaceAll("");

        // jieba tokenization
        List<String> tokens;
        try {
            tokens = SEGMENTER_TL.get().sentenceProcess(cleaned);
        } catch (Exception e) {
            // Fallback: simple split
            tokens = Arrays.stream(cleaned.split("[\\s,，、？?。.！!]+"))
                    .filter(t -> !t.isBlank())
                    .toList();
        }

        // Filter stopwords and short tokens (keep single CJK chars)
        List<String> keywords = new ArrayList<>();
        for (String t : tokens) {
            if (t.isBlank()) continue;
            if (ALL_STOPWORDS.contains(t)) continue;
            if (t.length() < 2 && !isCjk(t.charAt(0))) continue;
            keywords.add(t);
        }
        return keywords;
    }

    private static boolean isCjk(char ch) {
        int cp = ch;
        return (cp >= 0x4E00 && cp <= 0x9FFF)
                || (cp >= 0x3400 && cp <= 0x4DBF)
                || (cp >= 0x2E80 && cp <= 0x2EFF);
    }

    // =========================================================================
    // Intent normalization
    // =========================================================================

    private static String normalizeIntent(String rawIntent) {
        if (rawIntent == null || rawIntent.isBlank()) {
            return ServingConstants.INTENT_GENERAL;
        }
        return ServingConstants.LLM_INTENT_TO_INTERNAL.getOrDefault(rawIntent, ServingConstants.INTENT_GENERAL);
    }
}
