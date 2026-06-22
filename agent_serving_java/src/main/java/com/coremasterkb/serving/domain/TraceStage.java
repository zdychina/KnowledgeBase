package com.coremasterkb.serving.domain;

/**
 * A single stage within a pipeline trace.
 *
 * @param name           stage name
 * @param inputSummary   brief summary of stage input
 * @param outputSummary  brief summary of stage output
 * @param durationMs     stage duration in milliseconds
 * @param error          error message if the stage failed (null if successful)
 */
public record TraceStage(
        String name,
        String inputSummary,
        String outputSummary,
        double durationMs,
        String error
) {
}
