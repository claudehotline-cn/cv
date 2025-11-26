package com.cv.cp.controller;

import com.cv.cp.dto.SystemInfoDto;
import com.cv.cp.service.CacheService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/system")
public class SystemInfoController {

  private final CacheService cacheService;

  public SystemInfoController(CacheService cacheService) {
    this.cacheService = cacheService;
  }

  @GetMapping("/info")
  public ResponseEntity<CpResponse<SystemInfoDto>> getSystemInfo() {
    SystemInfoDto dto = cacheService.getSystemInfo();
    return ResponseEntity.ok(CpResponse.ok(dto));
  }
}
