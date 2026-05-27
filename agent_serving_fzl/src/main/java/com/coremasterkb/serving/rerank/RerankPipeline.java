package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Cascading rerank pipeline: model reranker &rarr; LLM reranker &rarr; score fallback.
 *
 * <p>Each step records a {@link RerankTraceStep} for observability.
 * After the cascade completes, unified post-processing applies:
 * <ol>
 *   <li>Annotate each candidate's {@link ScoreChain} with {@code rerankScore}</li>
 *   <li>Threshold filter: remove candidates with score &lt; 0.01</li>
 *   <li>Truncate to {@code routePlan.assembly().maxItems()}</li>
 * </ol>
 */
public class RerankPipeline {

    private static final Logger log = LoggerFactory.getLogger(RerankPipeline.class);
    private static final double MIN_RERANK_SCORE = 0.01;
    private static final int DEFAULT_MAX_ITEMS = 10;

    private final Reranker modelReranker;
    private final Reranker llmReranker;
    private final Reranker scoreReranker;

    public RerankPipeline(Reranker modelReranker, Reranker llmReranker, Reranker scoreReranker) {
        this.modelReranker = modelReranker;
        this.llmReranker = llmReranker;
        this.scoreReranker = scoreReranker != null ? scoreReranker : new ScoreReranker();
    }

    /**
     * Result of the rerank pipeline containing both candidates and trace steps.
     */
    public record RerankResult(List<RetrievalCandidate> candidates, List<RerankTraceStep> traces) {
    }

    /**
     * Execute the cascading rerank pipeline.
     *
     * @param candidates   input candidates from retrieval
     * @param routePlan    route plan controlling rerank behavior; may be {@code null}
     * @param understanding query understanding for context; may be {@code null}
     * @return reranked candidates with trace steps
     */
    public RerankResult rerank(
            List<RetrievalCandidate> candidates,
            RetrievalRoutePlan routePlan,
            QueryUnderstanding understanding) {

        if (candidates == null || candidates.isEmpty()) {
            return new RerankResult(List.of(), List.of());
        }

        List<RerankTraceStep> traces = new ArrayList<>();
        int countBefore = candidates.size();
        List<RetrievalCandidate> result = null;

        // 1. Try model-based reranker (Zhipu / Service)
        if (modelReranker != null) {
            long t0 = System.nanoTime();
            RerankTraceStep step = new RerankTraceStep("model", true, false, "", 0, countBefore, 0);
            try {
                result = modelReranker.rerank(candidates, understanding);
                double latencyMs = (System.nanoTime() - t0) / 1_000_000.0;
                if (result != null) {
                    step = new RerankTraceStep("model", true, true, "", latencyMs, countBefore, result.size());
                } else {
                    step = new RerankTraceStep("model", true, false, "model_reranker returned empty", latencyMs, countBefore, 0);
                    result = null;
                }
            } catch (Exception e) {
                double latencyMs = (System.nanoTime() - t0) / 1_000_000.0;
                String reason = truncate(e.getMessage(), 200);
                step = new RerankTraceStep("model", true, false, reason, latencyMs, countBefore, 0);
                log.warn("Model reranker failed: {}", e.getMessage());
                result = null;
            }
            traces.add(step);
        }

        // 2. Try LLM reranker if model failed and route plan allows
        if (result == null && llmReranker != null) {
            String method = resolveRerankMethod(routePlan);
            if ("llm".equals(method) || "cascade".equals(method)) {
                long t0 = System.nanoTime();
                RerankTraceStep step = new RerankTraceStep("llm", true, false, "", 0, countBefore, 0);
                try {
                    result = llmReranker.rerank(candidates, understanding);
                    double latencyMs = (System.nanoTime() - t0) / 1_000_000.0;
                    if (result != null) {
                        step = new RerankTraceStep("llm", true, true, "", latencyMs, countBefore, result.size());
                    } else {
                        step = new RerankTraceStep("llm", true, false, "llm_reranker returned empty", latencyMs, countBefore, 0);
                        result = null;
                    }
                } catch (Exception e) {
                    double latencyMs = (System.nanoTime() - t0) / 1_000_000.0;
                    String reason = truncate(e.getMessage(), 200);
                    step = new RerankTraceStep("llm", true, false, reason, latencyMs, countBefore, 0);
                    log.warn("LLM reranker failed: {}", e.getMessage());
                    result = null;
                }
                traces.add(step);
            }
        }

        // 3. Score-based fallback (always succeeds)
        if (result == null) {
            long t0 = System.nanoTime();
            result = scoreReranker.rerank(candidates, understanding);
            double latencyMs = (System.nanoTime() - t0) / 1_000_000.0;
            traces.add(new RerankTraceStep("score", true, true, "", latencyMs, countBefore, result.size()));
        }

        // === Unified post-processing ===

        // 1. Annotate rerank scores into score_chain
        result = annotateRerankScores(result);

        // 2. Minimum score threshold filter
        int beforeFilter = result.size();
        result = result.stream()
                .filter(c -> c.score() >= MIN_RERANK_SCORE)
                .collect(Collectors.toList());
        if (result.size() < beforeFilter) {
            double minScore = result.stream().mapToDouble(RetrievalCandidate::score).min().orElse(0);
            double maxScore = result.stream().mapToDouble(RetrievalCandidate::score).max().orElse(0);
            log.info("Rerank score filter: {} -> {} (threshold={}, min_score={}, max_score={})",
                    beforeFilter, result.size(), MIN_RERANK_SCORE,
                    String.format("%.4f", minScore), String.format("%.4f", maxScore));
        }

        // 3. Truncate to max_items
        int maxItems = resolveMaxItems(routePlan);
        if (result.size() > maxItems) {
            result = result.subList(0, maxItems);
        }

        return new RerankResult(result, traces);
    }

    private List<RetrievalCandidate> annotateRerankScores(List<RetrievalCandidate> candidates) {
        List<RetrievalCandidate> annotated = new ArrayList<>();
        for (RetrievalCandidate c : candidates) {
            ScoreChain chain = c.scoreChain();
            if (chain == null) {
                chain = new ScoreChain(c.score(), 0.0, c.score(),
                        c.source() != null ? List.of(c.source()) : List.of());
            } else {
                chain = new ScoreChain(chain.rawScore(), chain.fusionScore(), c.score(), chain.routeSources());
            }
            annotated.add(c.withScoreChain(chain));
        }
        return annotated;
    }

    private String resolveRerankMethod(RetrievalRoutePlan routePlan) {
        if (routePlan != null && routePlan.rerank() != null && routePlan.rerank().method() != null) {
            return routePlan.rerank().method();
        }
        return "score";
    }

    private int resolveMaxItems(RetrievalRoutePlan routePlan) {
        if (routePlan != null && routePlan.assembly() != null) {
            return routePlan.assembly().maxItems();
        }
        return DEFAULT_MAX_ITEMS;
    }

    private static String truncate(String s, int maxLen) {
        if (s == null) return "";
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }
}
