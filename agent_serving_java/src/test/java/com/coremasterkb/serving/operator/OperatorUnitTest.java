package com.coremasterkb.serving.operator;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.operator.core.ExecContext;
import com.coremasterkb.serving.operator.core.Params;
import com.coremasterkb.serving.operator.core.SlotValues;
import com.coremasterkb.serving.operator.operators.fuse.IdentityOperator;
import com.coremasterkb.serving.operator.operators.fuse.RrfOperator;
import com.coremasterkb.serving.operator.operators.fuse.WeightedRrfOperator;
import com.coremasterkb.serving.operator.operators.output.CollectOperator;
import com.coremasterkb.serving.operator.operators.rerank.ScoreRerankOperator;
import com.coremasterkb.serving.operator.operators.retrieve.DenseVectorOperator;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Per-operator unit tests (PRD §14.1) for the dependency-free / guard paths: parameter boundaries
 * (maxItems, threshold, k, weights) and empty-input handling. No DB or LLM involved.
 */
class OperatorUnitTest {

    private static final ObjectMapper M = new ObjectMapper();

    private static Params params(String json) {
        try { return new Params(M.readTree(json)); } catch (Exception e) { throw new RuntimeException(e); }
    }
    private static ExecContext ctx() { return new ExecContext("r", "d", "prod", false); }
    private static RetrievalCandidate c(String uid, double score, String source) {
        return new RetrievalCandidate(uid, score, source, Map.of(),
                new ScoreChain(score, 0.0, 0.0, List.of(source)));
    }
    private static SlotValues in(String slot, Object val) { return SlotValues.of(slot, val); }

    @Test
    void collectTruncatesToMaxItems() {
        var out = new CollectOperator().execute(
                in("candidates", List.of(c("a", 1, "s"), c("b", 2, "s"), c("c", 3, "s"))),
                params("{\"maxItems\":2}"), ctx());
        assertEquals(2, out.getCandidates("candidates").size());
    }

    @Test
    void collectKeepsAllWhenUnderLimit() {
        var out = new CollectOperator().execute(
                in("candidates", List.of(c("a", 1, "s"))), params("{\"maxItems\":50}"), ctx());
        assertEquals(1, out.getCandidates("candidates").size());
    }

    @Test
    void scoreRerankSortsDescAndFiltersThreshold() {
        var out = new ScoreRerankOperator().execute(
                in("candidates", List.of(c("a", 0.2, "s"), c("b", 0.9, "s"), c("c", 0.05, "s"))),
                params("{\"threshold\":0.1}"), ctx());
        var r = out.getCandidates("candidates");
        assertEquals(2, r.size());              // c (0.05) filtered out
        assertEquals("b", r.get(0).retrievalUnitId()); // highest first
        assertEquals("a", r.get(1).retrievalUnitId());
    }

    @Test
    void identityPassesThrough() {
        var input = List.of(c("a", 1, "s"), c("b", 2, "s"));
        var out = new IdentityOperator().execute(in("candidates", input), params("{}"), ctx());
        assertEquals(2, out.getCandidates("candidates").size());
    }

    @Test
    void rrfRanksSharedUnitFirst() {
        // u2 appears in both source groups → highest fused score
        var merged = List.of(
                c("u1", 0.9, "x"), c("u2", 0.8, "x"),
                c("u2", 0.95, "y"), c("u3", 0.7, "y"));
        var out = new RrfOperator().execute(in("candidates", merged), params("{\"k\":60}"), ctx());
        var r = out.getCandidates("candidates");
        assertEquals(3, r.size());
        assertEquals("u2", r.get(0).retrievalUnitId());
    }

    @Test
    void weightedRrfHonorsSourceWeights() {
        // single member per source; weight on 'y' lifts u2 above u1
        var merged = List.of(c("u1", 0.9, "x"), c("u2", 0.5, "y"));
        var out = new WeightedRrfOperator().execute(
                in("candidates", merged), params("{\"k\":60,\"weights\":{\"y\":5.0,\"x\":1.0}}"), ctx());
        assertEquals("u2", out.getCandidates("candidates").get(0).retrievalUnitId());
    }

    @Test
    void denseVectorReturnsEmptyWithoutEmbedding() {
        // null mapper is never touched: missing queryEmbedding short-circuits to empty
        var out = new DenseVectorOperator(null).execute(new SlotValues(), params("{}"), ctx());
        assertTrue(out.getCandidates("candidates").isEmpty());
    }
}
