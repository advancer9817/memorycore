package org.mcore.server.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.mcore.storage.transfer.TransferService;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * 备份导出 / 导入接口。
 *
 * 此前这两个端点完全缺失（404），前端「备份」面板的导出与导入按钮点了没有任何反应。
 *
 * 契约（与前端 components/form-view-backup.tsx 对齐）：
 * - POST /api/v1/backup/export  : JSON body，返回 application/zip 附件（前端直接 blob 下载）
 * - POST /api/v1/backup/import  : multipart/form-data，字段名 file（兼容 .zip 与 .json）
 */
@RestController
@RequestMapping("/api/v1/backup")
public class BackupController {

    private final TransferService transferService;
    private final ObjectMapper objectMapper;

    public BackupController(TransferService transferService, ObjectMapper objectMapper) {
        this.transferService = transferService;
        this.objectMapper = objectMapper;
    }

    /** 导出为 zip 附件 */
    @PostMapping(value = "/export", produces = "application/zip")
    public ResponseEntity<byte[]> export(@RequestBody(required = false) Map<String, Object> body) throws Exception {
        boolean full = body == null || !Boolean.FALSE.equals(body.get("full"));
        boolean includeAudit = body != null && Boolean.TRUE.equals(body.get("include_audit"));
        boolean memoriesOnly = body != null && Boolean.TRUE.equals(body.get("memories_only"));

        Map<String, Object> payload = transferService.exportPayload(full, includeAudit, memoriesOnly);
        byte[] json = objectMapper.writerWithDefaultPrettyPrinter()
                .writeValueAsBytes(payload);

        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            zos.putNextEntry(new ZipEntry("memories_export.json"));
            zos.write(json);
            zos.closeEntry();
            // 附带一份元信息，便于人工核对来源与规模
            zos.putNextEntry(new ZipEntry("manifest.json"));
            Map<String, Object> manifest = new LinkedHashMap<>();
            manifest.put("schema_version", payload.get("schema_version"));
            manifest.put("exported_at", payload.get("exported_at"));
            manifest.put("counts", payload.get("counts"));
            zos.write(objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(manifest));
            zos.closeEntry();
        }

        String stamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")
                .withZone(ZoneOffset.UTC).format(Instant.now());
        String filename = "memories_export-" + stamp + ".zip";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.parseMediaType("application/zip"));
        headers.set(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + filename + "\"");
        headers.setContentLength(bos.size());
        return new ResponseEntity<>(bos.toByteArray(), headers, org.springframework.http.HttpStatus.OK);
    }

    /** 导入（multipart，字段名 file；接受 zip 或裸 JSON） */
    @PostMapping(value = "/import", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<Map<String, Object>> importBackup(
            @RequestPart(value = "file", required = false) MultipartFile file,
            @RequestParam(value = "file", required = false) MultipartFile fileParam,
            @RequestParam(value = "conflict_policy", defaultValue = "overwrite") String conflictPolicy,
            @RequestParam(value = "full_replace", defaultValue = "false") boolean fullReplace) throws Exception {

        MultipartFile upload = file != null ? file : fileParam;
        if (upload == null || upload.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of(
                    "ok", false, "error", "missing_file", "message", "未收到上传文件（字段名应为 file）"));
        }

        byte[] raw = upload.getBytes();
        String jsonText = extractJson(raw);

        Map<String, Object> payload;
        try {
            payload = objectMapper.readValue(jsonText, new com.fasterxml.jackson.core.type.TypeReference<>() {
            });
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of(
                    "ok", false, "error", "invalid_payload",
                    "message", "无法解析备份内容: " + e.getMessage()));
        }

        Map<String, Object> result = transferService.importPayload(payload, conflictPolicy, fullReplace);
        Map<String, Object> res = new LinkedHashMap<>(result);
        res.put("filename", upload.getOriginalFilename());
        res.put("bytes", raw.length);
        return ResponseEntity.ok(res);
    }

    /**
     * 从上传内容中取出 JSON 文本。
     * 兼容三种形态：zip 包（取其中 *.json，优先 memories_export.json）、裸 JSON、以及 JSON 前置 BOM。
     */
    private String extractJson(byte[] raw) throws Exception {
        if (raw.length >= 2 && (raw[0] & 0xFF) == 0x50 && (raw[1] & 0xFF) == 0x4B) {
            // PK 头 → zip
            String fallback = null;
            try (ZipInputStream zis = new ZipInputStream(new ByteArrayInputStream(raw), StandardCharsets.UTF_8)) {
                ZipEntry entry;
                while ((entry = zis.getNextEntry()) != null) {
                    if (entry.isDirectory() || !entry.getName().toLowerCase().endsWith(".json")) {
                        continue;
                    }
                    String text = new String(zis.readAllBytes(), StandardCharsets.UTF_8);
                    if (entry.getName().endsWith("memories_export.json")) {
                        return text;
                    }
                    if (fallback == null && !entry.getName().endsWith("manifest.json")) {
                        fallback = text;
                    }
                }
            }
            if (fallback != null) {
                return fallback;
            }
            throw new IllegalArgumentException("zip 包中未找到 JSON 备份文件");
        }
        String text = new String(raw, StandardCharsets.UTF_8);
        if (!text.isEmpty() && text.charAt(0) == '\uFEFF') {
            text = text.substring(1);
        }
        return text;
    }

    /** 服务端落盘备份（不走浏览器下载通道的场景） */
    @PostMapping("/run")
    public Map<String, Object> runBackup(@RequestBody(required = false) Map<String, Object> body) {
        String path = body == null ? null : (String) body.get("path");
        return transferService.backup(path);
    }

    /** 记忆库导出载荷（JSON 直出，便于脚本与排障） */
    @PostMapping("/export-json")
    public Map<String, Object> exportJson(@RequestBody(required = false) Map<String, Object> body) {
        boolean full = body == null || !Boolean.FALSE.equals(body.get("full"));
        boolean includeAudit = body != null && Boolean.TRUE.equals(body.get("include_audit"));
        boolean memoriesOnly = body != null && Boolean.TRUE.equals(body.get("memories_only"));
        return transferService.exportPayload(full, includeAudit, memoriesOnly);
    }
}
