package org.mcore.server.controller;

import org.mcore.storage.service.UserProfileService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class ProfileController {

    private final UserProfileService userProfileService;

    public ProfileController(UserProfileService userProfileService) {
        this.userProfileService = userProfileService;
    }

    @GetMapping("/profile")
    public Map<String, Object> getProfile() {
        return userProfileService.getProfile();
    }

    @PostMapping("/profile/attrs")
    public ResponseEntity<Map<String, Object>> upsertAttr(@RequestBody Map<String, Object> body) {
        String key = (String) body.get("key");
        String value = (String) body.get("value");
        double confidence = body.get("confidence") != null ? ((Number) body.get("confidence")).doubleValue() : 0.8;
        boolean immutable = Boolean.TRUE.equals(body.get("immutable"));

        boolean ok = userProfileService.upsertAttribute(key, value, confidence, immutable);
        return ResponseEntity.ok(Map.of("success", ok, "key", key));
    }
}
