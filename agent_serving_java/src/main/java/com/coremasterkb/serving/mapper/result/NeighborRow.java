package com.coremasterkb.serving.mapper.result;

import lombok.Data;

@Data
public class NeighborRow {
    private String fromId;
    private String neighborId;
    private String relationType;
}
