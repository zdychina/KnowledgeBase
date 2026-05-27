package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.entity.ServingQueryLog;
import org.apache.ibatis.annotations.Param;

public interface ServingQueryLogMapper {

    void insert(ServingQueryLog log);
}
