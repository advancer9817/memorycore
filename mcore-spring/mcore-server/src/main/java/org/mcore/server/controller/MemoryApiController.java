package org.mcore.server.controller;

import org.mcore.common.dto.MemorySearchDTO;
import org.mcore.common.model.MemoryDO;
import org.mcore.common.result.Result;
import org.mcore.storage.repository.LinkRepository;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.mcore.storage.transfer.TransferService;
import org.mcore.tenancy.provisioner.TenantDatabaseProvisioner;
import org.mcore.tenancy.security.TenantApiKeyService;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
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
    private final TenantApiKeyService tenantApiKeyService;

    public MemoryApiController(MemoryRepository memoryRepository,
                               HybridSearchService hybridSearchService,
                               LinkRepository linkRepository,
                               TransferService transferService,
                               TenantDatabaseProvisioner tenantDatabaseProvisioner,
                               TenantApiKeyService tenantApiKeyService) {
        this.memoryRepository = memoryRepository;
        this.hybridSearchService = hybridSearchService;
        this.linkRepository = linkRepository;
        this.transferService = transferService;
        this.tenantDatabaseProvisioner = tenantDatabaseProvisioner;
        this.tenantApiKeyService = tenantApiKeyService;
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

    /**
     * 为租户签发 API Key —— 明文密钥仅此一次返回，请立即妥善保存
     */
    @PostMapping("/tenant/{tenantId}/keys")
    public Result<Map<String, Object>> issueTenantKey(@PathVariable String tenantId,
                                                      @RequestParam(required = false) String name,
                                                      @RequestParam(required = false) List<String> scopes,
                                                      @RequestParam(required = false) Integer ttlDays) {
        TenantApiKeyService.IssuedKey issued = tenantApiKeyService.issueKey(tenantId, name, scopes, ttlDays);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("keyId", issued.keyId());
        payload.put("apiKey", issued.rawKey());
        payload.put("tenantId", issued.tenantId());
        payload.put("scopes", issued.scopes());
        payload.put("expiresAt", issued.expiresAt() == null ? null : issued.expiresAt().toString());
        payload.put("notice", "明文密钥仅此一次返回，请立即保存");
        return Result.success(payload);
    }

    /**
     * 枚举租户已签发的密钥（脱敏，不含明文与散列）
     */
    @GetMapping("/tenant/{tenantId}/keys")
    public Result<List<Map<String, Object>>> listTenantKeys(@PathVariable String tenantId) {
        return Result.success(tenantApiKeyService.listKeys(tenantId));
    }

    /**
     * 立即吊销指定密钥（鉴权缓存同步失效）
     */
    @DeleteMapping("/tenant/{tenantId}/keys/{keyId}")
    public Result<Map<String, Object>> revokeTenantKey(@PathVariable String tenantId,
                                                        @PathVariable String keyId) {
        boolean revoked = tenantApiKeyService.revokeKey(tenantId, keyId);
        return Result.success(Map.of("keyId", keyId, "revoked", revoked));
    }
}
