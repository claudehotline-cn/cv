package com.cv.cp.controller;

import com.cv.cp.config.AppProperties;
import com.cv.cp.dto.SystemInfoDto;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/system")
public class SystemInfoController {

  private final AppProperties properties;

  public SystemInfoController(AppProperties properties) {
    this.properties = properties;
  }

  @GetMapping("/info")
  public ResponseEntity<CpResponse<SystemInfoDto>> getSystemInfo() {
    SystemInfoDto dto = new SystemInfoDto();
    SystemInfoDto.RestreamInfo restreamInfo = new SystemInfoDto.RestreamInfo();
    if (properties.getRestream() != null) {
      restreamInfo.setRtspBase(properties.getRestream().getRtspBase());
    }
    dto.setRestream(restreamInfo);
    return ResponseEntity.ok(CpResponse.ok(dto));
  }
}

