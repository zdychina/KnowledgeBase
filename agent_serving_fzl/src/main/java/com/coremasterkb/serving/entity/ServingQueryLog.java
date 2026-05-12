package com.coremasterkb.serving.entity;

public class ServingQueryLog {

    private String id;

    // Original input
    private String queryText;
    private String channel;

    // Query parsing results
    private String intent;
    private String normalizerSource;
    private String keywordsJson;
    private String entitiesJson;
    private String scopeJson;

    // Matched knowledge base version
    private String releaseId;
    private String buildId;
    private Integer snapshotCount;

    // Response summary
    private Integer resultItemCount;
    private Integer resultSeedCount;
    private Boolean resultHasResult;
    private String resultIssuesJson;

    // Response details
    private String resultItemsJson;
    private String resultSourcesJson;
    private String resultRelationsJson;

    // Performance
    private Integer durationMs;

    // Metadata
    private String queriedAt;
    private String metadataJson;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getQueryText() { return queryText; }
    public void setQueryText(String queryText) { this.queryText = queryText; }

    public String getChannel() { return channel; }
    public void setChannel(String channel) { this.channel = channel; }

    public String getIntent() { return intent; }
    public void setIntent(String intent) { this.intent = intent; }

    public String getNormalizerSource() { return normalizerSource; }
    public void setNormalizerSource(String normalizerSource) { this.normalizerSource = normalizerSource; }

    public String getKeywordsJson() { return keywordsJson; }
    public void setKeywordsJson(String keywordsJson) { this.keywordsJson = keywordsJson; }

    public String getEntitiesJson() { return entitiesJson; }
    public void setEntitiesJson(String entitiesJson) { this.entitiesJson = entitiesJson; }

    public String getScopeJson() { return scopeJson; }
    public void setScopeJson(String scopeJson) { this.scopeJson = scopeJson; }

    public String getReleaseId() { return releaseId; }
    public void setReleaseId(String releaseId) { this.releaseId = releaseId; }

    public String getBuildId() { return buildId; }
    public void setBuildId(String buildId) { this.buildId = buildId; }

    public Integer getSnapshotCount() { return snapshotCount; }
    public void setSnapshotCount(Integer snapshotCount) { this.snapshotCount = snapshotCount; }

    public Integer getResultItemCount() { return resultItemCount; }
    public void setResultItemCount(Integer resultItemCount) { this.resultItemCount = resultItemCount; }

    public Integer getResultSeedCount() { return resultSeedCount; }
    public void setResultSeedCount(Integer resultSeedCount) { this.resultSeedCount = resultSeedCount; }

    public Boolean getResultHasResult() { return resultHasResult; }
    public void setResultHasResult(Boolean resultHasResult) { this.resultHasResult = resultHasResult; }

    public String getResultIssuesJson() { return resultIssuesJson; }
    public void setResultIssuesJson(String resultIssuesJson) { this.resultIssuesJson = resultIssuesJson; }

    public String getResultItemsJson() { return resultItemsJson; }
    public void setResultItemsJson(String resultItemsJson) { this.resultItemsJson = resultItemsJson; }

    public String getResultSourcesJson() { return resultSourcesJson; }
    public void setResultSourcesJson(String resultSourcesJson) { this.resultSourcesJson = resultSourcesJson; }

    public String getResultRelationsJson() { return resultRelationsJson; }
    public void setResultRelationsJson(String resultRelationsJson) { this.resultRelationsJson = resultRelationsJson; }

    public Integer getDurationMs() { return durationMs; }
    public void setDurationMs(Integer durationMs) { this.durationMs = durationMs; }

    public String getQueriedAt() { return queriedAt; }
    public void setQueriedAt(String queriedAt) { this.queriedAt = queriedAt; }

    public String getMetadataJson() { return metadataJson; }
    public void setMetadataJson(String metadataJson) { this.metadataJson = metadataJson; }
}
