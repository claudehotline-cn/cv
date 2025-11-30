package com.cv.cp.controller;

import com.cv.cp.service.GraphReadService;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class GraphController {

  private final GraphReadService graphReadService;

  public GraphController(GraphReadService graphReadService) {
    this.graphReadService = graphReadService;
  }

  @GetMapping("/graphs")
  public ResponseEntity<CpResponse<List<Map<String, Object>>>> listGraphs() {
    List<Map<String, Object>> data;
    try {
      data = graphReadService.listGraphs();
    } catch (Exception ex) {
      data = Collections.emptyList();
    }
    return ResponseEntity.ok(CpResponse.ok(data));
  }
}

