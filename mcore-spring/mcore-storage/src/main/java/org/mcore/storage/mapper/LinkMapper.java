package org.mcore.storage.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.mcore.common.model.MemoryLinkDO;

import java.util.List;
import java.util.Map;

@Mapper
public interface LinkMapper {

    int insert(MemoryLinkDO link);

    List<Map<String, Object>> selectLinksBySourceId(@Param("sourceId") String sourceId);

    List<Map<String, Object>> selectLineageLinks(@Param("memoryId") String memoryId);

    List<Map<String, Object>> selectGraphNodes(@Param("limit") int limit);

    List<Map<String, Object>> selectGraphEdges(@Param("limit") int limit);

    List<Map<String, Object>> selectRelatedMemories(@Param("memoryId") String memoryId, @Param("limit") int limit);
}
