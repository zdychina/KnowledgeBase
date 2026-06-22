package com.coremasterkb.serving.mapper.result;

public class CacheHitRow {
    private String id;
    private String queryText;
    private String contextPackJson;
    private double similarity;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getQueryText() { return queryText; }
    public void setQueryText(String queryText) { this.queryText = queryText; }

    public String getContextPackJson() { return contextPackJson; }
    public void setContextPackJson(String contextPackJson) { this.contextPackJson = contextPackJson; }

    public double getSimilarity() { return similarity; }
    public void setSimilarity(double similarity) { this.similarity = similarity; }
}
