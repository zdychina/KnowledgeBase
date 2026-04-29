package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.client.ZhipuClient;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Reranker that calls the Zhipu rerank model API directly
 * (POST https://open.bigmodel.cn/api/paas/v4/rerank).
 *
 * Returns null when the API key is not configured or the call fails,
 * signalling SearchService to fall back to ScoreReranker.
 */
public class ZhipuModelReranker implements Reranker {

    private static final Logger log = LoggerFactory.getLogger(ZhipuModelReranker.class);

    private final ZhipuClient zhipuClient;

    public ZhipuModelReranker(ZhipuClient zhipuClient) {
        this.zhipuClient = zhipuClient;
    }

    /**
     * @return reranked list, or {@code null} if API not configured / call failed (caller falls back)
     */
    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryPlan plan) {
        if (!zhipuClient.isConfigured()) return null;
        if (candidates == null || candidates.isEmpty()) return Collections.emptyList();

        String query = String.join(" ", plan.keywords());

        List<String> documents = candidates.stream()
                .map(c -> {
                    Object text = c.metadata().get("text");
                    return text instanceof String s ? s : "";
                })
                .collect(Collectors.toList());

        int topN = plan.budget().maxItems();
        List<Map<String, Object>> results = zhipuClient.rerank(query, documents, topN);
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
