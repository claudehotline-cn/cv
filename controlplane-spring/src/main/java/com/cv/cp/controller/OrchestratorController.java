package com.cv.cp.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orch")
public class OrchestratorController {

  @GetMapping("/health")
  public ResponseEntity<CpResponse<Void>> health() {
    return ResponseEntity.ok(CpResponse.ok(null));
  }
}

