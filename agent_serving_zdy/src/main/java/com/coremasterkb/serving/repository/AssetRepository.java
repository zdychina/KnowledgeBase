package com.coremasterkb.serving.repository;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.entity.AssetBuildDocumentSnapshot;
import com.coremasterkb.serving.entity.AssetPublishRelease;
import com.coremasterkb.serving.mapper.*;
import com.coremasterkb.serving.mapper.result.*;
import org.springframework.stereotype.Repository;

import java.util.*;

/**
 * Asset database access layer.
 * Uses plain MyBatis mapper interfaces for all database queries.
 */
@Repository
public class AssetRepository {

    private final AssetPublishReleaseMapper releaseMapper;
    private final AssetBuildDocumentSnapshotMapper buildSnapshotMapper;
    private final AssetRawSegmentMapper rawSegmentMapper;
    private final AssetRawSegmentRelationMapper relationMapper;
    private final AssetDocumentMapper documentMapper;
    private final AssetRetrievalEmbeddingMapper embeddingMapper;

    public AssetRepository(
            AssetPublishReleaseMapper releaseMapper,
            AssetBuildDocumentSnapshotMapper buildSnapshotMapper,
            AssetRawSegmentMapper rawSegmentMapper,
            AssetRawSegmentRelationMapper relationMapper,
            AssetDocumentMapper documentMapper,
            AssetRetrievalEmbeddingMapper embeddingMapper) {
        this.releaseMapper       = releaseMapper;
        this.buildSnapshotMapper = buildSnapshotMapper;
        this.rawSegmentMapper    = rawSegmentMapper;
        this.relationMapper      = relationMapper;
        this.documentMapper      = documentMapper;
        this.embeddingMapper     = embeddingMapper;
    }

    // -------------------------------------------------------------------------
    // Active scope resolution
    // -------------------------------------------------------------------------

    /**
     * Resolve active release, build, and document snapshots for the given domain.
     *
     * @throws IllegalArgumentException("no_active_release") if zero active releases found
     * @throws IllegalArgumentException("multiple_active_releases") if more than 1 active releases found
     */
    public ActiveScope resolveActiveScope(String domain, String channel) {
        String effectiveDomain = (domain != null) ? domain : "default";
        String effectiveChannel = (channel != null) ? channel : "prod";

        List<AssetPublishRelease> releases = releaseMapper.selectActiveByDomain(effectiveDomain);

        // Filter by channel
        List<AssetPublishRelease> filtered = releases.stream()
                .filter(r -> effectiveChannel.equals(r.getChannel()))
                .toList();

        if (filtered.isEmpty()) {
            throw new IllegalArgumentException("no_active_release");
        }
        if (filtered.size() > 1) {
            throw new IllegalArgumentException("multiple_active_releases");
        }

        AssetPublishRelease release = filtered.get(0);

        List<AssetBuildDocumentSnapshot> snapshots =
                buildSnapshotMapper.selectByBuildIdAndStatus(release.getBuildId(), "active");

        List<String> snapshotIds = new ArrayList<>();
        Map<String, String> documentSnapshotMap = new HashMap<>();
        for (AssetBuildDocumentSnapshot snap : snapshots) {
            if (snap.getDocumentSnapshotId() != null) {
                snapshotIds.add(snap.getDocumentSnapshotId());
            }
            if (snap.getDocumentId() != null && snap.getDocumentSnapshotId() != null) {
                documentSnapshotMap.put(snap.getDocumentId(), snap.getDocumentSnapshotId());
            }
        }

        return new ActiveScope(release.getId(), release.getBuildId(), snapshotIds, documentSnapshotMap);
    }

    /** Convenience overload: default channel = "prod". */
    public ActiveScope resolveActiveScope(String domain) {
        return resolveActiveScope(domain, "prod");
    }

    // -------------------------------------------------------------------------
    // Segment resolution
    // -------------------------------------------------------------------------

    public List<SegmentWithMetaRow> resolveSegmentsByIds(
            List<String> segmentIds, List<String> snapshotIds) {
        if (segmentIds == null || segmentIds.isEmpty()) {
            return Collections.emptyList();
        }
        return rawSegmentMapper.selectWithMeta(segmentIds, snapshotIds);
    }

    // -------------------------------------------------------------------------
    // Relation queries
    // -------------------------------------------------------------------------

    public List<RelationRow> getRelationsForSegments(
            List<String> segmentIds, List<String> relationTypes, List<String> snapshotIds) {
        if (segmentIds == null || segmentIds.isEmpty()) {
            return Collections.emptyList();
        }
        return relationMapper.selectRelationsForSegments(segmentIds, relationTypes, snapshotIds);
    }

    // -------------------------------------------------------------------------
    // Document source queries
    // -------------------------------------------------------------------------

    public List<DocumentSourceRow> getDocumentSources(
            List<String> documentIds, List<String> snapshotIds) {
        if (documentIds == null || documentIds.isEmpty()) {
            return Collections.emptyList();
        }
        return documentMapper.selectDocumentSources(documentIds, snapshotIds);
    }

    // -------------------------------------------------------------------------
    // Graph traversal helpers
    // -------------------------------------------------------------------------

    public List<NeighborRow> getNeighbors(
            List<String> segmentIds,
            List<String> relationTypes,
            List<String> snapshotIds) {
        if (segmentIds == null || segmentIds.isEmpty()) {
            return Collections.emptyList();
        }
        return relationMapper.selectNeighbors(segmentIds, relationTypes, snapshotIds);
    }
}
