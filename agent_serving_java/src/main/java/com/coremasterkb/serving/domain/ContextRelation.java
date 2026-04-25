package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContextRelation(
        @JsonProperty("id") String id,
        @JsonProperty("from_id") String fromId,
        @JsonProperty("to_id") String toId,
        @JsonProperty("relation_type") String relationType,
        @JsonProperty("distance") Integer distance
) {
}
