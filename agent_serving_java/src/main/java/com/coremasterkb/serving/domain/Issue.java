package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.HashMap;
import java.util.Map;

public record Issue(
        @JsonProperty("type") String type,
        @JsonProperty("message") String message,
        @JsonProperty("detail") Map<String, Object> detail
) {
    public Issue(String type, String message) {
        this(type, message, new HashMap<>());
    }

    public Issue {
        if (detail == null) detail = new HashMap<>();
    }
}
