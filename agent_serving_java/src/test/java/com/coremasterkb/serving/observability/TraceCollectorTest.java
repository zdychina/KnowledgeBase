package com.coremasterkb.serving.observability;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("TraceCollector")
class TraceCollectorTest {

    private TraceCollector collector;

    @BeforeEach
    void setUp() {
        collector = new TraceCollector();
    }

    @Nested
    @DisplayName("startStage / endStage")
    class StageLifecycle {
        @Test
        @DisplayName("single stage recorded correctly")
        void singleStageRecorded() {
            collector.startStage("query_understanding");
            collector.endStage("query_understanding", "intent=general");
            var trace = collector.buildTrace("req-1");
            assertThat(trace.stages()).hasSize(1);
            assertThat(trace.stages().get(0).name()).isEqualTo("query_understanding");
            assertThat(trace.stages().get(0).outputSummary()).isEqualTo("intent=general");
            assertThat(trace.stages().get(0).durationMs()).isGreaterThanOrEqualTo(0);
        }

        @Test
        @DisplayName("multiple stages recorded in order")
        void multipleStagesInOrder() {
            collector.startStage("stage_a");
            collector.endStage("stage_a", "done_a");
            collector.startStage("stage_b");
            collector.endStage("stage_b", "done_b");

            var trace = collector.buildTrace("req-2");
            assertThat(trace.stages()).hasSize(2);
            assertThat(trace.stages().get(0).name()).isEqualTo("stage_a");
            assertThat(trace.stages().get(1).name()).isEqualTo("stage_b");
        }

        @Test
        @DisplayName("endStage without startStage records duration 0")
        void endWithoutStartRecordsZero() {
            collector.endStage("unknown_stage", "output");
            var trace = collector.buildTrace("req-3");
            assertThat(trace.stages()).hasSize(1);
            assertThat(trace.stages().get(0).durationMs()).isEqualTo(0.0);
        }

        @Test
        @DisplayName("endStage with error records error")
        void endStageWithError() {
            collector.startStage("failing_stage");
            collector.endStage("failing_stage", "partial", "timeout");
            var trace = collector.buildTrace("req-4");
            assertThat(trace.stages()).hasSize(1);
            assertThat(trace.stages().get(0).error()).isEqualTo("timeout");
        }
    }

    @Nested
    @DisplayName("buildTrace")
    class BuildTrace {
        @Test
        @DisplayName("empty trace has non-negative total duration (wall-clock from construction)")
        void emptyTraceZeroDuration() {
            var trace = collector.buildTrace("req-0");
            assertThat(trace.stages()).isEmpty();
            assertThat(trace.totalDurationMs()).isGreaterThanOrEqualTo(0.0);
        }

        @Test
        @DisplayName("totalDuration is wall-clock and >= sum of stage durations")
        void totalDurationIsSum() {
            collector.startStage("a");
            collector.endStage("a", "done");
            collector.startStage("b");
            collector.endStage("b", "done");

            var trace = collector.buildTrace("req-5");
            double stageSum = trace.stages().stream()
                    .mapToDouble(s -> s.durationMs()).sum();
            assertThat(trace.totalDurationMs()).isGreaterThanOrEqualTo(stageSum);
        }

        @Test
        @DisplayName("buildTrace without requestId uses empty string")
        void buildTraceNoRequestId() {
            var trace = collector.buildTrace();
            assertThat(trace.requestId()).isEmpty();
        }
    }
}
