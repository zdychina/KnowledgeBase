package com.coremasterkb.serving.mapper.result;

/** Expanded segment with its BFS distance, root seed, and the relation type that led to it. */
public record ExpandedSegmentRow(SegmentWithMetaRow segment, int expansionDistance, String sourceSegmentId, String relationType) {}
