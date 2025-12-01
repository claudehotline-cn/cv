package com.cv.cp.controller;

import java.util.HashMap;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/_metrics")
public class MetricsSummaryController {

  @GetMapping("/summary")
  public ResponseEntity<CpResponse<Map<String, Object>>> getSummary() {
    Map<String, Object> data = new HashMap<>();
    Map<String, Object> cp = new HashMap<>();
    Map<String, Object> cache = new HashMap<>();

    cp.put("error", "metrics_summary_not_implemented");
    cache.put("hits", 0);
    cache.put("misses", 0);

    data.put("cp", cp);
    data.put("cache", cache);
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}

