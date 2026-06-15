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
 *   <li>Segment dedup: same {@code source_segment_id} → keep highest-scored candidate</li>
 *   <li>Low-value type downweight: heading / toc / link × {@value #LOW_VALUE_SCORE_FACTOR}</li>
 *   <li>Text similarity dedup: {@code text} Jaccard &gt; {@value #TEXT_SIMILARITY_THRESHOLD} → keep highest-scored</li>
 *   <li>Annotate each candidate's {@link ScoreChain} with {@code rerankScore}</li>
 *   <li>Threshold filter: remove candidates with score &lt; {@value #MIN_RERANK_SCORE}</li>
 *   <li>Truncate to {@code routePlan.assembly().maxItems()}</li>
 * </ol>
 */
public class RerankPipeline {

    private static final Logger log = LoggerFactory.getLogger(RerankPipeline.class);
    private static final double MIN_RERANK_SCORE = 0.01;
    private static final int DEFAULT_MAX_ITEMS = 10;

    private static final Set<String> LOW_VALUE_UNIT_TYPES = Set.of("heading", "toc", "link");
    private static final double LOW_VALUE_SCORE_FACTOR = 0.5;
    private static final double TEXT_SIMILARITY_THRESHOLD = 0.9;

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

        // Resolve configured rerank method once before the cascade
        String configuredMethod = resolveRerankMethod(routePlan);

        // 1. Try model-based reranker (Zhipu / Service) — always attempt when available.
        //    The model reranker is the primary quality signal; the configuredMethod only
        //    controls whether the LLM-text fallback (step 2) is attempted when the model fails.
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
            if ("llm".equals(configuredMethod) || "cascade".equals(configuredMethod)) {
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

        // 1. Dedup: keep highest-scoring candidate per source_segment_id
        result = deduplicateBySegment(result);

        // 2. Downweight low-value unit types (heading / toc / link)
        result = downweightLowValueTypes(result);

        // 3. Text-similarity dedup: remove near-duplicate texts (Jaccard > 0.9), keep highest-scored
        result = deduplicateByTextSimilarity(result);

        // 4. Annotate rerank scores into score_chain
        result = annotateRerankScores(result);

        // 5. Minimum score threshold filter
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

        // 6. Truncate to max_items
        int maxItems = resolveMaxItems(routePlan);
        if (result.size() > maxItems) {
            result = result.subList(0, maxItems);
        }

        return new RerankResult(result, traces);
    }

    // =========================================================================
    // Post-processing steps
    // =========================================================================

    private List<RetrievalCandidate> deduplicateBySegment(List<RetrievalCandidate> candidates) {
        Map<String, RetrievalCandidate> bestBySegment = new LinkedHashMap<>();
        List<RetrievalCandidate> noSegment = new ArrayList<>();

        for (RetrievalCandidate c : candidates) {
            Object segId = c.metadata().get("source_segment_id");
            if (segId != null) {
                bestBySegment.merge(segId.toString(), c,
                        (existing, incoming) -> incoming.score() > existing.score() ? incoming : existing);
            } else {
                noSegment.add(c);
            }
        }

        int before = candidates.size();
        List<RetrievalCandidate> merged = new ArrayList<>(bestBySegment.values());
        merged.addAll(noSegment);
        merged.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        if (merged.size() < before) {
            log.debug("Segment dedup: {} -> {}", before, merged.size());
        }
        return merged;
    }

    private List<RetrievalCandidate> downweightLowValueTypes(List<RetrievalCandidate> candidates) {
        return candidates.stream()
                .map(c -> {
                    Object unitType = c.metadata().get("unit_type");
                    if (unitType != null && LOW_VALUE_UNIT_TYPES.contains(unitType.toString())) {
                        return c.withScore(c.score() * LOW_VALUE_SCORE_FACTOR);
                    }
                    return c;
                })
                .sorted(Comparator.comparingDouble(RetrievalCandidate::score).reversed())
                .collect(Collectors.toList());
    }

    /**
     * Remove near-duplicate candidates whose {@code text} metadata has character-bigram Jaccard
     * similarity above {@value #TEXT_SIMILARITY_THRESHOLD}.
     */
    private List<RetrievalCandidate> deduplicateByTextSimilarity(List<RetrievalCandidate> candidates) {
        List<RetrievalCandidate> kept = new ArrayList<>();
        List<Set<String>> keptBigrams = new ArrayList<>();

        for (RetrievalCandidate c : candidates) {
            String text = candidateText(c);
            if (text == null || text.isEmpty()) {
                kept.add(c);
                keptBigrams.add(Set.of());
                continue;
            }
            Set<String> bigrams = charBigrams(text);
            boolean isDuplicate = false;
            for (Set<String> kb : keptBigrams) {
                if (!kb.isEmpty() && jaccardSimilarity(bigrams, kb) > TEXT_SIMILARITY_THRESHOLD) {
                    isDuplicate = true;
                    break;
                }
            }
            if (!isDuplicate) {
                kept.add(c);
                keptBigrams.add(bigrams);
            }
        }

        int before = candidates.size();
        if (kept.size() < before) {
            log.debug("Text similarity dedup: {} -> {}", before, kept.size());
        }
        return kept;
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

    // =========================================================================
    // Text similarity helpers
    // =========================================================================

    private static String candidateText(RetrievalCandidate c) {
        Object text = c.metadata().get("text");
        return text != null ? text.toString().trim() : null;
    }

    private static Set<String> charBigrams(String text) {
        if (text.length() < 2) return Set.of();
        Set<String> bigrams = new HashSet<>();
        for (int i = 0; i < text.length() - 1; i++) {
            bigrams.add(text.substring(i, i + 2));
        }
        return bigrams;
    }

    private static double jaccardSimilarity(Set<String> a, Set<String> b) {
        if (a.isEmpty() && b.isEmpty()) return 1.0;
        if (a.isEmpty() || b.isEmpty()) return 0.0;
        int intersectionSize = 0;
        for (String s : a) {
            if (b.contains(s)) intersectionSize++;
        }
        int unionSize = a.size() + b.size() - intersectionSize;
        return (double) intersectionSize / unionSize;
    }

    // =========================================================================
    // Helpers
    // =========================================================================

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
