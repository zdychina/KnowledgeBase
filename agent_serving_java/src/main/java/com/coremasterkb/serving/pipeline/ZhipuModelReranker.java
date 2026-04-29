package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.client.LlmRuntimeClient;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Reranker that calls the Zhipu rerank model via LLM service (POST /api/v1/rerank).
 *
 * Returns null when the service is unavailable or the call fails,
 * signalling SearchService to fall back to ScoreReranker.
 *
 * Expected response format:
 *   {"results": [{"index": 0, "score": 0.95}, {"index": 2, "score": 0.87}, ...]}
 */
public class ZhipuModelReranker implements Reranker {

    private static final Logger log = LoggerFactory.getLogger(ZhipuModelReranker.class);

    private final LlmRuntimeClient llmClient;

    public ZhipuModelReranker(LlmRuntimeClient llmClient) {
        this.llmClient = llmClient;
    }

    /**
     * @return reranked list, or {@code null} if service unavailable/failed (caller should fall back)
     */
    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryPlan plan) {
        if (!llmClient.isAvailable()) return null;
        if (candidates == null || candidates.isEmpty()) return Collections.emptyList();

        String query = String.join(" ", plan.keywords());

        List<String> documents = candidates.stream()
                .map(c -> {
                    Object text = c.metadata().get("text");
                    return text instanceof String s ? s : "";
                })
                .collect(Collectors.toList());

        int topN = plan.budget().maxItems();
        List<Map<String, Object>> results = llmClient.rerank(query, documents, topN);
        if (results == null || results.isEmpty()) return null;

        List<RetrievalCandidate> reranked = new ArrayList<>();
        for (Map<String, Object> item : results) {
            Object idxObj   = item.get("index");
            Object scoreObj = item.get("score");
            if (!(idxObj instanceof Number) || !(scoreObj instanceof Number)) continue;
            int idx = ((Number) idxObj).intValue();
            if (idx < 0 || idx >= candidates.size()) continue;
            reranked.add(candidates.get(idx).withScore(((Number) scoreObj).doubleValue()));
        }

        return reranked.isEmpty() ? null : reranked;
    }
}
