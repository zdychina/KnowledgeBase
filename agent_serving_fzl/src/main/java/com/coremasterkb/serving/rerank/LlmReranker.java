package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.infrastructure.LlmClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * Listwise LLM reranker.
 *
 * <p>Sends query + top-N candidate previews to the LLM, which returns a ranking
 * with updated scores. Returns {@code null} on any failure to signal fallback.
 *
 * @see LlmClient#execute(String, String, Map)
 */
public class LlmReranker implements Reranker {

    private static final Logger log = LoggerFactory.getLogger(LlmReranker.class);
    private static final int MAX_CANDIDATES = 20;
    private static final int TEXT_PREVIEW_CHARS = 200;

    private final LlmClient llmClient;

    public LlmReranker(LlmClient llmClient) {
        this.llmClient = llmClient;
    }

    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding) {
        if (candidates == null || candidates.isEmpty()) {
            return null;
        }
        if (llmClient == null || !llmClient.isAvailable()) {
            return null;
        }

        try {
            return doRerank(candidates, understanding);
        } catch (Exception e) {
            log.warn("LLM rerank failed: {}", e.getMessage());
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private List<RetrievalCandidate> doRerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding) {
        int topN = Math.min(MAX_CANDIDATES, candidates.size());
        List<RetrievalCandidate> workingSet = candidates.subList(0, topN);

        String itemsText = buildItemsText(workingSet);
        String query = understanding != null ? understanding.originalQuery() : "";

        Map<String, Object> input = new HashMap<>();
        input.put("query", query != null ? query : "");
        input.put("candidates", itemsText);
        input.put("count", topN);

        Map<String, Object> result = llmClient.execute("reranker", "serving-reranker", input);
        if (result == null || result.isEmpty()) {
            throw new IllegalStateException("Empty LLM rerank response");
        }

        // Unwrap envelope: result.result.parsed_output.ranking  or  result.parsed_output.ranking
        Map<String, Object> inner = result;
        Object resultObj = result.get("result");
        if (resultObj instanceof Map<?, ?> m) {
            inner = (Map<String, Object>) m;
        }

        Object parsedObj = inner.get("parsed_output");
        if (!(parsedObj instanceof Map<?, ?> parsed)) {
            throw new IllegalStateException("No parsed_output in LLM rerank response");
        }

        Object rankingObj = parsed.get("ranking");
        if (!(rankingObj instanceof List<?> rankingList) || rankingList.isEmpty()) {
            throw new IllegalStateException("No ranking in LLM rerank response");
        }

        return applyRanking(workingSet, rankingList, candidates, topN);
    }

    @SuppressWarnings("unchecked")
    private List<RetrievalCandidate> applyRanking(
            List<RetrievalCandidate> workingSet,
            List<?> rankingList,
            List<RetrievalCandidate> allCandidates,
            int topN) {

        Map<Integer, RetrievalCandidate> indexed = new HashMap<>();
        for (int i = 0; i < workingSet.size(); i++) {
            indexed.put(i, workingSet.get(i));
        }

        Set<Integer> used = new HashSet<>();
        List<RetrievalCandidate> reordered = new ArrayList<>();

        for (Object item : rankingList) {
            if (!(item instanceof Map<?, ?> m)) continue;
            Map<String, Object> entry = (Map<String, Object>) m;

            Object idxObj = entry.get("index");
            if (!(idxObj instanceof Number)) continue;
            int idx = ((Number) idxObj).intValue();
            if (!indexed.containsKey(idx) || used.contains(idx)) continue;

            used.add(idx);
            RetrievalCandidate c = indexed.get(idx);

            double newScore = c.score();
            Object scoreObj = entry.get("score");
            if (scoreObj instanceof Number n) {
                newScore = n.doubleValue();
            }
            reordered.add(c.withScore(newScore));
        }

        // Append unranked working-set candidates
        for (int i = 0; i < workingSet.size(); i++) {
            if (!used.contains(i)) {
                reordered.add(workingSet.get(i));
            }
        }

        // Append remaining candidates beyond topN
        if (topN < allCandidates.size()) {
            reordered.addAll(allCandidates.subList(topN, allCandidates.size()));
        }

        return reordered;
    }

    private String buildItemsText(List<RetrievalCandidate> candidates) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < candidates.size(); i++) {
            RetrievalCandidate c = candidates.get(i);
            String textPreview = truncate(stringFromMetadata(c, "text"), TEXT_PREVIEW_CHARS);
            String title = stringFromMetadata(c, "title");
            sb.append(String.format("[%d] (score=%.3f) %s: %s%n", i, c.score(), title, textPreview));
        }
        return sb.toString();
    }

    private static String stringFromMetadata(RetrievalCandidate c, String key) {
        Object val = c.metadata().get(key);
        return val instanceof String s ? s : "";
    }

    private static String truncate(String s, int maxLen) {
        if (s == null) return "";
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }
}
