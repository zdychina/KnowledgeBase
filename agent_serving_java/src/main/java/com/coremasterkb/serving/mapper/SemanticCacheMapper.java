package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.mapper.result.CacheHitRow;
import org.apache.ibatis.annotations.Param;

public interface SemanticCacheMapper {

    CacheHitRow findNearest(
            @Param("domain") String domain,
            @Param("releaseId") String releaseId,
            @Param("queryVector") String queryVector);

    void insert(
            @Param("id") String id,
            @Param("domain") String domain,
            @Param("releaseId") String releaseId,
            @Param("queryText") String queryText,
            @Param("queryVector") String queryVector,
            @Param("contextPackJson") String contextPackJson);

    void incrementHit(@Param("id") String id);

    void evictByDomain(@Param("domain") String domain);
}
