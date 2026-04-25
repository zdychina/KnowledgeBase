package com.coremasterkb.serving.mapper.result;

import lombok.Data;

@Data
public class DocumentSourceRow {
    private String id;
    private String documentKey;
    private String relativePath;
    private String title;
    private String scopeJson;
}
