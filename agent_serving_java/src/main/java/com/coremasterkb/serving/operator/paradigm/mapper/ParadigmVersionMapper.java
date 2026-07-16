package com.coremasterkb.serving.operator.paradigm.mapper;

import com.coremasterkb.serving.operator.paradigm.ParadigmVersionEntity;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/** CRUD for {@code operator_paradigm_version} (immutable published snapshots). */
public interface ParadigmVersionMapper {

    int insert(ParadigmVersionEntity entity);

    ParadigmVersionEntity selectByParadigmAndVersion(
            @Param("paradigmId") String paradigmId, @Param("version") int version);

    List<ParadigmVersionEntity> selectVersionsByParadigm(@Param("paradigmId") String paradigmId);

    /** Highest version number for a paradigm, or null if it has none published yet. */
    Integer selectMaxVersion(@Param("paradigmId") String paradigmId);

    int deleteByParadigm(@Param("paradigmId") String paradigmId);
}
