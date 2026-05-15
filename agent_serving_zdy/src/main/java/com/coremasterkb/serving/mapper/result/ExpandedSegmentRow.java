package com.coremasterkb.serving.mapper.result;

/** Expanded segment with its BFS distance and the root seed that triggered the expansion. */
public record ExpandedSegmentRow(SegmentWithMetaRow segment, int expansionDistance, String sourceSegmentId) {}
