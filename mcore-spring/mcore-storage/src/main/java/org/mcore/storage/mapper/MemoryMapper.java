package org.mcore.storage.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.mcore.common.model.MemoryDO;

import java.util.List;
import java.util.Map;

@Mapper
public interface MemoryMapper {

    long countTotal();

    long countActive();

    List<Map<String, Object>> countGroupedByStatus();

    MemoryDO selectById(@Param("id") String id);

    List<MemoryDO> selectRecent(@Param("limit") int limit);

    int insert(MemoryDO record);

    int update(MemoryDO record);

    int batchUpdateStatus(@Param("ids") List<String> ids, @Param("status") String status);

    long countFilterMemories(Map<String, Object> params);

    List<Map<String, Object>> selectFilterMemories(Map<String, Object> params);

    List<Map<String, Object>> selectCategories();

    List<MemoryDO> selectNeedEmbedding(@Param("limit") int limit);

    int updateEmbedding(@Param("id") String id, @Param("embedding") com.pgvector.PGvector embedding);

    List<Map<String, Object>> selectWarnings();

    List<Map<String, Object>> selectAuditLogs(@Param("limit") int limit);

    int insertAuditLog(@Param("id") String id,
                       @Param("action") String action,
                       @Param("memoryId") String memoryId,
                       @Param("operator") String operator,
                       @Param("details") String details);
}
