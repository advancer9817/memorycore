package org.mcore.storage.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.mcore.common.model.MemoryEntityDO;

import java.util.List;
import java.util.Map;

@Mapper
public interface EntityMapper {

    int insert(MemoryEntityDO entity);

    List<Map<String, Object>> selectByMemoryId(@Param("memoryId") String memoryId);

    int deleteByMemoryId(@Param("memoryId") String memoryId);
}
