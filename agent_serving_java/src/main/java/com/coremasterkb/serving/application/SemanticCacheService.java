package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.ContextPack;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.mapper.SemanticCacheMapper;
import com.coremasterkb.serving.mapper.result.CacheHitRow;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * Semantic query cache backed by pgvector cosine similarity.
 *
 * <p>Best-effort — any exception is logged and silently swallowed
 * so the caller's pipeline is never interrupted.</p>
 */
@Service
public class SemanticCacheService {

    private static final Logger log = LoggerFactory.getLogger(SemanticCacheService.class);
    private static final double HIT_THRESHOLD = 0.92;

    private final SemanticCacheMapper cacheMapper;
    private final EmbeddingClient embeddingClient;
    private final ObjectMapper objectMapper;

    public SemanticCacheService(SemanticCacheMapper cacheMapper,
                                EmbeddingClient embeddingClient,
                                ObjectMapper objectMapper) {
        this.cacheMapper = cacheMapper;
        this.embeddingClient = embeddingClient;
        this.objectMapper = objectMapper;
    }

    public ContextPack lookup(String domain, String releaseId, float[] queryVector) {
        if (queryVector == null) {
            return null;
        }
        try {
            String vectorStr = formatVector(queryVector);
            CacheHitRow row = cacheMapper.findNearest(domain, releaseId, vectorStr);
            if (row == null || row.getSimilarity() < HIT_THRESHOLD) {
                return null;
            }
            log.info("Semantic cache HIT: domain={}, similarity={}", domain, String.format("%.4f", row.getSimilarity()));
            cacheMapper.incrementHit(row.getId());
            return objectMapper.readValue(row.getContextPackJson(), ContextPack.class);
        } catch (Exception e) {
            log.warn("Semantic cache lookup failed (non-fatal): {}", e.getMessage());
            return null;
        }
    }

    public void store(String domain, String releaseId, String query, float[] queryVector, ContextPack pack) {
        if (queryVector == null) {
            return;
        }
        try {
            String vectorStr = formatVector(queryVector);
            String packJson = objectMapper.writeValueAsString(pack);
            cacheMapper.insert(UUID.randomUUID().toString(), domain, releaseId, query, vectorStr, packJson);
        } catch (Exception e) {
            log.warn("Semantic cache store failed (non-fatal): {}", e.getMessage());
        }
    }

    public void evict(String domain) {
        try {
            cacheMapper.evictByDomain(domain);
            log.info("Semantic cache evicted for domain={}", domain);
        } catch (Exception e) {
            log.warn("Semantic cache eviction failed: {}", e.getMessage());
        }
    }

    private static String formatVector(float[] vec) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(vec[i]);
        }
        sb.append("]");
        return sb.toString();
    }
}
