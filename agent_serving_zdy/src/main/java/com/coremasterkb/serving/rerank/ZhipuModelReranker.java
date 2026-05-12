package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.infrastructure.ZhipuClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * Reranker backed by the Zhipu rerank model API.
 *
 * <p>Sends query + candidate documents to Zhipu's dedicated rerank endpoint
 * and returns candidates reordered by relevance score.
 * Returns {@code null} on any failure to signal fallback.
 *
 * @see ZhipuClient#rerank(String, List, int)
 */
public class ZhipuModelReranker implements Reranker {

    private static final Logger log = LoggerFactory.getLogger(ZhipuModelReranker.class);
    private static final int MAX_DOCUMENTS = 20;
    private static final int MAX_DOC_CHARS = 1000;

    private final ZhipuClient zhipuClient;
    private final int topN;

    public ZhipuModelReranker(ZhipuClient zhipuClient) {
        this(zhipuClient, MAX_DOCUMENTS);
    }

    public ZhipuModelReranker(ZhipuClient zhipuClient, int topN) {
        this.zhipuClient = zhipuClient;
        this.topN = topN;
    }

    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding) {
        if (candidates == null || candidates.isEmpty()) {
            return null;
        }
        if (zhipuClient == null || !zhipuClient.isAvailable()) {
            return null;
        }

        String query = resolveQuery(understanding);
        if (query == null || query.isBlank()) {
            return null;
        }

        int workingSize = Math.min(topN, candidates.size());
        List<RetrievalCandidate> workingSet = candidates.subList(0, workingSize);

        List<String> documents = buildDocuments(workingSet);

        List<Map<String, Object>> results;
        try {
            results = zhipuClient.rerank(query, documents, workingSize);
        } catch (Exception e) {
            log.warn("Zhipu rerank API call failed: {}", e.getMessage());
            return null;
        }

        if (results == null || results.isEmpty()) {
            return null;
        }

        return reorderCandidates(workingSet, results, candidates, workingSize);
    }

    private String resolveQuery(QueryUnderstanding understanding) {
        if (understanding != null && understanding.originalQuery() != null
                && !understanding.originalQuery().isBlank()) {
            return understanding.originalQuery();
        }
        return null;
    }

    private List<String> buildDocuments(List<RetrievalCandidate> workingSet) {
        List<String> documents = new ArrayList<>();
        for (RetrievalCandidate c : workingSet) {
            String text = stringFromMetadata(c, "text");
            String title = stringFromMetadata(c, "title");
            String doc = (title != null && !title.isEmpty())
                    ? title + ": " + text
                    : text;
            documents.add(truncate(doc, MAX_DOC_CHARS));
        }
        return documents;
    }

    private List<RetrievalCandidate> reorderCandidates(
            List<RetrievalCandidate> workingSet,
            List<Map<String, Object>> results,
            List<RetrievalCandidate> allCandidates,
            int workingSize) {

        Set<Integer> seenIndices = new HashSet<>();
        List<RetrievalCandidate> reordered = new ArrayList<>();

        for (Map<String, Object> item : results) {
            Object idxObj = item.get("index");
            Object scoreObj = item.get("score");
            if (!(idxObj instanceof Number) || !(scoreObj instanceof Number)) continue;

            int idx = ((Number) idxObj).intValue();
            if (idx < 0 || idx >= workingSet.size() || seenIndices.contains(idx)) continue;

            seenIndices.add(idx);
            double score = ((Number) scoreObj).doubleValue();
            reordered.add(workingSet.get(idx).withScore(score));
        }

        // Append working-set candidates not returned by the API
        for (int i = 0; i < workingSet.size(); i++) {
            if (!seenIndices.contains(i)) {
                reordered.add(workingSet.get(i));
            }
        }

        // Append remaining candidates beyond working set
        if (workingSize < allCandidates.size()) {
            reordered.addAll(allCandidates.subList(workingSize, allCandidates.size()));
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
