package com.coremasterkb.serving.repository;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.entity.AssetBuildDocumentSnapshot;
import com.coremasterkb.serving.entity.AssetPublishRelease;
import com.coremasterkb.serving.mapper.*;
import com.coremasterkb.serving.mapper.result.*;

import java.util.*;

/**
 * Asset database access layer.
 * Uses MyBatis-Plus BaseMapper for simple queries and XML mappers for complex joins.
 */
public class AssetRepository {

    private final AssetPublishReleaseMapper releaseMapper;
    private final AssetBuildDocumentSnapshotMapper buildSnapshotMapper;
    private final AssetRawSegmentMapper rawSegmentMapper;
    private final AssetRawSegmentRelationMapper relationMapper;
    private final AssetDocumentMapper documentMapper;
    private final com.coremasterkb.serving.mapper.AssetRetrievalEmbeddingMapper embeddingMapper;

    public AssetRepository(
            AssetPublishReleaseMapper releaseMapper,
            AssetBuildDocumentSnapshotMapper buildSnapshotMapper,
            AssetRawSegmentMapper rawSegmentMapper,
            AssetRawSegmentRelationMapper relationMapper,
            AssetDocumentMapper documentMapper,
            com.coremasterkb.serving.mapper.AssetRetrievalEmbeddingMapper embeddingMapper) {
        this.releaseMapper    = releaseMapper;
        this.buildSnapshotMapper = buildSnapshotMapper;
        this.rawSegmentMapper = rawSegmentMapper;
        this.relationMapper   = relationMapper;
        this.documentMapper   = documentMapper;
        this.embeddingMapper  = embeddingMapper;
    }

    // -------------------------------------------------------------------------
    // Active scope resolution
    // -------------------------------------------------------------------------

    /**
     * @throws IllegalArgumentException("no_active_release") if zero active releases found
     * @throws IllegalArgumentException("multiple_active_releases") if >1 active releases found
     */
    public ActiveScope resolveActiveScope(String channel) {
        List<AssetPublishRelease> releases = releaseMapper.selectList(
                new LambdaQueryWrapper<AssetPublishRelease>()
                        .eq(AssetPublishRelease::getStatus, "active")
                        .eq(AssetPublishRelease::getChannel, channel));

        if (releases.isEmpty()) throw new IllegalArgumentException("no_active_release");
        if (releases.size() > 1) throw new IllegalArgumentException("multiple_active_releases");

        AssetPublishRelease release = releases.get(0);

        List<AssetBuildDocumentSnapshot> snapshots = buildSnapshotMapper.selectList(
                new LambdaQueryWrapper<AssetBuildDocumentSnapshot>()
                        .eq(AssetBuildDocumentSnapshot::getBuildId, release.getBuildId())
                        .eq(AssetBuildDocumentSnapshot::getSelectionStatus, "active"));

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

    // -------------------------------------------------------------------------
    // Segment resolution
    // -------------------------------------------------------------------------

    public List<SegmentWithMetaRow> resolveSegmentsByIds(
            List<String> segmentIds, List<String> snapshotIds) {
        if (segmentIds == null || segmentIds.isEmpty()) return Collections.emptyList();
        return rawSegmentMapper.selectWithMeta(segmentIds, snapshotIds);
    }

    // -------------------------------------------------------------------------
    // Relation queries
    // -------------------------------------------------------------------------

    public List<RelationRow> getRelationsForSegments(
            List<String> segmentIds, List<String> relationTypes, List<String> snapshotIds) {
        if (segmentIds == null || segmentIds.isEmpty()) return Collections.emptyList();
        return relationMapper.selectRelationsForSegments(segmentIds, relationTypes, snapshotIds);
    }

    // -------------------------------------------------------------------------
    // Document source queries
    // -------------------------------------------------------------------------

    public List<DocumentSourceRow> getDocumentSources(
            List<String> documentIds, List<String> snapshotIds) {
        if (documentIds == null || documentIds.isEmpty()) return Collections.emptyList();
        return documentMapper.selectDocumentSources(documentIds, snapshotIds);
    }

    // -------------------------------------------------------------------------
    // Graph traversal helpers
    // -------------------------------------------------------------------------

    public List<NeighborRow> getNeighbors(
            List<String> segmentIds,
            List<String> relationTypes,
            List<String> snapshotIds) {
        if (segmentIds == null || segmentIds.isEmpty()) return Collections.emptyList();
        return relationMapper.selectNeighbors(segmentIds, relationTypes, snapshotIds);
    }
}
