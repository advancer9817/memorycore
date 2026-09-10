package org.mcore.server.controller;

import org.mcore.common.dto.MemorySearchDTO;
import org.mcore.common.model.MemoryDO;
import org.mcore.common.result.Result;
import org.mcore.storage.repository.LinkRepository;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.mcore.storage.transfer.TransferService;
import org.mcore.tenancy.provisioner.TenantDatabaseProvisioner;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class MemoryApiController {

    private final MemoryRepository memoryRepository;
    private final HybridSearchService hybridSearchService;
    private final LinkRepository linkRepository;
    private final TransferService transferService;
    private final TenantDatabaseProvisioner tenantDatabaseProvisioner;

    public MemoryApiController(MemoryRepository memoryRepository,
                               HybridSearchService hybridSearchService,
                               LinkRepository linkRepository,
                               TransferService transferService,
                               TenantDatabaseProvisioner tenantDatabaseProvisioner) {
        this.memoryRepository = memoryRepository;
        this.hybridSearchService = hybridSearchService;
        this.linkRepository = linkRepository;
        this.transferService = transferService;
        this.tenantDatabaseProvisioner = tenantDatabaseProvisioner;
    }

    @GetMapping("/memories/recent")
    public Result<List<MemoryDO>> getRecentMemories(@RequestParam(defaultValue = "20") int limit) {
        return Result.success(memoryRepository.listRecent(limit));
    }

    @PostMapping("/memories/search")
    public Result<List<HybridSearchService.SearchHit>> searchMemories(@RequestBody MemorySearchDTO searchDTO) {
        int limit = searchDTO.getLimit() != null ? searchDTO.getLimit() : 10;
        var hits = hybridSearchService.hybridSearch(searchDTO.getQuery(), searchDTO.getType(), limit);
        return Result.success(hits);
    }

    @GetMapping("/graph/data")
    public Result<Map<String, Object>> getGraphData(@RequestParam(defaultValue = "60") int limit) {
        return Result.success(linkRepository.getGraphData(limit));
    }

    @PostMapping("/vectors/rebuild")
    public Result<Map<String, Object>> rebuildVectors(@RequestParam(defaultValue = "1000") int limit) {
        return Result.success(memoryRepository.rebuildVectors(limit));
    }

    @PostMapping("/backup")
    public Result<Map<String, Object>> triggerBackup(@RequestParam(required = false) String path) {
        return Result.success(transferService.backup(path));
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

    @GetMapping("/tenant/list")
    public Result<List<Map<String, Object>>> listTenants() {
        return Result.success(tenantDatabaseProvisioner.listTenants());
    }

    @DeleteMapping("/tenant/{tenantId}")
    public Result<Map<String, Object>> dropTenant(@PathVariable String tenantId) {
        tenantDatabaseProvisioner.dropTenantDatabase(tenantId);
        return Result.success(Map.of("tenantId", tenantId, "status", "dropped"));
    }
}
