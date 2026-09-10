package org.mcore.server.controller;

import org.mcore.common.dto.MemorySearchDTO;
import org.mcore.common.model.MemoryDO;
import org.mcore.common.result.Result;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.mcore.tenancy.provisioner.TenantDatabaseProvisioner;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class MemoryApiController {

    private final MemoryRepository memoryRepository;
    private final HybridSearchService hybridSearchService;
    private final TenantDatabaseProvisioner tenantDatabaseProvisioner;

    public MemoryApiController(MemoryRepository memoryRepository,
                               HybridSearchService hybridSearchService,
                               TenantDatabaseProvisioner tenantDatabaseProvisioner) {
        this.memoryRepository = memoryRepository;
        this.hybridSearchService = hybridSearchService;
        this.tenantDatabaseProvisioner = tenantDatabaseProvisioner;
    }

    @GetMapping("/memories/recent")
    public Result<List<MemoryDO>> getRecentMemories(@RequestParam(defaultValue = "10") int limit) {
        return Result.success(memoryRepository.listRecent(limit));
    }

    @PostMapping("/memories/search")
    public Result<List<HybridSearchService.SearchHit>> searchMemories(@RequestBody MemorySearchDTO searchDTO) {
        int limit = searchDTO.getLimit() != null ? searchDTO.getLimit() : 10;
        var hits = hybridSearchService.hybridSearch(searchDTO.getQuery(), null, searchDTO.getType(), limit);
        return Result.success(hits);
    }

    @PostMapping("/tenant/provision")
    public Result<Map<String, Object>> provisionTenant(@RequestParam String tenantId) {
        tenantDatabaseProvisioner.provisionTenantDatabase(tenantId, "mcore_user");
        String cleanId = tenantId.replace("-", "_").toLowerCase();
        return Result.success(Map.of(
                "tenantId", tenantId,
                "dbName", "mcore_u_" + cleanId,
                "status", "ready"
        ));
    }
}
