package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record EntityRef(
        @JsonProperty("type") String type,
        @JsonProperty("name") String name,
        @JsonProperty("normalized_name") String normalizedName
) {
    /** Default constructor mirrors Python defaults: type="", normalizedName="" */
    public EntityRef(String name) {
        this("", name, "");
    }

    public EntityRef {
        if (type == null) type = "";
        if (name == null) name = "";
        if (normalizedName == null) normalizedName = "";
    }
}