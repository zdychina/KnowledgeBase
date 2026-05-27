package com.coremasterkb.serving.observability;

import com.coremasterkb.serving.domain.Trace;
import com.coremasterkb.serving.domain.TraceStage;

import java.util.*;

/**
 * Non-invasive per-request trace collector.
 *
 * <p>Usage:</p>
 * <pre>
 * TraceCollector collector = new TraceCollector();
 * collector.startStage("query_understanding");
 * // ... do work ...
 * collector.endStage("query_understanding", "intent=command_usage, 2 entities");
 * Trace trace = collector.buildTrace("req-123");
 * </pre>
 */
public class TraceCollector {

    private final List<TraceStage> stages = new ArrayList<>();
    private final Map<String, Long> stageStartTimes = new HashMap<>();

    public void startStage(String name) {
        stageStartTimes.put(name, System.nanoTime());
    }

    public void endStage(String name) {
        endStage(name, "");
    }

    public void endStage(String name, String outputSummary) {
        Long startTime = stageStartTimes.remove(name);
        double durationMs = startTime != null
                ? (System.nanoTime() - startTime) / 1_000_000.0
                : 0.0;
        stages.add(new TraceStage(name, "", outputSummary, durationMs, ""));
    }

    public void endStage(String name, String outputSummary, String error) {
        Long startTime = stageStartTimes.remove(name);
        double durationMs = startTime != null
                ? (System.nanoTime() - startTime) / 1_000_000.0
                : 0.0;
        stages.add(new TraceStage(name, "", outputSummary, durationMs, error));
    }

    public Trace buildTrace() {
        return buildTrace("");
    }

    public Trace buildTrace(String requestId) {
        double totalDuration = stages.stream()
                .mapToDouble(TraceStage::durationMs)
                .sum();
        return new Trace(requestId, List.copyOf(stages), totalDuration);
    }
}
