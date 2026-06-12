package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.infrastructure.LlmClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;

import java.util.*;

/**
 * Reranker backed by the shared LLM service rerank endpoint.
 *
 * <p>Calls the LLM service's dedicated rerank API.
 * Model is managed by llm_service — callers only provide query, documents, and top_n.
 * Returns {@code null} on any failure to signal fallback.
 */
public class ServiceReranker implements Reranker {

    private static final Logger log = LoggerFactory.getLogger(ServiceReranker.class);
    private static final int MAX_RERANK_DOCS = 200;
    private static final int MAX_DOC_CHARS = 1000;
    private static final int DEFAULT_TOP_N = 100;

    private final LlmClient llmClient;
    private final int topN;

    public ServiceReranker(LlmClient llmClient) {
        this(llmClient, DEFAULT_TOP_N);
    }

    public ServiceReranker(LlmClient llmClient, int topN) {
        this.llmClient = llmClient;
        this.topN = topN;
    }

    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding) {
        if (candidates == null || candidates.isEmpty()) {
            return null;
        }
        if (llmClient == null || !llmClient.isAvailable()) {
            return null;
        }

        String query = resolveQuery(understanding);
        if (query == null || query.isBlank()) {
            return null;
        }

        int workingSize = Math.min(topN, candidates.size());
        List<RetrievalCandidate> workingSet = candidates.subList(0, workingSize);

        try {
            if (workingSize <= MAX_RERANK_DOCS) {
                return rerankSingle(query, workingSet);
            }
            return rerankBatched(query, workingSet);
        } catch (Exception e) {
            log.warn("Service rerank call failed: {}", e.getMessage());
            return null;
        }
    }

    private String resolveQuery(QueryUnderstanding understanding) {
        if (understanding != null && understanding.originalQuery() != null
                && !understanding.originalQuery().isBlank()) {
            return understanding.originalQuery();
        }
        return null;
    }

    private List<RetrievalCandidate> rerankBatched(String query, List<RetrievalCandidate> candidates) {
        List<Map.Entry<Double, RetrievalCandidate>> scored = new ArrayList<>();

        for (int i = 0; i < candidates.size(); i += MAX_RERANK_DOCS) {
            int end = Math.min(i + MAX_RERANK_DOCS, candidates.size());
            List<RetrievalCandidate> batch = candidates.subList(i, end);
            List<RetrievalCandidate> batchResult = rerankSingle(query, batch);
            if (batchResult == null) {
                return null;
            }
            for (RetrievalCandidate c : batchResult) {
                scored.add(Map.entry(c.score(), c));
            }
        }

        scored.sort(Map.Entry.<Double, RetrievalCandidate>comparingByKey().reversed());
        return scored.stream().map(Map.Entry::getValue).toList();
    }

    @SuppressWarnings("unchecked")
    private List<RetrievalCandidate> rerankSingle(String query, List<RetrievalCandidate> candidates) {
        List<String> documents = new ArrayList<>();
        for (RetrievalCandidate c : candidates) {
            String text = stringFromMetadata(c, "text");
            String title = stringFromMetadata(c, "title");
            String doc = (title != null && !title.isEmpty())
                    ? title + ": " + text
                    : text;
            documents.add(truncate(doc, MAX_DOC_CHARS));
        }

        // Use LlmClient execute with rerank-specific payload
        Map<String, Object> input = new HashMap<>();
        input.put("query", query);
        input.put("documents", documents);
        input.put("top_n", documents.size());

        Map<String, Object> response = llmClient.execute("reranker", "service-rerank", input);
        if (response == null) {
            return null;
        }

        Object resultsObj = response.get("results");
        if (!(resultsObj instanceof List<?> rawList)) {
            return null;
        }

        Set<Integer> seenIndices = new HashSet<>();
        List<RetrievalCandidate> reordered = new ArrayList<>();

        for (Object item : rawList) {
            if (!(item instanceof Map<?, ?> m)) continue;
            Map<String, Object> r = (Map<String, Object>) m;

            Object idxObj = r.get("index");
            Object scoreObj = r.get("relevance_score");
            if (!(idxObj instanceof Number) || !(scoreObj instanceof Number)) continue;

            int idx = ((Number) idxObj).intValue();
            if (idx < 0 || idx >= candidates.size() || seenIndices.contains(idx)) continue;

            seenIndices.add(idx);
            double score = ((Number) scoreObj).doubleValue();
            reordered.add(candidates.get(idx).withScore(score));
        }

        return reordered.isEmpty() ? null : reordered;
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
